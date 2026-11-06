"""Qué licitación ha salido de cada consulta preliminar de mercado.

Una consulta previa es el aviso más temprano que hay: el órgano pregunta al mercado
antes de escribir el pliego. Lo que interesa después es saber cuándo sale ese pliego, y
PLACSP no lo dice: el anuncio de licitación no lleva ninguna referencia a la consulta de
la que viene (comprobado sobre el CODICE de los dos feeds).

Así que se deduce, y por dos caminos:

- **Mismo expediente.** Mismo NIF de órgano y mismo número de expediente, sin
  mayúsculas ni espacios. Es seguro, pero raro: de 2.310 consultas reales solo 76 se
  licitaron con el mismo número. «CPM_EXPT 2397/26/CAR» o «CONSULTA 316» no son el
  expediente del pliego.
- **Mismo órgano y objeto parecido.** Lo que el órgano ha licitado en los dos años
  siguientes a la consulta, comparando las palabras del objeto. Las palabras pesan según
  lo raras que son EN ESE ÓRGANO: para el CSIC, «suministro e instalación» no dice nada
  y «criomicroscopio» lo dice todo; para Renfe, «Renfe» no dice nada.

Medido sobre esas 2.310 consultas, revisando a mano muestras de cada tramo de
puntuación: de 0,65 para arriba aciertan unas 13 de cada 14; entre 0,5 y 0,65, unas 4
de cada 5; por debajo de 0,5, la mitad. Por eso por debajo de 0,5 no se guarda nada, y
lo que queda se enseña con su nivel («segura», «probable», «posible») y con un «es
esta / no es esta» para que lo cierre una persona.

El cálculo es incremental. La primera vez recorre los órganos de todas las consultas
(unos 20 s sobre una base real de 4 GB); después, en cada búsqueda, solo los órganos que
han publicado algo nuevo.
"""

from __future__ import annotations

import math
import re
import sqlite3
from collections import Counter
from datetime import date, timedelta

from . import db
from .model import normalizar

FUENTE_CONSULTAS = "placsp:consultas_previas"

# Se sube cuando cambia la forma de puntuar: la búsqueda siguiente lo rehace todo. Las
# decisiones de las personas («es esta», «no es esta») van en otra tabla y no se tocan.
VERSION = "1"
CLAVE_VERSION = "enlaces_version"
CLAVE_HASTA = "enlaces_hasta_id"

# Cuánto después de la consulta puede salir su pliego. Las medianas medidas están en
# meses, pero hay consultas de equipamiento científico que tardan año y medio.
DIAS_VENTANA = 730

UMBRAL = 0.5
UMBRAL_PROBABLE = 0.65
# Compartir un CPV de cinco cifras suma algo, pero poco: casi todo lo que contrata un
# mismo órgano cae en los mismos tres o cuatro CPV.
PLUS_CPV = 0.1
CANDIDATAS = 3
PALABRAS_EXPLICACION = 6

# Las palabras que salen en cualquier consulta o pliego y no distinguen uno de otro. Las
# de cada órgano —su nombre, su ciudad— no hace falta listarlas: las apaga el peso.
VACIAS = frozenset("""
    de la el los las del al y o en para por con sin a un una unos unas su sus se que lo
    le dels per amb les els
    consulta consultas preliminar preliminares mercado cpm licitacion objeto preparar
    preparacion informacion recabar conocer empresas operadores economicos mediante
    relativa relativo destinado destinada sobre entre como este esta estos finalidad fin
    eventual convocatoria posible futura futuro expediente contratacion contrato
""".split())

NIVELES = ("confirmada", "segura", "probable", "posible")
# Los que se dan por buenos para decir «ya se ha licitado» sin matices.
NIVELES_FIRMES = ("confirmada", "segura", "probable")


def palabras(texto: str | None) -> set[str]:
    return {
        w for w in re.findall(r"[a-z0-9]+", normalizar(texto))
        if len(w) > 2 and w not in VACIAS and not w.isdigit()
    }


def _expediente(valor: str | None) -> str:
    # La misma normalización que el índice `idx_lic_nif_exp`.
    return (valor or "").lower().replace(" ", "")


def _cpvs(valor: str | None) -> set[str]:
    return {c[:5] for c in (valor or "").split() if len(c) >= 5}


