"""Los bloques nuevos de la Analítica y la comparación con el año anterior.

Lo que se protege:

- La cuota de mercado: las cinco primeras y «Otras» suman el total de cada año, y cada
  empresa es la misma en todos los años (el color va con la empresa, no con su puesto).
- La comparación mide la MISMA ventana de días del año anterior, no el año entero.
- El enlace de consulta previa a licitación solo junta lo seguro: mismo NIF y mismo
  expediente sin mayúsculas ni espacios, con la licitación después, y entra por su índice.
- El calendario de renovaciones cuenta expedientes, no anuncios.
- El Resumen dice cuántos hubo en el mismo periodo un año antes.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from radar import consultas, db
from radar.model import Licitacion

HOY = date.today()


def hace(dias: int) -> str:
    return (HOY - timedelta(days=dias)).isoformat()


class Base(unittest.TestCase):
    def setUp(self):
        consultas._MEMO.clear()
        self.addCleanup(consultas._MEMO.clear)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.con = db.conectar(Path(self.dir.name) / "t.db")
        self.addCleanup(self.con.close)

    def alta(self, ide, *, perfil="p", grupo=None, **campos) -> int:
        base = dict(fuente="prueba", id_externo=ide, objeto=f"Objeto {ide}", organo="Órgano",
                    estado="adjudicada", fecha_publicacion=hace(100), clave_grupo=grupo or f"g-{ide}")
        base.update(campos)
        db.guardar(self.con, Licitacion(**base))
        lic_id = self.con.execute(
            "SELECT id FROM licitaciones WHERE id_externo = ?", (ide,)).fetchone()[0]
        if perfil:
            self.con.execute(
                "INSERT INTO matches (licitacion_id, perfil, puntuacion, motivo, creado_en)"
                " VALUES (?, ?, 3.0, 'm', ?)", (lic_id, perfil, db.ahora()))
        self.con.commit()
        return lic_id


class TestCuota(Base):
    def test_las_cinco_y_otras_suman_el_total_y_no_cambian_de_un_anio_a_otro(self):
        # Siete empresas en dos años; la A gana más en total aunque en 2025 gane poco.
        # Siempre los dos últimos años, que son los que comparan la variación.
        antes, ahora = str(HOY.year - 1), str(HOY.year)
        reparto = {antes: {"A": 4, "B": 1, "C": 1, "D": 1, "E": 1, "F": 1, "G": 1},
                   ahora: {"A": 1, "B": 3, "C": 2, "D": 1, "E": 1, "F": 2, "G": 0}}
        n = 0
        for anio, empresas in reparto.items():
            for empresa, veces in empresas.items():
                for _ in range(veces):
                    n += 1
                    self.alta(f"x{n}", adjudicatario=f"Empresa {empresa} SL",
                              fecha_adjudicacion=f"{anio}-01-02", fecha_publicacion=f"{anio}-01-01")
        c = consultas._bloque_cuota(self.con, consultas.Ambito())
        self.assertEqual(c["anios"][-2:], [antes, ahora])
        self.assertEqual(len(c["empresas"]), 5)
        self.assertEqual(c["empresas"][0]["empresa"], "Empresa A SL")
        for i in (len(c["anios"]) - 2, len(c["anios"]) - 1):
            suma = sum(e["por_anio"][i]["expedientes"] for e in c["empresas"])
            suma += c["otros"][i]["expedientes"]
            self.assertEqual(suma, c["totales"][i]["expedientes"])
            self.assertAlmostEqual(
                sum(e["por_anio"][i]["cuota"] for e in c["empresas"]) + c["otros"][i]["cuota"],
                100.0, delta=0.5)
        # Entre los dos últimos años: la A pasa de 4 de 10 a 1 de 10.
        self.assertEqual(c["empresas"][0]["variacion"], -30.0)

    def test_un_expediente_cuenta_una_vez_con_su_ultima_adjudicacion(self):
        self.alta("lote-1", grupo="exp", adjudicatario="Primera SL", fecha_adjudicacion="2025-01-01")
        self.alta("lote-2", grupo="exp", adjudicatario="Segunda SL", fecha_adjudicacion="2025-02-01")
        c = consultas._bloque_cuota(self.con, consultas.Ambito())
        self.assertEqual(c["empresas_distintas"], 1)
        self.assertEqual(c["empresas"][0]["empresa"], "Segunda SL")


class TestComparacion(Base):
    def test_misma_ventana_de_dias_del_anio_anterior(self):
        anterior = HOY.year - 1
        dia = min(HOY.day, 28)
        dentro = date(anterior, HOY.month, dia)
        despues = dentro + timedelta(days=1)
        self.alta("antes-dentro", fecha_publicacion=f"{anterior}-01-01")
        self.alta("antes-justo", fecha_publicacion=dentro.isoformat())
        self.alta("antes-fuera", fecha_publicacion=despues.isoformat())
        self.alta("este-anio", fecha_publicacion=f"{HOY.year}-01-02")
        c = consultas._comparacion(self.con, consultas.Ambito(), HOY)
        self.assertEqual((c["anio"], c["desde"]), (anterior, f"{anterior}-01-01"))
        self.assertEqual(c["expedientes"], 2)

    def test_solo_con_lo_que_va_de_anio(self):
        self.alta("uno", fecha_publicacion=f"{HOY.year}-01-02")
        con_anio = consultas.analitica(self.con, desde=f"{HOY.year}-01")
        self.assertIsNotNone(con_anio["comparacion"])
        consultas._MEMO.clear()
        self.assertIsNone(consultas.analitica(self.con, desde="2024-01")["comparacion"])

    def test_el_rango_por_dias_no_rompe_el_de_meses(self):
        self.alta("marzo", fecha_publicacion="2025-03-20")
        base, p = consultas._expedientes(None, "2025-03", "2025-03")
        self.assertEqual(self.con.execute(f"SELECT COUNT(*) FROM ({base})", p).fetchone()[0], 1)
        base, p = consultas._expedientes(None, "2025-03-01", "2025-03-19")
        self.assertEqual(self.con.execute(f"SELECT COUNT(*) FROM ({base})", p).fetchone()[0], 0)


class TestEstacionalidad(Base):
    def test_los_que_mas_publican_mes_a_mes(self):
        for i, mes in enumerate(("2024-03-01", "2025-03-01", "2025-07-01")):
            self.alta(f"a{i}", organo="Mucho", fecha_publicacion=mes)
        self.alta("b", organo="Poco", fecha_publicacion="2025-12-01")
        e = consultas._bloque_estacionalidad(self.con, consultas.Ambito(), None, None)
        self.assertEqual([o["organo"] for o in e["organos"]], ["Mucho", "Poco"])
        self.assertEqual(e["organos"][0]["meses"][2], 2)   # marzo, sumando años
        self.assertEqual(e["organos"][0]["meses"][6], 1)
        self.assertEqual(e["maximo"], 2)


class TestRenovacionesPorMes(Base):
    def test_doce_meses_por_expediente_con_sus_incumbentes(self):
        fin = (HOY.replace(day=1) + timedelta(days=40)).replace(day=15)
        self.alta("a1", grupo="exp", adjudicatario="Incumbente SA", fecha_fin_prevista=fin.isoformat())
        self.alta("a2", grupo="exp", adjudicatario="Incumbente SA", fecha_fin_prevista=fin.isoformat())
        self.alta("b", adjudicatario="Otra SL", fecha_fin_prevista=fin.isoformat())
        meses = consultas.vencimientos_por_mes(self.con)
        self.assertEqual(len(meses), 12)
        self.assertEqual(meses[0]["mes"], HOY.strftime("%Y-%m"))
        mes = next(m for m in meses if m["mes"] == fin.strftime("%Y-%m"))
        self.assertEqual(mes["contratos"], 2)
        self.assertEqual({i["empresa"] for i in mes["incumbentes"]}, {"Incumbente SA", "Otra SL"})


class TestConsultas(Base):
    def setUp(self):
        super().setUp()
        db.crear_indices_diferidos(self.con)

    def consulta(self, ide, **campos):
        return self.alta(ide, fuente="placsp:consultas_previas", estado="previo", **campos)

    def test_enlaza_lo_seguro_y_nada_mas(self):
        self.consulta("c1", nif_organo="Q1", expediente="Exp 2025/7", fecha_publicacion=hace(200),
                      perfil=None)
        self.alta("l1", fuente="placsp:licitaciones", nif_organo="Q1", expediente="EXP2025/7",
                  fecha_publicacion=hace(100), perfil=None)
        # Mismo expediente, otro NIF: no es la misma.
        self.consulta("c2", nif_organo="Q2", expediente="X-1", fecha_publicacion=hace(200),
                      perfil=None)
        self.alta("l2", fuente="placsp:licitaciones", nif_organo="Q9", expediente="X-1",
                  fecha_publicacion=hace(100), perfil=None)
        # La licitación antes de la consulta tampoco.
        self.consulta("c3", nif_organo="Q3", expediente="Y", fecha_publicacion=hace(50), perfil=None)
        self.alta("l3", fuente="placsp:licitaciones", nif_organo="Q3", expediente="Y",
                  fecha_publicacion=hace(300), perfil=None)
        c = consultas._bloque_consultas(self.con, consultas.Ambito())
        self.assertEqual((c["consultas"], c["enlazadas"]), (3, 1))
        self.assertEqual(c["mediana_dias"], 100)

    def test_las_abiertas_del_ambito_sin_pliego(self):
        abierta = self.consulta("abierta", nif_organo="Q1", expediente="A",
                                fecha_publicacion=hace(10), fecha_limite_presentacion=hace(-10))
        self.consulta("ya-licitada", nif_organo="Q1", expediente="B",
                      fecha_publicacion=hace(10), fecha_limite_presentacion=hace(-10))
        self.alta("su-pliego", fuente="placsp:licitaciones", nif_organo="Q1", expediente="b",
                  fecha_publicacion=hace(2), perfil=None)
        c = consultas._bloque_consultas(self.con, consultas.Ambito())
        self.assertEqual([it["id"] for it in c["abiertas"]], [abierta])
        self.assertEqual(c["del_ambito"], 2)

    def test_sin_el_indice_no_se_intenta_y_lo_dice(self):
        """Lo crea la búsqueda; abrir la base no puede tardar 18 s (ver INDICES_DIFERIDOS)."""
        self.con.execute(f"DROP INDEX {db.INDICE_CONSULTAS}")
        self.assertEqual(consultas._bloque_consultas(self.con, consultas.Ambito()),
                         {"preparando": True})
        otra = db.conectar(Path(self.dir.name) / "t.db")
        self.addCleanup(otra.close)
        self.assertFalse(db.hay_indice(otra, db.INDICE_CONSULTAS), "conectar no lo crea")

    def test_el_indice_esta_y_se_usa(self):
        indices = {f[0] for f in self.con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'")}
        self.assertIn("idx_lic_nif_exp", indices)
        plan = " ".join(str(tuple(f)) for f in self.con.execute(
            "EXPLAIN QUERY PLAN SELECT 1 FROM licitaciones c JOIN licitaciones l"
            f" ON l.nif_organo = c.nif_organo"
            f" AND {consultas.EXPEDIENTE_NORMALIZADO.format(t='l')}"
            f" = {consultas.EXPEDIENTE_NORMALIZADO.format(t='c')}"
            " WHERE c.fuente = 'x'"))
        self.assertIn("idx_lic_nif_exp", plan)


class TestResumenUnAnioAntes(Base):
    def test_cuenta_el_mismo_periodo_un_anio_antes(self):
        hace_un_anio = (HOY - timedelta(days=365 + 2)).isoformat()
        self.alta("de-hace-un-anio", fecha_publicacion=hace_un_anio)
        self.alta("de-esta-semana", fecha_publicacion=hace(1))
        r = consultas.resumen_novedades(self.con, "semana")
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["anterior"]["total"], 1)
        self.assertNotIn("anterior", consultas.resumen_novedades(self.con, "busqueda"))


if __name__ == "__main__":
    unittest.main()
