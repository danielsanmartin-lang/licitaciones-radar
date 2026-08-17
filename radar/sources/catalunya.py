"""Conector de la Plataforma de Serveis de Contractació Pública de Cataluña.

Cataluña tiene plataforma propia y PLACSP solo recoge parte de su actividad, así
que sin este conector se pierde un trozo grande del mercado.

Dataset Socrata `ybgg-dgi6` en analisi.transparenciacatalunya.cat, con 67 columnas
que incluyen justo lo que hace falta: `codi_cpv`, `objecte_contracte`,
`termini_presentacio_ofertes`, `valor_estimat_contracte`, `denominacio_adjudicatari`
y el desglose por lotes (`numero_lot`, `descripcio_lot`).

Se filtra en servidor con SoQL para no descargar 1,7 millones de filas: se piden
solo las que casan por CPV o por texto. El filtro fino lo hace después
`radar.matching` sobre lo descargado.

Ojo con el idioma: los textos están en catalán. "concienciación" es
"conscienciació" y "ciberseguridad" es "ciberseguretat". Los perfiles de búsqueda
deben incluir ambas formas, y por eso el índice FTS usa `remove_diacritics`.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from datetime import date, timedelta
from typing import Iterator

from .. import net, progreso
from ..model import (
    ESTADO_ADJUDICADA, ESTADO_ANULADA, ESTADO_DESCONOCIDO, ESTADO_EVALUACION,
    ESTADO_FORMALIZADA, ESTADO_PREVIO, ESTADO_PUBLICADA, ESTADO_RESUELTA,
    Licitacion,
)

log = logging.getLogger(__name__)

BASE = "https://analisi.transparenciacatalunya.cat/resource/ybgg-dgi6.json"
POR_PAGINA = 1000

# `fase_publicacio` -> estado normalizado.
FASES = {
    "anunci previ": ESTADO_PREVIO,
    "consulta preliminar del mercat": ESTADO_PREVIO,
    "licitació": ESTADO_PUBLICADA,
    "licitacio": ESTADO_PUBLICADA,
    "anunci de licitació": ESTADO_PUBLICADA,
    "avaluació": ESTADO_EVALUACION,
    "adjudicació": ESTADO_ADJUDICADA,
    "formalització": ESTADO_FORMALIZADA,
    "anul·lació": ESTADO_ANULADA,
    "anullació": ESTADO_ANULADA,
    "desistiment": ESTADO_RESUELTA,
    "renúncia": ESTADO_RESUELTA,
}


def _estado(fase: str | None, resultat: str | None) -> str:
    if fase:
        clave = fase.strip().lower()
        for patron, estado in FASES.items():
            if patron in clave:
                return estado
    if resultat:
        r = resultat.strip().lower()
        if "adjudic" in r:
            return ESTADO_ADJUDICADA
        if "desert" in r or "renúncia" in r or "desistiment" in r:
            return ESTADO_RESUELTA
    return ESTADO_DESCONOCIDO


def _url(valor) -> str | None:
    """Socrata devuelve las URLs como {'url': '...'}."""
    if isinstance(valor, dict):
        return valor.get("url")
    if isinstance(valor, str) and valor.startswith("http"):
        return valor
    return None


def _escapar(texto: str) -> str:
    return texto.replace("'", "''")


_RE_RANGO = re.compile(
    r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})\s*(?:a|al|fins|hasta|-|–)\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})",
    re.IGNORECASE,
)
_RE_MESES = re.compile(r"(\d{1,3})\s*(mes|mesos|meses)", re.IGNORECASE)
_RE_ANIOS = re.compile(r"(\d{1,2})\s*(any|anys|año|años|anio|anios)", re.IGNORECASE)


def parsear_duracion(texto: str | None) -> tuple[float | None, str | None, str | None]:
    """Interpreta `durada_contracte`, que es texto libre. Devuelve (meses, inicio, fin).

    Cataluña no publica un número de meses como PLACSP, sino cadenas del estilo
    "10/07/2026 a 09/01/2027". A veces viene la duración en meses o años. Si no se
    entiende, se devuelve todo a None en lugar de adivinar.
    """
    if not texto:
        return None, None, None
    t = str(texto).strip()

    m = _RE_RANGO.search(t)
    if m:
        d1, m1, a1, d2, m2, a2 = (int(x) for x in m.groups())
        try:
            inicio = date(a1, m1, d1)
            fin = date(a2, m2, d2)
        except ValueError:
            return None, None, None
        if fin < inicio:
            return None, None, None
        meses = round((fin - inicio).days / 30.44, 2)
        return meses, inicio.isoformat(), fin.isoformat()

    m = _RE_ANIOS.search(t)
    if m:
        return float(m.group(1)) * 12, None, None
    m = _RE_MESES.search(t)
    if m:
        return float(m.group(1)), None, None
    return None, None, None


def construir_where(
    *, cpv: list[str], terminos: list[str], desde: date | None
) -> str:
    """Filtro SoQL: (CPV o texto) y, si procede, fecha de publicación.

    `upper()` + `like` es lo que hay: SoQL no ofrece búsqueda insensible a
    acentos, así que los términos con tilde deben venir ya en las dos variantes
    desde el perfil.
    """
    alternativas = []
    for codigo in cpv:
        alternativas.append(f"starts_with(codi_cpv, '{_escapar(codigo)}')")
    for termino in terminos:
        patron = f"%{_escapar(termino).upper()}%"
        alternativas.extend(
            [
                f"upper(objecte_contracte) like '{patron}'",
                f"upper(denominacio) like '{patron}'",
                f"upper(descripcio_lot) like '{patron}'",
            ]
        )

    clausulas = []
    if alternativas:
        clausulas.append("(" + " OR ".join(alternativas) + ")")
    if desde:
        clausulas.append(f"data_publicacio_anunci >= '{desde.isoformat()}T00:00:00'")
    return " AND ".join(clausulas) if clausulas else "1=1"


def parsear_fila(fila: dict) -> Licitacion | None:
    interno = fila.get("id_intern") or fila.get("codi_expedient")
    if not interno:
        return None
    lote = fila.get("numero_lot")
    # Un id_intern se repite por lote: se incluye el lote en la clave para no
    # machacar unos lotes con otros.
    id_externo = f"{interno}#{lote}" if lote and lote not in ("0", 0) else str(interno)

    pliegos = [
        u for u in (
            _url(fila.get("url_json_licitacio")),
            _url(fila.get("url_json_previ")),
            _url(fila.get("url_json_adjudicacio")),
        ) if u
    ]

    meses, inicio, fin = parsear_duracion(fila.get("durada_contracte"))

    return Licitacion(
        fuente="catalunya",
        id_externo=id_externo,
        expediente=fila.get("codi_expedient"),
        organo=fila.get("nom_organ"),
        nif_organo=fila.get("codi_dir3"),
        objeto=fila.get("denominacio"),
        descripcion=fila.get("objecte_contracte"),
        cpv=fila.get("codi_cpv"),
        importe_sin_iva=fila.get("pressupost_licitacio_sense")
        or fila.get("pressupost_licitacio_sense_1"),
        valor_estimado=fila.get("valor_estimat_contracte") or fila.get("valor_estimat_expedient"),
        procedimiento=fila.get("procediment"),
        tipo_contrato=fila.get("tipus_contracte"),
        estado=_estado(fila.get("fase_publicacio"), fila.get("resultat")),
        estado_origen=fila.get("fase_publicacio"),
        fecha_publicacion=fila.get("data_publicacio_anunci")
        or fila.get("data_publicacio_previ")
        or fila.get("data_publicacio_contracte"),
        fecha_limite_presentacion=fila.get("termini_presentacio_ofertes"),
        fecha_actualizacion=fila.get("data_publicacio_adjudicacio")
        or fila.get("data_publicacio_anunci"),
        nuts=fila.get("codi_nuts"),
        lugar=fila.get("lloc_execucio"),
        ccaa="Cataluña",
        url_detalle=_url(fila.get("enllac_publicacio")),
        urls_pliegos=pliegos,
        lote_num=None if lote in ("0", 0) else lote,
        lote_desc=fila.get("descripcio_lot"),
        adjudicatario=fila.get("denominacio_adjudicatari"),
        importe_adjudicacion=fila.get("import_adjudicacio_sense"),
        fecha_adjudicacion=fila.get("data_adjudicacio_contracte"),
        duracion_meses=meses,
        fecha_inicio_ejecucion=inicio or fila.get("data_formalitzacio_contracte"),
        fecha_fin_prevista=fin,
        raw={
            "ambit": fila.get("nom_ambit"),
            "resultat": fila.get("resultat"),
            "durada_contracte": fila.get("durada_contracte"),
        },
    )


class FuenteCatalunya:
    nombre = "catalunya"

    def __init__(self, cpv: list[str], terminos: list[str], *, dias_ventana: int = 30):
        self.cpv = cpv
        self.terminos = terminos
        self.dias_ventana = dias_ventana
        self._cursor_nuevo: str | None = None

    def _paginar(self, where: str) -> Iterator[Licitacion]:
        offset = 0
        while True:
            consulta = urllib.parse.urlencode(
                {
                    "$where": where,
                    "$limit": POR_PAGINA,
                    "$offset": offset,
                    "$order": "data_publicacio_anunci DESC NULL LAST",
                }
            )
            progreso.pagina()
            filas = net.descargar_json(f"{BASE}?{consulta}")
            if not filas:
                break
            for fila in filas:
                lic = parsear_fila(fila)
                if lic is not None:
                    yield lic
            if len(filas) < POR_PAGINA:
                break
            offset += POR_PAGINA

    def incremental(self, cursor: str | None) -> Iterator[Licitacion]:
        if cursor:
            try:
                desde = date.fromisoformat(cursor) - timedelta(days=3)
            except ValueError:
                desde = date.today() - timedelta(days=self.dias_ventana)
        else:
            desde = date.today() - timedelta(days=self.dias_ventana)
        self._cursor_nuevo = date.today().isoformat()
        yield from self._paginar(
            construir_where(cpv=self.cpv, terminos=self.terminos, desde=desde)
        )

    def historico(self, anio: int) -> Iterator[Licitacion]:
        self._cursor_nuevo = date.today().isoformat()
        where = construir_where(cpv=self.cpv, terminos=self.terminos, desde=date(anio, 1, 1))
        where += f" AND data_publicacio_anunci < '{anio + 1}-01-01T00:00:00'"
        yield from self._paginar(where)

    def cursor_nuevo(self) -> str | None:
        return self._cursor_nuevo