# --- Cálculo -----------------------------------------------------------------


def necesita_pasada_completa(con: sqlite3.Connection) -> bool:
    return (db.hay_indice(con, db.INDICE_CONSULTAS)
            and db.leer_preferencia(con, CLAVE_VERSION) != VERSION)


def actualizar(con: sqlite3.Connection, *, completo: bool = False) -> dict:
    """Rehace las candidatas de los órganos que han cambiado desde la última vez.

    Necesita el índice de NIF y expediente (`db.INDICE_CONSULTAS`): sin él, cada órgano
    es un recorrido de la tabla entera. Lo crea la búsqueda antes de llegar aquí; si no
    está, no se intenta y se dice.
    """
    if not db.hay_indice(con, db.INDICE_CONSULTAS):
        return {"preparando": True}

    completo = completo or db.leer_preferencia(con, CLAVE_VERSION) != VERSION
    maximo = con.execute("SELECT COALESCE(MAX(id), 0) FROM licitaciones").fetchone()[0]
    if completo:
        con.execute("DELETE FROM enlaces_consulta")
        nifs = [f[0] for f in con.execute(
            "SELECT DISTINCT nif_organo FROM licitaciones"
            " WHERE fuente = ? AND nif_organo IS NOT NULL", (FUENTE_CONSULTAS,))]
    else:
        desde = int(db.leer_preferencia(con, CLAVE_HASTA) or 0)
        nifs = [f[0] for f in con.execute(
            """SELECT DISTINCT l.nif_organo FROM licitaciones l
                WHERE l.id > ? AND l.nif_organo IS NOT NULL
                  AND EXISTS (SELECT 1 FROM licitaciones c
                               WHERE c.nif_organo = l.nif_organo AND c.fuente = ?)""",
            (desde, FUENTE_CONSULTAS))]

    consultas = enlazadas = 0
    for nif in nifs:
        c, e = _enlazar_organo(con, nif)
        consultas += c
        enlazadas += e
    db.escribir_preferencia(con, CLAVE_HASTA, str(maximo))
    db.escribir_preferencia(con, CLAVE_VERSION, VERSION)
    con.commit()
    return {"completo": completo, "organos": len(nifs), "consultas": consultas,
            "enlazadas": enlazadas}


