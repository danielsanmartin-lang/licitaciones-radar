"""Parser de los ficheros ATOM/CODICE de PLACSP.

Los fixtures son descargas reales de la sindicación, no XML inventado: los códigos
CODICE y los caminos de los elementos se han comprobado contra las listas oficiales
publicadas por la propia plataforma.
"""

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from radar.model import ESTADO_ADJUDICADA, ESTADO_PREVIO
from radar.sources.placsp import (
    PROCEDIMIENTOS, TIPOS_CONTRATO, FuentePLACSP, parsear_atom,
)

FIXTURES = Path(__file__).parent / "fixtures"


def atom_vacio(pagina: int, updated: str) -> bytes:
    """Un feed sin entradas pero con `rel=next`: basta para contar páginas."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        f"<updated>{updated}</updated>"
        f'<link rel="next" href="https://ejemplo/pagina{pagina + 1}.atom"/>'
        "</feed>"
    ).encode()


class TestLicitaciones(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        datos = (FIXTURES / "placsp_muestra.atom").read_bytes()
        cls.lics, cls.siguiente, cls.updated = parsear_atom(datos, "licitaciones")

    def test_parsea_todas_las_entradas(self):
        self.assertEqual(len(self.lics), 21)

    def test_encadena_la_pagina_siguiente(self):
        """Sin `rel=next` no hay ingesta incremental posible."""
        self.assertIsNotNone(self.siguiente)
        self.assertIn("licitacionesPerfilesContratanteCompleto3_", self.siguiente)
        self.assertTrue(self.siguiente.endswith(".atom"))

    def test_updated_del_feed_no_es_el_de_una_entrada(self):
        self.assertIsNotNone(self.updated)
        self.assertTrue(self.updated.startswith("2026-"))

    def test_campos_esenciales_en_todas(self):
        """Si falta cualquiera de estos, la licitación no es utilizable comercialmente."""
        for campo in ("expediente", "organo", "objeto", "url_detalle",
                      "fecha_limite_presentacion", "importe_referencia"):
            with self.subTest(campo=campo):
                faltan = [l for l in self.lics if not getattr(l, campo)]
                self.assertEqual(faltan, [], f"{len(faltan)} sin {campo}")

    def test_codigos_traducidos_no_quedan_en_bruto(self):
        for l in self.lics:
            with self.subTest(exp=l.expediente):
                self.assertIn(l.procedimiento, PROCEDIMIENTOS.values())
                self.assertIn(l.tipo_contrato, TIPOS_CONTRATO.values())

    def test_procedimiento_9_es_abierto_simplificado(self):
        """El 9 es el más frecuente y se confunde con el 10."""
        self.assertEqual(PROCEDIMIENTOS["9"], "Abierto simplificado")
        self.assertEqual(PROCEDIMIENTOS["10"], "Asociación para la innovación")

    def test_adjudicaciones_traen_adjudicatario_e_importe(self):
        adjudicadas = [l for l in self.lics if l.estado == ESTADO_ADJUDICADA]
        self.assertTrue(adjudicadas)
        for l in adjudicadas:
            with self.subTest(exp=l.expediente):
                self.assertTrue(l.adjudicatario)
                self.assertTrue(l.importe_adjudicacion)
                self.assertTrue(l.fecha_adjudicacion)

    def test_ccaa_se_deduce_del_nuts(self):
        con_ccaa = [l for l in self.lics if l.ccaa]
        self.assertEqual(len(con_ccaa), len(self.lics))

    def test_solo_recoge_pliegos_no_las_actas_de_la_mesa(self):
        """Un expediente trae hasta 20 documentos: actas, anexos, composición de la
        mesa... Solo se guardan los pliegos (Legal/Technical/Additional), que van
        por el servlet de descarga; los demás cuelgan de GeneralDocument y usan
        rutas `docAccCmpnt`."""
        for l in self.lics:
            for url in l.urls_pliegos:
                with self.subTest(exp=l.expediente, url=url[:60]):
                    self.assertNotIn("docAccCmpnt", url)

    def test_el_texto_de_busqueda_incluye_los_lotes(self):
        con_lotes = [l for l in self.lics if l.lote_desc]
        self.assertTrue(con_lotes, "el fixture debe tener alguna con lotes")
        for l in con_lotes:
            self.assertIn(l.lote_desc.split("\n")[0][:20], l.texto_busqueda)

    def test_idempotencia_del_parseo(self):
        datos = (FIXTURES / "placsp_muestra.atom").read_bytes()
        otra_vez, _, _ = parsear_atom(datos, "licitaciones")
        self.assertEqual(
            [l.huella() for l in self.lics], [l.huella() for l in otra_vez],
            "el mismo fichero debe producir exactamente las mismas huellas",
        )


class TestConsultasPreliminares(unittest.TestCase):
    """Formato distinto: PreliminaryMarketConsultationStatus, no ContractFolderStatus."""

    @classmethod
    def setUpClass(cls):
        datos = (FIXTURES / "placsp_cpm_muestra.atom").read_bytes()
        cls.lics, _, _ = parsear_atom(datos, "consultas_previas")

    def test_parsea_las_consultas(self):
        self.assertGreater(len(self.lics), 300)

    def test_todas_en_estado_previo(self):
        for l in self.lics:
            self.assertEqual(l.estado, ESTADO_PREVIO)

    def test_trae_expediente_organo_y_plazo(self):
        for campo in ("expediente", "organo", "objeto", "fecha_limite_presentacion"):
            with self.subTest(campo=campo):
                faltan = [l for l in self.lics if not getattr(l, campo)]
                self.assertLessEqual(
                    len(faltan), len(self.lics) * 0.05, f"demasiadas sin {campo}"
                )

    def test_sin_importe_no_se_inventa_uno(self):
        """Las consultas previas no publican presupuesto; el filtro por importe
        debe ignorar los desconocidos, no descartarlos."""
        self.assertTrue(any(l.importe_referencia is None for l in self.lics))

    def test_la_fuente_las_identifica_como_consulta_previa(self):
        for l in self.lics:
            self.assertEqual(l.fuente, "placsp:consultas_previas")


class TestPrimeraPasada(unittest.TestCase):
    """Cuántas páginas del feed diario se traen cuando todavía no hay cursor.

    Este es el número que dejaba una instalación nueva con 51 coincidencias: una sola
    página del feed y, acto seguido, el cursor escrito en la posición de hoy. A partir
    de ahí la ingesta incremental —con razón— solo mira hacia delante, así que ese
    hueco no lo rellena nadie. La carga inicial sube el tope para cerrarlo.
    """

    def setUp(self):
        self.paginas = 0

    def _descargar_falso(self, url, **kw):
        # La cadena real va hacia atrás en el tiempo: la primera página es el snapshot
        # de hoy y cada `rel=next` es más antiguo.
        self.paginas += 1
        updated = f"2026-08-{11 - self.paginas:02d}T03:00:00+02:00"
        return atom_vacio(self.paginas, updated), {}, 200

    def _consumir(self, fuente, cursor=None):
        with mock.patch("radar.sources.placsp.net.descargar", self._descargar_falso):
            list(fuente.incremental(cursor))

    def test_por_defecto_una_sola_pagina(self):
        """Es lo que necesita la ingesta de cada mañana; cambiarlo la haría lenta."""
        self._consumir(FuentePLACSP("licitaciones"))
        self.assertEqual(self.paginas, 1)

    def test_la_carga_inicial_pide_varias(self):
        self._consumir(FuentePLACSP("licitaciones", paginas_primera_vez=5))
        self.assertEqual(self.paginas, 5)

    def test_nunca_menos_de_una(self):
        self._consumir(FuentePLACSP("licitaciones", paginas_primera_vez=0))
        self.assertEqual(self.paginas, 1)

    def test_no_pasa_del_tope_general(self):
        self._consumir(FuentePLACSP("licitaciones", paginas_primera_vez=99,
                                    max_paginas=4))
        self.assertEqual(self.paginas, 4)

    def test_con_cursor_manda_el_cursor_y_no_el_tope(self):
        """Con cursor la condición de parada es haber alcanzado el snapshot que ya
        teníamos; el tope de la primera vez no debe entrar en juego."""
        self._consumir(FuentePLACSP("licitaciones", paginas_primera_vez=1),
                       cursor="2026-08-08T03:00:00+02:00")
        self.assertEqual(self.paginas, 3)


class TestHistoricoZip(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.cache = Path(self.dir.name)
        # El ZIP ya en caché: `historico()` no descarga si el fichero está.
        with zipfile.ZipFile(self.cache / "licitaciones_2025.zip", "w") as zf:
            for i in range(1, 4):
                zf.writestr(f"lote_{i}.atom", atom_vacio(i, "2025-01-01T00:00:00+01:00"))
            zf.writestr("leeme.txt", "esto no es un atom")

    def test_informa_del_avance_sobre_el_total_de_ficheros(self):
        """El total se conoce de antemano, así que la barra puede decir cuánto queda
        en lugar de solo cuánto va. Es lo que se ve durante la carga inicial."""
        fuente = FuentePLACSP("licitaciones", dir_cache=self.cache)
        with mock.patch("radar.sources.placsp.progreso.subtarea") as subtarea:
            list(fuente.historico(2025))
        self.assertEqual([c.args for c in subtarea.call_args_list],
                         [(1, 3), (2, 3), (3, 3)])

    def _zip_al_descargar(self, url, destino, **kw):
        """Descarga de mentira que deja un ZIP válido donde toca."""
        with zipfile.ZipFile(destino, "w") as zf:
            zf.writestr("lote_1.atom", atom_vacio(1, "2024-01-01T00:00:00+01:00"))
        return destino

    def test_un_fichero_de_la_cache_que_no_es_un_zip_se_vuelve_a_descargar(self):
        """Una descarga cortada deja un fichero con el nombre bueno y basura dentro. Con
        fiarse de `exists()`, eso reventaba la fuente entera veinte minutos después."""
        malo = self.cache / "licitaciones_2024.zip"
        malo.write_text("no soy un zip")

        fuente = FuentePLACSP("licitaciones", dir_cache=self.cache)
        with mock.patch("radar.sources.placsp.net.descargar_a_fichero",
                        side_effect=self._zip_al_descargar) as bajar:
            list(fuente.historico(2024))

        self.assertEqual(bajar.call_count, 1, "hay que volver a bajarlo, no reventar")
        self.assertTrue(zipfile.is_zipfile(malo), "el bueno tiene que quedar en la caché")

    def test_un_fichero_vaciado_por_icloud_se_vuelve_a_descargar(self):
        """El caso que pasó de verdad: iCloud deja el tamaño en el directorio y se lleva
        los bytes, así que abrirlo da error de E/S en lugar de un ZIP inválido."""
        (self.cache / "licitaciones_2024.zip").write_bytes(b"PK\x03\x04 con el hueco")

        fuente = FuentePLACSP("licitaciones", dir_cache=self.cache)
        with mock.patch("radar.sources.placsp.zipfile.is_zipfile",
                        side_effect=OSError("Input/output error")), \
             mock.patch("radar.sources.placsp.net.descargar_a_fichero",
                        side_effect=self._zip_al_descargar) as bajar:
            list(fuente.historico(2024))

        self.assertEqual(bajar.call_count, 1)


if __name__ == "__main__":
    unittest.main()
