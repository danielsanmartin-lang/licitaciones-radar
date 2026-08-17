"""Modelo normalizado de una licitación, común a todas las fuentes.

Cada conector traduce su formato nativo (ATOM CODICE, JSON de TED, Socrata) a esta
misma forma. Los campos son los que un comercial necesita para decidir en diez
segundos si merece la pena, más lo necesario para detectar cambios de estado.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import date, datetime

# Estados normalizados. Cada fuente tiene su propia nomenclatura; se mapean a estos.
ESTADO_PREVIO = "previo"          # anuncio previo / consulta preliminar de mercado
ESTADO_PUBLICADA = "publicada"    # en plazo o pendiente de resolver
ESTADO_EVALUACION = "evaluacion"  # cerrado el plazo, en valoración
ESTADO_ADJUDICADA = "adjudicada"
ESTADO_FORMALIZADA = "formalizada"
ESTADO_RESUELTA = "resuelta"      # desierta, renuncia, desistimiento
ESTADO_ANULADA = "anulada"
ESTADO_DESCONOCIDO = "desconocido"

ESTADOS_VIVOS = {ESTADO_PREVIO, ESTADO_PUBLICADA, ESTADO_EVALUACION}


def _texto(valor) -> str | None:
    if valor is None:
        return None
    s = re.sub(r"\s+", " ", str(valor)).strip()
    return s or None


def _fecha_iso(valor) -> str | None:
    """Normaliza a ISO-8601. Acepta date, datetime y las variantes de las fuentes."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    s = str(valor).strip()
    if not s:
        return None
    # Socrata: 2026-03-13T13:00:00.000 · TED/CODICE: 2026-03-13T13:00:00+01:00
    s = s.replace("Z", "+00:00")
    for patron in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(s, patron).isoformat()
        except ValueError:
            continue
    try:  # último recurso: el parser flexible de la stdlib
        return datetime.fromisoformat(s).isoformat()
    except ValueError:
        return None


def normalizar(texto: str | None) -> str:
    """Minúsculas sin acentos, para que 'concienciación' == 'concienciacion'.

    Vive aquí, y no en el motor de reglas, porque el resultado se guarda con cada
    licitación: normalizar sobre la marcha costaba 8,7 segundos por cada evaluación
    de los perfiles sobre 127.000 registros, y era el 100% del tiempo.
    """
    if not texto:
        return ""
    descompuesto = unicodedata.normalize("NFD", texto.lower())
    sin_acentos = "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sin_acentos)


def titulo_util_ted(titulo: str | None) -> str:
    """Quita el prefijo genérico de los títulos de TED.

    TED titula «España – <etiqueta del CPV> – <título real>», y los dos primeros
    tramos son idénticos en cientos de anuncios. Usar el título completo para
    agrupar fusionaba licitaciones que no tienen nada que ver: se midieron 247
    grupos con objetos distintos metidos en el mismo saco, lo que **ocultaba**
    licitaciones de la bandeja. Peor que un duplicado.
    """
    if not titulo:
        return ""
    tramos = [t.strip() for t in re.split(r"\s+[–—-]\s+", titulo) if t.strip()]
    if len(tramos) >= 3:
        return " ".join(tramos[2:])
    if len(tramos) == 2:
        return tramos[1]
    return titulo.strip()


def duracion_a_meses(valor, unidad: str | None) -> float | None:
    """Convierte una duración a meses. La unidad NO es opcional interpretarla.

    PLACSP usa `unitCode` con `MON`, `DAY` y `ANN`; TED usa `MONTH` y `YEAR`. Un «48»
    sin mirar la unidad son cuatro años o mes y medio, así que si la unidad no se
    reconoce se asume meses —de largo la más frecuente— y nunca días.
    """
    if valor in (None, ""):
        return None
    try:
        n = float(str(valor).strip().replace(",", "."))
    except ValueError:
        return None
    if n <= 0:
        return None
    u = (unidad or "").strip().upper()
    if u in ("DAY", "DAYS", "D", "DIA", "DIAS"):
        return round(n / 30.44, 2)
    if u in ("ANN", "YEAR", "YEARS", "Y", "A", "ANIO", "ANIOS"):
        return n * 12
    if u in ("WEE", "WEEK", "WEEKS", "W"):
        return round(n / 4.35, 2)
    return n  # MON / MONTH / desconocida


