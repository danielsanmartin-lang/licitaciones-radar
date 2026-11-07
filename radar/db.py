"""Base de datos SQLite: esquema, migraciones idempotentes y acceso.

Todo vive en un único fichero (`data/radar.db` por defecto), sin servidor y sin
credenciales. Cada persona tiene el suyo.

Dos tablas cargan el peso del diseño:

- `licitaciones` guarda el estado ACTUAL de cada licitación, con clave
  `(fuente, id_externo)`.
- `licitaciones_versiones` guarda un snapshot por cada cambio real detectado.
  Esto no es un extra: la especificación de sindicación de PLACSP dice que una
  licitación se republica tantas veces como se modifique, así que sin historial
  la bandeja mostraría duplicados sin fin. A cambio salen gratis los eventos de
  transición (`publicada -> adjudicada`) y saber cuándo vence un contrato para
  llegar a tiempo a la renovación.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import rutas

# La raíz se conserva para lo que de verdad cuelga del código; lo que se ESCRIBE va
# por `rutas`, que sabe distinguir una copia de trabajo de la app empaquetada.
RAIZ = rutas.CODIGO
BD_POR_DEFECTO = rutas.BD

ESQUEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS licitaciones (
    id                        INTEGER PRIMARY KEY,
    fuente                    TEXT NOT NULL,
    id_externo                TEXT NOT NULL,
    expediente                TEXT,
    organo                    TEXT,
    nif_organo                TEXT,
    objeto                    TEXT,
    descripcion               TEXT,
    cpv                       TEXT,
    importe_sin_iva           REAL,
    valor_estimado            REAL,
    importe_referencia        REAL,
    procedimiento             TEXT,
    tipo_contrato             TEXT,
    estado                    TEXT,
    estado_origen             TEXT,
    fecha_publicacion         TEXT,
    fecha_limite_presentacion TEXT,
    fecha_actualizacion       TEXT,
    nuts                      TEXT,
    lugar                     TEXT,
    ccaa                      TEXT,
    url_detalle               TEXT,
    urls_pliegos              TEXT,
    lote_num                  TEXT,
    lote_desc                 TEXT,
    adjudicatario             TEXT,
    importe_adjudicacion      REAL,
    fecha_adjudicacion        TEXT,
    duracion_meses            REAL,
    fecha_inicio_ejecucion    TEXT,
    fecha_fin_prevista        TEXT,
    clave_grupo               TEXT,
    -- Para estimar el fin cuando la fuente no da con qué calcularlo. Ver COLUMNAS_NUEVAS.
    fecha_formalizacion       TEXT,
    fecha_anuncio_adjudicacion TEXT,
    fecha_fin_estimada        TEXT,
    fin_origen                TEXT,
    fin_base                  TEXT,
    raw                       TEXT,
    huella                    TEXT NOT NULL,
    -- Huella con la que se evaluaron los perfiles la última vez. Ver COLUMNAS_NUEVAS.
    huella_evaluada           TEXT,
    texto_busqueda            TEXT,
    texto_norm                TEXT,
    -- Texto sobre el que corren las reglas: sin el nombre del órgano. Ver COLUMNAS_NUEVAS.
    texto_reglas_norm         TEXT,
    visto_primera_vez         TEXT NOT NULL,
    visto_ultima_vez          TEXT NOT NULL,
    UNIQUE (fuente, id_externo)
);

CREATE INDEX IF NOT EXISTS idx_lic_estado    ON licitaciones (estado);
CREATE INDEX IF NOT EXISTS idx_lic_limite    ON licitaciones (fecha_limite_presentacion);
CREATE INDEX IF NOT EXISTS idx_lic_pub       ON licitaciones (fecha_publicacion);
CREATE INDEX IF NOT EXISTS idx_lic_importe   ON licitaciones (importe_referencia);
CREATE INDEX IF NOT EXISTS idx_lic_fuente    ON licitaciones (fuente);
CREATE INDEX IF NOT EXISTS idx_lic_primera    ON licitaciones (visto_primera_vez);

-- Historial de cambios. Un registro por cada huella distinta vista.
CREATE TABLE IF NOT EXISTS licitaciones_versiones (
    id             INTEGER PRIMARY KEY,
    licitacion_id  INTEGER NOT NULL REFERENCES licitaciones(id) ON DELETE CASCADE,
    huella         TEXT NOT NULL,
    estado         TEXT,
    estado_anterior TEXT,
    importe_referencia REAL,
    adjudicatario  TEXT,
    detectado_en   TEXT NOT NULL,
    -- Cuándo ocurrió el cambio SEGÚN LA FUENTE, que no es cuándo lo vio el radar.
    -- `detectado_en` sirve para auditar la ingesta, pero como fecha del historial
    -- miente: en una carga histórica las ocho republicaciones de un expediente de
    -- 2024 se leen del mismo ZIP en el mismo minuto y las ocho saldrían con la fecha
    -- de hoy. Nullable a propósito: NULL significa «la fuente no publicó ninguna
    -- fecha», y es lo que permite a la interfaz decir «visto el …» en lugar de
    -- colar la fecha de hoy disfrazada de fecha oficial.
    fecha_cambio   TEXT,
    snapshot       TEXT NOT NULL,
    UNIQUE (licitacion_id, huella)
);

CREATE INDEX IF NOT EXISTS idx_ver_lic ON licitaciones_versiones (licitacion_id, detectado_en);

-- Índice de texto completo. `remove_diacritics 2` es lo que hace que buscar
-- "concienciacion" encuentre "concienciación" y "conscienciació" (catalán).
--
-- Se guarda el contenido en el propio índice en lugar de usar una tabla
-- contentless: esas no admiten DELETE salvo con `contentless_delete=1`, que pide
-- SQLite 3.43+. Un compañero con un macOS más viejo se lo comería. La copia del
-- texto cuesta unos pocos MB y elimina toda una clase de fallos de sincronía.
CREATE VIRTUAL TABLE IF NOT EXISTS licitaciones_fts USING fts5(
    texto_busqueda,
    tokenize='unicode61 remove_diacritics 2'
);

-- Resultado del matching: qué perfil ha casado y POR QUÉ.
CREATE TABLE IF NOT EXISTS matches (
    id            INTEGER PRIMARY KEY,
    licitacion_id INTEGER NOT NULL REFERENCES licitaciones(id) ON DELETE CASCADE,
    perfil        TEXT NOT NULL,
    puntuacion    REAL NOT NULL,
    motivo        TEXT NOT NULL,
    creado_en     TEXT NOT NULL,
    UNIQUE (licitacion_id, perfil)
);

CREATE INDEX IF NOT EXISTS idx_match_perfil ON matches (perfil, puntuacion DESC);

-- Temática de cada ficha, case o no con los perfiles (ver `radar/categorias.py`).
-- Multietiqueta, y lo que no es IT va a 'resto' en lugar de quedarse sin fila: así
-- filtrar por cualquiera de ellas es la misma búsqueda por índice. Es una tabla aparte
-- y no una columna por la misma razón que `matches`: la Analítica tiene que poder
-- ENTRAR por aquí —unos miles de filas por temática— en lugar de recorrer las 700.000
-- de `licitaciones` para quedarse con unas pocas.
CREATE TABLE IF NOT EXISTS categorias (
    licitacion_id INTEGER NOT NULL REFERENCES licitaciones(id) ON DELETE CASCADE,
    categoria     TEXT NOT NULL,
    PRIMARY KEY (licitacion_id, categoria)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_cat_categoria ON categorias (categoria, licitacion_id);

-- Triaje humano. Se conserva aunque el matching se reevalúe.
CREATE TABLE IF NOT EXISTS revisiones (
    licitacion_id INTEGER PRIMARY KEY REFERENCES licitaciones(id) ON DELETE CASCADE,
    estado        TEXT NOT NULL DEFAULT 'nuevo',
    asignado_a    TEXT,
    notas         TEXT,
    motivo_descarte TEXT,
    actualizado_en TEXT NOT NULL
);

-- Preferencias locales de quien usa la herramienta (última visita, etc.).
CREATE TABLE IF NOT EXISTS preferencias (
    clave  TEXT PRIMARY KEY,
    valor  TEXT,
    actualizado_en TEXT
);

-- Cursor de ingesta por fuente, para no reprocesar lo ya visto.
CREATE TABLE IF NOT EXISTS fuentes_cursor (
    fuente        TEXT PRIMARY KEY,
    cursor        TEXT,
    etag          TEXT,
    actualizado_en TEXT
);

-- Salud de las fuentes: sin esto, "no hay licitaciones" y "el conector está roto"
-- se ven exactamente igual en la bandeja.
CREATE TABLE IF NOT EXISTS ingest_log (
    id           INTEGER PRIMARY KEY,
    fuente       TEXT NOT NULL,
    iniciado_en  TEXT NOT NULL,
    terminado_en TEXT,
    vistos       INTEGER DEFAULT 0,
    nuevos       INTEGER DEFAULT 0,
    actualizados INTEGER DEFAULT 0,
    ok           INTEGER DEFAULT 0,
    error        TEXT
);

CREATE INDEX IF NOT EXISTS idx_ingest_fuente ON ingest_log (fuente, iniciado_en DESC);

-- Una fila por búsqueda (una ejecución de `radar.py ingest`), con el tramo de ids que
-- ha añadido. Es lo que permite decir «esta búsqueda ha traído 12 nuevas» sin
-- adivinarlo por fechas: los ids son monotónicos, así que lo que trajo es justo lo que
-- cae entre `id_desde` (exclusivo) e `id_hasta`. `ingest_log` no sirve para esto: va
-- por fuente, y no dice qué fichas son de qué ejecución.
CREATE TABLE IF NOT EXISTS busquedas (
    id            INTEGER PRIMARY KEY,
    iniciada      TEXT NOT NULL,
    terminada     TEXT,
    id_desde      INTEGER NOT NULL,
    id_hasta      INTEGER,
    primera_carga INTEGER NOT NULL DEFAULT 0,
    motivo        TEXT   -- completa | con_errores | atascada
);

-- Qué licitación ha salido de cada consulta preliminar de mercado (ver `enlaces.py`).
-- Son CANDIDATAS calculadas: se rehacen en cada búsqueda para los órganos que han
-- publicado algo nuevo, así que aquí no se guarda nada que haya decidido una persona.
-- `licitacion_id` es el primer anuncio del expediente posterior a la consulta.
CREATE TABLE IF NOT EXISTS enlaces_consulta (
    consulta_id      INTEGER NOT NULL REFERENCES licitaciones(id) ON DELETE CASCADE,
    licitacion_id    INTEGER NOT NULL REFERENCES licitaciones(id) ON DELETE CASCADE,
    puntuacion       REAL NOT NULL,
    mismo_expediente INTEGER NOT NULL DEFAULT 0,
    palabras         TEXT,
    PRIMARY KEY (consulta_id, licitacion_id)
);

CREATE INDEX IF NOT EXISTS idx_enlace_licitacion ON enlaces_consulta (licitacion_id);

-- Lo que sí decide una persona: «es esta» o «no es esta». Va aparte para que rehacer las
-- candidatas no lo borre.
CREATE TABLE IF NOT EXISTS enlaces_decision (
    consulta_id   INTEGER NOT NULL REFERENCES licitaciones(id) ON DELETE CASCADE,
    licitacion_id INTEGER NOT NULL REFERENCES licitaciones(id) ON DELETE CASCADE,
    decision      TEXT NOT NULL CHECK (decision IN ('si', 'no')),
    decidido_en   TEXT NOT NULL,
    PRIMARY KEY (consulta_id, licitacion_id)
);

-- La prospección de Vencimientos: en qué punto está cada contrato que vence. Por
-- expediente (`clave` es su `clave_grupo`, o el id si no tiene) y no por anuncio, como
-- el triaje. No reutiliza `revisiones`: aquello dice qué hiciste con el PLIEGO cuando
-- salió; esto, si has llamado al cliente para la renovación.
CREATE TABLE IF NOT EXISTS prospeccion (
    clave          TEXT PRIMARY KEY,
    estado         TEXT NOT NULL DEFAULT 'pendiente',
    nota           TEXT,
    actualizado_en TEXT NOT NULL
);
"""

