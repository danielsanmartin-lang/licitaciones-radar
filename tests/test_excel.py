"""El `.xlsx` que se escribe a mano: que sea un zip válido que Excel abra, con los tipos
de cada columna y los enlaces como enlaces."""

from __future__ import annotations

import io
import unittest
import zipfile
import xml.etree.ElementTree as ET

from radar.excel import ENLACE, EUROS, FECHA, Columna, Hoja, libro

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


class TestLibro(unittest.TestCase):
    def setUp(self):
        columnas = [Columna("Objeto"), Columna("Importe", EUROS), Columna("Vence", FECHA),
                    Columna("Enlace", ENLACE)]
        url = "https://contrataciondelestado.es/wps/poc?uri=deeplink%3Adetalle&idEvl=" + "x" * 300
        self.zip = zipfile.ZipFile(io.BytesIO(libro([
            Hoja("Vencen en 6 meses", columnas, [
                ["Concienciación <&> «ciber»\x0b", 12500.5, "2026-12-31T00:00:00", url],
                ["Sin importe", None, None, None],
            ]),
            Hoja("Vencidos: [6 meses]", columnas, []),
        ])))
        self.url = url

    def _hoja(self, n: int) -> ET.Element:
        return ET.fromstring(self.zip.read(f"xl/worksheets/sheet{n}.xml"))

    def test_es_un_xlsx_bien_formado(self):
        self.assertIsNone(self.zip.testzip())
        for nombre in self.zip.namelist():
            if nombre.endswith((".xml", ".rels")):
                ET.fromstring(self.zip.read(nombre))  # no lanza

    def test_nombres_de_hoja_sin_caracteres_prohibidos(self):
        libro_xml = ET.fromstring(self.zip.read("xl/workbook.xml"))
        nombres = [h.get("name") for h in libro_xml.iterfind("m:sheets/m:sheet", NS)]
        self.assertEqual(nombres, ["Vencen en 6 meses", "Vencidos- -6 meses-"])

    def test_tipos_de_celda(self):
        celdas = {c.get("r"): c for c in self._hoja(1).iterfind(".//m:c", NS)}
        self.assertEqual(celdas["B2"].find("m:v", NS).text, "12500.5")
        # 31/12/2026 en días desde la época de Excel.
        self.assertEqual(celdas["C2"].find("m:v", NS).text, "46387")
        texto = celdas["A2"].find("m:is/m:t", NS).text
        self.assertEqual(texto, "Concienciación <&> «ciber»")  # sin el carácter de control
        self.assertNotIn("B3", celdas)  # lo vacío no se escribe

    def test_los_enlaces_largos_son_hipervinculos_de_verdad(self):
        rels = self.zip.read("xl/worksheets/_rels/sheet1.xml.rels").decode()
        self.assertIn('TargetMode="External"', rels)
        self.assertIn("x" * 300, rels)
        self.assertIsNotNone(self._hoja(1).find("m:hyperlinks/m:hyperlink[@ref='D2']", NS))

    def test_cabecera_inmovilizada_y_autofiltro(self):
        hoja = self._hoja(1)
        self.assertEqual(hoja.find(".//m:pane", NS).get("state"), "frozen")
        self.assertEqual(hoja.find("m:autoFilter", NS).get("ref"), "A1:D3")

    def test_sin_hojas_no_hay_libro(self):
        with self.assertRaises(ValueError):
            libro([])


if __name__ == "__main__":
    unittest.main()
