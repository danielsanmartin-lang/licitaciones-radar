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
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BD_POR_DEFECTO = RAIZ / "data" / "radar.db"

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
    raw                       TEXT,
    huella                    TEXT NOT NULL,
    texto_busqueda            TEXT,
    texto_norm                TEXT,
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
"""

ESTADOS_REVISION = ("nuevo", "siguiendo", "descartado", "presentada")


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
)


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
    con.commit()
    return {"grupos": len(cambios), "anuncios_fusionados": fusionadas, "ambiguos": ambiguos}


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
                    f"anuncios de TED unidos a su expediente de PLACSP "
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
    "raw", "huella", "texto_busqueda", "texto_norm",
)

# Lo que hace que un cambio merezca una entrada en el historial. Antes se guardaba
# versión con cualquier cambio de huella, y eso incluye retoques de metadatos: al
# añadir campos nuevos al modelo, la primera ingesta habría metido 9.000 versiones
# falsas con `estado_anterior == estado`. El historial cuenta la vida comercial del
# expediente (se publicó, se adjudicó, cambió de importe), no cada corrección de un
# CPV o una URL.
CAMPOS_HISTORIAL = ("estado", "adjudicatario", "importe_referencia", "importe_adjudicacion")


def guardar(con: sqlite3.Connection, lic) -> str:
    """Inserta o actualiza una licitación. Devuelve 'nueva', 'actualizada' o 'igual'.

    Solo escribe una versión nueva en el historial cuando la huella cambia, que es
    lo que evita el ruido de las republicaciones de PLACSP.
    """
    fila = lic.a_fila()
    momento = ahora()

    prev = con.execute(
        f"""SELECT id, huella, {", ".join(CAMPOS_HISTORIAL)}
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
    if prev["huella"] == fila["huella"]:
        con.execute("UPDATE licitaciones SET visto_ultima_vez = ? WHERE id = ?", (momento, lic_id))
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
