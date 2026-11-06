"""Consulta previa ↔ licitación: qué pliego sale de cada consulta (`radar/enlaces.py`)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from radar import consultas, db, enlaces
from radar.model import Licitacion

CPM = enlaces.FUENTE_CONSULTAS
NIF = "Q2800000A"


class BaseEnlaces(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = db.conectar(Path(self.dir.name) / "t.db")
        db.crear_indices_diferidos(self.con)
        self.n = 0

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def _añadir(self, objeto, fecha, *, fuente="placsp:licitaciones", nif=NIF,
                expediente=None, organo="Agencia de Pruebas", cpv=()) -> int:
        self.n += 1
        db.guardar(self.con, Licitacion(
            fuente=fuente, id_externo=f"x{self.n}", objeto=objeto, organo=organo,
            nif_organo=nif, expediente=expediente or f"EXP-{self.n}",
            fecha_publicacion=fecha + "T00:00:00", cpv=list(cpv), estado="publicada",
        ))
        self.con.commit()
        return self.con.execute("SELECT id FROM licitaciones WHERE id_externo = ?",
                                (f"x{self.n}",)).fetchone()[0]

    def _relleno(self, cuantos=6):
        """Otros pliegos del mismo órgano, para que sus palabras de siempre pesen poco."""
        for i in range(cuantos):
            self._añadir(f"Servicio de limpieza de la Agencia de Pruebas, sede {i}",
                         "2024-01-10")

    def _consulta(self, objeto, fecha="2025-01-15", **kw) -> int:
        return self._añadir(objeto, fecha, fuente=CPM, **kw)


class TestCalculo(BaseEnlaces):
    def test_mismo_expediente_es_seguro_aunque_el_objeto_cambie(self):
        c = self._consulta("Consulta sobre una plataforma de formación", expediente="AB 12/25")
        lic = self._añadir("Contrato de servicios varios", "2025-06-01", expediente="ab12/25")
        enlaces.actualizar(self.con)
        mejor = enlaces.mejores(self.con)[c]
        self.assertEqual(mejor["licitacion_id"], lic)
        self.assertEqual(mejor["nivel"], "segura")

    def test_objeto_parecido_del_mismo_organo(self):
        self._relleno()
        c = self._consulta("Consulta preliminar sobre la concienciación en ciberseguridad "
                           "y simulación de phishing para el personal")
        lic = self._añadir("Servicio de concienciación en ciberseguridad y simulación de "
                           "phishing para el personal de la Agencia", "2025-05-20")
        enlaces.actualizar(self.con)
        mejor = enlaces.mejores(self.con)[c]
        self.assertEqual(mejor["licitacion_id"], lic)
        self.assertEqual(mejor["nivel"], "probable")
        self.assertIn("phishing", mejor["palabras"])

    def test_otro_organo_no_cuenta(self):
        c = self._consulta("Concienciación en ciberseguridad y simulación de phishing")
        self._añadir("Concienciación en ciberseguridad y simulación de phishing",
                     "2025-05-20", nif="P4600000F")
        enlaces.actualizar(self.con)
        self.assertNotIn(c, enlaces.mejores(self.con))

    def test_lo_publicado_antes_o_demasiado_tarde_no_cuenta(self):
        c = self._consulta("Concienciación en ciberseguridad y simulación de phishing")
        self._añadir("Concienciación en ciberseguridad y simulación de phishing", "2024-12-01")
        self._añadir("Concienciación en ciberseguridad y simulación de phishing", "2027-02-01")
        enlaces.actualizar(self.con)
        self.assertNotIn(c, enlaces.mejores(self.con))

    def test_las_palabras_de_siempre_del_organo_no_enlazan(self):
        """«Agencia de Pruebas» sale en todo lo que publica: compartirla no dice nada."""
        self._relleno()
        c = self._consulta("Suministro de mobiliario para la sede de la Agencia de Pruebas")
        self._añadir("Servicio de limpieza de la Agencia de Pruebas, sede central", "2025-04-01")
        enlaces.actualizar(self.con)
        self.assertNotIn(c, enlaces.mejores(self.con))

    def test_como_mucho_tres_candidatas(self):
        c = self._consulta("Simulación de phishing para empleados públicos")
        for i in range(5):
            self._añadir(f"Simulación de phishing para empleados públicos, lote {i}",
                         f"2025-0{i + 2}-01")
        enlaces.actualizar(self.con)
        self.assertEqual(len(enlaces.de_consulta(self.con, c)["candidatas"]),
                         enlaces.CANDIDATAS)

    def test_sin_indice_no_se_intenta(self):
        self.con.execute(f"DROP INDEX {db.INDICE_CONSULTAS}")
        self.assertEqual(enlaces.actualizar(self.con), {"preparando": True})

    def test_incremental_solo_rehace_los_organos_con_algo_nuevo(self):
        c = self._consulta("Simulación de phishing para empleados públicos")
        self._consulta("Otra cosa de otro órgano", nif="P4600000F")
        primera = enlaces.actualizar(self.con)
        self.assertTrue(primera["completo"])
        self.assertEqual(primera["organos"], 2)
        self.assertNotIn(c, enlaces.mejores(self.con))

        lic = self._añadir("Simulación de phishing para empleados públicos", "2025-03-01")
        segunda = enlaces.actualizar(self.con)
        self.assertFalse(segunda["completo"])
        self.assertEqual(segunda["organos"], 1)
        self.assertEqual(enlaces.mejores(self.con)[c]["licitacion_id"], lic)

        self.assertEqual(enlaces.actualizar(self.con)["organos"], 0)

    def test_cambiar_la_version_lo_rehace_todo(self):
        self._consulta("Simulación de phishing para empleados públicos")
        enlaces.actualizar(self.con)
        db.escribir_preferencia(self.con, enlaces.CLAVE_VERSION, "0")
        self.assertTrue(enlaces.necesita_pasada_completa(self.con))
        self.assertTrue(enlaces.actualizar(self.con)["completo"])


class TestDecisiones(BaseEnlaces):
    def setUp(self):
        super().setUp()
        self.c = self._consulta("Simulación de phishing para empleados públicos")
        self.a = self._añadir("Simulación de phishing para empleados públicos", "2025-03-01")
        self.b = self._añadir("Simulación de phishing para empleados públicos y formación",
                              "2025-04-01")
        enlaces.actualizar(self.con)

    def test_no_es_esta_pasa_a_la_siguiente(self):
        primera = enlaces.mejores(self.con)[self.c]["licitacion_id"]
        otra = self.b if primera == self.a else self.a
        enlaces.decidir(self.con, self.c, primera, "no")
        self.assertEqual(enlaces.mejores(self.con)[self.c]["licitacion_id"], otra)
        self.assertEqual(enlaces.de_licitacion(self.con, primera), [])

    def test_es_esta_sobrevive_a_rehacer_las_candidatas(self):
        enlaces.decidir(self.con, self.c, self.b, "si")
        self.con.execute("DELETE FROM enlaces_consulta")
        self.con.commit()
        enlaces.actualizar(self.con, completo=True)
        self.con.execute("DELETE FROM enlaces_consulta")
        mejor = enlaces.mejores(self.con)[self.c]
        self.assertEqual((mejor["licitacion_id"], mejor["nivel"]), (self.b, "confirmada"))
        # Con una confirmada, la ficha de la consulta solo enseña esa.
        self.assertEqual([x["licitacion_id"] for x in
                          enlaces.de_consulta(self.con, self.c)["candidatas"]], [self.b])

    def test_confirmar_otra_quita_la_confirmacion_anterior(self):
        enlaces.decidir(self.con, self.c, self.a, "si")
        enlaces.decidir(self.con, self.c, self.b, "si")
        filas = self.con.execute(
            "SELECT licitacion_id FROM enlaces_decision WHERE decision = 'si'").fetchall()
        self.assertEqual([f[0] for f in filas], [self.b])

    def test_deshacer(self):
        enlaces.decidir(self.con, self.c, self.a, "no")
        enlaces.decidir(self.con, self.c, self.a, None)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM enlaces_decision").fetchone()[0], 0)

    def test_solo_sobre_consultas(self):
        with self.assertRaises(ValueError):
            enlaces.decidir(self.con, self.a, self.b, "si")
        with self.assertRaises(ValueError):
            enlaces.decidir(self.con, self.c, self.a, "quizá")

    def test_la_licitacion_dice_de_que_consulta_viene(self):
        lic = enlaces.mejores(self.con)[self.c]["licitacion_id"]
        origen = enlaces.de_licitacion(self.con, lic)
        self.assertEqual([o["id"] for o in origen], [self.c])


class TestAvisos(BaseEnlaces):
    def setUp(self):
        super().setUp()
        self.c = self._consulta("Simulación de phishing para empleados públicos")
        self.marca = self.con.execute("SELECT MAX(id) FROM licitaciones").fetchone()[0]
        self.lic = self._añadir("Simulación de phishing para empleados públicos", "2025-03-01")
        enlaces.actualizar(self.con)

    def test_las_tarjetas_llevan_el_enlace(self):
        items = enlaces.anotar(self.con, [
            {"id": self.c, "fuente": CPM, "clave_grupo": None},
            {"id": self.lic, "fuente": "placsp:licitaciones",
             "clave_grupo": self.con.execute("SELECT clave_grupo FROM licitaciones WHERE id = ?",
                                             (self.lic,)).fetchone()[0]},
        ])
        self.assertEqual(items[0]["licitada"], "probable")
        self.assertEqual(items[1]["consulta_previa"], "probable")

    def test_el_icono_cuenta_solo_las_consultas_que_sigues(self):
        estados = consultas.ESTADOS_PROTEGIDOS
        self.assertEqual(enlaces.licitadas_desde(self.con, self.marca, estados), 0)
        db.fijar_revision(self.con, self.c, estado="siguiendo")
        self.con.commit()
        self.assertEqual(enlaces.licitadas_desde(self.con, self.marca, estados), 1)
        # Lo que ya estaba antes de la última visita no es noticia.
        self.assertEqual(enlaces.licitadas_desde(self.con, self.lic, estados), 0)
        # Sin visita apuntada no hay «desde».
        self.assertEqual(enlaces.licitadas_desde(self.con, None, estados), 0)

    def test_el_resumen_suma_el_numero_del_icono(self):
        db.fijar_revision(self.con, self.c, estado="siguiendo")
        db.escribir_preferencia(self.con, "ultima_visita_id", str(self.marca))
        self.con.commit()
        r = consultas.resumen(self.con)
        self.assertEqual(r["insignia"], r["novedades"] + 1)


if __name__ == "__main__":
    unittest.main()


class TestRutas(BaseEnlaces):
    """Las rutas nuevas: la ficha con sus enlaces, «es esta», la prospección y su CSV."""

    def setUp(self):
        super().setUp()
        import threading

        from radar import server
        self.c = self._consulta("Simulación de phishing para empleados públicos")
        self.lic = self._añadir("Simulación de phishing para empleados públicos", "2025-03-01")
        enlaces.actualizar(self.con)
        self.srv = server.arrancar(0, Path(self.dir.name) / "t.db")
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def pedir(self, ruta, cuerpo=None):
        import json
        import urllib.error
        import urllib.request
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        peticion = urllib.request.Request(self.base + ruta, data=datos,
                                          headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(peticion, timeout=5) as r:
                crudo = r.read()
                return r.status, (json.loads(crudo) if "json" in r.headers["Content-Type"]
                                  else crudo.decode("utf-8-sig"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_la_ficha_de_la_consulta_trae_sus_licitaciones(self):
        _, d = self.pedir(f"/api/licitacion/{self.c}")
        self.assertEqual([x["licitacion_id"] for x in
                          d["licitaciones_de_la_consulta"]["candidatas"]], [self.lic])
        _, d = self.pedir(f"/api/licitacion/{self.lic}")
        self.assertEqual([x["id"] for x in d["consultas_previas"]], [self.c])

    def test_es_esta(self):
        codigo, _ = self.pedir("/api/enlace", {"consulta_id": self.c,
                                               "licitacion_id": self.lic, "decision": "si"})
        self.assertEqual(codigo, 200)
        self.assertEqual(enlaces.mejores(self.con)[self.c]["nivel"], "confirmada")
        self.assertEqual(self.pedir("/api/enlace", {"consulta_id": self.c})[0], 400)

    def test_prospeccion_y_csv(self):
        codigo, d = self.pedir("/api/prospeccion", {"clave": "g1", "estado": "reunion"})
        self.assertEqual((codigo, d["estado"]), (200, "reunion"))
        self.assertEqual(self.pedir("/api/prospeccion", {"clave": "g1", "estado": "x"})[0], 400)
        codigo, texto = self.pedir("/api/prospeccion.csv?meses=12")
        self.assertEqual(codigo, 200)
        self.assertTrue(texto.startswith("Apartado,Órgano"))
