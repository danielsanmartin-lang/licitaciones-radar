"""Orquestación de la ingesta: construir fuentes, recorrerlas y guardar.

Cada fuente se ingiere de forma aislada. Si una falla, se registra el error en
`ingest_log` y se sigue con las demás: perder Cataluña una mañana no debe impedir
ver lo que ha publicado PLACSP.
"""

from __future__ import annotations

import logging
import sqlite3
import zipfile

from . import db, net, progreso
from .matching import Perfil, terminos_para_consultas
from .sources.catalunya import FuenteCatalunya
from .sources.placsp import DATASETS as DATASETS_PLACSP, FuentePLACSP
from .sources.ted import FuenteTED

log = logging.getLogger(__name__)

# Nombre corto en la CLI -> constructor
FUENTES_DISPONIBLES = (
    [f"placsp:{d}" for d in DATASETS_PLACSP] + ["placsp", "ted", "catalunya"]
)

# El mismo nombre, dicho para quien no ha visto nunca esta base. El técnico sigue siendo
# el de `fuente.nombre`, que es el que hay que poder buscar en el log; este es el que se
# lee en la pantalla mientras la carga inicial se pasa dos horas trabajando.
TITULOS_FUENTE = {
    "placsp:licitaciones": "la Plataforma de Contratación del Estado",
    "placsp:agregadas": "las plataformas de las comunidades autónomas",
    "placsp:consultas_previas": "las consultas preliminares al mercado",
    "ted": "el diario oficial de la Unión Europea",
    "catalunya": "la contratación pública de Cataluña",
}

# Años de histórico que pide la carga inicial: el actual y los dos anteriores.
ANIOS_PRIMERA_CARGA = 3

# Páginas del feed diario que pide la etapa de cierre. El backfill trae los ZIP
# anuales, que se publican con retraso; sin esta pasada, el tramo entre la fecha de
# corte del ZIP y hoy no lo trae nadie, porque en cuanto se escribe el cursor la
# ingesta incremental solo mira hacia delante.
PAGINAS_CIERRE = 12

# Etapas de la carga inicial, de la más barata a la más cara. El orden no es estético:
# la primera llena la bandeja en minutos y por eso es la que se hace antes de abrir la
# aplicación; la tercera es la que cuesta 5 GB y hasta un par de horas, y se deja
# corriendo por detrás mientras ya se puede trabajar.
#
# El reparto de coste y provecho está medido sobre una base ya construida (449.094
# licitaciones, 2.934 coincidencias): TED y Cataluña filtran en servidor y aportan
# ~1.400 anuncios casi gratis; `placsp:licitaciones` aporta 974 y cuesta 5 GB. Las
# cifras absolutas han crecido desde entonces, pero la proporción y el reparto de coste
# —que es lo que decide el orden de las etapas— siguen igual.
ETAPAS_PRIMERA_CARGA = [
    {
        "etiqueta": "Anuncios europeos y de Cataluña",
        "fuentes": ["ted", "catalunya"],
        "historico": True,
        "coste": "unos minutos, apenas ocupa disco",
        "detalle": "las dos fuentes filtran en servidor, así que solo llega lo que "
                   "encaja con tus términos",
    },
    {
        "etiqueta": "Histórico de plataformas agregadas y consultas previas",
        "fuentes": ["placsp:agregadas", "placsp:consultas_previas"],
        "historico": True,
        "coste": "unos 360 MB de descarga, lo que tarde depende de tu conexión, "
                 "y unos 4 minutos de proceso",
        "detalle": "cubre Cataluña, Andalucía, País Vasco, Madrid, Galicia, Navarra "
                   "y La Rioja",
    },
    {
        "etiqueta": "Histórico de la Plataforma del Estado",
        "fuentes": ["placsp:licitaciones"],
        "historico": True,
        # No se anuncia un total a propósito. Medido: con los ZIP ya en la caché son 17
        # minutos de proceso, y bajándolos a 0,8 MB/s fueron casi dos horas. La descarga
        # manda, y varía casi dos órdenes de magnitud según la línea de cada uno; el
        # proceso solo depende de la máquina y sí se puede prometer.
        "coste": "unos 5 GB de descarga, lo que tarde depende de tu conexión, "
                 "y unos 15 minutos de proceso",
        "detalle": "es el que trae las otras diez comunidades y el que llena "
                   "Vencimientos y Adjudicatarios",
    },
    {
        "etiqueta": "Novedades desde el corte del histórico",
        "fuentes": None,  # todas
        "historico": False,
        "coste": "unos minutos",
        "detalle": "cierra el hueco entre la fecha del último ZIP anual y hoy, y deja "
                   "los cursores listos para la ingesta diaria",
    },
]