# «vista» es lo que deja «Limpiar sin revisar»: ya no cuenta como pendiente, pero sigue en
# la Bandeja y en la Analítica, porque nadie ha decidido que no interese. Es la diferencia
# con «descartado», que sí quita de en medio.
ESTADOS_REVISION = ("nuevo", "vista", "siguiendo", "descartado", "presentada")


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conectar(ruta: Path | str | None = None) -> sqlite3.Connection:
    ruta = Path(ruta) if ruta else BD_POR_DEFECTO
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(ruta), timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    migrar(con)
    return con


# Columnas añadidas después de la primera versión. `CREATE TABLE IF NOT EXISTS` no
# toca una tabla que ya existe, así que sin esto las bases en uso —la de cada
# compañero, con su triaje y sus notas dentro— se quedarían sin los campos nuevos y
# la aplicación fallaría al consultarlos.
COLUMNAS_NUEVAS = {
    "licitaciones": [
        ("duracion_meses", "REAL"),
        ("fecha_inicio_ejecucion", "TEXT"),
        ("fecha_fin_prevista", "TEXT"),
        ("clave_grupo", "TEXT"),
        ("texto_norm", "TEXT"),
        # El texto sobre el que corren las reglas, sin el nombre del organismo
        # contratante. `texto_norm` sí lo lleva, porque la caja de búsqueda tiene que
        # encontrar por órgano; el matcher no, porque «Instituto Nacional de
        # CIBERSEGURIDAD» o «Departament d'Educació i FORMACIÓ Professional» le
        # regalaban el término y el contexto. Eran 125 de 535 coincidencias del perfil
        # de concienciación —el 23 %— y ninguna llevaba un término fuerte. El detalle
        # está en `Licitacion.texto_reglas`.
        ("texto_reglas_norm", "TEXT"),
        # Con qué huella se evaluaron los perfiles sobre esta ficha. Es lo único que
        # distingue «modificada de verdad» de «republicada idéntica»: `visto_ultima_vez`
        # no sirve, porque `guardar()` lo toca también en la rama «igual». Sin esta
        # columna, cada ingesta diaria reevaluaba las 673.755 filas de la base —39 s de
        # Python— y emitía 2,7 millones de DELETE contra una tabla `matches` de 3.705.
        ("huella_evaluada", "TEXT"),
        # La fecha de fin estimada cuando la fuente no da con qué calcularla, y con qué se
        # ha estimado. Ver `model.fin_estimado`. Va aparte de `fecha_fin_prevista` para
        # que una fecha estimada no pase nunca por publicada.
        ("fecha_formalizacion", "TEXT"),
        ("fecha_anuncio_adjudicacion", "TEXT"),
        ("fecha_fin_estimada", "TEXT"),
        ("fin_origen", "TEXT"),
        ("fin_base", "TEXT"),
    ],
    "revisiones": [
        ("motivo_descarte", "TEXT"),
    ],
    "licitaciones_versiones": [
        ("fecha_cambio", "TEXT"),
    ],
}


# Índices sobre columnas añadidas después. Van aquí y no en ESQUEMA porque el script
# del esquema se ejecuta antes de la migración, y crear un índice sobre una columna
# que la tabla vieja todavía no tiene aborta el arranque.
INDICES_NUEVOS = (
    "CREATE INDEX IF NOT EXISTS idx_lic_fin   ON licitaciones (fecha_fin_prevista)",
    "CREATE INDEX IF NOT EXISTS idx_lic_grupo ON licitaciones (clave_grupo)",
    # PARCIAL a propósito: solo indexa las filas pendientes de evaluar, que después de
    # cada pasada son cero. Así ocupa nada y convierte el «¿hay algo nuevo?» de cada
    # mañana en una búsqueda por índice en lugar de un recorrido de las 673.755 filas
    # (unos 700 MB de tabla leídos para casi siempre nada).
    #
    # El WHERE de la consulta tiene que ser LITERALMENTE éste: SQLite solo usa un
    # índice parcial cuando su condición coincide con la de la consulta, y comprobado
    # con EXPLAIN QUERY PLAN, escrito como `IS NULL OR <>` el índice no se usa.
    "CREATE INDEX IF NOT EXISTS idx_lic_pendientes ON licitaciones (id) "
    "WHERE huella_evaluada IS NOT huella",
)

