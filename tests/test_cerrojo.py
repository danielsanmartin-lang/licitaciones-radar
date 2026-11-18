"""La bandeja no puede quedarse esperando a una búsqueda en marcha.

Lo que pasó: con PLACSP bajando a 0,1 MB/s, la ingesta tenía tomado el cerrojo de
escritura de la base unos diez minutos seguidos —la transacción seguía abierta mientras
esperaba la página siguiente— y cada petición del servidor, al abrir su conexión,
pasaba por `migrar()`, que escribía siempre. Resultado: hasta abrir la bandeja esperaba
30 s y acababa en «database is locked».

Aquí se comprueba cada mitad por separado: que abrir la base para leer no pide escribir,
y que la ingesta suelta el cerrojo antes de salir a la red.
"""

import json
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from radar import db, net, pipeline, server
from radar.model import Licitacion


def bloquear_escritura(ruta: Path) -> sqlite3.Connection:
    """Una conexión con el cerrojo de escritura tomado, como el de una ingesta."""
    otra = sqlite3.connect(str(ruta), isolation_level=None)
    otra.execute("BEGIN IMMEDIATE")
    return otra


def puede_escribir(ruta: Path) -> bool:
    """¿Consigue otra conexión el cerrojo de escritura sin esperar?"""
    otra = sqlite3.connect(str(ruta), timeout=0, isolation_level=None)
    try:
        otra.execute("BEGIN IMMEDIATE")
        otra.execute("ROLLBACK")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        otra.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.bd = Path(self.dir.name) / "t.db"
        con = db.conectar(self.bd)
        db.guardar(con, Licitacion(fuente="falsa", id_externo="1",
                                   objeto="Concienciación", organo="Órgano"))
        con.commit()
        con.close()
        # Con filas ya dentro, la segunda pasada aplica las migraciones que dependen
        # de que haya datos. Desde aquí la base está al día.
        db.conectar(self.bd).close()


class TestAbrirSinEscribir(Base):
    def test_conectar_una_base_al_dia_no_espera_al_cerrojo(self):
        """Si no hay nada que migrar, preparar la base no puede pedir escribir: es lo
        que hace `radar.py serve` al arrancar, quizá con una búsqueda ya en marcha."""
        otra = bloquear_escritura(self.bd)
        self.addCleanup(otra.close)
        inicio = time.monotonic()
        db.conectar(self.bd).close()
        self.assertLess(time.monotonic() - inicio, 2)

    def test_la_migracion_de_prospeccion_sigue_aplicandose(self):
        con = db.conectar(self.bd)
        con.execute("INSERT INTO prospeccion (clave, estado, actualizado_en)"
                    " VALUES ('x', 'reunion', ?)", (db.ahora(),))
        con.commit()
        con.close()
        con = db.conectar(self.bd)
        self.addCleanup(con.close)
        self.assertEqual(
            con.execute("SELECT estado FROM prospeccion").fetchone()[0], "siguiendo"
        )
        self.assertFalse(con.in_transaction)

    def test_abrir_mantiene_las_claves_ajenas(self):
        con = db.abrir(self.bd)
        self.addCleanup(con.close)
        self.assertEqual(con.execute("PRAGMA foreign_keys").fetchone()[0], 1)


class TestServidorConBusquedaEnMarcha(Base):
    def setUp(self):
        super().setUp()
        self.srv = server.arrancar(0, self.bd)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def test_la_bandeja_responde_aunque_la_base_este_tomada(self):
        otra = bloquear_escritura(self.bd)
        self.addCleanup(otra.close)
        for ruta in ("/api/resumen", "/api/bandeja", "/api/vencimientos"):
            with self.subTest(ruta=ruta):
                inicio = time.monotonic()
                with urllib.request.urlopen(self.base + ruta, timeout=10) as r:
                    self.assertEqual(r.status, 200)
                    json.loads(r.read())
                self.assertLess(time.monotonic() - inicio, 2)


class FuenteQueDescarga:
    """Fuente que trae dos páginas y sale a la red entre una y otra."""

    nombre = "falsa"

    def __init__(self, ruta: Path):
        self.ruta = ruta
        self.libre_al_descargar = []

    def incremental(self, cursor):
        for pagina in range(2):
            # Lo que haría `net.descargar`: pasar por `_abrir`. Se sustituye `urlopen`
            # para mirar, justo en el momento de salir a la red, si la base está libre.
            with mock.patch("urllib.request.urlopen", side_effect=self._urlopen):
                net._abrir(urllib.request.Request("https://ejemplo.invalid/"), 1)
            for i in range(3):
                yield Licitacion(fuente=self.nombre, id_externo=f"p{pagina}-{i}",
                                 objeto="Concienciación", organo="Órgano")

    def _urlopen(self, *_a, **_k):
        self.libre_al_descargar.append(puede_escribir(self.ruta))
        return mock.MagicMock()

    def cursor_nuevo(self):
        return None


class TestIngestaSueltaElCerrojo(Base):
    def test_guarda_lo_escrito_antes_de_cada_descarga(self):
        con = db.conectar(self.bd)
        self.addCleanup(con.close)
        fuente = FuenteQueDescarga(self.bd)
        pipeline.ingerir(con, [fuente])
        # La primera descarga llega con el registro de la ingesta recién abierto y la
        # segunda con la página anterior escrita: antes, las dos se hacían con el
        # cerrojo tomado.
        self.assertEqual(fuente.libre_al_descargar, [True, True])
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM licitaciones WHERE fuente = 'falsa'"
                        " AND id_externo LIKE 'p%'").fetchone()[0], 6
        )

    def test_fuera_de_la_ingesta_no_hay_gancho(self):
        con = db.conectar(self.bd)
        self.addCleanup(con.close)
        pipeline.ingerir(con, [FuenteQueDescarga(self.bd)])
        self.assertIsNone(net._antes_de_la_red)


if __name__ == "__main__":
    unittest.main()
