"""Un `.xlsx` mínimo con la biblioteca estándar, para exportar listas a Excel.

Por qué no un CSV: el Excel en español usa el punto y coma como separador, y un CSV con
comas se abre con todo metido en la primera columna. Un `.xlsx` se abre bien en
cualquier Excel, Numbers o LibreOffice, y deja dar a cada columna su tipo: los importes
como número en euros y las fechas como fecha, que se pueden ordenar y filtrar.

Un `.xlsx` es un zip con unos cuantos XML. Aquí solo lo que hace falta: varias hojas,
cabecera en negrita con la primera fila inmovilizada y autofiltro, anchos de columna,
y enlaces de verdad (con relaciones, no con la fórmula HYPERLINK, que corta a 255
caracteres y las URL de las plataformas los pasan).
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from xml.sax.saxutils import escape

# Tipos de columna.
TEXTO = "texto"
ENTERO = "entero"
EUROS = "euros"
FECHA = "fecha"
ENLACE = "enlace"

# Índices de `cellXfs` en STYLES.
_ESTILO = {"cabecera": 1, EUROS: 2, FECHA: 3, ENLACE: 4, TEXTO: 5, ENTERO: 0}

_EPOCA_EXCEL = date(1899, 12, 30)
# Los caracteres de control que XML 1.0 no admite: un objeto pegado de un PDF los trae.
_NO_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_MAX_CELDA = 32_767


@dataclass(frozen=True)
class Columna:
    titulo: str
    tipo: str = TEXTO
    ancho: float = 14


@dataclass
class Hoja:
    nombre: str
    columnas: list[Columna]
    filas: list[list]


def _letra(n: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letras = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        letras = chr(65 + r) + letras
    return letras


def _texto(valor) -> str:
    return escape(_NO_XML.sub("", str(valor))[:_MAX_CELDA])


def _a_fecha(valor) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str) and len(valor) >= 10:
        try:
            return date.fromisoformat(valor[:10])
        except ValueError:
            return None
    return None


def _nombre_hoja(nombre: str, usados: set) -> str:
    limpio = re.sub(r"[\[\]:*?/\\]", "-", nombre).strip("'")[:31] or "Hoja"
    base, n = limpio, 2
    while limpio.lower() in usados:
        sufijo = f" ({n})"
        limpio = base[:31 - len(sufijo)] + sufijo
        n += 1
    usados.add(limpio.lower())
    return limpio


def _celda(ref: str, valor, tipo: str) -> str:
    if valor is None or valor == "":
        return ""
    estilo = _ESTILO.get(tipo, 0)
    if tipo in (EUROS, ENTERO) and isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return f'<c r="{ref}" s="{estilo}"><v>{valor!r}</v></c>'
    if tipo == FECHA:
        f = _a_fecha(valor)
        if f is not None:
            return f'<c r="{ref}" s="{estilo}"><v>{(f - _EPOCA_EXCEL).days}</v></c>'
    return (f'<c r="{ref}" s="{estilo}" t="inlineStr"><is><t xml:space="preserve">'
            f"{_texto(valor)}</t></is></c>")


def _hoja_xml(hoja: Hoja) -> tuple[str, list[str]]:
    """El XML de la hoja y las URL de sus enlaces, en el orden de sus `rId`."""
    n_col = len(hoja.columnas)
    ultima = _letra(n_col - 1)
    n_filas = len(hoja.filas) + 1
    filas_xml = ['<row r="1">' + "".join(
        f'<c r="{_letra(i)}1" s="{_ESTILO["cabecera"]}" t="inlineStr"><is><t>'
        f"{_texto(c.titulo)}</t></is></c>"
        for i, c in enumerate(hoja.columnas)) + "</row>"]
    enlaces: list[tuple[str, str]] = []
    for r, fila in enumerate(hoja.filas, start=2):
        celdas = []
        for i, (col, valor) in enumerate(zip(hoja.columnas, fila)):
            ref = f"{_letra(i)}{r}"
            if col.tipo == ENLACE and valor:
                url = str(valor)
                enlaces.append((ref, url))
                celdas.append(_celda(ref, url, ENLACE))
            else:
                celdas.append(_celda(ref, valor, col.tipo))
        filas_xml.append(f'<row r="{r}">{"".join(celdas)}</row>')
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{c.ancho}" customWidth="1"/>'
                   for i, c in enumerate(hoja.columnas))
    hipervinculos = ""
    if enlaces:
        hipervinculos = "<hyperlinks>" + "".join(
            f'<hyperlink ref="{ref}" r:id="rId{k}"/>'
            for k, (ref, _) in enumerate(enlaces, start=1)) + "</hyperlinks>"
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<dimension ref="A1:{ultima}{n_filas}"/>'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        f"<cols>{cols}</cols>"
        f'<sheetData>{"".join(filas_xml)}</sheetData>'
        f'<autoFilter ref="A1:{ultima}{n_filas}"/>'
        f"{hipervinculos}"
        "</worksheet>"
    )
    return xml, [url for _, url in enlaces]


_ESTILOS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<numFmts count="2">'
    '<numFmt numFmtId="164" formatCode="#,##0\\ &quot;€&quot;"/>'
    '<numFmt numFmtId="165" formatCode="dd/mm/yyyy"/>'
    "</numFmts>"
    '<fonts count="3">'
    '<font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font>'
    '<font><u/><sz val="11"/><color rgb="FF0563C1"/><name val="Calibri"/></font>'
    "</fonts>"
    '<fills count="3"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFEEF2F7"/></patternFill></fill>'
    "</fills>"
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="6">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
    '<alignment vertical="top"/></xf>'
    "</cellXfs>"
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)


def libro(hojas: list[Hoja]) -> bytes:
    """Los bytes de un `.xlsx` con estas hojas, en este orden."""
    if not hojas:
        raise ValueError("un libro necesita al menos una hoja")
    usados: set = set()
    nombres = [_nombre_hoja(h.nombre, usados) for h in hojas]
    salida = BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + "".join(
                f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/'
                'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                for i in range(1, len(hojas) + 1))
            + "</Types>"))
        z.writestr("_rels/.rels", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"))
        filtros = "".join(
            f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1">'
            f"'{escape(n)}'!$A$1:${_letra(len(h.columnas) - 1)}${len(h.filas) + 1}</definedName>"
            for i, (n, h) in enumerate(zip(nombres, hojas)))
        z.writestr("xl/workbook.xml", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            "<sheets>" + "".join(
                f'<sheet name="{escape(n, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>'
                for i, n in enumerate(nombres, start=1))
            + f"</sheets><definedNames>{filtros}</definedNames></workbook>"))
        z.writestr("xl/_rels/workbook.xml.rels", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(
                f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/'
                f'officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                for i in range(1, len(hojas) + 1))
            + f'<Relationship Id="rId{len(hojas) + 1}" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>"))
        z.writestr("xl/styles.xml", _ESTILOS)
        for i, hoja in enumerate(hojas, start=1):
            xml, urls = _hoja_xml(hoja)
            z.writestr(f"xl/worksheets/sheet{i}.xml", xml)
            if urls:
                z.writestr(f"xl/worksheets/_rels/sheet{i}.xml.rels", (
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                    'relationships">' + "".join(
                        f'<Relationship Id="rId{k}" Type="http://schemas.openxmlformats.org/'
                        'officeDocument/2006/relationships/hyperlink" '
                        f'Target="{escape(u, {chr(34): "&quot;"})}" TargetMode="External"/>'
                        for k, u in enumerate(urls, start=1))
                    + "</Relationships>"))
    return salida.getvalue()
