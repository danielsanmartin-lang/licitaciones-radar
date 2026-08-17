"""Orquestación de la ingesta.

Lo que se protege aquí es que un fallo parcial no se lleve por delante lo que sí se
puede traer. La carga inicial pide varios años de golpe y PLACSP no publica el ZIP
anual de todos los años en todos los datasets: con un solo `try` para todos, un 404
en uno dejaba sin histórico a los que sí existían.
"""

import tempfile
import unittest
import zipfile
from pathlib import Path

from radar import db, net, pipeline
from radar.matching import Perfil
from radar.model import Licitacion
from radar.sources.placsp import FuentePLACSP


class FuenteFalsa:
    """Fuente de mentira con un guion por año: licitaciones o excepción."""

    def __init__(self, nombre="falsa", guion=None):
        self.nombre = nombre
        self.guion = guion or {}
        self.anios_pedidos = []

    def historico(self, anio):
        self.anios_pedidos.append(anio)
        guion = self.guion.get(anio, 0)
        if isinstance(guion, Exception):
            raise guion
        for i in range(guion):
            yield Licitacion(fuente=self.nombre, id_externo=f"{anio}-{i}",
                             objeto=f"Concienciación {anio}-{i}", organo="Órgano")

    def incremental(self, cursor):
        return iter(())

    def cursor_nuevo(self):
        return None


class TestBackfillPorAnios(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.con = db.conectar(Path(self.dir.name) / "t.db")
        self.addCleanup(self.con.close)

    def _contar(self):
        return self.con.execute("SELECT COUNT(*) FROM licitaciones").fetchone()[0]

    def test_un_anio_sin_zip_publicado_no_es_un_error(self):
        """Un 404 en el ZIP anual es información, no una avería: si contara como
        error, una carga inicial que fue bien acabaría diciendo «alguna fuente ha
        fallado» y el compañero pensaría que hay algo roto."""
        fuente = FuenteFalsa(guion={
            2024: 3,
            2025: net.ErrorRed("no existe", codigo=404),
            2026: 2,
        })
        resumen = pipeline.ingerir(self.con, [fuente], anios=[2024, 2025, 2026])

        self.assertIsNone(resumen["falsa"]["error"])
        self.assertEqual(resumen["falsa"]["vistos"], 5)
        self.assertEqual(self._contar(), 5)
        self.assertEqual(fuente.anios_pedidos, [2024, 2025, 2026])

    def test_un_fallo_de_verdad_no_se_lleva_los_demas_anios(self):
        """Antes, cualquier excepción salía del bucle de años y los que quedaban se
        perdían. Se sigue con ellos, pero la fuente queda marcada."""
        fuente = FuenteFalsa(guion={
            2024: 3,
            2025: net.ErrorRed("timeout tras 4 intentos"),
            2026: 2,
        })
        resumen = pipeline.ingerir(self.con, [fuente], anios=[2024, 2025, 2026])

        self.assertIn("timeout", resumen["falsa"]["error"])
        self.assertEqual(self._contar(), 5)
        self.assertEqual(fuente.anios_pedidos, [2024, 2025, 2026])

    def test_un_zip_ilegible_en_la_cache_no_se_lleva_los_demas_anios(self):
        """Pasó de verdad: iCloud vació `licitaciones_2024.zip` dejando el tamaño en el
        directorio, `zipfile` respondió BadZipFile y —al capturarse solo ErrorRed— 2025 y
        2026 se quedaron sin intentar. La fuente entera acabó con 0 fichas."""
        fuente = FuenteFalsa(guion={
            2024: zipfile.BadZipFile("File is not a zip file"),
            2025: 3,
            2026: 2,
        })
        resumen = pipeline.ingerir(self.con, [fuente], anios=[2024, 2025, 2026])

        self.assertIn("BadZipFile", resumen["falsa"]["error"])
        self.assertEqual(self._contar(), 5, "los años buenos tienen que entrar igual")
        self.assertEqual(fuente.anios_pedidos, [2024, 2025, 2026])

    def test_lo_traido_antes_del_fallo_se_conserva(self):
        """El generador puede reventar a mitad de un año; lo ya guardado se queda."""
        class MitadYFallo(FuenteFalsa):
            def historico(self, anio):
                self.anios_pedidos.append(anio)
                yield Licitacion(fuente="falsa", id_externo=f"{anio}-ok",
                                 objeto="Concienciación superviviente", organo="Órgano")
                raise net.ErrorRed("se cortó la descarga")

        resumen = pipeline.ingerir(self.con, [MitadYFallo()], anios=[2024])
        self.assertIsNotNone(resumen["falsa"]["error"])
        self.assertEqual(self._contar(), 1)

    def test_una_fuente_rota_no_impide_la_siguiente(self):
        """Comportamiento de siempre, con una prueba que faltaba: perder Cataluña una
        mañana no debe impedir ver lo que ha publicado PLACSP."""
        rota = FuenteFalsa("rota", guion={2024: net.ErrorRed("caída")})
        buena = FuenteFalsa("buena", guion={2024: 4})
        resumen = pipeline.ingerir(self.con, [rota, buena], anios=[2024])

        self.assertIsNotNone(resumen["rota"]["error"])
        self.assertIsNone(resumen["buena"]["error"])
        self.assertEqual(resumen["buena"]["vistos"], 4)


class TestConstruirFuentes(unittest.TestCase):
    PERFILES = [Perfil(nombre="p", terminos_fuertes=["conscienci"])]

    def test_el_tope_de_la_primera_pasada_llega_a_placsp(self):
        fuentes = pipeline.construir_fuentes(
            ["placsp"], self.PERFILES, paginas_primera_vez=12
        )
        self.assertTrue(fuentes)
        for f in fuentes:
            self.assertIsInstance(f, FuentePLACSP)
            self.assertEqual(f.paginas_primera_vez, 12)

    def test_tambien_pidiendo_un_dataset_suelto(self):
        (f,) = pipeline.construir_fuentes(
            ["placsp:agregadas"], self.PERFILES, paginas_primera_vez=7
        )
        self.assertEqual(f.paginas_primera_vez, 7)

    def test_por_defecto_una_pagina(self):
        """El defecto es lo que usa la ingesta de cada mañana."""
        (f,) = pipeline.construir_fuentes(["placsp:licitaciones"], self.PERFILES)
        self.assertEqual(f.paginas_primera_vez, 1)

    def test_una_fuente_desconocida_se_dice_con_las_opciones(self):
        with self.assertRaises(ValueError) as caja:
            pipeline.construir_fuentes(["euskadi"], self.PERFILES)
        self.assertIn("placsp:agregadas", str(caja.exception))


if __name__ == "__main__":
    unittest.main()
