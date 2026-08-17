"""Conector de la Plataforma de Contratación del Sector Público (PLACSP).

PLACSP no tiene API REST. Publica ficheros ATOM con carga CODICE 2.07:

- Feed diario: `<dataset>.atom`, que encadena snapshots hacia atrás mediante
  `<link rel="next">`. El nombre del siguiente lleva el timestamp
  (`..._20260805_201501.atom`), así que la ingesta incremental consiste en seguir
  la cadena hasta cruzar el cursor de la última ejecución.
- ZIP anuales para el histórico, con ficheros .atom de hasta 500 entradas dentro.

Cuatro datasets, todos con el mismo formato. Las consultas preliminares de mercado
son las más interesantes comercialmente: es la administración preguntando al
mercado ANTES de redactar el pliego.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree as ET

from .. import net, progreso
from ..model import (
    ESTADO_ADJUDICADA, ESTADO_ANULADA, ESTADO_DESCONOCIDO, ESTADO_EVALUACION,
    ESTADO_PREVIO, ESTADO_PUBLICADA, ESTADO_RESUELTA, Licitacion, duracion_a_meses,
)
from .base import ccaa_desde_nuts

log = logging.getLogger(__name__)

BASE = "https://contrataciondelestado.es/sindicacion"

# (clave, carpeta de sindicación, nombre base del fichero)
DATASETS = {
    "licitaciones": ("sindicacion_643", "licitacionesPerfilesContratanteCompleto3"),
    "menores": ("sindicacion_1143", "contratosMenoresPerfilesContratantes"),
    "agregadas": ("sindicacion_1044", "PlataformasAgregadasSinMenores"),
    "consultas_previas": ("sindicacion_1403", "CPM_SectorPublico"),
}

NS = {
    "a": "http://www.w3.org/2005/Atom",
    "at": "http://purl.org/atompub/tombstones/1.0",
    "cbc": "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
    "cac-pe": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2",
    "cbc-pe": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2",
}

# Lista oficial SyndicationContractFolderStatusCode-2.04
ESTADOS_CODICE = {
    "PRE": ESTADO_PREVIO,
    "PUB": ESTADO_PUBLICADA,
    "EV": ESTADO_EVALUACION,
    "ADJ": ESTADO_ADJUDICADA,
    "RES": ESTADO_RESUELTA,
    "ANUL": ESTADO_ANULADA,
}

# ContractCode-2.08 (cbc:TypeCode de ProcurementProject)
TIPOS_CONTRATO = {
    "1": "Suministros",
    "2": "Servicios",
    "3": "Obras",
    "7": "Administrativo especial",
    "8": "Privado",
    "21": "Gestión de servicios públicos",
    "22": "Concesión de servicios",
    "31": "Concesión de obras públicas",
    "32": "Concesión de obras",
    "40": "Colaboración público-privada",
    "50": "Patrimonial",
}

# TenderingProcessCode-2.08. Ojo: el código 9 (Abierto simplificado) es el más
# frecuente con diferencia, y es fácil confundirlo con el 10.
PROCEDIMIENTOS = {
    "1": "Abierto",
    "2": "Restringido",
    "3": "Negociado sin publicidad",
    "4": "Negociado con publicidad",
    "5": "Diálogo competitivo",
    "6": "Contrato menor",
    "7": "Basado en acuerdo marco",
    "8": "Concurso de proyectos",
    "9": "Abierto simplificado",
    "10": "Asociación para la innovación",
    "11": "Derivado de asociación para la innovación",
    "12": "Basado en sistema dinámico de adquisición",
    "13": "Licitación con negociación",
    "100": "Normas internas",
    "999": "Otros",
}

_RE_NIF = re.compile(r"^[A-Z]\d{8}$|^\d{8}[A-Z]$|^[A-Z]\d{7}[A-Z0-9]$")


def _txt(elem, ruta: str) -> str | None:
    if elem is None:
        return None
    hijo = elem.find(ruta, NS)
    if hijo is None or hijo.text is None:
        return None
    valor = hijo.text.strip()
    return valor or None


def _todos(elem, ruta: str) -> list[str]:
    if elem is None:
        return []
    return [e.text.strip() for e in elem.findall(ruta, NS) if e is not None and e.text]


def _fecha_hora(elem, ruta_base: str) -> str | None:
    """Combina EndDate + EndTime, que CODICE publica en elementos separados."""
    fecha = _txt(elem, f"{ruta_base}/cbc:EndDate")
    if not fecha:
        return None
    fecha = fecha.split("+")[0].split("Z")[0]
    hora = _txt(elem, f"{ruta_base}/cbc:EndTime")
    if hora:
        hora = hora.split("+")[0].split("Z")[0]
        return f"{fecha}T{hora}"
    return fecha


def _periodo_ejecucion(proyecto) -> tuple[float | None, str | None, str | None]:
    """Duración y fechas de ejecución. Devuelve (meses, inicio, fin).

    `cbc:DurationMeasure` lleva la unidad en el atributo `unitCode`, y en los datos
    reales aparecen MON, DAY y ANN mezclados: leer el número sin la unidad convierte
    un contrato de 11 años en uno de 11 meses.
    """
    if proyecto is None:
        return None, None, None
    periodo = proyecto.find("cac:PlannedPeriod", NS)
    if periodo is None:
        return None, None, None

    medida = periodo.find("cbc:DurationMeasure", NS)
    meses = None
    if medida is not None:
        meses = duracion_a_meses(medida.text, medida.get("unitCode"))

    inicio = _txt(periodo, "cbc:StartDate")
    fin = _txt(periodo, "cbc:EndDate")
    return meses, inicio, fin


def _nif(party) -> str | None:
    for ident in _todos(party, "cac:PartyIdentification/cbc:ID"):
        if _RE_NIF.match(ident.upper()):
            return ident.upper()
    return None


def _urls_pliegos(cfs) -> list[str]:
    """Solo los pliegos de verdad, no los 20 anexos y actas de la mesa.

    LegalDocumentReference = pliego de cláusulas administrativas,
    TechnicalDocumentReference = pliego de prescripciones técnicas.
    """
    urls: list[str] = []
    for ruta in (
        "cac:LegalDocumentReference",
        "cac:TechnicalDocumentReference",
        "cac:AdditionalDocumentReference",
    ):
        for ref in cfs.findall(ruta, NS):
            uri = _txt(ref, "cac:Attachment/cac:ExternalReference/cbc:URI")
            if uri and uri not in urls:
                urls.append(uri)
    return urls


def _fecha_publicacion(cfs) -> str | None:
    """Primera fecha en que se publicó en el perfil del contratante."""
    fechas = []
    for info in cfs.findall("cac-pe:ValidNoticeInfo", NS):
        for est in info.findall("cac-pe:AdditionalPublicationStatus", NS):
            medio = _txt(est, "cbc-pe:PublicationMediaName") or ""
            if "perfil" not in medio.lower():
                continue
            for ref in est.findall("cac-pe:AdditionalPublicationDocumentReference", NS):
                f = _txt(ref, "cbc:IssueDate")
                if f:
                    fechas.append(f.split("+")[0])
    return min(fechas) if fechas else None


def _texto_lotes(cfs) -> tuple[str | None, str | None, list[dict]]:
    """Devuelve (lote_num, lote_desc, detalle).

    Decisión de diseño: se emite UNA fila por licitación, no una por lote, y el
    texto de todos los lotes se concatena en `lote_desc` para que el índice de
    texto lo vea. Emitir una fila por lote duplicaría la misma licitación en la
    bandeja, y lo que se necesita es justo lo contrario: que una licitación
    genérica de ciberseguridad aparezca porque UNO de sus lotes habla de
    concienciación.
    """
    lotes = cfs.findall("cac:ProcurementProject/cac:ProcurementProjectLot", NS)
    if not lotes:
        lotes = cfs.findall("cac:ProcurementProjectLot", NS)
    if not lotes:
        return None, None, []

    detalle, textos = [], []
    for lote in lotes:
        num = _txt(lote, "cbc:ID")
        nombre = _txt(lote, "cac:ProcurementProject/cbc:Name")
        desc = _txt(lote, "cac:ProcurementProject/cbc:Description")
        cpvs = _todos(
            lote,
            "cac:ProcurementProject/cac:RequiredCommodityClassification/cbc:ItemClassificationCode",
        )
        importe = _txt(lote, "cac:ProcurementProject/cac:BudgetAmount/cbc:TaxExclusiveAmount")
        detalle.append(
            {"lote": num, "nombre": nombre, "descripcion": desc, "cpv": cpvs, "importe": importe}
        )
        trozo = " · ".join(p for p in (f"Lote {num}" if num else None, nombre, desc) if p)
        if trozo:
            textos.append(trozo)

    if len(lotes) == 1:
        único = detalle[0]
        return único["lote"], " · ".join(
            p for p in (único["nombre"], único["descripcion"]) if p
        ) or None, detalle

    return None, "\n".join(textos) or None, detalle


def _urls_generales(cfs) -> list[str]:
    """Documentos de las consultas preliminares, que no traen pliegos como tales."""
    urls = []
    for doc in cfs.findall("cac-pe:GeneralDocument", NS):
        uri = _txt(
            doc,
            "cac-pe:GeneralDocumentDocumentReference/cac:Attachment/cac:ExternalReference/cbc:URI",
        )
        if uri and uri not in urls:
            urls.append(uri)
    return urls


def parsear_consulta_previa(entry, pmc) -> Licitacion | None:
    """Consultas preliminares de mercado.

    Formato distinto al de las licitaciones: el elemento de carga es
    `PreliminaryMarketConsultationStatus`, el identificador es
    `PreliminaryMarketConsultationID` y el plazo es `LimitDate` (sin hora). No
    llevan presupuesto, de ahí que el filtro por importe deba ignorar los importes
    desconocidos en lugar de descartarlos.

    Merecen conector propio porque son la fase en la que todavía se puede influir
    en el pliego: cuando sale el anuncio de licitación ya solo queda competir.
    """
    id_entry = _txt(entry, "a:id")
    if not id_entry:
        return None
    id_externo = id_entry.rstrip("/").rsplit("/", 1)[-1]

    proyecto = pmc.find("cac:ProcurementProject", NS)
    parte = pmc.find("cac-pe:LocatedContractingParty/cac:Party", NS)
    enlace = entry.find("a:link", NS)
    estado_origen = _txt(pmc, "cbc-pe:PreliminaryMarketConsultationStatusCode")
    nuts = _txt(proyecto, "cac:RealizedLocation/cbc:CountrySubentityCode") if proyecto is not None else None

    objeto = (
        _txt(pmc, "cbc:ConsultationName")
        or (_txt(proyecto, "cbc:Name") if proyecto is not None else None)
        or _txt(entry, "a:title")
    )

    return Licitacion(
        fuente="placsp:consultas_previas",
        id_externo=f"consultas_previas:{id_externo}",
        expediente=_txt(pmc, "cbc:PreliminaryMarketConsultationID"),
        organo=_txt(parte, "cac:PartyName/cbc:Name"),
        nif_organo=_nif(parte),
        objeto=objeto,
        descripcion=_txt(proyecto, "cbc:Name") if proyecto is not None else None,
        cpv=_todos(
            proyecto, "cac:RequiredCommodityClassification/cbc:ItemClassificationCode"
        ) if proyecto is not None else [],
        procedimiento="Consulta preliminar de mercado",
        tipo_contrato=TIPOS_CONTRATO.get(
            _txt(proyecto, "cbc:TypeCode") if proyecto is not None else None
        ),
        estado=ESTADO_PREVIO,
        estado_origen=estado_origen,
        fecha_publicacion=_txt(pmc, "cbc:PlannedDate") or _fecha_publicacion(pmc),
        fecha_limite_presentacion=_txt(pmc, "cbc:LimitDate"),
        fecha_actualizacion=_txt(entry, "a:updated"),
        nuts=nuts,
        lugar=_txt(proyecto, "cac:RealizedLocation/cbc:CountrySubentity") if proyecto is not None else None,
        ccaa=ccaa_desde_nuts(nuts),
        url_detalle=enlace.get("href") if enlace is not None else None,
        urls_pliegos=_urls_generales(pmc),
        raw={"condiciones": _txt(pmc, "cbc:ConditionsText"), "id_entry": id_entry},
    )


def parsear_entry(entry, dataset: str) -> Licitacion | None:
    """Traduce un <entry> del ATOM a nuestro modelo. None si no es aprovechable."""
    cfs = entry.find("cac-pe:ContractFolderStatus", NS)
    if cfs is None:
        pmc = entry.find("cac-pe:PreliminaryMarketConsultationStatus", NS)
        if pmc is not None:
            return parsear_consulta_previa(entry, pmc)
        return None

    id_entry = _txt(entry, "a:id")
    if not id_entry:
        return None
    # https://.../sindicacion/licitacionesPerfilContratante/19498 -> 19498
    id_externo = id_entry.rstrip("/").rsplit("/", 1)[-1]

    proyecto = cfs.find("cac:ProcurementProject", NS)
    parte = cfs.find("cac-pe:LocatedContractingParty/cac:Party", NS)

    estado_origen = _txt(cfs, "cbc-pe:ContractFolderStatusCode")
    nuts = _txt(proyecto, "cac:RealizedLocation/cbc:CountrySubentityCode") if proyecto is not None else None

    enlace = entry.find("a:link", NS)
    url_detalle = enlace.get("href") if enlace is not None else None

    resultado = cfs.find("cac:TenderResult", NS)
    lote_num, lote_desc, lotes = _texto_lotes(cfs)

    proc = _txt(cfs, "cac:TenderingProcess/cbc:ProcedureCode")
    tipo = _txt(proyecto, "cbc:TypeCode") if proyecto is not None else None
    meses, inicio, fin = _periodo_ejecucion(proyecto)

    return Licitacion(
        fuente=f"placsp:{dataset}",
        id_externo=f"{dataset}:{id_externo}",
        expediente=_txt(cfs, "cbc:ContractFolderID"),
        organo=_txt(parte, "cac:PartyName/cbc:Name"),
        nif_organo=_nif(parte),
        objeto=_txt(proyecto, "cbc:Name") if proyecto is not None else _txt(entry, "a:title"),
        descripcion=_txt(proyecto, "cbc:Description") if proyecto is not None else None,
        cpv=_todos(
            proyecto, "cac:RequiredCommodityClassification/cbc:ItemClassificationCode"
        ) if proyecto is not None else [],
        importe_sin_iva=_txt(proyecto, "cac:BudgetAmount/cbc:TaxExclusiveAmount") if proyecto is not None else None,
        valor_estimado=_txt(
            proyecto, "cac:BudgetAmount/cbc:EstimatedOverallContractAmount"
        ) if proyecto is not None else None,
        procedimiento=PROCEDIMIENTOS.get(proc, proc),
        tipo_contrato=TIPOS_CONTRATO.get(tipo, tipo),
        estado=ESTADOS_CODICE.get(estado_origen or "", ESTADO_DESCONOCIDO),
        estado_origen=estado_origen,
        fecha_publicacion=_fecha_publicacion(cfs),
        fecha_limite_presentacion=_fecha_hora(
            cfs, "cac:TenderingProcess/cac:TenderSubmissionDeadlinePeriod"
        ),
        fecha_actualizacion=_txt(entry, "a:updated"),
        nuts=nuts,
        lugar=_txt(proyecto, "cac:RealizedLocation/cbc:CountrySubentity") if proyecto is not None else None,
        ccaa=ccaa_desde_nuts(nuts),
        url_detalle=url_detalle,
        urls_pliegos=_urls_pliegos(cfs),
        lote_num=lote_num,
        lote_desc=lote_desc,
        adjudicatario=_txt(resultado, "cac:WinningParty/cac:PartyName/cbc:Name") if resultado is not None else None,
        importe_adjudicacion=(
            _txt(resultado, "cac:AwardedTenderedProject/cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount")
            or _txt(resultado, "cac:AwardedTenderedProject/cac:LegalMonetaryTotal/cbc:PayableAmount")
        ) if resultado is not None else None,
        fecha_adjudicacion=_txt(resultado, "cbc:AwardDate") if resultado is not None else None,
        duracion_meses=meses,
        fecha_inicio_ejecucion=inicio,
        fecha_fin_prevista=fin,
        raw={"lotes": lotes, "id_entry": id_entry} if lotes else {"id_entry": id_entry},
    )


def parsear_atom(datos: bytes, dataset: str) -> tuple[list[Licitacion], str | None, str | None]:
    """Parsea un fichero ATOM completo.

    Devuelve (licitaciones, url_siguiente, updated_del_feed). Se usa iterparse para
    no cargar en memoria los .atom de 500 entradas del histórico enteros.
    """
    licitaciones: list[Licitacion] = []
    url_siguiente = None
    feed_updated = None

    fuente = io.BytesIO(datos)
    contexto = ET.iterparse(fuente, events=("end",))
    for _, elem in contexto:
        etiqueta = elem.tag.split("}")[-1]

        if etiqueta == "link" and elem.get("rel") == "next":
            url_siguiente = elem.get("href")

        elif etiqueta == "updated" and feed_updated is None and elem.text:
            # El primer <updated> del documento es el del feed, no el de una entry.
            feed_updated = elem.text.strip()

        elif etiqueta == "entry":
            try:
                lic = parsear_entry(elem, dataset)
            except Exception as exc:  # noqa: BLE001
                log.warning("Entrada de %s ilegible, se salta: %s", dataset, exc)
                lic = None
            if lic is not None:
                licitaciones.append(lic)
            elem.clear()

        elif etiqueta == "deleted-entry":
            # Lápida de atompub: la licitación se retiró. No la borramos (el
            # historial es útil), simplemente no la actualizamos.
            elem.clear()

    return licitaciones, url_siguiente, feed_updated


class FuentePLACSP:
    """Conector de un dataset concreto de PLACSP."""

    def __init__(self, dataset: str = "licitaciones", *, max_paginas: int = 60,
                 paginas_primera_vez: int = 1, dir_cache: Path | None = None):
        if dataset not in DATASETS:
            raise ValueError(f"Dataset desconocido: {dataset}. Opciones: {list(DATASETS)}")
        self.dataset = dataset
        self.nombre = f"placsp:{dataset}"
        self.max_paginas = max_paginas
        self.paginas_primera_vez = max(1, paginas_primera_vez)
        self.dir_cache = dir_cache or (net.RAIZ / "data" / "cache")
        self._cursor_nuevo: str | None = None

    @property
    def _url_feed(self) -> str:
        carpeta, base = DATASETS[self.dataset]
        return f"{BASE}/{carpeta}/{base}.atom"

    def _url_zip(self, anio: int) -> str:
        carpeta, base = DATASETS[self.dataset]
        return f"{BASE}/{carpeta}/{base}_{anio}.zip"

    def incremental(self, cursor: str | None) -> Iterator[Licitacion]:
        """Sigue la cadena `rel=next` hasta cruzar el cursor de la última ingesta."""
        url = self._url_feed
        paginas = 0
        vistas = set()

        while url and paginas < self.max_paginas:
            if url in vistas:  # la cadena de PLACSP se ha visto ciclar alguna vez
                log.warning("La cadena de %s vuelve sobre sí misma en %s; se corta", self.nombre, url)
                break
            vistas.add(url)

            progreso.pagina()
            datos, _, codigo = net.descargar(url)
            if codigo == 304:
                break

            progreso.fase("interpretando el atom")
            licitaciones, siguiente, feed_updated = parsear_atom(datos, self.dataset)
            paginas += 1

            if self._cursor_nuevo is None and feed_updated:
                self._cursor_nuevo = feed_updated

            yield from licitaciones

            # Paramos cuando el snapshot es anterior al cursor: ya lo teníamos.
            if cursor and feed_updated and feed_updated <= cursor:
                log.info("%s: alcanzado el cursor %s tras %d página(s)", self.nombre, cursor, paginas)
                break
            if not cursor and paginas >= self.paginas_primera_vez:
                # Primera ejecución: unas pocas páginas y paramos. El histórico se
                # trae con --backfill, que usa los ZIP y es mucho más eficiente que
                # recorrer miles de snapshots diarios.
                #
                # Con el defecto (1) esto es una sola página, que es lo que necesita
                # la ingesta de cada mañana. La carga inicial pide más para cerrar el
                # hueco entre la fecha de corte del ZIP anual y hoy: sin eso, ese
                # tramo no lo trae nadie, porque en cuanto se escribe el cursor la
                # ingesta incremental solo mira hacia delante.
                break

            url = siguiente

        if paginas >= self.max_paginas:
            log.warning(
                "%s: alcanzado el límite de %d páginas. Puede quedar histórico sin "
                "traer; lanza --backfill si el hueco es grande.",
                self.nombre, self.max_paginas,
            )

    def _zip_utilizable(self, destino: Path) -> bool:
        """¿Se puede leer de verdad el ZIP que hay en la caché?

        `exists()` no basta, y esto no es teórico: un fichero puede tener su tamaño en el
        directorio y no tener ni un byte legible detrás. iCloud vacía los ficheros
        grandes de las carpetas sincronizadas y deja solo el hueco —`ls -lO` los marca
        «dataless»—, y una descarga cortada a lo bruto deja restos. En los dos casos
        `zipfile` responde BadZipFile en mitad de la ingesta, cuando ya se han invertido
        veinte minutos, y con el mensaje menos informativo posible.

        `is_zipfile` es barato incluso con 1,8 GB: busca el directorio central al final
        del fichero, no lo lee entero.
        """
        if not destino.exists():
            return False
        try:
            legible = zipfile.is_zipfile(destino)
        except OSError as exc:
            log.warning(
                "%s está en la caché pero no se puede leer (%s). Suele ser iCloud, que "
                "vacía los ficheros grandes de las carpetas sincronizadas y deja el "
                "hueco. Se descarga otra vez.", destino.name, exc,
            )
            return False
        if not legible:
            log.warning("%s está en la caché pero no es un ZIP (¿descarga cortada?). "
                        "Se descarga otra vez.", destino.name)
        return legible

    def historico(self, anio: int) -> Iterator[Licitacion]:
        """Descarga el ZIP anual y recorre los .atom que contiene."""
        destino = self.dir_cache / f"{self.dataset}_{anio}.zip"
        if not self._zip_utilizable(destino):
            destino.unlink(missing_ok=True)
            log.info("Descargando histórico %s %s...", self.nombre, anio)
            # Los contadores de ficheros son del ZIP del año anterior y aquí ya no
            # significan nada. Sin reiniciarlos, la aplicación seguía enseñando
            # «fichero 1398 de 1398» con la barra clavada al 100% durante los cuarenta
            # minutos de descarga, que es exactamente como se ve una aplicación colgada.
            progreso.subtarea(0, 0)
            net.descargar_a_fichero(self._url_zip(anio), destino)

        with zipfile.ZipFile(destino) as zf:
            nombres = sorted(n for n in zf.namelist() if n.endswith(".atom"))
            log.info("%s %s: %d ficheros atom", self.nombre, anio, len(nombres))
            progreso.fase("leyendo el zip")
            # El número de ficheros del ZIP se conoce de antemano, así que aquí sí se
            # puede decir cuánto queda en lugar de solo cuánto va. Es lo que alimenta
            # la barra de progreso de la aplicación durante la carga inicial.
            for i, nombre in enumerate(nombres, 1):
                progreso.subtarea(i, len(nombres))
                with zf.open(nombre) as fh:
                    licitaciones, _, _ = parsear_atom(fh.read(), self.dataset)
                yield from licitaciones

    def cursor_nuevo(self) -> str | None:
        return self._cursor_nuevo