# Índices que NO se crean al abrir la base sino en la búsqueda, que corre por detrás.
# Sobre una base real de 4 GB este tarda unos 18 s, y al abrir se crean ANTES de que el
# servidor conteste: la app de macOS espera como mucho 90 s y, si se pasa, se cierra
# matando la creación a medias, que vuelve a empezar en la siguiente apertura. En la
# búsqueda no tapa nada.
INDICE_CONSULTAS = "idx_lic_nif_exp"
INDICES_DIFERIDOS = (
    # Para enlazar una consulta previa con la licitación que sale de ella: mismo NIF de
    # órgano y mismo número de expediente, sin mayúsculas ni espacios. Es un índice de
    # EXPRESIÓN y la consulta tiene que escribir la expresión igual (ver
    # `consultas.EXPEDIENTE_NORMALIZADO`). Sin él, el cruce de las 2.297 consultas con
    # la base entera tardaba minutos.
    f"CREATE INDEX IF NOT EXISTS {INDICE_CONSULTAS} ON licitaciones "
    "(nif_organo, lower(replace(expediente, ' ', '')))",
)


def crear_indices_diferidos(con) -> None:
    for sql in INDICES_DIFERIDOS:
        con.execute(sql)
    con.commit()


def hay_indice(con, nombre: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?",
                       (nombre,)).fetchone() is not None


# Se sube cuando cambia la forma de calcular `clave_grupo`. Al detectar un valor
# distinto al guardado, se recalcula la clave de todas las filas a partir de los
# datos que ya están en la base, sin volver a descargar nada. Así la base de
# cualquier compañero se autocorrige al actualizar.
VERSION_CLAVE_GRUPO = "3"

# Se sube cuando cambia lo que se guarda en el snapshot de las versiones, para
# recortar de una vez las copias antiguas.
VERSION_SNAPSHOT = "2"

# Se sube cuando hay que rellenar `texto_norm` en las bases que vienen de antes.
VERSION_TEXTO_NORM = "1"

# Igual, para `texto_reglas_norm`. Va en su propia versión y no reusa la de arriba
# porque son dos columnas con dos contenidos distintos: compartir marcador obligaría a
# recalcular las dos cada vez que cambiara cualquiera de ellas, y son 686.302 filas.
VERSION_TEXTO_REGLAS = "1"

# Se sube cuando cambia la forma de estimar `fecha_fin_estimada`. Se recalcula desde las
# columnas que ya están en la base, sin descargar nada, y NO al abrir sino al empezar la
# búsqueda (ver `rellenar_fin_estimado_si_toca`), por lo mismo que INDICES_DIFERIDOS:
# encontrar las filas que pueden llevarla es recorrer la tabla entera, 27 s sobre la base
# real de 4 GB con la caché fría, y al abrir la app espera al servidor.
VERSION_FIN_ESTIMADO = "1"

# Los campos que se reescriben aunque la huella no cambie: están fuera de ella (ver
# `model.CAMPOS_FUERA_DE_HUELLA`), y es lo que permite rellenarlos en lo ya guardado
# volviendo a leer los ficheros descargados, sin reevaluar ni versionar nada.
CAMPOS_FIN = ("fecha_formalizacion", "fecha_anuncio_adjudicacion",
              "fecha_fin_estimada", "fin_origen", "fin_base")


def rellenar_fin_estimado_si_toca(con: sqlite3.Connection) -> int | None:
    """Rellena las fechas de fin estimadas de lo ya guardado si no se ha hecho con la
    versión actual. None si no tocaba; si no, cuántas filas ha mirado."""
    if leer_preferencia(con, "version_fin_estimado") == VERSION_FIN_ESTIMADO:
        return None
    n = rellenar_fin_estimado(con)
    escribir_preferencia(con, "version_fin_estimado", VERSION_FIN_ESTIMADO)
    con.commit()
    return n


def completar_fechas_para_estimar(con: sqlite3.Connection, licitaciones) -> int:
    """Escribe en lo ya guardado SOLO la formalización y el anuncio de adjudicación.

    Es para releer los ZIP anuales y sacar de ellos esas dos fechas, que antes no se
    leían. Se escribió cuando `ingest --backfill` devolvía a su versión anterior las
    fichas que el feed diario había actualizado después del ZIP (285 de 188.000 en la
    base real); `guardar()` ya no lo hace (ver `_es_anterior`), pero esto sigue siendo lo
    más barato: no reescribe la ficha, no la reevalúa y no versiona nada. Aquí nada más
    se toca, y nunca se borra una fecha que ya estaba.
    """
    filas = [(l.fecha_formalizacion, l.fecha_anuncio_adjudicacion, l.fuente, l.id_externo)
             for l in licitaciones if l.fecha_formalizacion or l.fecha_anuncio_adjudicacion]
    con.executemany(
        "UPDATE licitaciones SET fecha_formalizacion = COALESCE(?, fecha_formalizacion),"
        " fecha_anuncio_adjudicacion = COALESCE(?, fecha_anuncio_adjudicacion)"
        " WHERE fuente = ? AND id_externo = ?", filas)
    return len(filas)


def rellenar_fin_estimado(con: sqlite3.Connection) -> int:
    """Recalcula la fecha de fin estimada de las filas que pueden tenerla (y la quita de
    las que ya no)."""
    from .model import fin_estimado

    filas = con.execute(
        """SELECT id, fecha_fin_prevista, duracion_meses, fecha_formalizacion,
                  fecha_anuncio_adjudicacion, fecha_publicacion, adjudicatario
             FROM licitaciones
            WHERE fecha_fin_prevista IS NULL AND duracion_meses IS NOT NULL
               OR fecha_fin_estimada IS NOT NULL"""
    ).fetchall()
    cambios = [
        (*fin_estimado(f["fecha_fin_prevista"], f["duracion_meses"],
                       f["fecha_formalizacion"], f["fecha_anuncio_adjudicacion"],
                       f["fecha_publicacion"], f["adjudicatario"]), f["id"])
        for f in filas
    ]
    con.executemany(
        "UPDATE licitaciones SET fecha_fin_estimada = ?, fin_origen = ?, fin_base = ?"
        " WHERE id = ?", cambios)
    con.commit()
    return len(cambios)


def rellenar_texto_norm(con: sqlite3.Connection) -> int:
    """Calcula `texto_norm` de las filas que no lo tengan."""
    from .model import normalizar

    filas = con.execute(
        "SELECT id, texto_busqueda FROM licitaciones WHERE texto_norm IS NULL"
    ).fetchall()
    if filas:
        con.executemany(
            "UPDATE licitaciones SET texto_norm = ? WHERE id = ?",
            [(normalizar(f["texto_busqueda"]), f["id"]) for f in filas],
        )
        con.commit()
    return len(filas)


def rellenar_texto_reglas(con: sqlite3.Connection) -> int:
    """Calcula `texto_reglas_norm` de las filas que no lo tengan.

    Se recompone desde las columnas y no desde `texto_busqueda`, que es de donde
    saldría la tentación: a `texto_busqueda` ya se le ha pegado el nombre del órgano y
    no hay manera fiable de despegárselo —los separadores son saltos de línea y los
    propios objetos de los pliegos traen saltos de línea a puñados—. Las tres columnas
    que hacen falta están en la tabla, así que se leen de ahí.
    """
    from .model import normalizar

    filas = con.execute(
        "SELECT id, objeto, descripcion, lote_desc FROM licitaciones"
        " WHERE texto_reglas_norm IS NULL"
    ).fetchall()
    if filas:
        con.executemany(
            "UPDATE licitaciones SET texto_reglas_norm = ? WHERE id = ?",
            [
                (
                    normalizar(
                        " \n".join(
                            p for p in (f["objeto"], f["descripcion"], f["lote_desc"]) if p
                        )
                    ),
                    f["id"],
                )
                for f in filas
            ],
        )
        con.commit()
    return len(filas)


def recortar_snapshots(con: sqlite3.Connection) -> int:
    """Reduce los snapshots antiguos a los campos que se siguen usando."""
    import json as _json

    filas = con.execute(
        "SELECT id, snapshot FROM licitaciones_versiones WHERE LENGTH(snapshot) > 400"
    ).fetchall()
    cambios = []
    for f in filas:
        try:
            datos = _json.loads(f["snapshot"])
        except (ValueError, TypeError):
            continue
        recortado = {k: datos.get(k) for k in CAMPOS_SNAPSHOT}
        cambios.append((_json.dumps(recortado, ensure_ascii=False), f["id"]))
    if cambios:
        con.executemany(
            "UPDATE licitaciones_versiones SET snapshot = ? WHERE id = ?", cambios
        )
        con.commit()
        con.execute("VACUUM")
    return len(cambios)