def _enlazar_organo(con: sqlite3.Connection, nif: str) -> tuple[int, int]:
    filas = con.execute(
        """SELECT id, fuente, expediente, objeto, descripcion, cpv, fecha_publicacion,
                  clave_grupo
             FROM licitaciones WHERE nif_organo = ?""", (nif,)).fetchall()
    consultas = [f for f in filas if f["fuente"] == FUENTE_CONSULTAS and f["fecha_publicacion"]]
    if not consultas:
        return 0, 0

    # Un expediente es UNA candidata, aunque tenga cinco anuncios. Lo representa su
    # primer anuncio, que es el que no cambia cuando llegan los siguientes: las
    # decisiones de las personas se guardan contra ese id.
    grupos: dict[str, dict] = {}
    for f in filas:
        if f["fuente"] == FUENTE_CONSULTAS or not f["fecha_publicacion"]:
            continue
        clave = f["clave_grupo"] or str(f["id"])
        g = grupos.get(clave)
        if g is None:
            g = grupos[clave] = {"id": f["id"], "pub": f["fecha_publicacion"],
                                 "objeto": f["objeto"], "exps": set(), "cpv": set()}
        elif (f["fecha_publicacion"], f["id"]) < (g["pub"], g["id"]):
            g.update(id=f["id"], pub=f["fecha_publicacion"], objeto=f["objeto"])
        if f["expediente"]:
            g["exps"].add(_expediente(f["expediente"]))
        g["cpv"] |= _cpvs(f["cpv"])
    for g in grupos.values():
        g["palabras"] = palabras(g["objeto"])

    df = Counter(w for g in grupos.values() for w in g["palabras"])
    total = len(grupos) + 1
    pesos: dict[str, float] = {}

    def peso(w: str) -> float:
        p = pesos.get(w)
        if p is None:
            p = pesos[w] = (math.log((total + 1) / (df.get(w, 0) + 1)) + 0.5) ** 2
        return p

    for g in grupos.values():
        g["norma"] = math.sqrt(sum(peso(w) for w in g["palabras"]))

    ids = [c["id"] for c in consultas]
    for tanda in db._por_tandas(ids):
        con.execute(f"DELETE FROM enlaces_consulta WHERE consulta_id IN "
                    f"({', '.join('?' * len(tanda))})", tanda)

    enlazadas = 0
    for c in consultas:
        tc = palabras(c["objeto"]) | palabras(c["descripcion"])
        norma_c = math.sqrt(sum(peso(w) for w in tc))
        exp_c = _expediente(c["expediente"])
        cpv_c = _cpvs(c["cpv"])
        try:
            limite = (date.fromisoformat(c["fecha_publicacion"][:10])
                      + timedelta(days=DIAS_VENTANA)).isoformat()
        except ValueError:
            continue

        candidatas = []
        for g in grupos.values():
            if not (g["pub"] > c["fecha_publicacion"] and g["pub"][:10] <= limite):
                continue
            mismo = bool(exp_c) and exp_c in g["exps"]
            comunes = tc & g["palabras"]
            parecido = 0.0
            if comunes and norma_c and g["norma"]:
                parecido = sum(peso(w) for w in comunes) / (norma_c * g["norma"])
                if cpv_c & g["cpv"]:
                    parecido += PLUS_CPV
            if mismo or parecido >= UMBRAL:
                explicacion = sorted(comunes, key=lambda w: (-peso(w), w))[:PALABRAS_EXPLICACION]
                candidatas.append((mismo, round(parecido, 3), g["id"], ", ".join(explicacion)))

        candidatas.sort(key=lambda x: (x[0], x[1]), reverse=True)
        for mismo, parecido, lic_id, explicacion in candidatas[:CANDIDATAS]:
            con.execute(
                """INSERT OR REPLACE INTO enlaces_consulta
                       (consulta_id, licitacion_id, puntuacion, mismo_expediente, palabras)
                   VALUES (?, ?, ?, ?, ?)""",
                (c["id"], lic_id, parecido, int(mismo), explicacion))
        enlazadas += bool(candidatas)
    return len(consultas), enlazadas


# --- Lectura -----------------------------------------------------------------


def _nivel(mismo: int, puntuacion: float | None, decision: str | None) -> str:
    if decision == "si":
        return "confirmada"
    if mismo:
        return "segura"
    return "probable" if (puntuacion or 0) >= UMBRAL_PROBABLE else "posible"


def _todas(con: sqlite3.Connection, consulta_id: int | None = None) -> list[dict]:
    """Candidatas y confirmaciones, con la decisión de cada una.

    Lo confirmado a mano entra aunque el cálculo ya no lo proponga —porque se cambió la
    puntuación o el objeto del pliego—: lo que decide una persona no lo deshace un número.
    """
    filtro_e = filtro_d = ""
    params: list = []
    if consulta_id is not None:
        filtro_e, filtro_d = " WHERE e.consulta_id = ?", " AND d.consulta_id = ?"
        params = [consulta_id, consulta_id]
    filas = con.execute(
        f"""SELECT e.consulta_id, e.licitacion_id, e.puntuacion, e.mismo_expediente,
                   e.palabras, d.decision
              FROM enlaces_consulta e
              LEFT JOIN enlaces_decision d
                ON d.consulta_id = e.consulta_id AND d.licitacion_id = e.licitacion_id
              {filtro_e}
            UNION ALL
            SELECT d.consulta_id, d.licitacion_id, NULL, 0, NULL, d.decision
              FROM enlaces_decision d
             WHERE d.decision = 'si'{filtro_d}
               AND NOT EXISTS (SELECT 1 FROM enlaces_consulta e
                                WHERE e.consulta_id = d.consulta_id
                                  AND e.licitacion_id = d.licitacion_id)""",
        params).fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        d["nivel"] = _nivel(d["mismo_expediente"], d["puntuacion"], d["decision"])
        salida.append(d)
    salida.sort(key=lambda d: (NIVELES.index(d["nivel"]), -(d["puntuacion"] or 0),
                               d["licitacion_id"]))
    return salida


