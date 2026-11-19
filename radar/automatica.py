"""Lo que el radar hace solo mientras la aplicación está abierta: buscar y avisar.

Dos piezas:

1. **Buscar cada N horas** (`Planificador`). Hasta la 2.4 lo hacía la propia página, con
   un `setInterval` que cada cuarto de hora miraba si la última búsqueda tenía más de
   cuatro horas. Desde la 2.4 cerrar la ventana no cierra la aplicación, y WebKit
   ralentiza los temporizadores de una página que no se ve: la búsqueda dejaba de tener
   hora justo cuando más falta hacía. El servidor de Python no tiene ese problema, y así
   vale igual para `start.command`, que abre la bandeja en el navegador.

2. **Decir qué ha llegado** (`avisos_pendientes`). El aviso de macOS lo pone la ventana
   nativa (`Radar.swift`), que pregunta aquí cada minuto. La marca `aviso_busqueda_id`
   dice hasta qué búsqueda se ha avisado ya. Es otra cosa que «N nuevas», que se borra al
   mirarlas: si miras la bandeja antes de que llegue el aviso, el aviso tiene que llegar
   igual, y si no la miras, no se repite cada minuto.

Las preferencias van en la tabla `preferencias`, como todo lo que es de quien usa la
herramienta, y solo con las claves de aquí: el endpoint no escribe claves arbitrarias.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import busqueda, consultas, db

log = logging.getLogger(__name__)

PREF_INTERVALO = "auto_intervalo_min"
PREF_AVISOS = "avisos_activos"
PREF_SONIDO = "avisos_sonido"
PREF_MARCA = "aviso_busqueda_id"

# Cada cuánto buscar, en minutos. 0 es «nunca». Menos de una hora no tiene sentido: una
# búsqueda normal tarda un minuto, pero con PLACSP lenta se han visto horas, y el cerrojo
# haría que la siguiente esperase de todas formas.
INTERVALOS = (0, 60, 120, 240, 480)
INTERVALO_POR_DEFECTO = 120

# Al arrancar el servidor, la pantalla de arranque hace su propia búsqueda. Si el
# planificador se adelantara, la pantalla se encontraría una búsqueda que no ha pedido
# —la esperaría, pero diría «Terminando la búsqueda que ya estaba en marcha»—, y una
# actualización pendiente tendría que esperar a que acabe.
GRACIA_ARRANQUE = 5 * 60
COMPROBAR_CADA = 60.0

# Cuántos títulos van en el aviso. macOS corta el cuerpo a unas pocas líneas.
TITULOS_EN_AVISO = 3


# --- Preferencias ------------------------------------------------------------------


def _si_no(valor: str | None, defecto: bool) -> bool:
    return defecto if valor is None else valor == "1"


def preferencias(con) -> dict:
    valor = db.leer_preferencia(con, PREF_INTERVALO)
    try:
        intervalo = int(valor) if valor is not None else INTERVALO_POR_DEFECTO
    except ValueError:
        intervalo = INTERVALO_POR_DEFECTO
    if intervalo not in INTERVALOS:
        intervalo = INTERVALO_POR_DEFECTO
    return {
        "intervalo_min": intervalo,
        "avisos": _si_no(db.leer_preferencia(con, PREF_AVISOS), True),
        "sonido": _si_no(db.leer_preferencia(con, PREF_SONIDO), True),
    }


def fijar_preferencias(con, datos: dict) -> dict:
    """Cambia las que vengan en `datos` y deja las demás. ValueError si algo no vale."""
    if not isinstance(datos, dict):
        raise ValueError("se esperaba un objeto")
    cambios: list[tuple[str, str]] = []
    if "intervalo_min" in datos:
        try:
            intervalo = int(datos["intervalo_min"])
        except (TypeError, ValueError):
            raise ValueError("intervalo_min no es un número") from None
        if intervalo not in INTERVALOS:
            raise ValueError(
                f"intervalo_min debe ser uno de {', '.join(map(str, INTERVALOS))}")
        cambios.append((PREF_INTERVALO, str(intervalo)))
    for clave, pref in (("avisos", PREF_AVISOS), ("sonido", PREF_SONIDO)):
        if clave in datos:
            if not isinstance(datos[clave], bool):
                raise ValueError(f"{clave} debe ser true o false")
            cambios.append((pref, "1" if datos[clave] else "0"))
    for pref, valor in cambios:
        db.escribir_preferencia(con, pref, valor)
    con.commit()
    return preferencias(con)


# --- Cuándo buscar -----------------------------------------------------------------


def _segundos(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        cuando = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if cuando.tzinfo is None:
        cuando = cuando.replace(tzinfo=timezone.utc)
    return cuando.timestamp()


def _iso(segundos: float | None) -> str | None:
    if segundos is None:
        return None
    return datetime.fromtimestamp(segundos, timezone.utc).isoformat(timespec="seconds")


def ultima_iniciada(con) -> float | None:
    """Cuándo empezó la última búsqueda, fuera bien o mal.

    La que empezó y no terminó cuenta igual: sin red, la última que fue bien no avanza
    nunca, y se volvería a intentar cada minuto.
    """
    fila = con.execute("SELECT MAX(iniciada) FROM busquedas").fetchone()
    return _segundos(fila[0] if fila else None)


def toca_buscar(*, intervalo_min: int, ahora: float, arrancado: float,
                ultima: float | None, ultimo_intento: float | None,
                hay_busqueda: bool, hay_actualizacion: bool,
                etapas_pendientes: bool) -> bool:
    """La decisión entera, sin efectos, para poder probarla con un reloj de mentira."""
    if intervalo_min <= 0:
        return False
    # Con etapas de la carga inicial por hacer, una búsqueda normal escribiría el cursor
    # de PLACSP y dejaría un hueco entre el último ZIP y hoy (ver `buscarLoNuevo` en la
    # web): esas las retoma la propia aplicación, no esto.
    if hay_busqueda or hay_actualizacion or etapas_pendientes:
        return False
    if ahora - arrancado < GRACIA_ARRANQUE:
        return False
    referencias = [t for t in (ultima, ultimo_intento) if t is not None]
    if not referencias:
        return True
    return ahora - max(referencias) >= intervalo_min * 60


class Planificador:
    """Un hilo que cada minuto mira si toca buscar y, si toca, lanza la búsqueda normal.

    La misma que «Buscar ahora» (`busqueda.lanzar`), con su cerrojo: si la tarea de las
    mañanas o el botón se adelantan, esta se aparta.
    """

    def __init__(self, ruta_bd: Path | str, *, bd: Path | str | None = None,
                 reloj=time.time, lanzar=None, comprobar_cada: float = COMPROBAR_CADA):
        self.ruta_bd = ruta_bd
        self.bd = bd
        self.reloj = reloj
        self._lanzar = lanzar or busqueda.lanzar
        self.cada = comprobar_cada
        self.arrancado = reloj()
        self.ultimo_intento: float | None = None
        self._parada = threading.Event()
        self._hilo: threading.Thread | None = None

    def iniciar(self) -> None:
        if self._hilo is not None:
            return
        self._parada.clear()
        self._hilo = threading.Thread(target=self._bucle, name="planificador", daemon=True)
        self._hilo.start()

    def parar(self) -> None:
        self._parada.set()
        if self._hilo is not None:
            self._hilo.join(timeout=1.0)
        self._hilo = None

    def _bucle(self) -> None:
        while not self._parada.wait(self.cada):
            try:
                self.tic()
            except Exception:  # noqa: BLE001 - un fallo no puede parar el hilo para siempre
                log.exception("El planificador ha fallado al decidir si buscar")

    def tic(self) -> bool:
        """Una vuelta. True si ha lanzado una búsqueda."""
        from . import actualizacion, pipeline

        con = db.abrir(self.ruta_bd)
        try:
            intervalo = preferencias(con)["intervalo_min"]
            ultima = ultima_iniciada(con)
            pendientes = db.etapas_pendientes(con, len(pipeline.ETAPAS_PRIMERA_CARGA))
        finally:
            con.close()
        ahora = self.reloj()
        if not toca_buscar(
            intervalo_min=intervalo, ahora=ahora, arrancado=self.arrancado,
            ultima=ultima, ultimo_intento=self.ultimo_intento,
            hay_busqueda=busqueda.en_marcha() is not None,
            hay_actualizacion=actualizacion.en_marcha() is not None,
            etapas_pendientes=bool(pendientes),
        ):
            return False
        self.ultimo_intento = ahora
        try:
            self._lanzar(bd=self.bd)
        except RuntimeError:
            return False  # otra se ha adelantado entre la comprobación y el lanzamiento
        except OSError as exc:
            log.warning("No se ha podido lanzar la búsqueda automática: %s", exc)
            return False
        log.info("Búsqueda automática lanzada (cada %d min)", intervalo)
        return True

    def proxima(self, con) -> float | None:
        intervalo = preferencias(con)["intervalo_min"]
        if intervalo <= 0:
            return None
        referencias = [t for t in (ultima_iniciada(con), self.ultimo_intento)
                       if t is not None]
        base = max(referencias) if referencias else self.reloj()
        return max(base + intervalo * 60, self.arrancado + GRACIA_ARRANQUE)


_ACTUAL: Planificador | None = None


def iniciar(ruta_bd: Path | str, *, bd: Path | str | None = None) -> Planificador | None:
    """Arranca el planificador de este proceso. Lo llama `radar.py serve`.

    `RADAR_SIN_AUTOMATICA` lo apaga: para mirar la interfaz contra la base real sin que
    se ponga a descargar por su cuenta.
    """
    global _ACTUAL
    if os.environ.get("RADAR_SIN_AUTOMATICA"):
        log.info("Búsqueda automática desactivada por RADAR_SIN_AUTOMATICA")
        return None
    if _ACTUAL is None:
        _ACTUAL = Planificador(ruta_bd, bd=bd)
        _ACTUAL.iniciar()
    return _ACTUAL


def estado(con) -> dict:
    """Las preferencias y lo que se ve debajo de ellas: cuándo fue y cuándo toca."""
    datos = preferencias(con)
    datos["activa"] = _ACTUAL is not None
    datos["intervalos"] = list(INTERVALOS)
    datos["ultima_iniciada"] = _iso(ultima_iniciada(con))
    datos["proxima"] = _iso(_ACTUAL.proxima(con)) if _ACTUAL is not None else None
    return datos


# --- Avisos ------------------------------------------------------------------------


def _ultima_terminada(con) -> int:
    fila = con.execute(
        "SELECT COALESCE(MAX(id), 0) FROM busquedas WHERE terminada IS NOT NULL"
    ).fetchone()
    return int(fila[0])


def preparar_marca(con) -> int:
    """La primera vez se avisa de lo que llegue a partir de ahora, no del histórico."""
    valor = db.leer_preferencia(con, PREF_MARCA)
    try:
        if valor is not None:
            return int(valor)
    except ValueError:
        pass
    marca = _ultima_terminada(con)
    db.escribir_preferencia(con, PREF_MARCA, str(marca))
    con.commit()
    return marca


def _plural(n: int, uno: str, varios: str) -> str:
    return f"{n} {uno if n == 1 else varios}"


def avisos_pendientes(con, *, perfiles_activos: list[str] | None = None) -> dict:
    """Lo que han traído las búsquedas terminadas desde el último aviso.

    `hasta` es la búsqueda hasta la que llega esto: es lo que se devuelve en
    `/api/avisos/entregados` después de enseñar el aviso, aunque no haya nada que avisar,
    para no volver a mirar las mismas búsquedas cada minuto.
    """
    salida = {**preferencias(con), "hasta": None, "total": 0, "por_perfil": [],
              "titulos": [], "titulo": None, "cuerpo": None}
    marca = preparar_marca(con)
    filas = con.execute(
        """SELECT id, id_desde, id_hasta, primera_carga FROM busquedas
            WHERE id > ? AND terminada IS NOT NULL ORDER BY id""",
        (marca,),
    ).fetchall()
    if not filas:
        return salida
    salida["hasta"] = filas[-1]["id"]
    # La carga inicial no se avisa: son miles de expedientes de hace dos años, y la
    # pantalla de arranque ya lo cuenta.
    normales = [f for f in filas if not f["primera_carga"] and f["id_hasta"] is not None]
    if not normales:
        return salida
    novedades = consultas.novedades_entre(
        con, min(f["id_desde"] for f in normales), max(f["id_hasta"] for f in normales),
        perfiles_activos=perfiles_activos)
    total = novedades["total"]
    salida["total"] = total
    if not total:
        return salida
    salida["por_perfil"] = [p for p in novedades["por_perfil"] if p["total"]]
    salida["titulos"] = [(it.get("objeto") or "").strip()
                         for it in novedades["items"][:TITULOS_EN_AVISO]]
    salida["titulo"] = _plural(total, "licitación nueva", "licitaciones nuevas")
    reparto = " · ".join(f"{p['perfil']} {p['total']}" for p in salida["por_perfil"])
    primeras = "\n".join(f"• {t[:110]}" for t in salida["titulos"] if t)
    salida["cuerpo"] = "\n".join(x for x in (reparto, primeras) if x)
    return salida


def marcar_entregados(con, hasta: int) -> int:
    """Avanza la marca hasta esa búsqueda. Nunca hacia atrás."""
    marca = max(preparar_marca(con), int(hasta))
    db.escribir_preferencia(con, PREF_MARCA, str(marca))
    con.commit()
    return marca
