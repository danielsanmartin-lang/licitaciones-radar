"""La carga inicial apunta lo que le falta, para que la aplicación pueda terminarla sola.

Lo que se protege: quien descarga la app de GitHub empieza con la base vacía, y la app
solo lanzaba búsquedas normales. PLACSP sin cursor trae una página, TED y Cataluña los
últimos 30 días, y en cuanto se escribe el cursor ya no se vuelve atrás: la herramienta
se quedaba en unas decenas de coincidencias para siempre. Con las etapas apuntadas, la
pantalla de arranque sabe que tiene que hacer la 1 y lanzar el resto por detrás, y una
carga que se corta se retoma la próxima vez.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from radar import db, novedades, pipeline, progreso, server

RAIZ = Path(__file__).resolve().parent.parent
TOTAL = len(pipeline.ETAPAS_PRIMERA_CARGA)


def _cli():
    """`radar.py`, que se llama igual que el paquete y no se puede importar sin más."""
    spec = importlib.util.spec_from_file_location("radar_cli", RAIZ / "radar.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.bd = Path(self.dir.name) / "t.db"
        self.con = db.conectar(self.bd)
        self.addCleanup(self.con.close)


class TestEtapasPendientes(Base):
    def test_una_base_que_nunca_ha_buscado_las_tiene_todas(self):
        self.assertEqual(db.etapas_pendientes(self.con, TOTAL), list(range(1, TOTAL + 1)))

    def test_una_base_con_historia_y_sin_nada_apuntado_no_tiene_ninguna(self):
        """Es la de quien ya usaba el radar antes de este registro: no se le pide nada."""
        db.cerrar_ingest(self.con, db.abrir_ingest(self.con, "ted"), vistos=3)
        self.assertEqual(db.etapas_pendientes(self.con, TOTAL), [])

    def test_lo_apuntado_manda_aunque_haya_historia(self):
        db.cerrar_ingest(self.con, db.abrir_ingest(self.con, "ted"))
        db.apuntar_etapas_pendientes(self.con, [4, 2, 2])
        self.assertEqual(db.etapas_pendientes(self.con, TOTAL), [2, 4])

    def test_lo_que_no_se_entiende_no_bloquea(self):
        for valor in ("no es json", json.dumps({"a": 1}), json.dumps([1, 99, 0])):
            with self.subTest(valor=valor):
                db.escribir_preferencia(self.con, db.ETAPAS_PENDIENTES, valor)
                self.assertIn(db.etapas_pendientes(self.con, TOTAL), ([], [1]))


class TestLaCargaLasVaQuitando(Base):
    """`_primera_carga` sin red: las fuentes y la evaluación se sustituyen."""

    def setUp(self):
        super().setUp()
        self.cli = _cli()
        self.fallan = set()  # etapas cuyas fuentes devuelven error
        self.vistas = []  # lo apuntado al empezar cada etapa
        for parche in (
            mock.patch.object(progreso, "etapa", side_effect=self._etapa),
            mock.patch.object(progreso, "imprimir"),
            mock.patch.object(pipeline, "construir_fuentes", return_value=[]),
            mock.patch.object(pipeline, "ingerir", side_effect=self._ingerir),
            mock.patch.object(self.cli, "cargar_perfiles", return_value=[]),
            mock.patch.object(self.cli, "_evaluar_perfiles"),
        ):
            parche.start()
            self.addCleanup(parche.stop)

    def _etapa(self, numero, *_):
        self.actual = numero
        con = db.conectar(self.bd)
        self.vistas.append(db.etapas_pendientes(con, TOTAL))
        con.close()

    def _ingerir(self, con, fuentes, anios=None):
        error = "se cortó" if self.actual in self.fallan else None
        return {f"fuente-{self.actual}": {"error": error}}

    def cargar(self, *etapas):
        args = argparse.Namespace(perfiles=None, bd=self.bd, etapas=list(etapas) or None,
                                  dias=30)
        return self.cli._primera_carga(args)

    def pendientes(self):
        return db.etapas_pendientes(self.con, TOTAL)

    def test_lanzar_solo_la_1_deja_apuntadas_las_demas(self):
        """Lo que hace la pantalla de arranque en una instalación nueva."""
        self.assertEqual(self.cargar(1), 0)
        self.assertEqual(self.vistas, [[1, 2, 3, 4]])
        self.assertEqual(self.pendientes(), [2, 3, 4])

    def test_cada_etapa_se_quita_al_terminar_no_al_final(self):
        """Si se cierra a mitad de la 3, la 2 ya no se repite."""
        self.cargar(1)
        self.assertEqual(self.cargar(2, 3, 4), 0)
        self.assertEqual(self.vistas, [[1, 2, 3, 4], [2, 3, 4], [3, 4], [4]])
        self.assertEqual(self.pendientes(), [])

    def test_una_etapa_con_una_fuente_caida_sigue_pendiente(self):
        """El histórico de un ZIP que no bajó no lo trae ninguna búsqueda diaria."""
        self.fallan = {3}
        self.assertEqual(self.cargar(), 1)
        self.assertEqual(self.pendientes(), [3])

    def test_una_carga_cortada_deja_pendiente_lo_que_le_faltaba(self):
        """Cancelar o cerrar la aplicación mata el proceso a mitad de una etapa."""
        def cortar(con, fuentes, anios=None):
            if self.actual == 3:
                raise KeyboardInterrupt
            return {}
        pipeline.ingerir.side_effect = cortar
        with self.assertRaises(KeyboardInterrupt):
            self.cargar()
        self.assertEqual(self.pendientes(), [3, 4])


class TestRutas(Base):
    """Lo que pregunta la pantalla de arranque, contra un servidor de verdad."""

    def setUp(self):
        super().setUp()
        self.srv = server.arrancar(0, self.bd)
        hilo = threading.Thread(target=self.srv.serve_forever, daemon=True)
        hilo.start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def pedir(self, ruta):
        with urllib.request.urlopen(self.base + ruta, timeout=5) as r:
            return json.loads(r.read())

    def test_el_estado_dice_que_etapas_faltan(self):
        self.assertEqual(self.pedir("/api/busqueda-estado")["etapas_pendientes"],
                         [1, 2, 3, 4])
        db.apuntar_etapas_pendientes(self.con, [3, 4])
        self.assertEqual(self.pedir("/api/busqueda-estado")["etapas_pendientes"], [3, 4])

    def test_una_instalacion_nueva_recibe_las_notas_de_su_version(self):
        notas = {"versiones": [{"version": "1.8.0", "bloques": []}], "mas_antiguas": 0,
                 "error": None, "url": "u"}
        with mock.patch.object(novedades, "recien_actualizada",
                               return_value={"desde": None, "hasta": "1.8.0",
                                             "bienvenida": True}), \
             mock.patch.object(novedades, "notas", return_value=notas) as pedidas:
            d = self.pedir("/api/novedades")
        pedidas.assert_called_once_with(None, "1.8.0")
        self.assertTrue(d["actualizada"])
        self.assertTrue(d["bienvenida"])
        self.assertEqual(d["versiones"][0]["version"], "1.8.0")


if __name__ == "__main__":
    unittest.main()
