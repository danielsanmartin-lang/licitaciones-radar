"""El vigilante de la ingesta y la señal de avance de la que vive.

Lo que se protege: que una búsqueda atascada de verdad se corte sola —antes nada podía
soltar el cerrojo de un proceso clavado— y, sobre todo, que una búsqueda LENTA no se
confunda con una atascada. La que motivó esto tardó 1h45 bajando de PLACSP a 0,05 MB/s
y avanzaba todo el rato: cortarla habría sido peor que esperarla.
"""

import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from radar import db, pipeline, progreso, vigilante
from radar.model import Licitacion


class SalidaFalsa(io.StringIO):
    def isatty(self) -> bool:
        return True


class SalidaRota(SalidaFalsa):
    """Una terminal que se ha cerrado debajo: cualquier escritura revienta."""

    def write(self, texto):
        raise OSError("la terminal ya no existe")


class TestSinAvance(unittest.TestCase):
    def setUp(self):
        self.ind = progreso._Indicador()
        self.addCleanup(self.ind.parar)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.estado = Path(self.dir.name) / "progreso.json"

    def test_sin_indicador_no_hay_atasco_que_medir(self):
        self.assertEqual(self.ind.sin_avance(), 0.0)

    def test_crece_si_no_se_mueve_nada_y_vuelve_a_cero_al_avanzar(self):
        self.ind.iniciar(SalidaFalsa(), estado=self.estado)
        self.ind.fuente("placsp:licitaciones")
        self.ind.fase("descargando")
        time.sleep(0.5)
        # Solo pasa el tiempo: el reloj de `segundos` no cuenta como avance.
        self.assertGreaterEqual(self.ind.sin_avance(), 0.4)
        self.ind.sumar_bytes(64 << 10)
        # Un tic (0,1 s) para que lo vea, con margen.
        time.sleep(0.15)
        self.assertLess(self.ind.sin_avance(), 0.3)

    def test_un_reintento_tambien_es_avance(self):
        """Durante los reintentos no llegan bytes, pero la fase cambia: es lentitud, no
        un atasco, y no debe acercar la búsqueda al corte."""
        self.ind.iniciar(SalidaFalsa(), estado=self.estado)
        self.ind.fuente("placsp:licitaciones")
        time.sleep(0.5)
        self.assertGreaterEqual(self.ind.sin_avance(), 0.4)
        self.ind.fase("falló el intento 1/4, reintento en 2s")
        time.sleep(0.15)
        self.assertLess(self.ind.sin_avance(), 0.3)

    def test_la_instantanea_lo_publica(self):
        self.ind.iniciar(SalidaFalsa(), estado=self.estado)
        self.ind.fuente("ted")
        time.sleep(0.2)
        self.assertIn("sin_avance", self.ind.instantanea())

    def test_cerrar_la_terminal_no_deja_de_contar(self):
        """Si el hilo muriera con la terminal, el vigilante vería la ingesta parada para
        siempre y la cortaría por haber cerrado una ventana."""
        self.ind.iniciar(SalidaRota(), estado=self.estado)
        self.ind.fuente("ted")
        time.sleep(0.5)
        self.ind.fichas(10)
        time.sleep(0.15)
        self.assertTrue(self.ind._hilo.is_alive())
        self.assertLess(self.ind.sin_avance(), 0.3)
        self.assertTrue(self.estado.exists(), "la instantánea se sigue publicando")


class TestVigilante(unittest.TestCase):
    def setUp(self):
        self.addCleanup(vigilante.parar)
        self.salidas = []

    def _iniciar(self, callado, **kw):
        parche = mock.patch.object(vigilante.progreso, "sin_avance", side_effect=callado)
        parche.start()
        self.addCleanup(parche.stop)
        vigilante.iniciar(sin_avance_max=1, comprobar_cada=0.02,
                          gracia=kw.get("gracia", 0.3), salir=self.salidas.append)

    def _esperar(self, segundos):
        fin = time.monotonic() + segundos
        while time.monotonic() < fin:
            time.sleep(0.01)

    def test_una_busqueda_que_avanza_no_se_toca(self):
        self._iniciar(lambda: 0.5)
        self._esperar(0.3)
        self.assertEqual(self.salidas, [])

    def test_un_atasco_se_corta_en_el_hilo_principal(self):
        self._iniciar(lambda: 99)
        with self.assertLogs(vigilante.log, "ERROR") as registro:
            with self.assertRaises(vigilante.Atascada) as cm:
                self._esperar(2)
        self.assertIn("sin avanzar", str(cm.exception))
        self.assertIn("sin avanzar", registro.output[0], "el registro dice por qué")
        self.assertEqual(self.salidas, [], "reaccionó: no hace falta salir a lo bruto")

    def test_si_no_reacciona_se_sale_para_soltar_el_cerrojo(self):
        """Un bloqueo dentro de código en C no deja ejecutarse al manejador. Aquí se
        imita tragándose el aviso y siguiendo parado."""
        self._iniciar(lambda: 99, gracia=0.2)
        fin = time.monotonic() + 2
        with self.assertLogs(vigilante.log, "ERROR"):
            while not self.salidas and time.monotonic() < fin:
                try:
                    self._esperar(0.05)
                except vigilante.Atascada:
                    pass
        self.assertEqual(self.salidas, [vigilante.CODIGO_SALIDA])

    def test_atascada_no_la_atrapa_un_except_exception(self):
        """Si heredara de Exception, el bucle de reintentos de la red se la tragaría y
        volvería a empezar la descarga."""
        self.assertFalse(issubclass(vigilante.Atascada, Exception))


class FuenteClavada:
    nombre = "clavada"

    def incremental(self, cursor):
        yield Licitacion(fuente=self.nombre, id_externo="antes-del-atasco",
                         objeto="Concienciación", organo="Órgano")
        raise vigilante.Atascada("sin avanzar desde hace 15m 00s")

    def cursor_nuevo(self):
        return "no-debe-escribirse"


class FuenteBuena:
    nombre = "buena"

    def incremental(self, cursor):
        for i in range(3):
            yield Licitacion(fuente=self.nombre, id_externo=str(i),
                             objeto="Protección del correo", organo="Órgano")

    def cursor_nuevo(self):
        return None


class TestPipelineConAtasco(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.con = db.conectar(Path(self.dir.name) / "t.db")
        self.addCleanup(self.con.close)

    def test_la_fuente_atascada_se_corta_y_las_demas_siguen(self):
        with self.assertLogs(pipeline.log, "ERROR"):
            resumen = pipeline.ingerir(self.con, [FuenteClavada(), FuenteBuena()])
        self.assertTrue(resumen["clavada"]["error"].startswith("atascada"))
        self.assertIsNone(resumen["buena"]["error"])
        self.assertEqual(resumen["buena"]["vistos"], 3)
        # Lo que llegó antes del atasco se queda, y el cursor no avanza: la próxima
        # búsqueda vuelve a pedir lo que faltaba.
        n = self.con.execute(
            "SELECT COUNT(*) FROM licitaciones WHERE fuente = 'clavada'").fetchone()[0]
        self.assertEqual(n, 1)
        self.assertIsNone(db.leer_cursor(self.con, "clavada"))
        fila = self.con.execute(
            "SELECT ok, error, terminado_en FROM ingest_log WHERE fuente = 'clavada'"
        ).fetchone()
        self.assertEqual(fila["ok"], 0)
        self.assertIsNotNone(fila["terminado_en"], "la fila del registro se cierra")


if __name__ == "__main__":
    unittest.main()