def _sumar_meses(fecha_iso: str | None, meses: float | None) -> str | None:
    if not fecha_iso or not meses:
        return None
    try:
        base = datetime.fromisoformat(fecha_iso).date()
    except ValueError:
        try:
            base = date.fromisoformat(fecha_iso[:10])
        except ValueError:
            return None
    total = base.month - 1 + int(round(meses))
    anio = base.year + total // 12
    mes = total % 12 + 1
    dia = min(base.day, [31, 29 if anio % 4 == 0 and (anio % 100 != 0 or anio % 400 == 0)
                         else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mes - 1])
    return date(anio, mes, dia).isoformat()


def _importe(valor) -> float | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    s = str(valor).strip().replace("€", "").replace(" ", "")
    if not s:
        return None
    # "1.234.567,89" (es) frente a "1234567.89" (fuentes en formato máquina)
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def normalizar_cpv(valor) -> list[str]:
    """Devuelve códigos CPV de 8 dígitos, sin el dígito de control tras el guion."""
    if not valor:
        return []
    bruto = valor if isinstance(valor, (list, tuple, set)) else re.split(r"[;,\s|]+", str(valor))
    salida: list[str] = []
    for item in bruto:
        if not item:
            continue
        m = re.search(r"(\d{8})", str(item))
        if m and m.group(1) not in salida:
            salida.append(m.group(1))
    return salida


