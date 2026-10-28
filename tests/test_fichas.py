"""Las fichas de organismo y de competidor, y el listado de organismos.

Lo que se protege: que cuenten como la Analítica —por expediente, con el ámbito de
perfiles o temática, sin lo descartado—, que un competidor junte sus razones sociales
como el ranking de Adjudicatarios, y que una ficha no se quede con datos viejos cuando la
base cambia.
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from radar import consultas, db, server
from radar.model import Licitacion

ORGANO = "Ayuntamiento de Ávila"


def dia(desplazamiento: int) -> str:
    return (date.today() + timedelta(days=desplazamiento)).isoformat()


class Base(unittest.TestCase):
    def setUp(self):
        consultas._MEMO_FICHAS.clear()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.bd = Path(self.dir.name) / "t.db"
        self.con = db.conectar(self.bd)
        self.addCleanup(self.con.close)

    def alta(self, ide, *, perfil="p", organo=ORGANO, grupo=None, publicada=-200,
             limite=None, estado="adjudicada", **extra) -> int:
        db.guardar(self.con, Licitacion(
            fuente="prueba", id_externo=ide, objeto=f"Objeto {ide}", organo=organo,
            fecha_publicacion=dia(publicada) + "T10:00:00", estado=estado,
            fecha_limite_presentacion=dia(limite) + "T14:00:00" if limite is not None else None,
            clave_grupo=grupo or f"g-{ide}", **extra,
        ))
        lic_id = self.con.execute(
            "SELECT id FROM licitaciones WHERE id_externo = ?", (ide,)).fetchone()[0]
        if perfil:
            self.con.execute(
                """INSERT INTO matches (licitacion_id, perfil, puntuacion, motivo, creado_en)
                   VALUES (?, ?, 3.0, 'prueba', ?)""", (lic_id, perfil, db.ahora()))
        self.con.commit()
        return lic_id


class TestOrganismo(Base):
    def setUp(self):
        super().setUp()
        # Un expediente con dos anuncios: el pliego y la adjudicación.
        self.alta("a-pliego", grupo="exp-a", publicada=-200, limite=-180, estado="publicada",
                  importe_sin_iva=100_000.0, nif_organo="P0501900E")
        self.alta("a-adj", grupo="exp-a", publicada=-150, importe_sin_iva=100_000.0,
                  importe_adjudicacion=80_000.0, adjudicatario="S2 GRUPO SOLUCIONES, S.L.U.",
                  fecha_adjudicacion=dia(-150), fecha_fin_prevista=dia(200))
        self.alta("b", publicada=-100, importe_sin_iva=30_000.0, importe_adjudicacion=27_000.0,
                  adjudicatario="Otra Empresa SA", fecha_adjudicacion=dia(-90))
        self.abierto = self.alta("c-abierto", publicada=-5, limite=20, estado="publicada",
                                 importe_sin_iva=50_000.0)
        self.alta("de-otro-perfil", perfil="q", publicada=-50)
        self.alta("de-otro-organo", organo="Diputación de Ávila")

    def test_cuenta_expedientes_con_las_reglas_de_la_analitica(self):
        f = consultas.ficha_organismo(self.con, ORGANO)
        c = f["cifras"]
        self.assertEqual((c["expedientes"], c["abiertos"], c["adjudicados"]), (4, 1, 2))
        # Baja del anuncio de adjudicación de cada expediente: 20 % y 10 %.
        self.assertEqual((c["baja_mediana"], c["baja_comparables"]), (15.0, 2))
        # Plazo del primer anuncio: 20 días en el pliego de exp-a, 25 en el abierto.
        self.assertEqual(c["plazo_expedientes"], 2)
        self.assertEqual(f["nifs"], ["P0501900E"])
        self.assertEqual(sum(m["expedientes"] for m in f["meses"]), 4)

    def test_lo_abierto_aparte_y_con_formato_de_tarjeta(self):
        f = consultas.ficha_organismo(self.con, ORGANO)
        self.assertEqual([it["id"] for it in f["abiertos"]], [self.abierto])
        tarjeta = f["abiertos"][0]
        self.assertEqual(tarjeta["dias_restantes"], 20)
        self.assertEqual(tarjeta["estado_revision"], "nuevo")
        self.assertEqual(f["anteriores_total"], 3)
        agrupado = next(it for it in f["anteriores"] if it["id_externo"] == "a-adj")
        self.assertEqual(agrupado["anuncios"], 2)

    def test_quien_gana_y_que_vence(self):
        f = consultas.ficha_organismo(self.con, ORGANO)
        self.assertEqual({e["empresa"] for e in f["adjudicatarios"]["empresas"]},
                         {"S2 GRUPO SOLUCIONES, S.L.U.", "Otra Empresa SA"})
        self.assertEqual([v["adjudicatario"] for v in f["vencen"]], ["S2 GRUPO SOLUCIONES, S.L.U."])
        self.assertEqual(f["vencen"][0]["dias_para_vencer"], 200)

    def test_el_ambito_manda(self):
        self.assertEqual(
            consultas.ficha_organismo(self.con, ORGANO, ambito=consultas.Ambito.de("q"))
            ["cifras"]["expedientes"], 1)
        self.assertIsNone(consultas.ficha_organismo(self.con, "Nadie"))

    def test_lo_descartado_no_cuenta_y_la_ficha_no_se_queda_vieja(self):
        self.assertEqual(consultas.ficha_organismo(self.con, ORGANO)["cifras"]["expedientes"], 4)
        db.fijar_revision(self.con, self.abierto, estado="descartado")
        self.con.commit()
        self.assertEqual(consultas.ficha_organismo(self.con, ORGANO)["cifras"]["expedientes"], 3)


class TestCompetidor(Base):
    def setUp(self):
        super().setUp()
        self.alta("s2-uno", organo="Ayuntamiento de Ávila", ccaa="Castilla y León",
                  adjudicatario="S2 GRUPO SOLUCIONES DE SEGURIDAD, S.L.U.",
                  importe_sin_iva=100_000.0, importe_adjudicacion=90_000.0,
                  fecha_adjudicacion="2025-03-01", fecha_fin_prevista=dia(100))
        self.alta("s2-dos", organo="Gobierno de Navarra", ccaa="Navarra",
                  adjudicatario="S2 Grupo Soluciones de Seguridad S.L.U.",
                  importe_sin_iva=50_000.0, importe_adjudicacion=40_000.0,
                  fecha_adjudicacion="2026-02-01")
        self.alta("s2-lote", organo="Gobierno de Navarra", ccaa="Navarra", grupo="g-s2-dos",
                  adjudicatario="S2 GRUPO SOLUCIONES DE SEGURIDAD, S.L.",
                  importe_adjudicacion=10_000.0, fecha_adjudicacion="2026-02-01")
        self.alta("otra", adjudicatario="Otra SA", importe_adjudicacion=5_000.0)

    def test_junta_las_razones_sociales_como_el_ranking(self):
        f = consultas.ficha_competidor(self.con, "S2 Grupo Soluciones de Seguridad, S.L.")
        self.assertEqual(len(f["variantes"]), 3)
        c = f["cifras"]
        # Dos expedientes: el lote va con el suyo y su importe es el mayor, no la suma.
        self.assertEqual((c["ganados"], c["importe"], c["organismos"]), (2, 130_000.0, 2))
        ranking = consultas.competencia(self.con, limite=5)
        s2 = next(e for e in ranking if e["empresa"].startswith("S2"))
        self.assertEqual(s2["organos"], c["organismos"])

    def test_dice_donde_gana_cuando_y_que_le_vence(self):
        f = consultas.ficha_competidor(self.con, "S2 GRUPO SOLUCIONES DE SEGURIDAD SLU")
        self.assertEqual([a["anio"] for a in f["por_anio"]], ["2025", "2026"])
        self.assertEqual({x["ccaa"] for x in f["comunidades"]}, {"Castilla y León", "Navarra"})
        self.assertEqual(f["organismos"][0]["organo"], "Ayuntamiento de Ávila")
        self.assertEqual(len(f["vencen"]), 1)
        self.assertTrue(f["contratos"][0]["fecha_adjudicacion"].startswith("2026-02-01"))
        self.assertEqual(f["cifras"]["baja_mediana"], 15.0)

    def test_una_empresa_que_no_esta_no_tiene_ficha(self):
        self.assertIsNone(consultas.ficha_competidor(self.con, "Inexistente SL"))
        self.assertIsNone(consultas.ficha_competidor(self.con, "S.L."))


class TestOrganismos(Base):
    def test_ordena_por_expedientes_y_busca_sin_acentos(self):
        self.alta("a1")
        self.alta("a2", estado="publicada", limite=10)
        self.alta("d1", organo="Diputación de Ávila")
        o = consultas.organismos(self.con)
        self.assertEqual([x["organo"] for x in o["items"]],
                         [ORGANO, "Diputación de Ávila"])
        self.assertEqual((o["items"][0]["expedientes"], o["items"][0]["abiertos"]), (2, 1))
        self.assertEqual([x["organo"] for x in consultas.organismos(self.con, q="DIPUTACION")
                          ["items"]], ["Diputación de Ávila"])


class TestRutas(Base):
    def setUp(self):
        super().setUp()
        self.alta("a1", adjudicatario="Ganadora SL", importe_adjudicacion=1000.0)
        self.srv = server.arrancar(0, self.bd)
        hilo = threading.Thread(target=self.srv.serve_forever, daemon=True)
        hilo.start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def pedir(self, ruta):
        try:
            with urllib.request.urlopen(self.base + ruta, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_las_tres_rutas(self):
        nombre = urllib.parse.quote(ORGANO)
        self.assertEqual(self.pedir("/api/organismos")[1]["items"][0]["organo"], ORGANO)
        codigo, d = self.pedir(f"/api/organismo?nombre={nombre}")
        self.assertEqual((codigo, d["cifras"]["expedientes"]), (200, 1))
        codigo, d = self.pedir("/api/competidor?empresa=Ganadora%20S.L.")
        self.assertEqual((codigo, d["cifras"]["ganados"]), (200, 1))

    def test_sin_nombre_400_y_sin_datos_404(self):
        self.assertEqual(self.pedir("/api/organismo")[0], 400)
        self.assertEqual(self.pedir("/api/competidor")[0], 400)
        codigo, d = self.pedir("/api/organismo?nombre=Nadie")
        self.assertEqual(codigo, 404)
        self.assertIn("Todos los perfiles", d["error"])
        self.assertEqual(self.pedir(f"/api/organismo?nombre=x&categoria=resto")[0], 400)


if __name__ == "__main__":
    unittest.main()