def recomputar_claves_grupo(con: sqlite3.Connection) -> int:
    """Recalcula `clave_grupo` con la lógica actual del modelo."""
    from .model import Licitacion

    filas = con.execute(
        "SELECT id, fuente, id_externo, organo, expediente, objeto FROM licitaciones"
    ).fetchall()
    cambios = []
    for f in filas:
        clave = Licitacion(
            fuente=f["fuente"], id_externo=f["id_externo"], organo=f["organo"],
            expediente=f["expediente"], objeto=f["objeto"],
        ).clave_grupo
        cambios.append((clave, f["id"]))
    con.executemany("UPDATE licitaciones SET clave_grupo = ? WHERE id = ?", cambios)
    con.commit()
    return len(cambios)


def fusionar_grupos_ted(con: sqlite3.Connection) -> dict:
    """Une el anuncio de TED con el de PLACSP de la misma licitación.

    Todo lo que supera el umbral europeo se publica dos veces, y hasta ahora salía
    como dos filas con dos triajes: `clave_grupo` se calcula por fila y se ancla al
    expediente en PLACSP y al título en TED, porque el «expediente» de TED es su
    número de publicación, único por anuncio. La oficina de ciberseguridad del
    Ministerio de Cultura ocupaba dos filas de la bandeja.

    No se puede resolver dentro de `Licitacion._clave_grupo()`: hace falta comparar
    unas filas con otras, así que es un paso de reconciliación sobre la base.

    La clave es **importe exacto + día de cierre**, y el resto de candidatos se
    descartaron midiendo sobre datos reales:

    - El nombre del órgano no vale: la misma licitación aparece como «Consellería de
      Sanidade- SERGAS» en PLACSP y «Servicio Gallego de Salud» en TED.
    - El título tampoco: PLACSP lo publica en catalán y TED traducido al castellano
      («Manteniment integral de la xarxa local» / «Servicio de mantenimiento integral
      de la red local»). Exigir solape textual rechazaba 245 de 629 duplicados reales.

    Dos licitaciones distintas con el mismo importe al céntimo y el mismo día de
    cierre son raras, pero existen: se midieron 10 casos sobre 629, todos con
    importes redondos (400.000, 660.000, 380.000). Por eso, cuando el grupo contiene
    más de un expediente de PLACSP **no se fusiona nada** y se cuenta como ambiguo,
    en vez de elegir uno a ojo.

    Lo que esta regla no puede unir —TED sin importe, o un importe ambiguo— pasa después
    por una segunda, de órgano, día de cierre y título, que une también con Cataluña:
    ver `parejas_ted_por_organo`. `anuncios_fusionados` cuenta los de las dos, y
    `por_organo` los de la segunda.
    """
    grupos = con.execute(
        """SELECT l.importe_referencia AS importe,
                  substr(l.fecha_limite_presentacion, 1, 10) AS limite,
                  GROUP_CONCAT(DISTINCT CASE WHEN l.fuente LIKE 'placsp%'
                                             THEN l.clave_grupo END) AS claves_placsp
             FROM licitaciones l
            WHERE l.importe_referencia IS NOT NULL AND l.importe_referencia > 0
              AND l.fecha_limite_presentacion IS NOT NULL
            GROUP BY importe, limite
           HAVING SUM(l.fuente = 'ted') > 0 AND SUM(l.fuente LIKE 'placsp%') > 0"""
    ).fetchall()

    cambios: list[tuple[str, float, str]] = []
    ambiguos = 0
    for g in grupos:
        claves = [c for c in (g["claves_placsp"] or "").split(",") if c]
        if len(claves) != 1:
            ambiguos += 1
            continue
        cambios.append((claves[0], g["importe"], g["limite"]))

    fusionadas = 0
    for clave, importe, limite in cambios:
        cur = con.execute(
            """UPDATE licitaciones SET clave_grupo = ?
                WHERE fuente = 'ted' AND importe_referencia = ?
                  AND substr(fecha_limite_presentacion, 1, 10) = ?
                  AND clave_grupo IS NOT ?""",
            (clave, importe, limite, clave),
        )
        fusionadas += cur.rowcount

    # Después de la primera regla, nunca antes: solo mira lo que esa no ha podido unir.
    parejas, ambiguos_organo = parejas_ted_por_organo(con)
    con.executemany("UPDATE licitaciones SET clave_grupo = ? WHERE id = ?",
                    [(clave, ted_id) for ted_id, clave in parejas])
    fusionadas += len(parejas)
    con.commit()
    return {"grupos": len(cambios), "anuncios_fusionados": fusionadas, "ambiguos": ambiguos,
            "por_organo": len(parejas), "ambiguos_por_organo": ambiguos_organo}


# Raíces que salen en el título de casi cualquier contrato y no dicen cuál es: «servicio»
# y «servei», «contrato» y «contracte», «acuerdo marco»… Contarlas como coincidencia
# daría por iguales dos contratos que solo comparten ser contratos.
_RAICES_GENERICAS = frozenset((
    "serv", "cont", "sumi", "subm", "acue", "acor", "marc", "obje", "pres", "proc",
    "medi", "mitj", "trav", "entr", "lote", "part", "espa",
))

# Qué parte del título de TED tiene que aparecer en el texto del expediente candidato.
# Medido sobre la base real con los 113 anuncios que la regla del órgano encontraba: por
# debajo de la mitad, casi todos eran otro contrato del mismo órgano que cerraba el
# mismo día («Desarrollo de aplicaciones Java» contra unas obras en la sede); de la mitad
# para arriba, casi todos eran el mismo contrato, muchos traducidos del catalán. Subirlo
# a 0,7 para quitar el único error que quedaba costaba ocho parejas buenas.
UMBRAL_TITULO_TED = 0.5


def _raices(texto: str | None) -> set[str]:
    """Las cuatro primeras letras de cada palabra de cinco o más, sin acentos.

    Cuatro letras porque el título de TED llega traducido al castellano y el de PLACSP o
    Cataluña a menudo en catalán, y las raíces aguantan la traducción: «formación» y
    «formació», «homologación» y «homologació», «ciberseguridad» y «ciberseguretat».
    """
    from .model import normalizar

    return {p[:4] for p in re.findall(r"[a-z0-9]{5,}", normalizar(texto))} - _RAICES_GENERICAS


def _organo_comparable(organo: str | None) -> str:
    """El nombre del órgano sin acentos, espacios ni signos, como en `clave_grupo`."""
    from .model import normalizar

    return re.sub(r"[^a-z0-9]+", "", normalizar(organo))[:40]


