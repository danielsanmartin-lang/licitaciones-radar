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
    # Hay pliegos con duraciones imposibles (120.000 meses, una errata de unidades): sin
    # esto, `date()` revienta y la ficha entera se daba por ilegible y no se guardaba.
    if not 1 <= anio <= 9999:
        return None
    mes = total % 12 + 1
    dia = min(base.day, [31, 29 if anio % 4 == 0 and (anio % 100 != 0 or anio % 400 == 0)
                         else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mes - 1])
    return date(anio, mes, dia).isoformat()


# De dónde sale la fecha de fin que usa Vencimientos, de más a menos fiable.
# «publicada» no se guarda: es la de `fecha_fin_prevista`, y las consultas la nombran así.
ORIGEN_FIN_PUBLICADA = "publicada"    # la fuente la da, o adjudicación/inicio + duración
ORIGEN_FIN_ESTIMADA = "estimada"      # formalización o anuncio de adjudicación + duración
ORIGEN_FIN_APROXIMADA = "aproximada"  # publicación de la licitación + duración
# Lo que se deriva de otros campos o solo sirve para estimar la fecha de fin. Fuera de la
# huella: si entrara, la primera vez que se volviera a ver cada licitación pasaría a
# «actualizada» y se re-evaluarían cientos de miles de filas por un dato que no cambia
# nada de lo que se avisa.
CAMPOS_FUERA_DE_HUELLA = frozenset({
    "fecha_formalizacion", "fecha_anuncio_adjudicacion",
    "fecha_fin_estimada", "fin_origen", "fin_base",
})


def fin_estimado(fin_prevista: str | None, duracion_meses: float | None,
                 formalizacion: str | None, anuncio_adjudicacion: str | None,
                 publicacion: str | None, adjudicatario: str | None
                 ) -> tuple[str | None, str | None, str | None]:
    """La fecha de fin estimada: (fecha, origen, base), o tres None si no hace falta o no
    se puede.

    Solo cuando no hay `fecha_fin_prevista` —publicada, o adjudicación/inicio más
    duración—: entonces se estima a partir de la duración y, por este orden, la
    formalización del contrato, el anuncio de adjudicación o, como último recurso y SOLO
    si ya hay adjudicatario, la publicación de la licitación. Esta última se adelanta a la
    real lo que tarde la adjudicación (meses), que en prospección es el lado bueno del
    error: se llama antes de tiempo, no tarde. La base va con su nombre delante
    («formalizacion:2025-12-31») para poder explicarlo en la tarjeta.
    """
    if fin_prevista or not duracion_meses:
        return None, None, None
    candidatas = (
        ("formalizacion", formalizacion, ORIGEN_FIN_ESTIMADA),
        ("anuncio_adjudicacion", anuncio_adjudicacion, ORIGEN_FIN_ESTIMADA),
        ("publicacion", publicacion if adjudicatario else None, ORIGEN_FIN_APROXIMADA),
    )
    for nombre, base, origen in candidatas:
        fin = _sumar_meses(base, duracion_meses)
        if fin:
            return fin, origen, f"{nombre}:{base[:10]}"
    return None, None, None


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

    # Cuando la fuente no da con qué calcular `fecha_fin_prevista` —el feed de
    # plataformas agregadas de PLACSP no publica NUNCA la fecha de adjudicación—, estas
    # dos fechas permiten estimarla: la de formalización del contrato y la de
    # publicación del anuncio de adjudicación.
    fecha_formalizacion: str | None = None
    fecha_anuncio_adjudicacion: str | None = None
    # La fecha estimada, solo cuando no hay `fecha_fin_prevista`, que no cambia de
    # significado: va aparte para que una fecha estimada nunca pase por publicada.
    # `fin_origen` es ORIGEN_FIN_ESTIMADA o _APROXIMADA y `fin_base`, la fecha de la que
    # parte la estimación con su nombre delante. Ver `fin_estimado`.
    fecha_fin_estimada: str | None = None
    fin_origen: str | None = None
    fin_base: str | None = None

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

        self.fecha_formalizacion = _fecha_iso(self.fecha_formalizacion)
        self.fecha_anuncio_adjudicacion = _fecha_iso(self.fecha_anuncio_adjudicacion)
        self.fecha_fin_estimada, self.fin_origen, self.fin_base = fin_estimado(
            self.fecha_fin_prevista, self.duracion_meses, self.fecha_formalizacion,
            self.fecha_anuncio_adjudicacion, self.fecha_publicacion, self.adjudicatario)

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
        """Lo que se indexa en FTS5, para la caja de búsqueda libre de la bandeja.

        Lleva el expediente y el nombre del órgano a propósito: buscar «Ayuntamiento de
        Viladecans» o un número de expediente es exactamente lo que se espera de una
        caja de búsqueda. Lo que NO puede llevarlos es el texto sobre el que corren las
        reglas; para eso está `texto_reglas`.
        """
        partes = [self.objeto, self.descripcion, self.lote_desc, self.expediente, self.organo]
        return " \n".join(p for p in partes if p)

    @property
    def texto_reglas(self) -> str:
        """Sobre lo que corre el motor de reglas: el CONTRATO, no quién lo saca.

        Durante un tiempo esto y `texto_busqueda` eran el mismo campo, y el nombre del
        organismo contratante entraba en el matching. En España los organismos se
        llaman «Instituto Nacional de CIBERSEGURIDAD», «Departament d'Educació i
        FORMACIÓ Professional», «Fundación Estatal para la FORMACIÓN en el Empleo» o
        «ENS d'Abastament d'Aigua Ter-Llobregat», así que el nombre regalaba el término
        débil, el contexto requerido, o los dos.

        Medido antes de arreglarlo: de las 535 coincidencias del perfil de
        concienciación, 125 —el 23 %, una de cada cuatro fichas de la bandeja— entraban
        solo por el nombre del órgano. Entre ellas, «Formación en Gestión de Proyectos
        Europeos y soft-skills» del INCIBE, formación en riesgos laborales de una
        empresa de aguas y obras de un módulo prefabricado. Ninguna de las 125 llevaba
        un término fuerte, así que quitar el órgano no costó ni un verdadero positivo.

        El expediente también se queda fuera: es un código, y lo que casara dentro de
        «F260000477_492» sería casualidad, no señal.
        """
        partes = [self.objeto, self.descripcion, self.lote_desc]
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
            if k not in {"raw", "fecha_actualizacion"} | CAMPOS_FUERA_DE_HUELLA
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
        # Los dos ya normalizados: `texto_norm` lo usa la búsqueda libre y
        # `texto_reglas_norm` el motor de reglas. Normalizar en la ingesta y no en cada
        # evaluación es lo que permite pasarle `ya_normalizado=True` a `evaluar()`.
        d["texto_norm"] = normalizar(self.texto_busqueda)
        d["texto_reglas_norm"] = normalizar(self.texto_reglas)
        d["importe_referencia"] = self.importe_referencia
        return d