def _mejor_de(enlaces: list[dict]) -> dict | None:
    """El enlace que vale de una consulta: el confirmado, o la mejor candidata no
    rechazada. `enlaces` ya viene ordenado."""
    for e in enlaces:
        if e["decision"] != "no":
            return e
    return None


def mejores(con: sqlite3.Connection) -> dict[int, dict]:
    """El enlace que vale de cada consulta. La tabla es pequeña —como mucho tres filas
    por consulta— así que se lee entera en lugar de afinar la consulta para cada uso."""
    por_consulta: dict[int, list[dict]] = {}
    for e in _todas(con):
        por_consulta.setdefault(e["consulta_id"], []).append(e)
    salida = {}
    for cid, lista in por_consulta.items():
        mejor = _mejor_de(lista)
        if mejor:
            salida[cid] = mejor
    return salida


def _grupo_de(con: sqlite3.Connection, lic_id: int) -> list[sqlite3.Row]:
    """Los anuncios del expediente de una licitación, del más reciente al primero."""
    fila = con.execute("SELECT clave_grupo FROM licitaciones WHERE id = ?",
                       (lic_id,)).fetchone()
    if fila is None:
        return []
    if fila["clave_grupo"] is None:
        return con.execute("SELECT * FROM licitaciones WHERE id = ?", (lic_id,)).fetchall()
    return con.execute(
        """SELECT * FROM licitaciones WHERE clave_grupo = ?
            ORDER BY fecha_publicacion DESC, id DESC""", (fila["clave_grupo"],)).fetchall()


def _resumen(con: sqlite3.Connection, lic_id: int) -> dict | None:
    """Lo que se enseña de un expediente enlazado. Se abre su anuncio más reciente,
    como en la bandeja; la fecha es la de su primera publicación."""
    anuncios = _grupo_de(con, lic_id)
    if not anuncios:
        return None
    ultimo = anuncios[0]
    return {
        "id": ultimo["id"],
        "objeto": ultimo["objeto"],
        "organo": ultimo["organo"],
        "estado": ultimo["estado"],
        "fuente": ultimo["fuente"],
        "publicada": min((a["fecha_publicacion"] for a in anuncios
                          if a["fecha_publicacion"]), default=None),
        "fecha_limite_presentacion": ultimo["fecha_limite_presentacion"],
        "importe": ultimo["importe_referencia"],
        "adjudicatario": next((a["adjudicatario"] for a in anuncios if a["adjudicatario"]),
                              None),
    }


def de_consulta(con: sqlite3.Connection, consulta_id: int) -> dict:
    """Las licitaciones que pueden haber salido de una consulta, para su ficha."""
    if not db.hay_indice(con, db.INDICE_CONSULTAS) and not con.execute(
            "SELECT 1 FROM enlaces_consulta LIMIT 1").fetchone():
        return {"preparando": True, "candidatas": []}
    enlaces = _todas(con, consulta_id)
    if any(e["decision"] == "si" for e in enlaces):
        enlaces = [e for e in enlaces if e["decision"] == "si"]
    candidatas = []
    for e in enlaces:
        ficha = _resumen(con, e["licitacion_id"])
        if ficha:
            candidatas.append({**ficha, "licitacion_id": e["licitacion_id"],
                               "nivel": e["nivel"], "decision": e["decision"],
                               "puntuacion": e["puntuacion"], "palabras": e["palabras"]})
    return {"preparando": False, "candidatas": candidatas}


def de_licitacion(con: sqlite3.Connection, lic_id: int) -> list[dict]:
    """Las consultas previas de las que sale esta licitación.

    Solo las que la tienen como enlace QUE VALE: una consulta con tres candidatas no se
    anuncia en las tres.
    """
    ids_grupo = {a["id"] for a in _grupo_de(con, lic_id)}
    if not ids_grupo:
        return []
    salida = []
    for cid, e in mejores(con).items():
        if e["licitacion_id"] not in ids_grupo:
            continue
        c = con.execute(
            "SELECT id, objeto, organo, fecha_publicacion, fecha_limite_presentacion"
            " FROM licitaciones WHERE id = ?", (cid,)).fetchone()
        if c:
            salida.append({**dict(c), "licitacion_id": e["licitacion_id"],
                           "nivel": e["nivel"], "decision": e["decision"]})
    salida.sort(key=lambda d: d["fecha_publicacion"] or "")
    return salida


