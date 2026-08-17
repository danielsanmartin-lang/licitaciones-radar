"""Consultas de lectura para la bandeja y el export.

Se aísla del servidor para poder probarlas sin levantar HTTP.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime

from .model import ESTADOS_VIVOS

ORDENES = {
    # "Cierran antes" tiene que poner primero lo que cierra pronto y AÚN está
    # abierto. Ordenar solo por días restantes ascendente dejaba arriba lo vencido
    # hace cuatro años, que es lo último que le interesa a nadie.
    # Tres grupos: primero lo abierto con plazo (lo que cierra antes arriba),
    # después lo que no publica plazo, y al final lo vencido. Dentro de lo vencido
    # se invierte el orden: lo que cerró la semana pasada aún sirve para seguir la
    # adjudicación; lo de hace cuatro años no.
    "urgencia": (
        "CASE WHEN orden_urgencia < 0 THEN 2 "
        "     WHEN orden_urgencia = 9999 THEN 1 "
        "     ELSE 0 END ASC, "
        "CASE WHEN orden_urgencia < 0 THEN -orden_urgencia ELSE orden_urgencia END ASC, "
        "puntuacion DESC"
    ),
    "puntuacion": "puntuacion DESC, l.fecha_publicacion DESC",
    "reciente": "l.fecha_publicacion DESC",
    "importe": "l.importe_referencia DESC",
}

# Todas las ordenaciones terminan en `l.id`. Sin un criterio único al final, SQLite
# no garantiza el mismo orden entre dos consultas, y con LIMIT/OFFSET eso significa
# que la página 2 puede repetir filas de la página 1 y perder otras. Hay cientos de
# licitaciones empatadas a 3.0 de puntuación, así que no es un caso teórico.
ORDENES = {clave: f"{expr}, l.id ASC" for clave, expr in ORDENES.items()}

# Clave con la que se agrupan los anuncios de un mismo expediente. Los registros
# que vienen de la versión anterior tienen `clave_grupo` a NULL hasta que se
# vuelven a ingerir, y el COALESCE hace que entonces cada uno sea su propio grupo:
# la vista funciona igual, solo que sin agrupar todavía.
_GRUPO = "COALESCE(l.clave_grupo, CAST(l.id AS TEXT))"


def _dias_restantes(limite: str | None) -> int | None:
    if not limite:
        return None
    try:
        fecha = datetime.fromisoformat(limite).date()
    except ValueError:
        try:
            fecha = date.fromisoformat(limite[:10])
        except ValueError:
            return None
    return (fecha - date.today()).days


def _condiciones(
    con: sqlite3.Connection,
    *,
    perfil: str | None = None,
    estado_revision: str | None = None,
    solo_vivas: bool = True,
    cierran_en_dias: int | None = None,
    ccaa: str | None = None,
    fuente: str | None = None,
    importe_min: float | None = None,
    busqueda: str | None = None,
    solo_novedades: bool = False,
) -> tuple[list[str], list]:
    """Construye el WHERE de la bandeja. Lo comparten la lista y los contadores.

    Está extraído a propósito: los contadores de la cabecera tenían sus propias
    consultas y acabaron contando otra cosa que la lista (decían 945 sin revisar
    donde la lista mostraba 57). Con un solo sitio donde se deciden los filtros,
    no pueden volver a divergir.
    """
    where = ["1=1"]
    params: list = []

    if perfil:
        where.append("m.perfil = ?")
        params.append(perfil)
    if estado_revision:
        where.append("COALESCE(r.estado, 'nuevo') = ?")
        params.append(estado_revision)
    else:
        # Por defecto, lo descartado no estorba.
        where.append("COALESCE(r.estado, 'nuevo') != 'descartado'")
    if solo_vivas:
        # "Abierta" son dos condiciones, no una: que el estado siga vivo Y que el
        # plazo no haya pasado. Hay licitaciones catalanas en estado "publicada"
        # con fecha límite de hace cuatro años; filtrar solo por estado las colaba.
        marcas = ", ".join("?" * len(ESTADOS_VIVOS))
        where.append(f"l.estado IN ({marcas})")
        params.extend(sorted(ESTADOS_VIVOS))
        where.append(
            "(l.fecha_limite_presentacion IS NULL"
            " OR substr(l.fecha_limite_presentacion, 1, 10) >= date('now'))"
        )
    if cierran_en_dias is not None:
        where.append(
            "substr(l.fecha_limite_presentacion, 1, 10) "
            "BETWEEN date('now') AND date('now', ?)"
        )
        params.append(f"+{int(cierran_en_dias)} day")
    if ccaa:
        where.append("l.ccaa = ?")
        params.append(ccaa)
    if fuente:
        where.append("l.fuente LIKE ?")
        params.append(f"{fuente}%")
    if importe_min:
        where.append("l.importe_referencia >= ?")
        params.append(importe_min)
    if busqueda:
        where.append(
            "l.id IN (SELECT rowid FROM licitaciones_fts WHERE licitaciones_fts MATCH ?)"
        )
        params.append(busqueda)
    if solo_novedades:
        marca = _marca_visita(con)
        if marca is not None:
            where.append("l.id > ?")
            params.append(marca)

    return where, params


def contar(con: sqlite3.Connection, **filtros) -> int:
    """Cuántos expedientes cumplen esos filtros. La misma unidad que la lista."""
    where, params = _condiciones(con, **filtros)
    return con.execute(
        f"""SELECT COUNT(*) FROM (
                SELECT {_GRUPO} AS g
                  FROM licitaciones l
                  JOIN matches m ON m.licitacion_id = l.id
                  LEFT JOIN revisiones r ON r.licitacion_id = l.id
                 WHERE {" AND ".join(where)}
                 GROUP BY g
            )""",
        params,
    ).fetchone()[0]


def bandeja(
    con: sqlite3.Connection,
    *,
    perfil: str | None = None,
    estado_revision: str | None = None,
    solo_vivas: bool = True,
    cierran_en_dias: int | None = None,
    ccaa: str | None = None,
    fuente: str | None = None,
    importe_min: float | None = None,
    busqueda: str | None = None,
    solo_novedades: bool = False,
    orden: str = "urgencia",
    limite: int = 200,
    offset: int = 0,
) -> dict:
    """Licitaciones que han casado con algún perfil, con su estado de triaje."""
    filtros = dict(
        perfil=perfil, estado_revision=estado_revision, solo_vivas=solo_vivas,
        cierran_en_dias=cierran_en_dias, ccaa=ccaa, fuente=fuente,
        importe_min=importe_min, busqueda=busqueda, solo_novedades=solo_novedades,
    )
    where, params = _condiciones(con, **filtros)
    orden_sql = ORDENES.get(orden, ORDENES["urgencia"])

    # Dos agrupaciones encadenadas, cada una arreglando un problema distinto:
    #
    # 1. `GROUP BY l.id` — una licitación puede casar con varios perfiles y el JOIN
    #    devolvía una fila por cada uno, así que salía repetida mientras `total`
    #    contaba licitaciones distintas. Eso descuadraba también la paginación,
    #    porque `offset` avanza contando filas.
    # 2. `PARTITION BY clave_grupo` — una misma licitación genera varios anuncios a
    #    lo largo de su vida (licitación, corrección, adjudicación por lotes) y cada
    #    uno es un registro: LANTIK aparecía dos veces y CSIRT Canarias cuatro. Se
    #    queda el anuncio más reciente de cada expediente, con el número de anuncios
    #    del grupo para poder decirlo en la tarjeta.
    sql = f"""
        SELECT * FROM (
            SELECT l.*,
                   group_concat(DISTINCT m.perfil) AS perfil,
                   MAX(m.puntuacion) AS puntuacion,
                   group_concat(m.motivo, '  ||  ') AS motivo,
                   COALESCE(r.estado, 'nuevo') AS estado_revision,
                   r.asignado_a, r.notas, r.motivo_descarte,
                   CASE
                     WHEN l.fecha_limite_presentacion IS NULL THEN 9999
                     ELSE CAST(julianday(substr(l.fecha_limite_presentacion, 1, 10))
                               - julianday('now') AS INTEGER)
                   END AS orden_urgencia,
                   COUNT(*) OVER (PARTITION BY {_GRUPO}) AS anuncios,
                   ROW_NUMBER() OVER (
                       PARTITION BY {_GRUPO}
                       ORDER BY l.fecha_publicacion DESC, l.id DESC
                   ) AS _rn
              FROM licitaciones l
              JOIN matches m ON m.licitacion_id = l.id
              LEFT JOIN revisiones r ON r.licitacion_id = l.id
             WHERE {" AND ".join(where)}
             GROUP BY l.id
        ) l
         WHERE _rn = 1
         ORDER BY {orden_sql}
         LIMIT ? OFFSET ?
    """
    filas = con.execute(sql, [*params, limite, offset]).fetchall()

    total = contar(con, **filtros)

    # Cuántas habría sin los filtros del usuario, para poder decir "57 de 668" y
    # que se entienda por qué no salen todas.
    total_sin_filtros = contar(con, solo_vivas=False)

    items = []
    for f in filas:
        d = dict(f)
        d["cpv"] = (d.get("cpv") or "").split()
        try:
            d["urls_pliegos"] = json.loads(d.get("urls_pliegos") or "[]")
        except json.JSONDecodeError:
            d["urls_pliegos"] = []
        d.pop("raw", None)
        d.pop("texto_busqueda", None)
        d["dias_restantes"] = _dias_restantes(d.get("fecha_limite_presentacion"))
        items.append(d)

    return {"total": total, "total_sin_filtros": total_sin_filtros, "items": items}


def resumen(con: sqlite3.Connection, *, en_marcha: bool = False) -> dict:
    """Cifras de cabecera y salud de las fuentes.

    Cada cifra se calcula con `contar()`, que es la misma función que usa la lista.
    Antes cada contador tenía su propia consulta y acabaron midiendo cosas
    distintas: la cabecera decía 945 «sin revisar» y al pulsar el filtro salían 57,
    porque la lista agrupa los anuncios de un expediente y los contadores no.

    No se publica el recuento de lo descargado que no cumple los criterios: es un
    número que no se puede consultar en ninguna vista y solo despista.

    `en_marcha` dice si hay una ingesta corriendo ahora mismo. Lo sabe quien llama —el
    servidor tiene el cerrojo a mano— y sirve para no confundir una fila de registro
    todavía abierta con una fuente rota.
    """
    # También por expedientes agrupados: si aquí se contaran anuncios, el desglose
    # sumaría 921 mientras el total de arriba dice 640, que es justo la incoherencia
    # que había que quitar.
    nombres = [
        f["perfil"] for f in con.execute("SELECT DISTINCT perfil FROM matches ORDER BY perfil")
    ]
    perfiles = sorted(
        (
            {
                "perfil": nombre,
                "total": contar(con, solo_vivas=False, perfil=nombre),
                "nuevos": contar(
                    con, solo_vivas=False, perfil=nombre, estado_revision="nuevo"
                ),
            }
            for nombre in nombres
        ),
        key=lambda p: -p["total"],
    )

    return {
        # Todas las coincidencias, sin filtrar por plazo ni por triaje. Es el
        # denominador de "57 de 668".
        "coincidencias": contar(con, solo_vivas=False),
        "en_plazo": contar(con, solo_vivas=True),
        "cierran_7_dias": contar(con, solo_vivas=True, cierran_en_dias=7),
        "sin_revisar": contar(con, solo_vivas=False, estado_revision="nuevo"),
        "siguiendo": contar(con, solo_vivas=False, estado_revision="siguiendo"),
        "presentadas": contar(con, solo_vivas=False, estado_revision="presentada"),
        "novedades": _novedades(con),
        "ultima_visita": _ultima_visita(con),
        "ultima_busqueda": _ultima_busqueda(con),
        "por_perfil": perfiles,
        "ccaa": [
            dict(f)
            for f in con.execute(
                """SELECT l.ccaa, COUNT(DISTINCT l.id) AS total
                     FROM licitaciones l JOIN matches m ON m.licitacion_id = l.id
                    WHERE l.ccaa IS NOT NULL
                    GROUP BY l.ccaa ORDER BY total DESC"""
            )
        ],
        "fuentes": _salud(con, en_marcha),
    }


def _ultima_busqueda(con) -> str | None:
    """Cuándo terminó la última ingesta que fue bien, para poder mostrarla."""
    fila = con.execute(
        """SELECT MAX(terminado_en) AS cuando FROM ingest_log
            WHERE ok = 1 AND terminado_en IS NOT NULL"""
    ).fetchone()
    return fila["cuando"] if fila else None


def _preferencia(con, clave: str) -> str | None:
    fila = con.execute("SELECT valor FROM preferencias WHERE clave = ?", (clave,)).fetchone()
    return fila["valor"] if fila else None


def _ultima_visita(con) -> str | None:
    return _preferencia(con, "ultima_visita")


def _marca_visita(con) -> int | None:
    """Último id de licitación visto en la visita anterior.

    Se usa el id y no la hora a propósito: las marcas de tiempo tienen resolución de
    segundo, así que una ingesta que termina en el mismo segundo en que se marca la
    visita dejaría sus licitaciones fuera de las novedades. Los ids son monotónicos
    y no tienen ese problema.
    """
    valor = _preferencia(con, "ultima_visita_id")
    try:
        return int(valor) if valor is not None else None
    except ValueError:
        return None


def _novedades(con) -> int:
    """Coincidencias que han entrado después de la última visita."""
    marca = _marca_visita(con)
    if marca is None:
        return 0
    return con.execute(
        """SELECT COUNT(DISTINCT l.id)
             FROM licitaciones l
             JOIN matches m ON m.licitacion_id = l.id
             LEFT JOIN revisiones r ON r.licitacion_id = l.id
            WHERE l.id > ?
              AND COALESCE(r.estado, 'nuevo') != 'descartado'""",
        (marca,),
    ).fetchone()[0]


def _salud(con, en_marcha: bool = False) -> list[dict]:
    filas = con.execute(
        """SELECT l.fuente, l.iniciado_en, l.terminado_en, l.vistos, l.nuevos,
                  l.actualizados, l.ok, l.error
             FROM ingest_log l
             JOIN (SELECT fuente, MAX(id) AS ult FROM ingest_log GROUP BY fuente) u
               ON u.ult = l.id
            ORDER BY l.fuente"""
    ).fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        # Una fuente que no trae nada y una fuente rota se ven igual si no se avisa.
        #
        # Pero mientras la ingesta corre su fila está abierta (`terminado_en` a NULL y
        # `ok` a 0), y eso es indistinguible de un fallo si solo se mira `ok`. Sin
        # `en_marcha`, una carga inicial en segundo plano pintaba «la última ingesta
        # falló» en rojo durante las dos horas que dura.
        #
        # Hace falta el dato de fuera, no basta con `terminado_en`: una ingesta cortada
        # a lo bruto deja la fila abierta para siempre, y ésa sí es un fallo que hay
        # que contar.
        d["en_curso"] = d["terminado_en"] is None and en_marcha
        d["aviso"] = None
        if not d["en_curso"]:
            if not d["ok"]:
                d["aviso"] = "la última ingesta falló"
            elif d["vistos"] == 0:
                d["aviso"] = "la última ingesta no trajo ningún registro"
        salida.append(d)
    return salida


# Ordenados de más largo a más corto: hay que quitar "s l u" antes de que "s l"
# lo parta por la mitad y deje una "u" suelta.
_SUFIJOS = (
    "sociedad cooperativa", "sociedad limitada", "sociedad anonima",
    "s l u", "s l p", "s l l", "s a u", "s a m", "s coop",
    "s l", "s a", "sau", "slu", "sll", "slp", "sa", "sl", "ute", "sme", "mp",
)


def normalizar_empresa(nombre: str | None) -> str | None:
    """Agrupa variantes de la misma razón social.

    "S2 GRUPO SOLUCIONES DE SEGURIDAD, S.L.U.", "S2 Grupo Soluciones de Seguridad
    S.L.U." y "S2 GRUPO SOLUCIONES DE SEGURIDAD, S.L." son el mismo proveedor y
    aparecían como tres. Sin esto, un ranking de adjudicatarios no sirve para nada.
    """
    if not nombre:
        return None
    import re
    import unicodedata

    t = unicodedata.normalize("NFD", nombre.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[.,;:()\"']", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    for sufijo in _SUFIJOS:
        t = re.sub(rf"(^|\s){re.escape(sufijo)}(\s|$)", " ", t)
    return re.sub(r"\s+", " ", t).strip() or None


def competencia(con: sqlite3.Connection, *, limite: int = 20) -> list[dict]:
    """Quién se está llevando estos contratos y por cuánto.

    Sale gratis del historial y probablemente vale más que las alertas de lo nuevo:
    dice contra quién se compite, a qué precios y en qué organismos.

    En la aplicación esto es la pestaña «Adjudicatarios» (`/api/adjudicatarios`); el
    nombre de aquí se quedó del original y no lo ve nadie desde fuera.
    """
    # Deduplicar por licitación no es opcional: sin ello, una que casa con dos
    # perfiles se contaba dos veces y el ranking no cuadraba con su propio
    # desglose (Vodafone salía con 6 contratos y al abrirlo mostraba 4). Se hace
    # con un DISTINCT sobre `matches` en lugar de un `GROUP BY l.id` sobre el
    # cruce, porque además de deduplicar es lo que decide por dónde entra la
    # consulta: partiendo de las ~3.000 filas de `matches` y buscando cada
    # licitación por clave primaria, en vez de recorrer las 450.000 de
    # `licitaciones`. Es la misma lección que `contratos_de`: 4,6 s -> 0,03 s.
    filas = con.execute(
        """SELECT l.adjudicatario,
                  COALESCE(l.importe_adjudicacion, l.importe_referencia) AS importe,
                  l.organo
             FROM (SELECT DISTINCT licitacion_id FROM matches) m
             JOIN licitaciones l ON l.id = m.licitacion_id
            WHERE l.adjudicatario IS NOT NULL"""
    ).fetchall()

    agrupado: dict[str, dict] = {}
    for f in filas:
        clave = normalizar_empresa(f["adjudicatario"])
        if not clave:
            continue
        entrada = agrupado.setdefault(
            clave, {"empresa": f["adjudicatario"], "contratos": 0, "importe": 0.0,
                    "organos": set(), "variantes": set()}
        )
        entrada["contratos"] += 1
        entrada["importe"] += f["importe"] or 0
        if f["organo"]:
            entrada["organos"].add(f["organo"])
        entrada["variantes"].add(f["adjudicatario"])

    salida = []
    for datos in agrupado.values():
        # Se muestra la variante más larga: suele ser la razón social completa.
        datos["empresa"] = max(datos["variantes"], key=len)
        datos["organos"] = len(datos["organos"])
        datos.pop("variantes")
        salida.append(datos)
    salida.sort(key=lambda d: (-d["contratos"], -d["importe"]))
    return salida[:limite]


def contratos_de(con: sqlite3.Connection, empresa: str, *, limite: int = 60) -> list[dict]:
    """Contratos de un adjudicatario, agrupando sus variantes de razón social.

    El filtro fino tiene que hacerse en Python porque la agrupación de razones
    sociales no se puede expresar en SQL. Traer las 99.000 filas adjudicadas de la
    tabla entera para descartarlas aquí tardaba 2,2 segundos; entrando por
    `matches` baja a milisegundos, porque son unos cientos de filas.

    Se probó además a acotar con un `LIKE` sobre el nombre, y era un error: el LIKE
    va contra la columna sin normalizar, que lleva acentos ("INFORMACIÓN"), mientras
    el término salía de la clave ya normalizada. Perdía variantes de la misma
    empresa y el desglose no cuadraba con el ranking.
    """
    clave = normalizar_empresa(empresa)
    if not clave:
        return []

    filas = con.execute(
        """SELECT l.id, l.objeto, l.organo, l.adjudicatario, l.fecha_adjudicacion,
                  l.fecha_fin_prevista, l.url_detalle,
                  COALESCE(l.importe_adjudicacion, l.importe_referencia) AS importe
             FROM licitaciones l
            WHERE l.adjudicatario IS NOT NULL
              AND l.id IN (SELECT licitacion_id FROM matches)
            ORDER BY l.fecha_adjudicacion DESC, l.id ASC"""
    ).fetchall()
    salida = [dict(f) for f in filas if normalizar_empresa(f["adjudicatario"]) == clave]
    return salida[:limite]


def motivos_descarte(con: sqlite3.Connection) -> list[dict]:
    """Por qué se descarta, para afinar los perfiles con datos en vez de a ojo.

    Cuenta expedientes, como el resto de la aplicación. El triaje se guarda en todos
    los anuncios del expediente (ver `db.ids_del_grupo`), así que contar filas de
    `revisiones` diría "4 descartadas por importe bajo" donde hubo una sola decisión
    sobre una licitación con cuatro anuncios.
    """
    return [
        dict(f)
        for f in con.execute(
            f"""SELECT motivo, COUNT(*) AS total FROM (
                    SELECT COALESCE(r.motivo_descarte, '(sin motivo)') AS motivo,
                           {_GRUPO} AS g
                      FROM revisiones r
                      JOIN licitaciones l ON l.id = r.licitacion_id
                     WHERE r.estado = 'descartado'
                     GROUP BY g, motivo
                )
                GROUP BY motivo ORDER BY total DESC"""
        )
    ]


# Ventana de vencimiento. La columna se compara DESNUDA a propósito: envolverla en
# `substr(..., 1, 10)` —como estaba— impide que SQLite use `idx_lic_fin` y convierte
# cada consulta en un recorrido completo de las 450.000 licitaciones (4,7 s la lista
# y 19,2 s las cuatro ventanas, medido). El `+1 day` del extremo superior es lo que
# conserva la semántica que daba el substr, porque las fechas pueden traer hora:
# '2027-02-11T10:00' vence el 11 de febrero y tiene que entrar en la ventana que
# acaba ese día. El `>= date('now')` descarta además los nulos por sí solo.
EN_VENTANA = (
    "l.fecha_fin_prevista >= date('now')"
    " AND l.fecha_fin_prevista < date('now', ?, '+1 day')"
)


def vencimientos(con: sqlite3.Connection, *, meses: int = 6, limite: int = 200) -> dict:
    """Contratos ya adjudicados cuyo plazo termina pronto.

    Es la lista para llamar ANTES de que salga el pliego, cuando el incumbente aún no
    ha renovado. Solo aparecen los que tienen fecha de fin conocida: si la fuente no
    la publica y no se puede deducir de la duración, la licitación no entra aquí en
    lugar de entrar con una fecha inventada.
    """
    filas = con.execute(
        f"""SELECT l.id, l.objeto, l.organo, l.ccaa, l.fuente, l.url_detalle,
                   l.adjudicatario, l.fecha_adjudicacion, l.duracion_meses,
                   l.fecha_inicio_ejecucion, l.fecha_fin_prevista,
                   COALESCE(l.importe_adjudicacion, l.importe_referencia) AS importe,
                   group_concat(DISTINCT m.perfil) AS perfil,
                   CAST(julianday(substr(l.fecha_fin_prevista, 1, 10))
                        - julianday('now') AS INTEGER) AS dias_para_vencer
              FROM licitaciones l
              JOIN matches m ON m.licitacion_id = l.id
              LEFT JOIN revisiones r ON r.licitacion_id = l.id
             WHERE {EN_VENTANA}
               AND COALESCE(r.estado, 'nuevo') != 'descartado'
             GROUP BY l.id
             ORDER BY l.fecha_fin_prevista ASC, importe DESC, l.id ASC
             LIMIT ?""",
        (f"+{int(meses)} months", limite),
    ).fetchall()

    agregado = con.execute(
        f"""SELECT COUNT(*) AS total, COALESCE(SUM(importe), 0) AS importe FROM (
                SELECT COALESCE(l.importe_adjudicacion, l.importe_referencia) AS importe
                  FROM licitaciones l
                  JOIN matches m ON m.licitacion_id = l.id
                  LEFT JOIN revisiones r ON r.licitacion_id = l.id
                 WHERE {EN_VENTANA}
                   AND COALESCE(r.estado, 'nuevo') != 'descartado'
                 GROUP BY l.id
            )""",
        (f"+{int(meses)} months",),
    ).fetchone()

    return {
        "total": agregado["total"],
        "importe_total": agregado["importe"],
        "meses": meses,
        "items": [dict(f) for f in filas],
        # Recuento de cada ventana, para poder comparar de un vistazo sin cambiar
        # de selección una por una.
        "por_ventana": ventanas_vencimiento(con),
    }


def ventanas_vencimiento(con: sqlite3.Connection,
                         ventanas: tuple[int, ...] = (3, 6, 12, 24)) -> list[dict]:
    """Cuántos contratos vencen en cada ventana y por cuánto importe.

    Una sola pasada, no una consulta por ventana: las ventanas estrechas están
    contenidas en la más ancha, así que sus recuentos salen de la misma lectura con
    agregación condicional. Cuatro consultas casi idénticas sobre 450.000
    licitaciones tardaban 19,2 s; así tarda 0,04 s.
    """
    meses = [int(m) for m in ventanas]
    if not meses:
        return []

    # El orden de los parámetros es el de aparición en el texto de la consulta:
    # primero los de cada ventana, y el de la ventana ancha al final, dentro de
    # EN_VENTANA.
    columnas, params = [], []
    for i, m in enumerate(meses):
        columnas.append(
            f"COUNT(CASE WHEN fin < date('now', ?, '+1 day') THEN 1 END) AS n{i}"
        )
        columnas.append(
            "COALESCE(SUM(CASE WHEN fin < date('now', ?, '+1 day') THEN importe END), 0)"
            f" AS i{i}"
        )
        params += [f"+{m} months", f"+{m} months"]
    params.append(f"+{max(meses)} months")

    f = con.execute(
        f"""SELECT {', '.join(columnas)} FROM (
                SELECT l.fecha_fin_prevista AS fin,
                       COALESCE(l.importe_adjudicacion, l.importe_referencia) AS importe
                  FROM licitaciones l
                  JOIN matches m ON m.licitacion_id = l.id
                  LEFT JOIN revisiones r ON r.licitacion_id = l.id
                 WHERE {EN_VENTANA}
                   AND COALESCE(r.estado, 'nuevo') != 'descartado'
                 GROUP BY l.id
            )""",
        params,
    ).fetchone()

    return [
        {"meses": m, "total": f[f"n{i}"], "importe": f[f"i{i}"]}
        for i, m in enumerate(meses)
    ]


def historial(con: sqlite3.Connection, licitacion_id: int) -> list[dict]:
    """Las versiones de una licitación, en el orden en que ocurrieron.

    Se ordena por la fecha de la fuente y no por `detectado_en`, que en el histórico
    es la misma para todas. El desempate por `id` no es decorativo: PLACSP publica
    fechas sin hora, y dos cambios del mismo día empatarían dejando el orden a merced
    del planificador de SQLite.
    """
    return [
        dict(f)
        for f in con.execute(
            """SELECT estado, estado_anterior, importe_referencia, adjudicatario,
                      detectado_en, fecha_cambio
                 FROM licitaciones_versiones
                WHERE licitacion_id = ?
                ORDER BY COALESCE(fecha_cambio, detectado_en), id""",
            (licitacion_id,),
        )
    ]


def para_csv(con: sqlite3.Connection, **filtros) -> tuple[list[str], list[list]]:
    filtros.setdefault("limite", 100000)
    datos = bandeja(con, **filtros)
    columnas = [
        "perfil", "puntuacion", "estado_revision", "dias_restantes", "organo", "objeto",
        "importe_referencia", "fecha_limite_presentacion", "fecha_publicacion", "estado",
        "procedimiento", "ccaa", "expediente", "cpv", "fuente", "url_detalle", "motivo",
        "adjudicatario", "notas",
    ]
    filas = []
    for item in datos["items"]:
        filas.append([
            " ".join(item[c]) if isinstance(item.get(c), list) else item.get(c, "")
            for c in columnas
        ])
    return columnas, filas