def anios_primera_carga(hoy) -> list[int]:
    """El año en curso y los anteriores. `hoy` se pasa para poder fijarlo en tests."""
    return list(range(hoy.year - ANIOS_PRIMERA_CARGA + 1, hoy.year + 1))


def construir_fuentes(nombres: list[str] | None, perfiles: list[Perfil],
                      *, dias_ventana: int = 30,
                      paginas_primera_vez: int = 1) -> list:
    """Instancia los conectores pedidos.

    A las fuentes que filtran en servidor (TED, Cataluña) se les pasan los CPV y
    términos de los perfiles para no descargar el país entero. El filtrado fino
    se hace después en local.

    `paginas_primera_vez` solo lo usa PLACSP, y solo cuando no hay cursor todavía.
    Lo sube la carga inicial para cerrar el tramo entre el corte del ZIP anual y hoy.
    """
    cpv, terminos = terminos_para_consultas(perfiles)

    if not nombres:
        # `placsp:agregadas` es el dataset donde PLACSP recoge las comunidades con
        # plataforma propia. Medido sobre el feed diario, cubre País Vasco (65
        # entradas), Galicia (15) y Navarra (6) además de Cataluña, Andalucía y
        # Madrid, con los campos al 100%. Es decir: los tres huecos que parecían
        # exigir conectores nativos ya estaban cubiertos aquí.
        nombres = [
            "placsp:licitaciones",
            "placsp:agregadas",
            "placsp:consultas_previas",
            "ted",
            "catalunya",
        ]

    fuentes = []
    for nombre in nombres:
        if nombre == "placsp":
            fuentes.extend(
                FuentePLACSP(d, paginas_primera_vez=paginas_primera_vez)
                for d in DATASETS_PLACSP
            )
        elif nombre.startswith("placsp:"):
            fuentes.append(FuentePLACSP(nombre.split(":", 1)[1],
                                        paginas_primera_vez=paginas_primera_vez))
        elif nombre == "ted":
            fuentes.append(FuenteTED(cpv, terminos, dias_ventana=dias_ventana))
        elif nombre == "catalunya":
            fuentes.append(FuenteCatalunya(cpv, terminos, dias_ventana=dias_ventana))
        else:
            raise ValueError(
                f"Fuente desconocida: {nombre}. Disponibles: {', '.join(FUENTES_DISPONIBLES)}"
            )
    return fuentes