@dataclass
class Licitacion:
    """Una licitación (o un lote de una licitación) ya normalizada."""

    fuente: str
    id_externo: str

    expediente: str | None = None
    organo: str | None = None
    nif_organo: str | None = None
    objeto: str | None = None
    descripcion: str | None = None
    cpv: list[str] = field(default_factory=list)

    importe_sin_iva: float | None = None
    valor_estimado: float | None = None
    procedimiento: str | None = None
    tipo_contrato: str | None = None
    estado: str = ESTADO_DESCONOCIDO
    estado_origen: str | None = None

    fecha_publicacion: str | None = None
    fecha_limite_presentacion: str | None = None
    fecha_actualizacion: str | None = None

    nuts: str | None = None
    lugar: str | None = None
    ccaa: str | None = None

    url_detalle: str | None = None
    urls_pliegos: list[str] = field(default_factory=list)

    lote_num: str | None = None
    lote_desc: str | None = None

    adjudicatario: str | None = None
    importe_adjudicacion: float | None = None
    fecha_adjudicacion: str | None = None

    # Para saber cuándo vence el contrato del incumbente y llegar antes de que se
    # renueve. `fecha_fin_prevista` queda a None si no hay forma de saberlo: más vale
    # no tener el dato que tener uno inventado sobre el que llamar a un cliente.
    duracion_meses: float | None = None
    fecha_inicio_ejecucion: str | None = None
    fecha_fin_prevista: str | None = None
    clave_grupo: str | None = None

    raw: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.expediente = _texto(self.expediente)
        self.organo = _texto(self.organo)
        self.nif_organo = _texto(self.nif_organo)
        self.objeto = _texto(self.objeto)
        self.descripcion = _texto(self.descripcion)
        self.procedimiento = _texto(self.procedimiento)
        self.tipo_contrato = _texto(self.tipo_contrato)
        self.lugar = _texto(self.lugar)
        self.lote_desc = _texto(self.lote_desc)
        self.adjudicatario = _texto(self.adjudicatario)
        self.cpv = normalizar_cpv(self.cpv)
        self.importe_sin_iva = _importe(self.importe_sin_iva)
        self.valor_estimado = _importe(self.valor_estimado)
        self.importe_adjudicacion = _importe(self.importe_adjudicacion)
        self.fecha_publicacion = _fecha_iso(self.fecha_publicacion)
        self.fecha_limite_presentacion = _fecha_iso(self.fecha_limite_presentacion)
        self.fecha_actualizacion = _fecha_iso(self.fecha_actualizacion)
        self.fecha_adjudicacion = _fecha_iso(self.fecha_adjudicacion)
        self.fecha_inicio_ejecucion = _fecha_iso(self.fecha_inicio_ejecucion)
        self.fecha_fin_prevista = _fecha_iso(self.fecha_fin_prevista)
        self.urls_pliegos = [u for u in dict.fromkeys(self.urls_pliegos or []) if u]

        # Si la fuente no publica fecha de fin, se deduce del inicio (o, en su
        # defecto, de la adjudicación) más la duración.
        if not self.fecha_fin_prevista and self.duracion_meses:
            arranque = self.fecha_inicio_ejecucion or self.fecha_adjudicacion
            self.fecha_fin_prevista = _sumar_meses(arranque, self.duracion_meses)

        if not self.clave_grupo:
            self.clave_grupo = self._clave_grupo()

    def _clave_grupo(self) -> str:
        """Agrupa los anuncios de un mismo expediente a lo largo de su vida.

        Una licitación genera varios anuncios (licitación, corrección, adjudicación
        por lotes) y cada uno es un registro distinto: LANTIK aparecía dos veces y
        CSIRT Canarias cuatro. En PLACSP el expediente se mantiene entre anuncios y
        sirve de clave; en TED el «expediente» es el número de publicación, único por
        anuncio, así que ahí hay que agrupar por título.
        """
        organo = re.sub(r"[^a-z0-9]+", "", (self.organo or "").lower())[:40]
        if self.fuente.startswith("ted"):
            ancla = re.sub(r"[^a-z0-9]+", "", titulo_util_ted(self.objeto).lower())[:80]
        else:
            ancla = re.sub(r"[^a-z0-9]+", "", (self.expediente or self.objeto or "").lower())[:40]
        if not ancla:
            return f"{self.fuente}:{self.id_externo}"
        return f"{organo}|{ancla}"

    @property
    def clave(self) -> str:
        return f"{self.fuente}:{self.id_externo}"

    @property
    def texto_busqueda(self) -> str:
        """Lo que se indexa en FTS5 y sobre lo que corre el matching por texto."""
        partes = [self.objeto, self.descripcion, self.lote_desc, self.expediente, self.organo]
        return " \n".join(p for p in partes if p)

    @property
    def importe_referencia(self) -> float | None:
        """El importe más representativo disponible, para filtrar por tamaño."""
        for valor in (self.valor_estimado, self.importe_sin_iva, self.importe_adjudicacion):
            if valor:
                return valor
        return None

    def huella(self) -> str:
        """Hash del contenido relevante: si cambia, es una versión nueva.

        Deliberadamente NO incluye `fecha_actualizacion` ni `raw`. PLACSP republica
        una licitación cada vez que se toca cualquier cosa, y sin esto el equipo
        recibiría la misma alerta ocho veces por la misma licitación.
        """
        relevante = {
            k: v
            for k, v in asdict(self).items()
            if k not in {"raw", "fecha_actualizacion"}
        }
        serializado = json.dumps(relevante, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(serializado.encode("utf-8")).hexdigest()

    def a_fila(self) -> dict:
        d = asdict(self)
        d["cpv"] = " ".join(self.cpv)
        d["urls_pliegos"] = json.dumps(self.urls_pliegos, ensure_ascii=False)
        d["raw"] = json.dumps(self.raw, ensure_ascii=False, default=str)
        d["huella"] = self.huella()
        d["texto_busqueda"] = self.texto_busqueda
        # Se guarda ya normalizado: es lo que consulta el motor de reglas.
        d["texto_norm"] = normalizar(self.texto_busqueda)
        d["importe_referencia"] = self.importe_referencia
        return d
