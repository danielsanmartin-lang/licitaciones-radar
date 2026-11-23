"""De una barra, una baldosa o una celda de un gráfico a los expedientes que cuenta.

Pulsar «febrero» en «Cuándo sale el trabajo» tiene que enseñar exactamente los
expedientes que suman esa columna: ni uno más ni uno menos. Por eso aquí no se vuelve a
escribir ninguna regla. Cada desglose sale de la MISMA función que alimenta su gráfico
(`consultas._filas_calendario`, `_filas_baja`, `_filas_comunidades`…) y reparte con la
misma regla (`_tramo_de`, `_baja_de`, `_plazo_de`…). Si un día cambia cómo se cuenta un
bloque, cambian a la vez el gráfico y su lista. `tests/test_desglose.py` lo comprueba
elemento a elemento: cada columna, cada baldosa y cada celda contra su lista.

La Bandeja no sirve de destino, y no por pereza: no sabe filtrar por mes de primera
publicación, tramo de importe, CPV, organismo ni empresa; con una temática del mercado
no tiene esas fichas, y cuenta por anuncio donde la Analítica cuenta por expediente. El
número de la lista no cuadraría con el de la gráfica, que es justo lo que no puede pasar.

Lo que devuelve son tarjetas con la forma de la Bandeja (`consultas._tarjetas`), cada una
con el `dato` que la metió en ese elemento —el importe con el que cayó en su tramo, su
baja, sus días de plazo—, porque ese dato no siempre es el que enseña la tarjeta: el
importe de un tramo es el MAYOR publicado del expediente y la tarjeta enseña el de su
último anuncio.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from . import consultas as c
from .consultas import Ambito

LIMITE = 100
LIMITE_MAXIMO = 500

# La porción de la cuota que no es ninguna de las cinco empresas. Con asteriscos para que
# no pueda ser el nombre de una.
OTRAS_EMPRESAS = "*otras*"

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")

# Las formas de ordenar dentro de un grupo.
RECIENTE = "reciente"          # primera publicación, de la más nueva a la más antigua
VALOR_DESC = "valor_desc"      # el dato, de mayor a menor (importes, bajas)
FECHA_ASC = "fecha_asc"        # la fecha del dato, de la más cercana a la más lejana

# Lo calculado, hasta que cambie la base: «Cargar más» pide la misma lista otra vez.
_MEMO: dict = {}
_MEMO_MAXIMO = 16
# Aparte y más corto: en toda la IT son decenas de miles de pares por rango.
_MEMO_RECORRIDOS: dict = {}
_MEMO_RECORRIDOS_MAXIMO = 4


# --- Validación de la clave del elemento pulsado -------------------------------------

def _mes_del_anio(clave: str) -> str:
    if len(clave or "") == 2 and clave.isdigit() and 1 <= int(clave) <= 12:
        return clave
    raise ValueError("el mes tiene que ser '01'…'12'")


def _anio_mes(clave: str) -> str:
    if (len(clave or "") == 7 and clave[4] == "-" and clave[:4].isdigit()
            and clave[5:].isdigit() and 1 <= int(clave[5:]) <= 12):
        return clave
    raise ValueError("el mes tiene que ser 'AAAA-MM'")


def _anio(clave: str) -> str:
    if len(clave or "") == 4 and clave.isdigit():
        return clave
    raise ValueError("el año tiene que ser 'AAAA'")


def _tramo(clave: str, cortes: tuple) -> int:
    if (clave or "").isdigit() and int(clave) <= len(cortes):
        return int(clave)
    raise ValueError(f"el tramo tiene que ser un número de 0 a {len(cortes)}")


def _texto(clave: str, que: str) -> str:
    if clave and clave.strip():
        return clave
    raise ValueError(f"falta {que}")


def _por_anio(miembros: list, mes: str) -> list:
    """Los grupos de un mes del año: uno por año, del más reciente al más antiguo."""
    anios = sorted({m["grupo"] for m in miembros}, reverse=True)
    return [{"clave": a, "titulo": f"{MESES[int(mes) - 1]} de {a}"} for a in anios]


# --- Analítica ------------------------------------------------------------------------
#
# Cada función recibe lo mismo que su bloque y devuelve `miembros`: un dict por expediente
# con `g` (o `rep`, si ya se sabe qué anuncio enseñar), y opcionalmente `dato` y `grupo`.

def _calendario(con, ambito, desde, hasta, nombre, clave):
    mes = _mes_del_anio(clave)
    miembros = [{"g": f["g"], "grupo": f["mes"][:4]}
                for f in c._filas_calendario(con, ambito, desde, hasta)
                if f["mes"][5:7] == mes]
    return {"miembros": miembros, "grupos": _por_anio(miembros, mes), "orden": RECIENTE}


def _importes(con, ambito, desde, hasta, nombre, clave):
    i = _tramo(clave, c.TRAMOS_IMPORTE)
    return {"orden": VALOR_DESC, "miembros": [
        {"g": f["g"], "dato": {"texto": "mayor importe publicado", "valor": f["imp"],
                               "unidad": "eur"}}
        for f in c._filas_importes(con, ambito, desde, hasta)
        if c._tramo_de(f["imp"], c.TRAMOS_IMPORTE) == i
    ]}


def _baja(con, ambito, desde, hasta, nombre, clave):
    i = _tramo(clave, c.TRAMOS_BAJA)
    miembros = []
    for f in c._filas_baja(con, ambito, desde, hasta):
        baja, motivo = c._baja_de(f["pres"], f["adj"])
        if motivo is None and c._tramo_de(baja, c.TRAMOS_BAJA) == i:
            miembros.append({"g": f["g"], "dato": {
                "texto": "de baja", "valor": round(baja, 1), "unidad": "pct",
                "detalle": {"presupuesto": f["pres"], "adjudicado": f["adj"]}}})
    return {"miembros": miembros, "orden": VALOR_DESC}


def _plazo(con, ambito, desde, hasta, nombre, clave):
    i = _tramo(clave, c.TRAMOS_PLAZO)
    miembros = []
    for f in c._filas_plazo(con, ambito, desde, hasta):
        dias, motivo = c._plazo_de(f["pub"], f["lim"])
        if motivo is None and c._tramo_de(dias, c.TRAMOS_PLAZO) == i:
            miembros.append({"g": f["g"], "dato": {
                "texto": "días para presentar", "valor": dias, "unidad": "dias"}})
    return {"miembros": miembros, "orden": RECIENTE}


def _recorridos(con, ambito, desde, hasta) -> list:
    """[(g, días)] del ciclo, guardados hasta que cambie la base. Es la consulta cara de la
    pestaña —cruza el historial de versiones: 8 a 11 s medidos en toda la IT— y cada
    columna del ciclo la necesita entera; sin esto, cada clic la repetía."""
    memo = (c._firma_de_la_base(con), ambito, desde, hasta)
    if memo not in _MEMO_RECORRIDOS:
        if len(_MEMO_RECORRIDOS) >= _MEMO_RECORRIDOS_MAXIMO:
            _MEMO_RECORRIDOS.clear()
        filtro, p_rango = c._solo_en_rango(ambito, desde, hasta)
        _MEMO_RECORRIDOS[memo] = [(f["g"], f["dias"])
                                  for f in c._recorridos(con, ambito, filtro, p_rango)]
    return _MEMO_RECORRIDOS[memo]


def _ciclo(con, ambito, desde, hasta, nombre, clave):
    i = _tramo(clave, c.TRAMOS_CICLO)
    return {"orden": RECIENTE, "miembros": [
        {"g": g, "dato": {"texto": "días de la publicación a la adjudicación",
                          "valor": dias, "unidad": "dias"}}
        for g, dias in _recorridos(con, ambito, desde, hasta)
        if dias is not None and dias > 0 and c._tramo_de(dias, c.TRAMOS_CICLO) == i
    ]}


def _comunidad(vista: str):
    """Una baldosa del mapa o una barra por comunidad, de lo adjudicado o de lo activo.

    Los de más de 50 M€ van en su propio grupo: no suman en el mapa ni en las barras de
    importe, pero sí en las de número, y esconderlos dejaría fuera licitaciones a las que
    se puede ir."""
    campo, texto = ("adj", "adjudicado") if vista == "adjudicadas" else ("pres", "en juego")

    def calcular(con, ambito, desde, hasta, nombre, clave):
        ccaa = _texto(clave, "la comunidad")
        adjudicadas, activas = c._filas_comunidades(con, ambito, desde, hasta)
        miembros = [
            {"g": f["g"],
             "grupo": "fuera" if f[campo] > c.IMPORTE_MAXIMO_COMPARABLE else "dentro",
             "dato": {"texto": texto, "valor": f[campo], "unidad": "eur"}}
            for f in (adjudicadas if vista == "adjudicadas" else activas)
            if f["ccaa"] == ccaa
        ]
        grupos = [{"clave": "dentro", "titulo": None}]
        if any(m["grupo"] == "fuera" for m in miembros):
            grupos.append({
                "clave": "fuera",
                "titulo": f"De más de {c.IMPORTE_MAXIMO_COMPARABLE // 1_000_000} M€: no suman "
                          "en el mapa ni en las barras de importe, sí en las de número"})
        return {"miembros": miembros, "grupos": grupos, "orden": VALOR_DESC}

    return calcular


def _cpv(con, ambito, desde, hasta, nombre, clave):
    codigo = clave or ""
    if not (codigo.isdigit() and len(codigo) in (2, 8)):
        raise ValueError("el CPV tiene que ser una división (2 cifras) o un código (8)")
    trocear = c._divisiones_cpv if len(codigo) == 2 else c._codigos_cpv
    return {"orden": RECIENTE, "miembros": [
        {"g": g, "dato": {"texto": "CPV " + ", ".join(sorted(c._codigos_cpv(propios)))}}
        for g, propios in c._cpv_por_expediente(con, ambito, desde, hasta)
        if propios and codigo in trocear(propios)
    ]}


def _procedimiento(con, ambito, desde, hasta, nombre, clave):
    elegido = _texto(clave, "el procedimiento")
    filas = c._procedimientos_por_expediente(con, ambito, desde, hasta)
    if elegido == "el resto":
        cuenta: dict = {}
        for _, p in filas:
            if p:
                cuenta[p] = cuenta.get(p, 0) + 1
        resto = {p for p, _ in c._orden_procedimientos(cuenta)[c.TOP_PROCEDIMIENTOS:]}
        casa = lambda p: p in resto  # noqa: E731
    else:
        casa = lambda p: p == elegido  # noqa: E731
    return {"orden": RECIENTE, "miembros": [
        {"g": g, "dato": {"texto": p}} for g, p in filas if p and casa(p)]}


def _estacionalidad(con, ambito, desde, hasta, nombre, clave):
    mes = _mes_del_anio(clave)
    organo = _texto(nombre, "el órgano")
    miembros = [{"g": g, "grupo": m[:4]}
                for g, o, m in c._organos_por_expediente(con, ambito, desde, hasta)
                if o == organo and m and m[5:7] == mes]
    return {"miembros": miembros, "grupos": _por_anio(miembros, mes), "orden": RECIENTE}


def _cuota(con, ambito, desde, hasta, nombre, clave):
    anio = _anio(clave)
    empresa = _texto(nombre, "la empresa")
    _, filas = c._filas_cuota(con, ambito)
    if empresa == OTRAS_EMPRESAS:
        primeras = set(c._primeras_cuota(filas)[0])
        casa = lambda f: f["clave"] not in primeras  # noqa: E731
    else:
        buscada = c.normalizar_empresa(empresa)
        casa = lambda f: f["clave"] == buscada  # noqa: E731
    return {"orden": RECIENTE, "miembros": [
        {"g": f["g"], "dato": {"texto": "adjudicado", "valor": f["imp"],
                               "unidad": "eur", "fecha": f["fecha"]}}
        for f in filas if f["anio"] == anio and casa(f)
    ]}


def _consultas(con, ambito, desde, hasta, nombre, clave):
    i = _tramo(clave, c.TRAMOS_CONSULTA)
    if not c.db.hay_indice(con, c.db.INDICE_CONSULTAS):
        raise ValueError("el bloque de consultas todavía se está preparando")
    filas = c._consultas_enlazadas(con)
    publicada = {f["id"]: f["pub"] for f in filas}
    return {"orden": RECIENTE, "miembros": [
        {"rep": {"id": id_, "anuncios": 1, "primera_publicacion": publicada[id_]},
         "dato": {"texto": "días hasta su licitación", "valor": dias, "unidad": "dias"}}
        for id_, dias in c._dias_de_consultas(filas)
        if c._tramo_de(dias, c.TRAMOS_CONSULTA) == i
    ]}


def _incumbentes(con, ambito, desde, hasta, nombre, clave):
    if clave not in ("repite", "cambia"):
        raise ValueError("tiene que ser 'repite' o 'cambia'")
    quiere = clave == "repite"
    return {"forma": "pareja", "miembros": [
        {"pareja": p} for p in c._sucesiones_en_rango(con, ambito, desde, hasta)
        if p["repite"] is quiere
    ]}


def _renovaciones(con, ambito, desde, hasta, nombre, clave):
    mes = _anio_mes(clave)
    return {"orden": FECHA_ASC, "miembros": [
        {"g": f["g"], "dato": {"texto": "acaba", "fecha": f["fin_dia"]}}
        for f in c._filas_vencimientos_por_mes(con, ambito, c.MESES_CALENDARIO_RENOVACIONES)
        if f["fin"] == mes
    ]}


# --- Fichas -----------------------------------------------------------------------------

def _rep(e: dict) -> dict:
    return {"id": e["id"], "anuncios": e["anuncios"],
            "primera_publicacion": e["primera_publicacion"]}


def _organismo_meses(con, ambito, desde, hasta, nombre, clave):
    mes = _mes_del_anio(clave)
    _, expedientes = c._expedientes_de_organismo(con, _texto(nombre, "el órgano"), ambito)
    miembros = [{"rep": _rep(e), "grupo": e["mes"][:4]}
                for e in expedientes if e["mes"] and e["mes"][5:7] == mes]
    return {"miembros": miembros, "grupos": _por_anio(miembros, mes), "orden": RECIENTE}


def _organismo_procedimiento(con, ambito, desde, hasta, nombre, clave):
    elegido = _texto(clave, "el procedimiento")
    _, expedientes = c._expedientes_de_organismo(con, _texto(nombre, "el órgano"), ambito)
    return {"orden": RECIENTE, "miembros": [
        {"rep": _rep(e)} for e in expedientes if c._procedimiento_de(e) == elegido]}


def _ganados(con, ambito, nombre) -> list:
    clave = c.normalizar_empresa(_texto(nombre, "la empresa"))
    if not clave:
        raise ValueError("no es una razón social reconocible")
    return c._expedientes_de_competidor(con, clave, ambito)[1]


def _dato_ganado(e: dict, ultima) -> dict:
    return {"texto": "adjudicado", "valor": e["imp"], "unidad": "eur",
            "fecha": ultima["fecha_adjudicacion"]}


def _competidor_anios(con, ambito, desde, hasta, nombre, clave):
    anio = _anio(clave)
    miembros = []
    for e in _ganados(con, ambito, nombre):
        ultima, suyo = c._adjudicacion_de(e)
        if suyo == anio:
            miembros.append({"rep": _rep(e), "dato": _dato_ganado(e, ultima)})
    return {"miembros": miembros, "orden": RECIENTE}


def _competidor_comunidades(con, ambito, desde, hasta, nombre, clave):
    ccaa = _texto(clave, "la comunidad")
    miembros = []
    for e in _ganados(con, ambito, nombre):
        ultima, _ = c._adjudicacion_de(e)
        if ultima["ccaa"] == ccaa:
            miembros.append({"rep": _rep(e), "dato": _dato_ganado(e, ultima)})
    return {"miembros": miembros, "orden": RECIENTE}


# --- Vencimientos -------------------------------------------------------------------------

def _vencimientos_meses(con, ambito, desde, hasta, nombre, clave):
    salida = _renovaciones(con, ambito, desde, hasta, nombre, clave)
    salida["forma"] = "prospecto"
    return salida


# (origen, bloque) -> función. Los nombres de bloque son los de la pantalla (las anclas de
# las tarjetas de la Analítica) para que se lea de dónde viene cada uno.
DESGLOSES = {
    ("analitica", "calendario"): _calendario,
    ("analitica", "importes"): _importes,
    ("analitica", "baja"): _baja,
    ("analitica", "plazo"): _plazo,
    ("analitica", "ciclo"): _ciclo,
    ("analitica", "comunidades-adjudicadas"): _comunidad("adjudicadas"),
    ("analitica", "comunidades-activas"): _comunidad("activas"),
    ("analitica", "cpv"): _cpv,
    ("analitica", "procedimiento"): _procedimiento,
    ("analitica", "estacionalidad"): _estacionalidad,
    ("analitica", "cuota"): _cuota,
    ("analitica", "consultas"): _consultas,
    ("analitica", "incumbentes"): _incumbentes,
    ("analitica", "renovaciones"): _renovaciones,
    ("organismo", "meses"): _organismo_meses,
    ("organismo", "procedimiento"): _organismo_procedimiento,
    ("competidor", "anios"): _competidor_anios,
    ("competidor", "comunidades"): _competidor_comunidades,
    ("vencimientos", "meses"): _vencimientos_meses,
}


# --- Lo común: qué anuncio enseñar, en qué orden, y en páginas -----------------------------

def _indice_expedientes(con, ambito: Ambito) -> dict:
    """{g: el anuncio que se enseña de cada expediente del ámbito}: el más reciente, como en
    la Bandeja y en `_por_expediente`, con cuántos anuncios tiene y su primera publicación.

    Una pasada por todo el ámbito y no una consulta por expediente: `_GRUPO` es una
    expresión (`COALESCE`) y no entra por ningún índice. Se guarda con las fichas, porque
    cambia exactamente cuando ellas.
    """
    def calcular():
        entrada, params = c._entrada_expedientes(ambito)
        indice: dict = {}
        for f in con.execute(
                f"SELECT {c._GRUPO} AS g, l.id, l.fecha_publicacion{entrada}", params):
            pub = f["fecha_publicacion"]
            e = indice.get(f["g"])
            if e is None:
                indice[f["g"]] = {"id": f["id"], "anuncios": 1, "primera_publicacion": pub,
                                  "_ultimo": (pub or "", f["id"])}
                continue
            e["anuncios"] += 1
            if pub and (e["primera_publicacion"] is None or pub < e["primera_publicacion"]):
                e["primera_publicacion"] = pub
            if (pub or "", f["id"]) > e["_ultimo"]:
                e["id"], e["_ultimo"] = f["id"], (pub or "", f["id"])
        return indice

    return c._memo_fichas(con, ("indice-expedientes", ambito), calcular)


def _clave_orden(orden: str):
    if orden == VALOR_DESC:
        return (lambda m: ((m.get("dato") or {}).get("valor") or 0,
                           m["rep"]["primera_publicacion"] or "", m["rep"]["id"])), True
    if orden == FECHA_ASC:
        return (lambda m: ((m.get("dato") or {}).get("fecha") or "9999",
                           m["rep"]["id"])), False
    return (lambda m: (m["rep"]["primera_publicacion"] or "", m["rep"]["id"])), True


def _calcular(con, origen, bloque, ambito, desde, hasta, nombre, clave) -> dict:
    funcion = DESGLOSES.get((origen, bloque))
    if funcion is None:
        raise ValueError(f"no hay desglose para {origen}/{bloque}")
    hecho = funcion(con, ambito, desde, hasta, nombre, clave)
    miembros = hecho["miembros"]
    forma = hecho.get("forma", "tarjeta")

    if forma != "pareja":
        indice = None
        for m in miembros:
            if "rep" not in m:
                indice = indice if indice is not None else _indice_expedientes(con, ambito)
                m["rep"] = indice[m["g"]]
        clave_orden, al_reves = _clave_orden(hecho.get("orden", RECIENTE))
        miembros.sort(key=clave_orden, reverse=al_reves)

    grupos = [g for g in (hecho.get("grupos") or [])]
    if grupos:
        posicion = {g["clave"]: i for i, g in enumerate(grupos)}
        # Estable: dentro de cada grupo se queda el orden de arriba.
        miembros.sort(key=lambda m: posicion.get(m.get("grupo"), len(grupos)))
        for g in grupos:
            g["total"] = sum(1 for m in miembros if m.get("grupo") == g["clave"])
        grupos = [g for g in grupos if g["total"]]
    return {"forma": forma, "miembros": miembros, "grupos": grupos}


def desglose(con: sqlite3.Connection, *, origen: str, bloque: str, clave: str | None,
             perfil: str | None = None, categoria: str | None = None,
             desde: str | None = None, hasta: str | None = None, nombre: str | None = None,
             limite: int = LIMITE, offset: int = 0) -> dict:
    """Los expedientes de un elemento de un gráfico, en páginas de `limite`.

    `origen` y `bloque` dicen de qué gráfico (ver `DESGLOSES`); `clave`, qué elemento (un
    mes, un tramo, una comunidad…); `nombre`, de quién, cuando el gráfico es de un órgano o
    de una empresa. El ámbito y el rango son los del gráfico de origen: con otros, el
    número de la lista no sería el que se acaba de pulsar.

    Lanza ValueError si el gráfico o el elemento no existen.
    """
    ambito = Ambito.de(perfil, categoria)
    limite = max(1, min(int(limite), LIMITE_MAXIMO))
    offset = max(0, int(offset))
    memo = (c._firma_de_la_base(con), origen, bloque, clave, nombre, ambito, desde, hasta,
            date.today())
    if memo not in _MEMO:
        if len(_MEMO) >= _MEMO_MAXIMO:
            _MEMO.clear()
        _MEMO[memo] = _calcular(con, origen, bloque, ambito, desde, hasta, nombre, clave)
    hecho = _MEMO[memo]

    pagina = hecho["miembros"][offset:offset + limite]
    if hecho["forma"] == "pareja":
        items = [dict(m["pareja"], forma="pareja") for m in pagina]
    else:
        items = _items(con, pagina, ambito, prospecto=hecho["forma"] == "prospecto")
    return {
        "origen": origen, "bloque": bloque, "clave": clave, "nombre": nombre,
        "ambito": ambito.etiqueta, "mercado": ambito.mercado,
        "total": len(hecho["miembros"]),
        "grupos": [dict(g) for g in hecho["grupos"]],
        "offset": offset, "limite": limite,
        "hay_mas": offset + len(pagina) < len(hecho["miembros"]),
        "items": items,
    }


def _items(con, pagina: list, ambito: Ambito, *, prospecto: bool) -> list:
    """Las tarjetas de una página, con su `dato` y su `grupo`.

    Las de Vencimientos van con la forma de la prospección (incumbente, fin, «Seguir»), que
    es lo que se hace con ellas; si alguna no está en la prospección —un anuncio nuevo de
    un expediente descartado—, sale con la tarjeta de siempre antes que desaparecer.
    """
    prospectos: dict = {}
    if prospecto:
        prospectos = _prospectos(con, ambito)
    normales = [m for m in pagina if m["rep"]["id"] not in prospectos]
    tarjetas = {t["id"]: t for t in c._tarjetas(con, [m["rep"] for m in normales])}
    salida = []
    for m in pagina:
        rid = m["rep"]["id"]
        if rid in prospectos:
            item = dict(prospectos[rid], forma="prospecto")
        elif rid in tarjetas:
            item = dict(tarjetas[rid], forma="tarjeta")
        else:
            continue
        item["dato"] = m.get("dato")
        item["grupo"] = m.get("grupo")
        salida.append(item)
    return salida


def _prospectos(con, ambito: Ambito) -> dict:
    """{id del anuncio que enseña la Bandeja: su tarjeta de prospección}.

    La prospección elige otro anuncio por expediente (el de la fecha de fin más fiable),
    así que se cruza por expediente y se indexa por el anuncio que el desglose enseña."""
    expedientes = c._expedientes_prospeccion(con, ambito.perfil)
    c._marcar_renovaciones(expedientes)
    indice = _indice_expedientes(con, ambito)
    hoy = date.today()
    salida = {}
    for e in expedientes:
        rep = indice.get(e["clave"])
        if rep is None:
            continue
        if e.get("fecha_fin"):
            try:
                e["dias_para_vencer"] = (date.fromisoformat(e["fecha_fin"][:10]) - hoy).days
            except ValueError:
                pass
        salida[rep["id"]] = e
    return salida