def ingerir(con: sqlite3.Connection, fuentes: list, *, anios: list[int] | None = None,
            reiniciar_cursor: bool = False) -> dict:
    """Ejecuta la ingesta. Devuelve un resumen por fuente.

    `reiniciar_cursor` olvida por dónde se quedó la última vez y vuelve a pedir la
    ventana completa. Hace falta cuando cambia la forma de interpretar los datos:
    los registros ya guardados no se reprocesan solos, porque la ingesta
    incremental —con razón— solo pide lo publicado desde la última ejecución.
    """
    resumen = {}

    for fuente in fuentes:
        progreso.fuente(fuente.nombre, TITULOS_FUENTE.get(fuente.nombre, fuente.nombre))
        if reiniciar_cursor:
            db.escribir_cursor(con, fuente.nombre, None)
            con.commit()
        log_id = db.abrir_ingest(con, fuente.nombre)
        vistos = nuevos = actualizados = 0
        error = None
        try:
            if anios:
                for i, anio in enumerate(anios, 1):
                    progreso.tarea(f"el histórico de {anio} (año {i} de {len(anios)})")
                    # Cada año va en su propio try. PLACSP no publica el ZIP anual de
                    # todos los años en todos los datasets, y con un try único para
                    # todos, un 404 en uno se llevaba por delante los que sí existen.
                    # Por el mismo motivo se recogen los fallos de fichero y no solo los
                    # de red: un ZIP de la caché que no se puede leer —iCloud vacía los
                    # ficheros grandes de las carpetas sincronizadas— dejaba los años
                    # siguientes sin intentar siquiera.
                    try:
                        for lic in fuente.historico(anio):
                            vistos += 1
                            progreso.procesando()
                            progreso.fichas(vistos)
                            estado = db.guardar(con, lic)
                            nuevos += estado == "nueva"
                            actualizados += estado == "actualizada"
                            if vistos % 2000 == 0:
                                con.commit()
                                log.info("  %s %s: %d procesadas...",
                                         fuente.nombre, anio, vistos)
                    except (net.ErrorRed, zipfile.BadZipFile, OSError) as exc:
                        if isinstance(exc, net.ErrorRed) and exc.codigo == 404:
                            # No es una avería: ese año no existe para este dataset.
                            # Si se contara como error, una carga inicial que fue bien
                            # acabaría diciendo «alguna fuente ha fallado».
                            log.info("%s: no hay histórico publicado de %s",
                                     fuente.nombre, anio)
                            continue
                        log.warning("%s %s falló: %s; se sigue con los demás años",
                                    fuente.nombre, anio, exc)
                        error = error or f"{type(exc).__name__}: {exc}"
                    con.commit()
            else:
                progreso.tarea("las novedades desde la última descarga")
                cursor_fila = db.leer_cursor(con, fuente.nombre)
                cursor = cursor_fila["cursor"] if cursor_fila else None
                for lic in fuente.incremental(cursor):
                    vistos += 1
                    progreso.procesando()
                    progreso.fichas(vistos)
                    estado = db.guardar(con, lic)
                    nuevos += estado == "nueva"
                    actualizados += estado == "actualizada"
                    if vistos % 2000 == 0:
                        con.commit()
                nuevo_cursor = fuente.cursor_nuevo()
                if nuevo_cursor:
                    db.escribir_cursor(con, fuente.nombre, nuevo_cursor)
        except Exception as exc:  # noqa: BLE001 - se aísla la fuente a propósito
            error = f"{type(exc).__name__}: {exc}"
            log.error("Fuente %s falló: %s", fuente.nombre, error)

        con.commit()
        db.cerrar_ingest(
            con, log_id, vistos=vistos, nuevos=nuevos, actualizados=actualizados, error=error
        )
        con.commit()
        resumen[fuente.nombre] = {
            "vistos": vistos, "nuevos": nuevos, "actualizados": actualizados, "error": error
        }
        estado_txt = f"ERROR: {error}" if error else f"{nuevos} nuevas, {actualizados} actualizadas"
        log.info("%-28s %6d vistas · %s", fuente.nombre, vistos, estado_txt)

    # Un anuncio de TED y el de PLACSP del mismo expediente solo se pueden reconocer
    # comparándolos entre sí, así que no puede hacerse al guardar cada fila. Va aquí,
    # una vez terminadas todas las fuentes: si se hiciera por fuente, el anuncio de
    # TED que llega antes que su pareja de PLACSP se quedaría suelto hasta la
    # siguiente ingesta.
    # No entra en `resumen`: quien lo consume espera una entrada por fuente con su
    # campo `error` (radar.py lo recorre para decidir el código de salida).
    fusion = db.fusionar_grupos_ted(con)
    if fusion["anuncios_fusionados"]:
        log.info(
            "%-28s %6d anuncios unidos a su expediente de PLACSP "
            "(%d grupos ambiguos, sin tocar)",
            "dedup ted/placsp", fusion["anuncios_fusionados"], fusion["ambiguos"],
        )

    # Va después de la fusión, no antes: un anuncio que acaba de entrar en el grupo de
    # un expediente ya triado tiene que heredar ese triaje aquí. Si no, lo descartado
    # reaparecería en la bandeja al día siguiente por la puerta de atrás.
    heredados = db.propagar_revisiones_en_grupos(con)
    if heredados:
        log.info(
            "%-28s %6d anuncios heredan el triaje de su expediente",
            "triaje por expediente", heredados,
        )

    return resumen
