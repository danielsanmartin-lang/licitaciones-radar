"""Favoritos de empresas y organismos (botones encima de Adjudicatarios y Organismos).

Lo que se protege: que una empresa sea favorita con cualquiera de sus razones sociales
—la misma normalización que junta sus variantes en el ranking—, que el listado y la
ficha lo digan, y que el endpoint no acepte tipos inventados.
"""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from radar import consultas, db, server
from radar.model import Licitacion


class TestFavoritos(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.con = db.conectar(Path(self.dir.name) / "t.db")
        self.addCleanup(self.con.close)

    def test_una_empresa_es_favorita_con_cualquiera_de_sus_razones_sociales(self):
        consultas.fijar_favorito(self.con, "empresa", "S2 GRUPO SOLUCIONES DE SEGURIDAD, S.L.U.",
                                 True)
        claves = consultas.claves_favoritas(self.con, "empresa")
        self.assertIn(consultas.normalizar_empresa("S2 Grupo Soluciones de Seguridad S.L."),
                      claves)
        # Volver a marcarla con otra variante no la duplica.
        d = consultas.fijar_favorito(self.con, "empresa", "S2 Grupo Soluciones de Seguridad SL",
                                     True)
        self.assertEqual(len(d["empresa"]), 1)
        d = consultas.fijar_favorito(self.con, "empresa", "S2 GRUPO SOLUCIONES DE SEGURIDAD",
                                     False)
        self.assertEqual(d["empresa"], [])

    def test_organismos_por_nombre_exacto_y_en_orden_alfabetico(self):
        for nombre in ("Ayuntamiento de Zaragoza", "agencia Tributaria", "Bilbao"):
            consultas.fijar_favorito(self.con, "organismo", nombre, True)
        d = consultas.favoritos(self.con)
        self.assertEqual([f["nombre"] for f in d["organismo"]],
                         ["agencia Tributaria", "Ayuntamiento de Zaragoza", "Bilbao"])

    def test_rechaza_lo_que_no_vale(self):
        with self.assertRaises(ValueError):
            consultas.fijar_favorito(self.con, "licitacion", "x", True)
        with self.assertRaises(ValueError):
            consultas.fijar_favorito(self.con, "empresa", "  ", True)


class TestFavoritosPorHttp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        ruta = Path(self.dir.name) / "t.db"
        con = db.conectar(ruta)
        db.guardar(con, Licitacion(
            fuente="prueba", id_externo="1", objeto="Concienciación", organo="Ayuntamiento X",
            estado="adjudicada", fecha_publicacion="2025-03-10", expediente="E/1",
            adjudicatario="ACME SEGURIDAD, S.L.", importe_adjudicacion=10000.0))
        con.execute("INSERT INTO matches (licitacion_id, perfil, puntuacion, motivo, creado_en)"
                    " VALUES (1, 'p', 3.0, 'm', ?)", (db.ahora(),))
        con.commit()
        con.close()
        consultas._MEMO_FICHAS.clear()
        self.addCleanup(consultas._MEMO_FICHAS.clear)
        self.servidor = server.arrancar(0, ruta)
        self.puerto = self.servidor.server_address[1]
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.addCleanup(self.servidor.server_close)
        self.addCleanup(self.servidor.shutdown)

    def pedir(self, ruta, cuerpo=None):
        datos = None if cuerpo is None else json.dumps(cuerpo).encode()
        peticion = urllib.request.Request(
            f"http://127.0.0.1:{self.puerto}{ruta}", data=datos,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(peticion, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    def test_el_listado_y_las_fichas_dicen_si_es_favorito(self):
        self.assertFalse(self.pedir("/api/adjudicatarios")[1]["items"][0]["favorito"])
        codigo, d = self.pedir("/api/favoritos",
                               {"tipo": "empresa", "nombre": "Acme Seguridad SL", "favorito": True})
        self.assertEqual((codigo, [f["nombre"] for f in d["empresa"]]), (200, ["Acme Seguridad SL"]))
        self.assertTrue(self.pedir("/api/adjudicatarios")[1]["items"][0]["favorito"])
        codigo, ficha = self.pedir("/api/competidor?empresa=ACME%20SEGURIDAD%2C%20S.L.")
        self.assertEqual((codigo, ficha["favorito"]), (200, True))

        self.pedir("/api/favoritos", {"tipo": "organismo", "nombre": "Ayuntamiento X",
                                      "favorito": True})
        self.assertTrue(self.pedir("/api/organismos")[1]["items"][0]["favorito"])
        codigo, ficha = self.pedir("/api/organismo?nombre=Ayuntamiento%20X")
        self.assertEqual((codigo, ficha["favorito"]), (200, True))
        self.assertEqual(len(self.pedir("/api/favoritos")[1]["organismo"]), 1)

    def test_el_endpoint_valida(self):
        self.assertEqual(self.pedir("/api/favoritos", {"tipo": "x", "nombre": "a",
                                                       "favorito": True})[0], 400)
        self.assertEqual(self.pedir("/api/favoritos", {"tipo": "empresa", "nombre": "a",
                                                       "favorito": "sí"})[0], 400)


if __name__ == "__main__":
    unittest.main()
