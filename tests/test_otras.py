"""«Otras licitaciones» y el ámbito por temática de la Analítica y los Adjudicatarios.

Lo que más importa de la pestaña es lo que NO enseña: nada que ya esté en la Bandeja.
Ni lo que casa con un perfil —tampoco por otro anuncio del mismo expediente— ni lo que
sigues aunque no case. Si una de las dos cosas falla, el mismo contrato sale en dos
sitios y nadie sabe en cuál trabajarlo.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from radar import categorias, consultas, db, matching
from radar.model import Licitacion


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.con = db.conectar(Path(self.dir.name) / "t.db")
        self.addCleanup(self.con.close)
        consultas._MEMO.clear()
        self.addCleanup(consultas._MEMO.clear)
        self.perfiles = [matching.Perfil(nombre="Concienciación",
                                         terminos_fuertes=["concienciacion"]).preparar()]

    def guardar(self, nombre: str, **kw) -> int:
        base = {"fuente": "placsp:licitaciones", "id_externo": nombre,
                "objeto": f"Obras {nombre}", "organo": "Ayuntamiento",
                "expediente": f"EXP/{nombre}", "estado": "publicada",
                "fecha_publicacion": "2026-09-01", "tipo_contrato": "Obras"}
        base.update(kw)
        db.guardar(self.con, Licitacion(**base))
        self.con.commit()
        return self.con.execute(
            "SELECT id FROM licitaciones WHERE id_externo = ?", (nombre,)).fetchone()[0]

    def evaluar(self):
        matching.reevaluar(self.con, self.perfiles, incremental=True)

    def ids(self, **kw) -> set[int]:
        kw.setdefault("solo_vivas", False)
        return {it["id"] for it in consultas.otras(self.con, **kw)["items"]}


class TestQueNoSaleLoDeLaBandeja(Base):
    def test_lo_que_casa_con_un_perfil_no_sale(self):
        casa = self.guardar("a", objeto="Campaña de concienciación")
        otra = self.guardar("b", objeto="Servicio de ciberseguridad")
        self.evaluar()
        self.assertEqual(self.ids(), {otra})
        self.assertNotIn(casa, self.ids())

    def test_ni_otro_anuncio_del_mismo_expediente(self):
        """La corrección de un pliego que casa no casa ella misma, pero es el mismo
        contrato: se excluye por expediente, no por ficha."""
        self.guardar("a", objeto="Campaña de concienciación", expediente="EXP/1")
        self.guardar("b", objeto="Corrección de errores", expediente="EXP/1")
        self.evaluar()
        self.assertEqual(self.ids(), set())

    def test_seguir_la_pasa_a_la_bandeja(self):
        lic = self.guardar("a", objeto="Servicio de ciberseguridad")
        self.evaluar()
        self.assertEqual(self.ids(), {lic})
        db.fijar_revision(self.con, lic, estado="siguiendo")
        self.con.commit()
        self.assertEqual(self.ids(), set())
        bandeja = consultas.bandeja(self.con, solo_vivas=False)
        self.assertEqual([it["id"] for it in bandeja["items"]], [lic])

    def test_lo_descartado_solo_sale_si_se_pide(self):
        lic = self.guardar("a")
        self.evaluar()
        db.fijar_revision(self.con, lic, estado="descartado", motivo_descarte="otro")
        self.con.commit()
        self.assertEqual(self.ids(), set())
        self.assertEqual(self.ids(estado_revision="descartado"), {lic})


class TestFiltros(Base):
    def setUp(self):
        super().setUp()
        self.ciber = self.guardar("ciber", objeto="Servicio de ciberseguridad",
                                  tipo_contrato="Servicios", importe_sin_iva=80_000)
        self.cloud = self.guardar("cloud", objeto="Alojamiento web de la sede",
                                  tipo_contrato="Serveis", importe_sin_iva=10_000)
        self.obra = self.guardar("obra", objeto="Reurbanización de la plaza",
                                 importe_sin_iva=500_000)
        self.evaluar()

    def test_por_tematica(self):
        self.assertEqual(self.ids(categorias_elegidas=["ciberseguridad"]), {self.ciber})
        self.assertEqual(self.ids(categorias_elegidas=["ciberseguridad", "cloud"]),
                         {self.ciber, self.cloud})

    def test_resto_es_lo_que_no_es_it(self):
        self.assertEqual(self.ids(categorias_elegidas=[categorias.RESTO]), {self.obra})
        self.assertEqual(self.ids(categorias_elegidas=[categorias.RESTO, "cloud"]),
                         {self.obra, self.cloud})

    def test_una_tematica_desconocida_no_filtra(self):
        self.assertEqual(self.ids(categorias_elegidas=["inventada"]),
                         {self.ciber, self.cloud, self.obra})

    def test_por_tipo_de_contrato_en_castellano_y_catalan(self):
        self.assertEqual(self.ids(tipo="servicios"), {self.ciber, self.cloud})
        self.assertEqual(self.ids(tipo="obras"), {self.obra})
        self.assertEqual(self.ids(tipo="otros"), set())

    def test_busqueda_e_importe(self):
        self.assertEqual(self.ids(busqueda="ciberseguridad"), {self.ciber})
        self.assertEqual(self.ids(importe_min=50_000), {self.ciber, self.obra})

    def test_solo_abiertas(self):
        self.guardar("cerrada", objeto="Servicio de ciberseguridad antiguo",
                     estado="adjudicada")
        self.evaluar()
        self.assertNotIn("cerrada",
                         {it["id_externo"] for it in
                          consultas.otras(self.con, solo_vivas=True)["items"]})

    def test_las_cifras_de_los_chips_ignoran_el_filtro_de_tematica(self):
        d = consultas.otras(self.con, categorias_elegidas=["cloud"], solo_vivas=True)
        self.assertEqual(d["total"], 1)
        self.assertEqual(d["por_categoria"],
                         {"ciberseguridad": 1, "cloud": 1, categorias.RESTO: 1})

    def test_con_el_historico_sin_busqueda_no_se_calculan_las_cifras(self):
        """Serían ocho segundos sobre la base real solo para poner números en botones."""
        self.assertIsNone(consultas.otras(self.con, solo_vivas=False)["por_categoria"])
        self.assertIsNotNone(
            consultas.otras(self.con, solo_vivas=False, busqueda="plaza")["por_categoria"])

    def test_cada_ficha_lleva_sus_tematicas_y_ningun_texto_interno(self):
        it = consultas.otras(self.con, categorias_elegidas=["ciberseguridad"],
                             solo_vivas=False)["items"][0]
        self.assertEqual(it["categorias"], ["ciberseguridad"])
        for columna in ("raw", "texto_busqueda", "texto_norm", "texto_reglas_norm"):
            self.assertNotIn(columna, it)

    def test_un_expediente_con_varios_anuncios_sale_una_vez(self):
        self.guardar("ciber-2", objeto="Servicio de ciberseguridad (corrección)",
                     expediente="EXP/ciber", fecha_publicacion="2026-09-05")
        self.evaluar()
        d = consultas.otras(self.con, categorias_elegidas=["ciberseguridad"],
                            solo_vivas=False)
        self.assertEqual(d["total"], 1)
        self.assertEqual(d["items"][0]["anuncios"], 2)

    def test_la_paginacion_no_repite(self):
        for n in range(5):
            self.guardar(f"p{n}", objeto=f"Servicio de ciberseguridad {n}")
        self.evaluar()
        vistos = []
        for offset in range(0, 6, 2):
            vistos += [it["id"] for it in consultas.otras(
                self.con, categorias_elegidas=["ciberseguridad"], solo_vivas=False,
                limite=2, offset=offset)["items"]]
        self.assertEqual(len(vistos), len(set(vistos)))
        self.assertEqual(len(vistos), 6)


class TestAmbito(Base):
    def setUp(self):
        super().setUp()
        self.casa = self.guardar("casa", objeto="Campaña de concienciación",
                                 adjudicatario="Empresa Uno, S.L.", importe_sin_iva=10_000)
        self.ciber = self.guardar("ciber", objeto="Servicio de ciberseguridad",
                                  adjudicatario="EMPRESA DOS SL", importe_sin_iva=20_000)
        self.ciber2 = self.guardar("ciber2", objeto="Oficina de ciberseguridad",
                                   adjudicatario="Empresa Dos, S.L.",
                                   importe_sin_iva=30_000)
        self.obra = self.guardar("obra", adjudicatario="Constructora")
        self.evaluar()

    def test_sin_ambito_la_analitica_es_la_de_los_perfiles(self):
        self.assertEqual(consultas.analitica(self.con)["generado_para"]["expedientes"], 1)

    def test_una_tematica_mira_todo_el_mercado(self):
        d = consultas.analitica(self.con, categoria="ciberseguridad")
        self.assertEqual(d["generado_para"]["expedientes"], 2)
        self.assertTrue(d["generado_para"]["mercado"])
        self.assertEqual(d["generado_para"]["ambito"], "Ciberseguridad")
        self.assertIsNone(d["cartera"], "la cartera es tu triaje, no el mercado")
        self.assertEqual(d["cpv"]["del_producto"], [])

    def test_toda_la_it_une_las_tematicas_sin_duplicar(self):
        self.guardar("doble", objeto="Ciberseguridad y alojamiento web")
        self.evaluar()
        d = consultas.analitica(self.con, categoria=categorias.TODA_LA_IT)
        self.assertEqual(d["generado_para"]["expedientes"], 3)

    def test_resto_no_se_puede_analizar(self):
        with self.assertRaises(ValueError):
            consultas.analitica(self.con, categoria=categorias.RESTO)

    def test_el_memo_distingue_el_ambito(self):
        perfiles = consultas.analitica(self.con)
        tema = consultas.analitica(self.con, categoria="ciberseguridad")
        self.assertNotEqual(perfiles["generado_para"]["expedientes"],
                            tema["generado_para"]["expedientes"])

    def test_el_memo_se_invalida_al_cambiar_las_reglas(self):
        consultas.analitica(self.con, categoria="ciberseguridad")
        self.con.execute("DELETE FROM categorias WHERE licitacion_id = ?", (self.ciber2,))
        db.escribir_preferencia(self.con, categorias.CLAVE_VERSION, "otra")
        self.con.commit()
        d = consultas.analitica(self.con, categoria="ciberseguridad")
        self.assertEqual(d["generado_para"]["expedientes"], 1)

    def test_quien_gana_agrupa_razones_sociales_y_cuenta_expedientes(self):
        d = consultas.analitica(self.con, categoria="ciberseguridad")["adjudicatarios"]
        self.assertEqual(d["expedientes_adjudicados"], 2)
        self.assertEqual(d["distintas"], 1)
        self.assertEqual(d["empresas"][0]["expedientes"], 2)
        self.assertEqual(d["empresas"][0]["importe"], 50_000)

    def test_el_ranking_de_la_pestana_respeta_el_ambito(self):
        self.assertEqual([e["contratos"] for e in consultas.competencia(self.con)], [1])
        tema = consultas.Ambito.de(categoria="ciberseguridad")
        ranking = consultas.competencia(self.con, ambito=tema)
        self.assertEqual(len(ranking), 1)
        self.assertEqual(ranking[0]["contratos"], 2)
        desglose = consultas.contratos_de(self.con, ranking[0]["empresa"], ambito=tema)
        self.assertEqual({c["id"] for c in desglose}, {self.ciber, self.ciber2})

    def test_la_entrada_por_tematica_va_por_el_indice(self):
        """Si la Analítica de una temática entrara por `licitaciones` en lugar de por
        `categorias`, recorrería las 700.000 fichas en cada bloque."""
        for clave in ("cloud", categorias.TODA_LA_IT):
            sub, params = consultas.Ambito.de(categoria=clave).fichas()
            plan = "\n".join(str(f[3]) for f in
                             self.con.execute("EXPLAIN QUERY PLAN " + sub, params))
            with self.subTest(clave=clave):
                self.assertIn("idx_cat_categoria", plan)

    def test_un_ambito_de_perfil_sigue_funcionando(self):
        d = consultas.analitica(self.con, perfil="Concienciación")
        self.assertEqual(d["generado_para"]["expedientes"], 1)
        self.assertFalse(d["generado_para"]["mercado"])


if __name__ == "__main__":
    unittest.main()