def parejas_ted_por_organo(con: sqlite3.Connection) -> tuple[list[tuple[int, str]], int]:
    """Los anuncios de TED que la regla del importe no ha unido, con el grupo al que van.

    Devuelve `([(id del anuncio de TED, clave_grupo de destino)], ambiguos)` y no escribe
    nada, para poder medirla contra una base sin tocarla.

    Hace falta porque TED no siempre publica el importe: la homologación de formación
    del Ens d'Abastament d'Aigua Ter-Llobregat salía dos veces en la Bandeja, el anuncio
    catalán y el de TED en castellano, y su importe en TED es NULL. En la base real, 1.024
    de los 8.472 anuncios de TED no traen importe. Extender la regla del importe a
    `catalunya` no habría unido ninguno —medido: cero—, porque lo que se publica en
    Cataluña también está en las plataformas agregadas de PLACSP y ya comparte grupo con
    él; lo que faltaba era una regla que no dependiera del importe.

    La clave es **mismo órgano + mismo día de cierre + título parecido** contra cualquier
    fuente que no sea TED (PLACSP o Cataluña). El órgano y el día solos no bastan: sobre
    la base real eran 113 parejas y casi la mitad, otro contrato del mismo órgano que
    cerraba el mismo día; de ahí el título (`UMBRAL_TITULO_TED`). Con las tres salen 132
    parejas y 11 ambiguas; revisadas a mano, una sola era otro contrato —dos
    mantenimientos de equipos del mismo hospital que cerraban el mismo día—. Si más de
    un expediente pasa el umbral, no se elige: se cuenta como ambiguo y se deja como
    está, igual que la regla del importe.
    """
    from .model import titulo_util_ted

    pendientes = con.execute(
        """SELECT t.id, t.organo, t.objeto,
                  substr(t.fecha_limite_presentacion, 1, 10) AS dia
             FROM licitaciones t
            WHERE t.fuente = 'ted' AND t.fecha_limite_presentacion IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM licitaciones h
                               WHERE h.clave_grupo = t.clave_grupo AND h.fuente != 'ted')"""
    ).fetchall()
    por_dia: dict[str, list] = {}
    for t in pendientes:
        por_dia.setdefault(t["dia"], []).append(t)

    # Los nombres de órgano se repiten muchísimo —unas 660 fichas cierran cada día, de
    # unos pocos cientos de órganos— y normalizarlos era el 80 % del tiempo.
    comparables: dict = {}

    def organo(nombre):
        if nombre not in comparables:
            comparables[nombre] = _organo_comparable(nombre)
        return comparables[nombre]

    parejas: list[tuple[int, str]] = []
    ambiguos = 0
    for dia, anuncios in por_dia.items():
        try:
            siguiente = (date.fromisoformat(dia) + timedelta(days=1)).isoformat()
        except ValueError:
            continue
        # Por rango y no con `substr(...) = ?`, para que entre por `idx_lic_limite`. Y
        # primero solo el órgano: el texto se lee únicamente de los que pueden ser.
        candidatos: dict[str, list] = {}
        for h in con.execute(
            """SELECT id, organo, clave_grupo FROM licitaciones
                WHERE fecha_limite_presentacion >= ? AND fecha_limite_presentacion < ?
                  AND fuente != 'ted' AND clave_grupo IS NOT NULL""", (dia, siguiente)):
            candidatos.setdefault(organo(h["organo"]), []).append(h)
        for t in anuncios:
            del_organo = candidatos.get(organo(t["organo"]))
            # Sin las palabras del nombre del órgano, que los dos textos comparten por ser
            # del mismo órgano y no por ser el mismo contrato: «Soporte informático a los
            # centros de MC MUTUAL» casaba por «mutual» con una auditoría de MC Mutual.
            raices_ted = _raices(titulo_util_ted(t["objeto"])) - _raices(t["organo"])
            if not del_organo or not raices_ted:
                continue
            ids = [h["id"] for h in del_organo]
            texto_por_clave: dict[str, set] = {}
            for f in con.execute(
                f"""SELECT clave_grupo, objeto, descripcion, lote_desc FROM licitaciones
                     WHERE id IN ({", ".join("?" * len(ids))})""", ids):
                texto = " ".join(p for p in (f["objeto"], f["descripcion"], f["lote_desc"]) if p)
                texto_por_clave.setdefault(f["clave_grupo"], set()).update(_raices(texto))
            buenas = [
                clave for clave, raices in texto_por_clave.items()
                if len(raices_ted & raices) / len(raices_ted) >= UMBRAL_TITULO_TED
            ]
            if len(buenas) == 1:
                parejas.append((t["id"], buenas[0]))
            elif len(buenas) > 1:
                ambiguos += 1
    return parejas, ambiguos


