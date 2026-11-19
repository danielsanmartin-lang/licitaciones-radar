"""Quién repite: cada contrato emparejado con su renovación, y lo que se cuenta con eso.

Lo emparejado alimenta tres sitios —«¿Cambia de proveedor?» en la ficha de organismo,
«Clientes que retiene y que pierde» en la de competidor y «¿Se puede desbancar al
incumbente?» en la Analítica—, así que lo que se protege es el emparejamiento:

- mismo órgano, objeto parecido y al menos tres meses después; nada de emparejar un
  software con una formación solo porque el órgano publicó una cosa después de la otra
  (lo que hacía el primer intento, medido sobre la base real);
- cada contrato y cada renovación una sola vez, el más parecido primero;
- con todos los perfiles, no se cruzan perfiles distintos;
- una renovación sin adjudicar es «en marcha», no un cambio.

Y los otros bloques nuevos de las fichas: «Dónde te ha ganado», «Rivales y socios»,
«Precio y tamaño» y «Cómo compra».
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from radar import consultas, db
from radar.model import Licitacion

ORGANO = "Ayuntamiento de Ávila"


def dia(desplazamiento: int) -> str:
    return (date.today() + timedelta(days=desplazamiento)).isoformat()


class Base(unittest.TestCase):
    def setUp(self):
        consultas._MEMO_FICHAS.clear()
        consultas._MEMO.clear()
        self.addCleanup(consultas._MEMO_FICHAS.clear)
        self.addCleanup(consultas._MEMO.clear)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.con = db.conectar(Path(self.dir.name) / "t.db")
        self.addCleanup(self.con.close)

    def alta(self, ide, objeto, *, publicada, ganador=None, perfil="p", organo=ORGANO,
             estado=None, **extra) -> int:
        db.guardar(self.con, Licitacion(
            fuente=extra.pop("fuente", "prueba"), id_externo=ide, objeto=objeto,
            organo=organo, fecha_publicacion=dia(publicada) + "T10:00:00",
            estado=estado or ("adjudicada" if ganador else "publicada"),
            adjudicatario=ganador, clave_grupo=extra.pop("grupo", f"g-{ide}"),
            fecha_adjudicacion=dia(publicada + 60) if ganador else None, **extra,
        ))
        lic_id = self.con.execute(
            "SELECT id FROM licitaciones WHERE id_externo = ?", (ide,)).fetchone()[0]
        for p in ([perfil] if isinstance(perfil, str) else perfil or []):
            self.con.execute(
                """INSERT INTO matches (licitacion_id, perfil, puntuacion, motivo, creado_en)
                   VALUES (?, ?, 3.0, 'prueba', ?)""", (lic_id, p, db.ahora()))
        self.con.commit()
        return lic_id

    def pares(self, **ambito):
        consultas._MEMO_FICHAS.clear()
        return consultas._sucesiones(self.con, consultas.Ambito.de(**ambito))


class TestEmparejamiento(Base):
    def test_empareja_el_contrato_con_su_renovacion_parecida(self):
        self.alta("2024", "Servicio de concienciación en ciberseguridad para empleados",
                  publicada=-700, ganador="ACME SEGURIDAD, S.L.")
        self.alta("software", "Suministro de licencias de antivirus", publicada=-600,
                  ganador="Otra SA")
        self.alta("2025", "Servicio de concienciación en ciberseguridad del personal",
                  publicada=-300, ganador="Acme Seguridad SL")
        pares = self.pares()
        self.assertEqual(len(pares), 1)
        p = pares[0]
        self.assertEqual((p["previo"]["objeto"][:30], p["siguiente"]["objeto"][:30]),
                         ("Servicio de concienciación en ", "Servicio de concienciación en "))
        self.assertTrue(p["repite"], "la misma empresa con dos razones sociales")

    def test_no_empareja_lo_que_no_se_parece_ni_lo_demasiado_cercano(self):
        self.alta("a", "Formación en ciberseguridad", publicada=-500, ganador="Acme SL")
        self.alta("b", "Mantenimiento de servidores del CPD", publicada=-200, ganador="Beta SL")
        self.alta("c", "Formación en ciberseguridad avanzada", publicada=-470, ganador="Gamma SL")
        self.assertEqual(self.pares(), [], "c sale a los 30 días: no es una renovación")

    def test_otro_organo_no_es_renovacion(self):
        self.alta("a", "Formación en ciberseguridad", publicada=-500, ganador="Acme SL")
        self.alta("b", "Formación en ciberseguridad", publicada=-100, ganador="Beta SL",
                  organo="Diputación de Ávila")
        self.assertEqual(self.pares(), [])

    def test_cada_contrato_y_cada_renovacion_una_sola_vez(self):
        self.alta("a", "Formación en ciberseguridad", publicada=-900, ganador="Acme SL")
        self.alta("b", "Formación en ciberseguridad", publicada=-600, ganador="Beta SL")
        self.alta("c", "Formación en ciberseguridad", publicada=-300, ganador="Beta SL")
        pares = self.pares()
        self.assertEqual(len(pares), 2)
        self.assertEqual(len({p["siguiente"]["id"] for p in pares}), 2)
        self.assertEqual(len({p["previo"]["id"] for p in pares}), 2)
        # El más parecido y, a igualdad, el más cercano: a→b y b→c, no a→c.
        self.assertEqual(sorted((p["previo"]["fecha"], p["siguiente"]["fecha"]) for p in pares),
                         [(dia(-900), dia(-600)), (dia(-600), dia(-300))])

    def test_con_todos_los_perfiles_no_cruza_perfiles(self):
        self.alta("a", "Plataforma de formación online", publicada=-600, ganador="Acme SL",
                  perfil="concienciación")
        self.alta("b", "Plataforma de formación online", publicada=-200, ganador="Beta SL",
                  perfil="correo")
        self.assertEqual(self.pares(), [])
        self.assertEqual(len(self.pares(perfil="concienciación")), 0)

    def test_la_renovacion_sin_adjudicar_esta_en_marcha(self):
        self.alta("a", "Formación en ciberseguridad", publicada=-500, ganador="Acme SL")
        self.alta("b", "Formación en ciberseguridad", publicada=-10)
        p = self.pares()[0]
        self.assertIsNone(p["repite"])
        self.assertEqual(p["siguiente"]["empresas"], [])


class TestLoQueSeCuenta(Base):
    def setUp(self):
        super().setUp()
        self.alta("a1", "Formación en ciberseguridad", publicada=-900, ganador="Acme SL")
        self.alta("a2", "Formación en ciberseguridad", publicada=-500, ganador="Acme SL")
        self.alta("b1", "Simulación de phishing", publicada=-800, ganador="Acme SL",
                  organo="Diputación")
        self.alta("b2", "Simulación de phishing", publicada=-400, ganador="Beta SL",
                  organo="Diputación")
        self.alta("c1", "Correo seguro antispam", publicada=-700, ganador="Beta SL",
                  organo="Universidad")
        self.alta("c2", "Correo seguro antispam", publicada=-300, ganador="Acme SL",
                  organo="Universidad")
        self.alta("a3", "Formación en ciberseguridad", publicada=-20)

    def test_retencion_de_una_empresa(self):
        r = consultas._retencion_de(self.pares(), "acme")
        self.assertEqual((r["resueltos"], r["retenidos"]), (2, 1))
        self.assertEqual([p["organo"] for p in r["perdidos"]], ["Diputación"])
        self.assertEqual([p["organo"] for p in r["ganados_a_otros"]], ["Universidad"])
        self.assertEqual([p["organo"] for p in r["en_marcha"]], [ORGANO])

    def test_cambios_de_proveedor_de_un_organo(self):
        c = consultas._cambios_de_proveedor(self.pares(), "Diputación")
        self.assertEqual((c["resueltos"], c["repite"]), (1, 0))

    def test_incumbentes_en_la_analitica(self):
        d = consultas.analitica(self.con)["incumbentes"]
        self.assertEqual((d["renovaciones"], d["repite"], d["en_marcha"]), (3, 1, 1))
        self.assertFalse(d["suficiente"], f"hacen falta {consultas.MINIMO_SUCESIONES_ANALITICA}")
        acme = next(x for x in d["incumbentes"] if x["empresa"] == "Acme SL")
        self.assertEqual((acme["contratos"], acme["retenidos"]), (2, 1))
        self.assertEqual({x["organo"] for x in d["organos_que_cambian"]},
                         {"Diputación", "Universidad"})

    def test_el_periodo_es_el_de_la_renovacion(self):
        desde = dia(-350)[:7]
        d = consultas.bloque_incumbentes(self.con, consultas.Ambito(), desde, None)
        self.assertEqual(d["renovaciones"], 1, "solo c2 se publicó dentro del periodo")

    def test_las_fichas_lo_llevan(self):
        f = consultas.ficha_competidor(self.con, "ACME, S.L.")
        self.assertEqual((f["retencion"]["resueltos"], f["retencion"]["retenidos"]), (2, 1))
        o = consultas.ficha_organismo(self.con, "Diputación")
        self.assertEqual((o["proveedor"]["resueltos"], o["proveedor"]["repite"]), (1, 0))


class TestOtrosBloquesDeLasFichas(Base):
    def test_donde_te_ha_ganado(self):
        presentada = self.alta("p", "Concienciación", publicada=-300, ganador="Acme SL")
        db.fijar_revision(self.con, presentada, estado="presentada")
        otra = self.alta("q", "Phishing", publicada=-250, ganador="Beta SL",
                         organo="Diputación de Ávila")
        db.fijar_revision(self.con, otra, estado="presentada")
        # Acme ya tenía contrato en el órgano antes de este pliego descartado.
        atado = self.alta("r", "Formación", publicada=-30)
        db.fijar_revision(self.con, atado, estado="descartado", motivo_descarte="incumbente atado")
        self.con.commit()
        d = consultas.ficha_competidor(self.con, "Acme SL")["donde_te_gano"]
        self.assertEqual((d["presentadas_adjudicadas"], d["ganadas_por_ella"]), (2, 1))
        self.assertEqual([x["id"] for x in d["le_gano"]], [presentada])
        self.assertEqual([x["id"] for x in d["incumbente_atado"]], [atado])
        self.assertEqual(consultas.ficha_competidor(self.con, "Beta SL")["donde_te_gano"]
                         ["incumbente_atado"], [], "Beta no tenía nada antes en el órgano")

    def test_rivales_y_socios(self):
        self.alta("a", "Uno", publicada=-300, ganador="Acme SL")
        self.alta("b", "Dos", publicada=-200, ganador="Beta SL")
        self.alta("c", "Tres", publicada=-100, ganador="Gamma SL", organo="Otro órgano")
        self.alta("d", "Cuatro", publicada=-90, ganador="UTE ACME SL - DELTA SA",
                  organo="Otro órgano")
        r = consultas.ficha_competidor(self.con, "Acme SL")["rivales"]
        self.assertEqual([x["empresa"] for x in r["rivales"]], ["Beta SL"])
        self.assertEqual([x["empresa"] for x in r["socios"]], ["UTE ACME SL - DELTA SA"])
        self.assertTrue(consultas._es_ute("U.T.E. Acme, S.L. y Delta, S.A."))
        self.assertTrue(consultas._es_ute("Unión Temporal de Empresas Acme"))
        self.assertFalse(consultas._es_ute("Computer Solutions SL"), "«ute» dentro de una palabra")

    def test_precio_frente_al_mercado(self):
        for i, (imp, quien) in enumerate([(100_000, "Acme SL"), (200_000, "Acme SL"),
                                          (300_000, "Acme SL"), (10_000, "Beta SL")]):
            self.alta(f"x{i}", f"Objeto {i}", publicada=-300 + i, ganador=quien,
                      importe_adjudicacion=float(imp), procedimiento="Abierto")
        p = consultas.ficha_competidor(self.con, "Acme SL")["precio"]
        self.assertEqual(p["empresa"]["importe_mediano"], 200_000)
        self.assertEqual(p["mercado"]["importe_mediano"], 150_000)
        self.assertEqual(p["empresa"]["procedimientos"],
                         [{"procedimiento": "Abierto", "expedientes": 3, "pct": 100}])

    def test_como_compra(self):
        self.alta("lotes", "Con lotes", publicada=-300, ganador="Acme SL", duracion_meses=12,
                  lote_num="1", fuente="catalunya")
        self.alta("sin", "Sin lotes", publicada=-200, ganador="Acme SL", duracion_meses=24,
                  fuente="placsp:licitaciones")
        self.alta("ted", "De TED", publicada=-150, ganador="Acme SL", duracion_meses=36,
                  fuente="ted")
        consulta = self.alta("cpm", "Consulta preliminar", publicada=-5, estado="previo",
                             fuente="placsp:consultas_previas")
        c = consultas.ficha_organismo(self.con, ORGANO)["como_compra"]
        self.assertEqual((c["duracion_mediana"], c["duraciones"]), (24, 3))
        self.assertEqual((c["con_lotes"], c["lotes_sabidos"]), (1, 2), "TED no cuenta")
        self.assertEqual([x["id"] for x in c["consultas_abiertas"]], [consulta])


if __name__ == "__main__":
    unittest.main()