def anotar(con: sqlite3.Connection, items: list[dict]) -> list[dict]:
    """Pone en cada tarjeta lo que hace falta para sus píldoras.

    - En una consulta, `licitada`: el nivel de su enlace, si lo tiene.
    - En una licitación, `consulta_previa`: el nivel del enlace con la consulta de la
      que sale, si sale de alguna.
    """
    if not items:
        return items
    try:
        validos = mejores(con)
    except sqlite3.OperationalError:
        # Una base abierta en solo lectura que todavía no tiene las tablas nuevas.
        return items
    if not validos:
        return items
    grupos_enlazados: dict[str, str] = {}
    ids = list({e["licitacion_id"] for e in validos.values()})
    nivel_por_id = {}
    for e in validos.values():
        previo = nivel_por_id.get(e["licitacion_id"])
        if previo is None or NIVELES.index(e["nivel"]) < NIVELES.index(previo):
            nivel_por_id[e["licitacion_id"]] = e["nivel"]
    for tanda in db._por_tandas(ids):
        for f in con.execute(
                "SELECT id, COALESCE(clave_grupo, CAST(id AS TEXT)) AS g FROM licitaciones"
                f" WHERE id IN ({', '.join('?' * len(tanda))})", tanda):
            grupos_enlazados[f["g"]] = nivel_por_id[f["id"]]
    for it in items:
        if it.get("fuente") == FUENTE_CONSULTAS:
            e = validos.get(it["id"])
            if e:
                it["licitada"] = e["nivel"]
        else:
            nivel = grupos_enlazados.get(it.get("clave_grupo") or str(it["id"]))
            if nivel:
                it["consulta_previa"] = nivel
    return items


def licitadas_desde(con: sqlite3.Connection, marca: int | None,
                    estados: tuple[str, ...]) -> int:
    """Consultas que sigues cuyo pliego ha aparecido después de `marca` (la última
    visita). Es lo que suma al número del icono de la aplicación: el aviso que se
    quiere de una consulta es «ya ha salido el pliego»."""
    if marca is None:
        return 0
    try:
        validos = mejores(con)
    except sqlite3.OperationalError:
        return 0
    if not validos:
        return 0
    seguidas = {f[0] for f in con.execute(
        f"""SELECT r.licitacion_id FROM revisiones r
             JOIN licitaciones l ON l.id = r.licitacion_id
            WHERE l.fuente = ? AND r.estado IN ({', '.join('?' * len(estados))})""",
        (FUENTE_CONSULTAS, *estados))}
    return sum(1 for cid, e in validos.items()
               if cid in seguidas and e["nivel"] in NIVELES_FIRMES
               and e["licitacion_id"] > marca)


def decidir(con: sqlite3.Connection, consulta_id: int, licitacion_id: int,
            decision: str | None) -> None:
    """«Es esta» (`si`), «no es esta» (`no`) o deshacer (`None`)."""
    fila = con.execute("SELECT fuente FROM licitaciones WHERE id = ?",
                       (consulta_id,)).fetchone()
    if fila is None or fila["fuente"] != FUENTE_CONSULTAS:
        raise ValueError("eso no es una consulta preliminar de mercado")
    if con.execute("SELECT 1 FROM licitaciones WHERE id = ?",
                   (licitacion_id,)).fetchone() is None:
        raise ValueError("no existe esa licitación")
    if decision is None:
        con.execute("DELETE FROM enlaces_decision WHERE consulta_id = ? AND licitacion_id = ?",
                    (consulta_id, licitacion_id))
    elif decision in ("si", "no"):
        if decision == "si":
            # Una consulta acaba en un pliego: confirmar uno quita la confirmación de otro.
            con.execute("DELETE FROM enlaces_decision WHERE consulta_id = ? AND decision = 'si'",
                        (consulta_id,))
        con.execute(
            """INSERT OR REPLACE INTO enlaces_decision
                   (consulta_id, licitacion_id, decision, decidido_en)
               VALUES (?, ?, ?, ?)""", (consulta_id, licitacion_id, decision, db.ahora()))
    else:
        raise ValueError("decisión no válida")
    con.commit()