def migrar(con: sqlite3.Connection) -> list[str]:
    """Añade las columnas que falten. Idempotente: se ejecuta en cada arranque."""
    aplicadas = []
    for tabla, columnas in COLUMNAS_NUEVAS.items():
        existentes = {
            f["name"] for f in con.execute(f"PRAGMA table_info({tabla})").fetchall()
        }
        if not existentes:  # la tabla aún no existe; el esquema la crea completa
            continue
        for nombre, tipo in columnas:
            if nombre not in existentes:
                con.execute(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {tipo}")
                aplicadas.append(f"{tabla}.{nombre}")
    for sql in INDICES_NUEVOS:
        con.execute(sql)
    if aplicadas:
        con.commit()

    # Vencimientos dejó de distinguir «contactado» y «reunión»: ahora se sigue o no se
    # sigue, y lo que estaba en marcha pasa a «siguiendo» con su nota intacta.
    # El commit va siempre: el UPDATE abre transacción aunque no toque ninguna fila, y
    # dejarla abierta bloquea las escrituras de cualquier otra conexión a la base.
    pasados = con.execute("UPDATE prospeccion SET estado = 'siguiendo'"
                          " WHERE estado IN ('contactado', 'reunion')").rowcount
    con.commit()
    if pasados:
        aplicadas.append("prospección: contactado y reunión pasan a «siguiendo»")

    # Autocorrección de las claves de agrupación cuando cambia su lógica.
    if con.execute("SELECT COUNT(*) FROM licitaciones").fetchone()[0]:
        guardada = leer_preferencia(con, "version_clave_grupo")
        if guardada != VERSION_CLAVE_GRUPO:
            n = recomputar_claves_grupo(con)
            # Después del recálculo por fila, nunca antes: la fusión compara las
            # claves ya calculadas de unas filas con otras.
            fusion = fusionar_grupos_ted(con)
            escribir_preferencia(con, "version_clave_grupo", VERSION_CLAVE_GRUPO)
            con.commit()
            aplicadas.append(f"claves de grupo recalculadas ({n} filas)")
            if fusion["anuncios_fusionados"]:
                aplicadas.append(
                    f"anuncios de TED unidos a su expediente de PLACSP o Cataluña "
                    f"({fusion['anuncios_fusionados']})"
                )
            # Detrás del reagrupamiento: los anuncios que acaban de cambiar de grupo
            # tienen que quedarse con el triaje del expediente al que ahora pertenecen.
            heredados = propagar_revisiones_en_grupos(con)
            if heredados:
                aplicadas.append(
                    f"triaje extendido a {heredados} anuncios del mismo expediente"
                )

        if leer_preferencia(con, "version_texto_norm") != VERSION_TEXTO_NORM:
            n = rellenar_texto_norm(con)
            escribir_preferencia(con, "version_texto_norm", VERSION_TEXTO_NORM)
            con.commit()
            if n:
                aplicadas.append(f"texto normalizado calculado ({n} filas)")

        if leer_preferencia(con, "version_texto_reglas") != VERSION_TEXTO_REGLAS:
            n = rellenar_texto_reglas(con)
            escribir_preferencia(con, "version_texto_reglas", VERSION_TEXTO_REGLAS)
            con.commit()
            if n:
                aplicadas.append(f"texto de reglas calculado ({n} filas)")

        if leer_preferencia(con, "version_snapshot") != VERSION_SNAPSHOT:
            n = recortar_snapshots(con)
            escribir_preferencia(con, "version_snapshot", VERSION_SNAPSHOT)
            con.commit()
            if n:
                aplicadas.append(f"snapshots recortados ({n} versiones)")

    return aplicadas


# --- Escritura -------------------------------------------------------------


CAMPOS = (
    "fuente", "id_externo", "expediente", "organo", "nif_organo", "objeto",
    "descripcion", "cpv", "importe_sin_iva", "valor_estimado", "importe_referencia",
    "procedimiento", "tipo_contrato", "estado", "estado_origen", "fecha_publicacion",
    "fecha_limite_presentacion", "fecha_actualizacion", "nuts", "lugar", "ccaa",
    "url_detalle", "urls_pliegos", "lote_num", "lote_desc", "adjudicatario",
    "importe_adjudicacion", "fecha_adjudicacion", "duracion_meses",
    "fecha_inicio_ejecucion", "fecha_fin_prevista", "clave_grupo",
    "raw", "huella", "texto_busqueda", "texto_norm", "texto_reglas_norm",
) + CAMPOS_FIN

# Lo que hace que un cambio merezca una entrada en el historial. Antes se guardaba
# versión con cualquier cambio de huella, y eso incluye retoques de metadatos: al
# añadir campos nuevos al modelo, la primera ingesta habría metido 9.000 versiones
# falsas con `estado_anterior == estado`. El historial cuenta la vida comercial del
# expediente (se publicó, se adjudicó, cambió de importe), no cada corrección de un
# CPV o una URL.
CAMPOS_HISTORIAL = ("estado", "adjudicatario", "importe_referencia", "importe_adjudicacion")


def _instante(valor: str | None) -> datetime | None:
    """`fecha_actualizacion` como instante comparable. None si no hay o no se lee.

    No vale comparar el texto: PLACSP publica `<updated>` con su zona horaria, «+02:00»
    en verano y «+01:00» en invierno, y como cadenas las 09:30+01:00 van delante de las
    10:00+02:00 aunque sean media hora después. Lo que llega sin zona —Cataluña— se toma
    como UTC: dentro de una misma ficha la fuente es siempre la misma, así que las dos
    fechas que se comparan se leen igual.
    """
    if not valor:
        return None
    try:
        instante = datetime.fromisoformat(valor)
    except ValueError:
        return None
    return instante if instante.tzinfo else instante.replace(tzinfo=timezone.utc)


def _es_anterior(llega: str | None, guardada: str | None) -> bool:
    """Si la ficha que llega es una versión ANTERIOR a la que ya está en la base.

    Solo cuando las dos traen fecha y la que llega es estrictamente más antigua. Sin
    fecha en cualquiera de las dos —TED no publica ninguna, y en Cataluña solo la llevan
    las adjudicadas— no hay manera de saber cuál es más nueva, y se escribe como siempre:
    es lo que se hacía y lo que espera cada fuente que no la tiene. Con la misma fecha
    también se escribe, porque entonces lo que cambia es cómo la LEE el radar —un campo
    nuevo en el modelo— y releer los ficheros descargados para rellenarlo es justo lo que
    se busca.
    """
    a, b = _instante(llega), _instante(guardada)
    return a is not None and b is not None and a < b


def guardar(con: sqlite3.Connection, lic) -> str:
    """Inserta o actualiza una licitación. Devuelve 'nueva', 'actualizada', 'igual' o
    'anterior'.

    Solo escribe una versión nueva en el historial cuando la huella cambia, que es
    lo que evita el ruido de las republicaciones de PLACSP.

    'anterior' es una ficha MÁS VIEJA que la guardada (ver `_es_anterior`), y no se
    escribe. Pasaba con `ingest --backfill` sobre una base con datos: el ZIP anual del
    año en curso llega hasta el mes pasado, y guardarlo entero devolvía a su versión de
    entonces lo que el feed diario ya había actualizado, con lo que una adjudicación
    podía volver a «publicada». Medido en la base real: 285 de las 188.000 fichas de
    `placsp:agregadas` tenían una `fecha_actualizacion` más antigua que la que ya se
    había visto. También cubre el feed diario, que se recorre de la página más nueva a
    la más vieja: si una ficha se republica dos veces en el tramo que se lee, la
    versión vieja llega después de la buena.
    """
    fila = lic.a_fila()
    momento = ahora()

    prev = con.execute(
        f"""SELECT id, huella, fecha_actualizacion, fecha_formalizacion,
                   fecha_anuncio_adjudicacion, {", ".join(CAMPOS_HISTORIAL)}
              FROM licitaciones WHERE fuente = ? AND id_externo = ?""",
        (fila["fuente"], fila["id_externo"]),
    ).fetchone()

    if prev is None:
        columnas = ", ".join(CAMPOS) + ", visto_primera_vez, visto_ultima_vez"
        marcas = ", ".join("?" * (len(CAMPOS) + 2))
        valores = [fila[c] for c in CAMPOS] + [momento, momento]
        cur = con.execute(f"INSERT INTO licitaciones ({columnas}) VALUES ({marcas})", valores)
        lic_id = cur.lastrowid
        con.execute(
            "INSERT INTO licitaciones_fts (rowid, texto_busqueda) VALUES (?, ?)",
            (lic_id, fila["texto_busqueda"]),
        )
        _guardar_version(con, lic_id, fila, None, momento)
        _heredar_revision(con, lic_id, fila["clave_grupo"])
        return "nueva"

    lic_id = prev["id"]
    # Antes que la rama «igual», y no solo cuando cambia la huella: esa rama reescribe
    # `CAMPOS_FIN`, que están fuera de la huella, y una versión vieja con la misma huella
    # puede no traer todavía la fecha de formalización que la nueva sí trae.
    if _es_anterior(fila["fecha_actualizacion"], prev["fecha_actualizacion"]):
        _completar_desde_anterior(con, lic_id, prev, fila, momento)
        return "anterior"

    if prev["huella"] == fila["huella"]:
        con.execute(
            f"UPDATE licitaciones SET {', '.join(f'{c} = ?' for c in CAMPOS_FIN)},"
            " visto_ultima_vez = ? WHERE id = ?",
            [fila[c] for c in CAMPOS_FIN] + [momento, lic_id])
        return "igual"

    asignaciones = ", ".join(f"{c} = ?" for c in CAMPOS)
    valores = [fila[c] for c in CAMPOS] + [momento, lic_id]
    con.execute(
        f"UPDATE licitaciones SET {asignaciones}, visto_ultima_vez = ? WHERE id = ?", valores
    )
    con.execute("DELETE FROM licitaciones_fts WHERE rowid = ?", (lic_id,))
    con.execute(
        "INSERT INTO licitaciones_fts (rowid, texto_busqueda) VALUES (?, ?)",
        (lic_id, fila["texto_busqueda"]),
    )
    # Solo se anota versión si ha cambiado algo con significado comercial.
    if any(prev[c] != fila[c] for c in CAMPOS_HISTORIAL):
        _guardar_version(con, lic_id, fila, prev["estado"], momento)
    return "actualizada"


def _completar_desde_anterior(con, lic_id: int, prev, fila: dict, momento: str) -> None:
    """Lo único que se aprovecha de una versión anterior a la guardada.

    `visto_ultima_vez`, porque la ficha se ha visto. Y las dos fechas de las que sale el
    fin estimado, pero SOLO si la guardada no las tiene: así una relectura del ZIP sigue
    sirviendo para rellenar lo que una versión vieja del radar no leía (como
    `completar_fechas_para_estimar`), sin que la versión vieja borre ni cambie nada. No
    se copian `CAMPOS_FIN` tal cual, como hace la rama «igual»: el fin estimado de una
    versión todavía sin adjudicar es «ninguno», y pisaría el de la buena.
    """
    nuevas = {
        c: prev[c] or fila[c]
        for c in ("fecha_formalizacion", "fecha_anuncio_adjudicacion")
    }
    if all(nuevas[c] == prev[c] for c in nuevas):
        con.execute("UPDATE licitaciones SET visto_ultima_vez = ? WHERE id = ?",
                    (momento, lic_id))
        return

    from .model import fin_estimado

    g = con.execute(
        "SELECT fecha_fin_prevista, duracion_meses, fecha_publicacion, adjudicatario"
        " FROM licitaciones WHERE id = ?", (lic_id,)).fetchone()
    fin, origen, base = fin_estimado(
        g["fecha_fin_prevista"], g["duracion_meses"], nuevas["fecha_formalizacion"],
        nuevas["fecha_anuncio_adjudicacion"], g["fecha_publicacion"], g["adjudicatario"])
    con.execute(
        "UPDATE licitaciones SET fecha_formalizacion = ?, fecha_anuncio_adjudicacion = ?,"
        " fecha_fin_estimada = ?, fin_origen = ?, fin_base = ?, visto_ultima_vez = ?"
        " WHERE id = ?",
        (nuevas["fecha_formalizacion"], nuevas["fecha_anuncio_adjudicacion"], fin, origen,
         base, momento, lic_id))


# Campos que se conservan en el snapshot de cada versión. Antes se guardaba una
# copia JSON de TODOS los campos, y con 270.000 versiones eran 534 MB —el 46% de la
# base— de datos que la aplicación no lee en ningún sitio: `historial()` solo usa
# estado, adjudicatario, importe y fecha. Se queda lo que puede cambiar y tiene
# significado, que ocupa una décima parte y sigue permitiendo auditar qué pasó.
CAMPOS_SNAPSHOT = (
    "estado", "estado_origen", "fecha_limite_presentacion", "importe_referencia",
    "adjudicatario", "importe_adjudicacion", "fecha_adjudicacion", "fecha_fin_prevista",
)


def _fecha_del_cambio(fila: dict, estado_anterior: str | None) -> str | None:
    """La fecha que la fuente da a este cambio. None si no publica ninguna.

    La primera versión se fecha con `fecha_publicacion`, no con el `<updated>` de la
    republicación: es la fecha que la ficha ya muestra en el campo «Publicada», y
    discrepar de ella por un día se lee como otro error. Las siguientes usan
    `fecha_actualizacion`, que en PLACSP es el `<updated>` del `<entry>` —el momento
    exacto en que se publicó ese cambio— y en Cataluña la fecha de publicación de la
    adjudicación. TED no trae ninguna de las dos, pero allí cada anuncio es una ficha
    propia, así que su `fecha_publicacion` ya es la fecha del cambio.
    """
    if estado_anterior is None:
        return fila["fecha_publicacion"] or fila["fecha_actualizacion"]
    return fila["fecha_actualizacion"] or fila["fecha_publicacion"]


def _guardar_version(con, lic_id: int, fila: dict, estado_anterior: str | None, momento: str) -> None:
    con.execute(
        """INSERT OR IGNORE INTO licitaciones_versiones
           (licitacion_id, huella, estado, estado_anterior, importe_referencia,
            adjudicatario, detectado_en, fecha_cambio, snapshot)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            lic_id,
            fila["huella"],
            fila["estado"],
            estado_anterior,
            fila["importe_referencia"],
            fila["adjudicatario"],
            momento,
            _fecha_del_cambio(fila, estado_anterior),
            json.dumps({k: fila[k] for k in CAMPOS_SNAPSHOT}, ensure_ascii=False),
        ),
    )


# --- Cursores y log --------------------------------------------------------


def leer_cursor(con, fuente: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM fuentes_cursor WHERE fuente = ?", (fuente,)).fetchone()


def escribir_cursor(con, fuente: str, cursor: str | None, etag: str | None = None) -> None:
    con.execute(
        """INSERT INTO fuentes_cursor (fuente, cursor, etag, actualizado_en)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(fuente) DO UPDATE SET
             cursor = excluded.cursor,
             etag = excluded.etag,
             actualizado_en = excluded.actualizado_en""",
        (fuente, cursor, etag, ahora()),
    )


def abrir_ingest(con, fuente: str) -> int:
    cur = con.execute(
        "INSERT INTO ingest_log (fuente, iniciado_en) VALUES (?, ?)", (fuente, ahora())
    )
    return cur.lastrowid


def cerrar_ingest(con, log_id: int, *, vistos=0, nuevos=0, actualizados=0, error=None) -> None:
    con.execute(
        """UPDATE ingest_log SET terminado_en = ?, vistos = ?, nuevos = ?,
                  actualizados = ?, ok = ?, error = ? WHERE id = ?""",
        (ahora(), vistos, nuevos, actualizados, 0 if error else 1, error, log_id),
    )


def _max_id(con) -> int:
    return con.execute("SELECT COALESCE(MAX(id), 0) FROM licitaciones").fetchone()[0]


def abrir_busqueda(con, *, primera_carga: bool = False) -> int:
    """Apunta que empieza una búsqueda y desde qué id cuenta lo que traiga."""
    cur = con.execute(
        "INSERT INTO busquedas (iniciada, id_desde, primera_carga) VALUES (?, ?, ?)",
        (ahora(), _max_id(con), 1 if primera_carga else 0),
    )
    con.commit()
    return cur.lastrowid


def cerrar_busqueda(con, busqueda_id: int, motivo: str) -> None:
    """Cierra la fila con el último id que hay ahora: lo de en medio es lo traído.

    Se llama DESPUÉS de evaluar los perfiles, para que cuando alguien pregunte qué trajo
    esta búsqueda las coincidencias ya estén escritas.
    """
    con.execute(
        "UPDATE busquedas SET terminada = ?, id_hasta = ?, motivo = ? WHERE id = ?",
        (ahora(), _max_id(con), motivo, busqueda_id),
    )
    con.commit()


# Las dos marcas de «desde la última vez». Van en `preferencias` como el resto de lo
# que es de quien usa la herramienta.
APERTURA_ACTUAL = "apertura_actual_id"
APERTURA_PREVIA = "apertura_previa_id"
# Cuándo fue esa vez anterior, para poder decir «desde el martes a las 9:30».
APERTURA_PREVIA_EN = "apertura_previa_en"


def rotar_apertura(con) -> int | None:
    """Se entra en la aplicación: lo que había hasta ahora pasa a ser «lo de antes».

    Se guarda el último id que había al entrar la vez anterior (`APERTURA_PREVIA`), y
    «desde la última vez» es todo lo posterior: lo que ha traído la búsqueda al abrir y
    lo que entró mientras la aplicación estaba abierta la vez pasada.

    Solo rota si ha entrado algo desde la última vez. Si no, recargar la página —o abrir
    y cerrar la ventana dos veces seguidas— dejaría «desde la última vez» vacío justo
    cuando no ha cambiado nada que justifique olvidarlo. Devuelve la marca previa.
    """
    actual = _max_id(con)
    guardada = leer_preferencia(con, APERTURA_ACTUAL)
    try:
        guardada_id = int(guardada) if guardada is not None else None
    except ValueError:
        guardada_id = None
    if guardada_id is None or actual > guardada_id:
        if guardada_id is not None:
            cuando = con.execute(
                "SELECT actualizado_en FROM preferencias WHERE clave = ?", (APERTURA_ACTUAL,)
            ).fetchone()
            escribir_preferencia(con, APERTURA_PREVIA, str(guardada_id))
            escribir_preferencia(con, APERTURA_PREVIA_EN, cuando[0] if cuando else None)
        escribir_preferencia(con, APERTURA_ACTUAL, str(actual))
        con.commit()
    previa = leer_preferencia(con, APERTURA_PREVIA)
    try:
        return int(previa) if previa is not None else None
    except ValueError:
        return None


# Las etapas de la carga inicial que faltan por terminar, como lista JSON. La escribe
# `radar.py ingest --primera-carga`: al empezar apunta las que se le piden y quita cada
# una al acabarla sin errores. Así una carga que se corta —se cierra la aplicación, se
# cae la red, se cancela— sigue sabiendo lo que le falta la próxima vez.
ETAPAS_PENDIENTES = "etapas_pendientes"


def etapas_pendientes(con, total: int) -> list[int]:
    """Las etapas de la carga inicial (de 1 a `total`) que quedan por hacer.

    Sin nada apuntado, una base que nunca ha buscado —ni una fila en `ingest_log`— las
    tiene todas pendientes: es la instalación recién descargada. Una base con historia y
    sin nada apuntado es de antes de este registro y ya hizo su carga como fuese; a esa
    no se le pide nada.
    """
    guardada = leer_preferencia(con, ETAPAS_PENDIENTES)
    if guardada is None:
        if con.execute("SELECT 1 FROM ingest_log LIMIT 1").fetchone():
            return []
        return list(range(1, total + 1))
    try:
        return sorted({int(e) for e in json.loads(guardada)} & set(range(1, total + 1)))
    except (TypeError, ValueError):
        return []


def apuntar_etapas_pendientes(con, etapas) -> None:
    escribir_preferencia(con, ETAPAS_PENDIENTES, json.dumps(sorted(set(etapas))))
    con.commit()


def salud_fuentes(con) -> list[dict]:
    filas = con.execute(
        """SELECT l.fuente, l.iniciado_en, l.terminado_en, l.vistos, l.nuevos,
                  l.actualizados, l.ok, l.error
             FROM ingest_log l
             JOIN (SELECT fuente, MAX(id) AS ult FROM ingest_log GROUP BY fuente) u
               ON u.ult = l.id
            ORDER BY l.fuente"""
    ).fetchall()
    return [dict(f) for f in filas]


# --- Triaje ----------------------------------------------------------------


MOTIVOS_DESCARTE = (
    "fuera de nicho",
    "importe bajo",
    "incumbente atado",
    "fuera de plazo",
    "ya presentada por otro",
    "otro",
)

# Lo que decide una persona sobre un expediente. Se copia tal cual entre los
# anuncios del grupo, así que va en un solo sitio.
CAMPOS_REVISION = ("estado", "asignado_a", "notas", "motivo_descarte")


def ids_del_grupo(con, lic_id: int) -> list[int]:
    """Los anuncios que la bandeja colapsa en la misma tarjeta que `lic_id`.

    El triaje es del EXPEDIENTE, no del anuncio, y esta función es lo que lo hace
    posible. La bandeja agrupa por `clave_grupo` y muestra solo el anuncio más
    reciente de cada expediente; guardando el triaje únicamente en la fila que se
    tenía delante, el filtro «lo descartado no estorba» quitaba ese anuncio y la
    tarjeta volvía a aparecer con el siguiente del grupo, otra vez «sin revisar».
    Sobre una base real, el 21% de los expedientes con coincidencia (423 de 2.057)
    tienen más de un anuncio, así que no era un caso de laboratorio.

    Las filas sin `clave_grupo` —las que vienen de una versión anterior y aún no se
    han recalculado— se tratan como grupo de una, igual que hace el COALESCE de las
    consultas.
    """
    fila = con.execute(
        "SELECT clave_grupo FROM licitaciones WHERE id = ?", (lic_id,)
    ).fetchone()
    if fila is None or not fila["clave_grupo"]:
        return [lic_id]
    return [
        f["id"]
        for f in con.execute(
            "SELECT id FROM licitaciones WHERE clave_grupo = ? ORDER BY id",
            (fila["clave_grupo"],),
        )
    ]


def _heredar_revision(con, lic_id: int, clave_grupo: str | None) -> bool:
    """Un anuncio nuevo de un expediente ya triado nace con el triaje del expediente.

    Es la otra mitad de `ids_del_grupo`, y sin ella descartar no aguanta la siguiente
    ingesta: PLACSP republica el expediente cuando se corrige o se adjudica, y una
    republicación con `id_externo` distinto es una fila nueva. Llegaría sin triaje y
    devolvería a la bandeja algo que ya se había descartado.

    Solo se hereda lo que ya existe; si nadie ha triado el expediente no se escribe
    nada, para no llenar `revisiones` de filas 'nuevo' que no dicen nada.
    """
    if not clave_grupo:
        return False
    columnas = ", ".join(f"r.{c} AS {c}" for c in CAMPOS_REVISION)
    fila = con.execute(
        f"""SELECT {columnas}
              FROM revisiones r
              JOIN licitaciones l ON l.id = r.licitacion_id
             WHERE l.clave_grupo = ? AND l.id != ?
             ORDER BY r.actualizado_en DESC, r.licitacion_id DESC
             LIMIT 1""",
        (clave_grupo, lic_id),
    ).fetchone()
    if fila is None:
        return False
    con.execute(
        """INSERT OR IGNORE INTO revisiones
             (licitacion_id, estado, asignado_a, notas, motivo_descarte, actualizado_en)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (lic_id, *(fila[c] for c in CAMPOS_REVISION), ahora()),
    )
    return True


def propagar_revisiones_en_grupos(con) -> int:
    """Extiende el triaje a los anuncios del expediente que todavía no lo tienen.

    Hace falta cuando `clave_grupo` cambia DESPUÉS de haber triado: el anuncio de TED
    que hoy se une al expediente de PLACSP que se descartó la semana pasada entró en
    su día con grupo propio y triaje propio (ninguno), así que sin este paso la
    fusión devolvería la tarjeta a la bandeja. Por eso se llama detrás de
    `fusionar_grupos_ted` y de `recomputar_claves_grupo`.

    Solo AÑADE: nunca sobrescribe una decisión ya tomada. Si dos anuncios del mismo
    expediente tienen triajes distintos —posible únicamente en bases anteriores a
    este cambio— se dejan como están en vez de elegir por la persona.
    """
    columnas = ", ".join(f"r.{c} AS {c}" for c in CAMPOS_REVISION)
    faltantes = con.execute(
        f"""SELECT l.id AS id, {", ".join(f"c.{c}" for c in CAMPOS_REVISION)}
              FROM licitaciones l
              JOIN (
                   SELECT l2.clave_grupo AS clave, {columnas},
                          ROW_NUMBER() OVER (
                              PARTITION BY l2.clave_grupo
                              ORDER BY r.actualizado_en DESC, r.licitacion_id DESC
                          ) AS rn
                     FROM revisiones r
                     JOIN licitaciones l2 ON l2.id = r.licitacion_id
                    WHERE l2.clave_grupo IS NOT NULL
                   ) c ON c.clave = l.clave_grupo AND c.rn = 1
             WHERE l.clave_grupo IS NOT NULL
               AND l.id NOT IN (SELECT licitacion_id FROM revisiones)"""
    ).fetchall()
    if not faltantes:
        return 0
    momento = ahora()
    antes = con.total_changes
    con.executemany(
        """INSERT OR IGNORE INTO revisiones
             (licitacion_id, estado, asignado_a, notas, motivo_descarte, actualizado_en)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [(f["id"], *(f[c] for c in CAMPOS_REVISION), momento) for f in faltantes],
    )
    con.commit()
    return con.total_changes - antes


def _por_tandas(ids, tamano: int = 500):
    """SQLite admite un número limitado de `?` por consulta; se va de 500 en 500."""
    ids = list(ids)
    for i in range(0, len(ids), tamano):
        yield ids[i:i + tamano]


def marcar_vistas(con, ids) -> list[int]:
    """Pasa a «vista» los anuncios de `ids` que sigan sin revisar. Devuelve los cambiados.

    Solo toca lo que está en «nuevo» (o sin fila en `revisiones`, que es lo mismo): lo
    que sigues, lo presentado o lo descartado no se mueve aunque venga en la lista. Las
    notas y el asignado se conservan. Lo que devuelve es lo que hay que pasar a
    `desmarcar_vistas` para deshacerlo.
    """
    cambiados: list[int] = []
    for tanda in _por_tandas(ids):
        marcas = ", ".join("?" * len(tanda))
        cambiados += [
            f["id"] for f in con.execute(
                f"""SELECT l.id FROM licitaciones l
                      LEFT JOIN revisiones r ON r.licitacion_id = l.id
                     WHERE l.id IN ({marcas}) AND COALESCE(r.estado, 'nuevo') = 'nuevo'""",
                tanda,
            )
        ]
    momento = ahora()
    con.executemany(
        """INSERT INTO revisiones (licitacion_id, estado, actualizado_en)
           VALUES (?, 'vista', ?)
           ON CONFLICT(licitacion_id) DO UPDATE SET
             estado = 'vista', actualizado_en = excluded.actualizado_en
           WHERE revisiones.estado = 'nuevo'""",
        [(i, momento) for i in cambiados],
    )
    con.commit()
    return sorted(cambiados)


def desmarcar_vistas(con, ids) -> int:
    """Deshace `marcar_vistas`: vuelve a «nuevo» lo que siga en «vista». Devuelve cuántos.

    Lo que se haya movido entre tanto —lo que pasaste a seguir después de limpiar— se
    queda como lo dejaste: deshacer la limpieza no puede deshacer otra decisión.
    """
    antes = con.total_changes
    momento = ahora()
    for tanda in _por_tandas(ids):
        marcas = ", ".join("?" * len(tanda))
        con.execute(
            f"""UPDATE revisiones SET estado = 'nuevo', actualizado_en = ?
                 WHERE estado = 'vista' AND licitacion_id IN ({marcas})""",
            [momento, *tanda],
        )
    con.commit()
    return con.total_changes - antes


def leer_preferencia(con, clave: str) -> str | None:
    fila = con.execute("SELECT valor FROM preferencias WHERE clave = ?", (clave,)).fetchone()
    return fila["valor"] if fila else None


def escribir_preferencia(con, clave: str, valor: str | None) -> None:
    con.execute(
        """INSERT INTO preferencias (clave, valor, actualizado_en) VALUES (?, ?, ?)
           ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor,
                                            actualizado_en = excluded.actualizado_en""",
        (clave, valor, ahora()),
    )


def fijar_revision(con, lic_id: int, *, estado=None, asignado_a=None, notas=None,
                   motivo_descarte=None) -> list[int]:
    """Actualiza el triaje. Un campo a None significa "déjalo como está".

    Se aplica a todos los anuncios del expediente, no solo a la fila que se tenía
    delante: el motivo está en `ids_del_grupo`. Devuelve los ids tocados.

    Ojo con el UPSERT: aquí los parámetros del UPDATE van aparte de los del
    INSERT a propósito. Usar `excluded.estado` sobre un `VALUES (COALESCE(?,
    'nuevo'))` hacía que guardar solo las notas machacara el estado con 'nuevo',
    porque "no toques el estado" y "ponlo en nuevo" llegaban indistinguibles. Es
    decir: escribir una nota en una licitación que seguías la sacaba del
    seguimiento sin avisar.
    """
    if estado is not None and estado not in ESTADOS_REVISION:
        raise ValueError(
            f"Estado de revisión no válido: {estado}. Válidos: {', '.join(ESTADOS_REVISION)}"
        )
    if motivo_descarte is not None and motivo_descarte not in MOTIVOS_DESCARTE:
        raise ValueError(
            f"Motivo de descarte no válido: {motivo_descarte}. "
            f"Válidos: {', '.join(MOTIVOS_DESCARTE)}"
        )
    momento = ahora()
    ids = ids_del_grupo(con, lic_id)
    con.executemany(
        """INSERT INTO revisiones
             (licitacion_id, estado, asignado_a, notas, motivo_descarte, actualizado_en)
           VALUES (?, COALESCE(?, 'nuevo'), ?, ?, ?, ?)
           ON CONFLICT(licitacion_id) DO UPDATE SET
             estado = COALESCE(?, revisiones.estado),
             asignado_a = COALESCE(?, revisiones.asignado_a),
             notas = COALESCE(?, revisiones.notas),
             motivo_descarte = COALESCE(?, revisiones.motivo_descarte),
             actualizado_en = ?""",
        [
            (i, estado, asignado_a, notas, motivo_descarte, momento,
             estado, asignado_a, notas, motivo_descarte, momento)
            for i in ids
        ],
    )
    return ids
