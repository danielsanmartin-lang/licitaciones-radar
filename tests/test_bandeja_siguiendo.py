"""La Bandeja se puede poner al día, y lo que sigues tiene su propia vista.

Lo que se protege:

- «Limpiar sin revisar…» pasa a «vista» exactamente lo que dice: las vencidas, las sin
  fecha o todas, por expediente, y nunca lo que sigues, has presentado o descartado. Y
  «Deshacer» lo deja como estaba.
- El contador «coincidencias» ya no cuenta lo de plazo vencido, y su filtro enseña lo
  mismo que cuenta.
- «Ocultar sin plazo» quita lo que no publica fecha límite.
- «Siguiendo» reparte en plazo y plazo vencido, y de lo vencido dice quién ganó.
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from radar import consultas, db, server
from radar.model import Licitacion

PERFIL = "Concienciación y phishing"


def dia(desplazamiento: int) -> str:
    return (date.today() + timedelta(days=desplazamiento)).isoformat() + "T12:00:00"


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.bd = Path(self.dir.name) / "t.db"
        self.con = db.conectar(self.bd)
        self.addCleanup(self.con.close)

    def alta(self, ide, *, limite=None, estado="publicada", grupo=None, perfil=PERFIL,
             revision=None, publicada=-30, **extra) -> int:
        db.guardar(self.con, Licitacion(
            fuente="prueba", id_externo=ide, objeto=f"Objeto {ide}", organo="Órgano",
            fecha_publicacion=dia(publicada), estado=estado,
            fecha_limite_presentacion=dia(limite) if limite is not None else None,
            clave_grupo=grupo or f"g-{ide}", **extra,
        ))
        lic_id = self.con.execute(
            "SELECT id FROM licitaciones WHERE id_externo = ?", (ide,)).fetchone()[0]
        if perfil:
            self.con.execute(
                """INSERT INTO matches (licitacion_id, perfil, puntuacion, motivo, creado_en)
                   VALUES (?, ?, 3.0, 'prueba', ?)""", (lic_id, perfil, db.ahora()))
        if revision:
            db.fijar_revision(self.con, lic_id, estado=revision)
        self.con.commit()
        return lic_id

    def estado(self, lic_id) -> str:
        fila = self.con.execute(
            "SELECT estado FROM revisiones WHERE licitacion_id = ?", (lic_id,)).fetchone()
        return fila["estado"] if fila else "nuevo"


class TestLimpiar(Base):
    def setUp(self):
        super().setUp()
        self.vencida = self.alta("vencida", limite=-10)
        self.sin_fecha = self.alta("sin-fecha")
        self.en_plazo = self.alta("en-plazo", limite=10)
        self.seguida = self.alta("seguida", limite=-10, revision="siguiendo")
        self.presentada = self.alta("presentada", limite=-10, revision="presentada")
        self.descartada = self.alta("descartada", limite=-10, revision="descartado")

    def test_el_reparto_suma_lo_que_dice_el_contador(self):
        r = consultas.resumen(self.con)
        self.assertEqual(r["sin_revisar"], 3)
        self.assertEqual((r["sin_revisar_vencidas"], r["sin_revisar_sin_fecha"]), (1, 1))

    def test_cada_criterio_marca_lo_suyo(self):
        for criterio, marcada in (("vencidas", "vencida"), ("sin_fecha", "sin-fecha")):
            with self.subTest(criterio=criterio):
                hecho = consultas.limpiar_sin_revisar(self.con, criterio)
                self.assertEqual(hecho["expedientes"], 1)
                lic = getattr(self, marcada.replace("-", "_"))
                self.assertEqual(hecho["ids"], [lic])
                self.assertEqual(self.estado(lic), "vista")
                db.desmarcar_vistas(self.con, hecho["ids"])

    def test_todas_marca_las_tres_y_nada_mas(self):
        hecho = consultas.limpiar_sin_revisar(self.con, "todas")
        self.assertEqual(sorted(hecho["ids"]),
                         sorted([self.vencida, self.sin_fecha, self.en_plazo]))
        self.assertEqual(
            [self.estado(i) for i in (self.seguida, self.presentada, self.descartada)],
            ["siguiendo", "presentada", "descartado"])
        r = consultas.resumen(self.con)
        self.assertEqual(r["sin_revisar"], 0)

    def test_lo_visto_sigue_en_la_bandeja(self):
        """No es descartar: nadie ha decidido que no interese."""
        consultas.limpiar_sin_revisar(self.con, "todas")
        ids = {it["id"] for it in consultas.bandeja(self.con, solo_vivas=False)["items"]}
        self.assertIn(self.vencida, ids)
        self.assertEqual(consultas.contar(self.con, solo_vivas=False, estado_revision="vista"), 3)

    def test_se_decide_por_expediente_y_se_escribe_en_todos_sus_anuncios(self):
        """Una corrección que amplía el plazo manda sobre el anuncio original."""
        original = self.alta("original", limite=-20, grupo="exp")
        ampliado = self.alta("ampliado", limite=5, grupo="exp", perfil=None, publicada=-2)
        self.assertNotIn(original, consultas.limpiar_sin_revisar(self.con, "vencidas")["ids"])
        hecho = consultas.limpiar_sin_revisar(self.con, "todas")
        self.assertIn(original, hecho["ids"])
        self.assertIn(ampliado, hecho["ids"])

    def test_deshacer_no_deshace_otra_decision(self):
        hecho = consultas.limpiar_sin_revisar(self.con, "todas")
        db.fijar_revision(self.con, self.vencida, estado="siguiendo")
        self.assertEqual(db.desmarcar_vistas(self.con, hecho["ids"]), 2)
        self.assertEqual(self.estado(self.vencida), "siguiendo")
        self.assertEqual(self.estado(self.sin_fecha), "nuevo")
        self.assertEqual(consultas.resumen(self.con)["sin_revisar"], 2)

    def test_las_notas_se_conservan(self):
        db.fijar_revision(self.con, self.vencida, notas="llamar a Juan")
        consultas.limpiar_sin_revisar(self.con, "vencidas")
        fila = self.con.execute("SELECT estado, notas FROM revisiones WHERE licitacion_id = ?",
                                (self.vencida,)).fetchone()
        self.assertEqual((fila["estado"], fila["notas"]), ("vista", "llamar a Juan"))

    def test_un_criterio_desconocido_se_rechaza(self):
        with self.assertRaises(ValueError):
            consultas.limpiar_sin_revisar(self.con, "las-viejas")

    def test_vista_es_un_estado_que_se_puede_poner_a_mano(self):
        db.fijar_revision(self.con, self.en_plazo, estado="vista")
        self.assertEqual(self.estado(self.en_plazo), "vista")
        columnas, filas = consultas.para_csv(self.con, solo_vivas=False, estado_revision="vista")
        self.assertEqual([f[columnas.index("estado_revision")] for f in filas], ["vista"])


class TestContadores(Base):
    def setUp(self):
        super().setUp()
        self.alta("vencida", limite=-3)
        self.alta("sin-fecha")
        self.alta("abierta", limite=3)
        self.alta("cerrada-sin-fecha", estado="adjudicada")

    def test_coincidencias_no_cuenta_lo_vencido_y_su_filtro_tampoco(self):
        r = consultas.resumen(self.con)
        self.assertEqual(r["coincidencias"], 3)
        lista = consultas.bandeja(self.con, solo_vivas=False, sin_vencidas=True)
        self.assertEqual(lista["total"], 3)
        self.assertEqual(len(lista["items"]), 3)
        # El denominador de «3 de 4» sigue siendo todo.
        self.assertEqual(lista["total_sin_filtros"], 4)

    def test_ocultar_sin_plazo(self):
        lista = consultas.bandeja(self.con, solo_vivas=False, con_plazo=True)
        self.assertEqual(sorted(it["id_externo"] for it in lista["items"]), ["abierta", "vencida"])
        self.assertEqual(consultas.contar(self.con, solo_vivas=True, con_plazo=True), 1)


class TestSiguiendo(Base):
    def test_reparte_ordena_y_dice_quien_gano(self):
        cerca = self.alta("cerca", limite=2, revision="siguiendo")
        lejos = self.alta("lejos", limite=20, revision="presentada")
        sin_fecha = self.alta("sin-fecha", estado="previo", revision="siguiendo")
        vieja = self.alta("vieja", limite=-40, revision="siguiendo", grupo="exp-vieja")
        # El ganador llega en otro anuncio del expediente, y el que se enseña es una
        # corrección posterior sin adjudicatario.
        self.alta("vieja-adj", limite=-40, estado="adjudicada", grupo="exp-vieja", perfil=None,
                  adjudicatario="Ganadora S.L.", importe_adjudicacion=12000.0,
                  fecha_adjudicacion=dia(-20)[:10], publicada=-20)
        self.alta("vieja-corr", limite=-40, estado="adjudicada", grupo="exp-vieja", perfil=None,
                  publicada=-1)
        reciente = self.alta("reciente", limite=-5, estado="evaluacion", revision="siguiendo")
        self.alta("sin-seguir", limite=5)

        s = consultas.siguiendo(self.con)
        self.assertEqual([it["id"] for it in s["en_plazo"]], [cerca, lejos, sin_fecha])
        self.assertEqual([it["id_externo"] for it in s["vencidas"]], ["reciente", "vieja-corr"])
        self.assertEqual(s["total"], 5)
        ganada = s["vencidas"][1]
        self.assertEqual((ganada["adjudicatario"], ganada["importe_adjudicacion"]),
                         ("Ganadora S.L.", 12000.0))
        self.assertIsNone(s["vencidas"][0].get("adjudicatario"))
        self.assertNotIn(vieja, [it["id"] for it in s["en_plazo"]])
        self.assertIn(reciente, [it["id"] for it in s["vencidas"]])
        self.assertEqual(consultas.resumen(self.con)["siguiendo_en_plazo"], 3)

    def test_lo_que_sigues_sale_aunque_ya_no_case(self):
        sola = self.alta("sola", limite=8, perfil=None, revision="siguiendo")
        self.assertEqual([it["id"] for it in consultas.siguiendo(self.con)["en_plazo"]], [sola])


class TestRutas(Base):
    def setUp(self):
        super().setUp()
        self.srv = server.arrancar(0, self.bd)
        hilo = threading.Thread(target=self.srv.serve_forever, daemon=True)
        hilo.start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def pedir(self, ruta, cuerpo=None):
        datos = None if cuerpo is None else json.dumps(cuerpo).encode()
        req = urllib.request.Request(self.base + ruta, data=datos,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_limpiar_y_deshacer(self):
        vencida = self.alta("vencida", limite=-3)
        codigo, d = self.pedir("/api/revision/lote", {"criterio": "vencidas"})
        self.assertEqual((codigo, d["expedientes"], d["ids"]), (200, 1, [vencida]))
        self.assertEqual(self.pedir("/api/resumen")[1]["sin_revisar"], 0)
        codigo, d = self.pedir("/api/revision/lote/deshacer", {"ids": d["ids"]})
        self.assertEqual((codigo, d["deshechas"]), (200, 1))
        self.assertEqual(self.pedir("/api/resumen")[1]["sin_revisar"], 1)

    def test_lo_que_no_se_entiende_es_un_400(self):
        self.assertEqual(self.pedir("/api/revision/lote", {"criterio": "x"})[0], 400)
        self.assertEqual(self.pedir("/api/revision/lote/deshacer", {"ids": "1"})[0], 400)
        self.assertEqual(self.pedir("/api/revision/lote/deshacer", {"ids": ["a"]})[0], 400)

    def test_la_bandeja_y_siguiendo(self):
        self.alta("sin-fecha")
        self.alta("seguida", limite=4, revision="siguiendo")
        self.assertEqual(self.pedir("/api/bandeja?vivas=0&con_plazo=1")[1]["total"], 1)
        self.assertEqual(self.pedir("/api/bandeja?vivas=0")[1]["total"], 2)
        d = self.pedir("/api/siguiendo")[1]
        self.assertEqual((len(d["en_plazo"]), len(d["vencidas"])), (1, 0))


if __name__ == "__main__":
    unittest.main()
