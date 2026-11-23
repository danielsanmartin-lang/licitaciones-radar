"""«Más filtros» de la Bandeja: organismo, empresa, CPV, procedimiento, fechas, importe
máximo y fuente.

Lo que se protege:

- Cada filtro deja exactamente lo que dice, con los casos que en la base real engañan:
  un órgano con tildes y mayúsculas distintas según el anuncio, una empresa con varias
  razones sociales o ganando lotes junto a otras, «72» que no puede casar con «172…»,
  el procedimiento en catalán, y un expediente de 2024 adjudicado este año, que por
  fecha de publicación sigue siendo de 2024.
- El número de la cabecera (`contar`) y la lista (`bandeja`) cuentan lo mismo con
  cualquier combinación, y el CSV baja lo que se ve.
- Lo mal escrito es un 400, no una lista vacía que parece una respuesta.
- Las opciones de los desplegables cuentan expedientes y cuadran con lo que trae la lista
  al elegirlas.
"""

from __future__ import annotations

import itertools
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from radar import consultas, db, server
from radar.model import Licitacion

PERFIL = "p"


class Base(unittest.TestCase):
    def setUp(self):
        for memo in (consultas._MEMO, consultas._MEMO_FICHAS):
            memo.clear()
            self.addCleanup(memo.clear)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.bd = Path(self.dir.name) / "t.db"
        self.con = db.conectar(self.bd)
        self.addCleanup(self.con.close)

    def alta(self, ide, *, grupo=None, perfil=PERFIL, revision=None, **campos) -> int:
        base = dict(fuente="prueba", id_externo=ide, objeto=f"Objeto {ide}",
                    organo="Órgano", estado="publicada", fecha_publicacion="2025-03-10",
                    clave_grupo=grupo or f"g-{ide}")
        base.update(campos)
        db.guardar(self.con, Licitacion(**base))
        lic_id = self.con.execute(
            "SELECT id FROM licitaciones WHERE id_externo = ? AND fuente = ?",
            (ide, base["fuente"])).fetchone()[0]
        if perfil:
            self.con.execute(
                "INSERT INTO matches (licitacion_id, perfil, puntuacion, motivo, creado_en)"
                " VALUES (?, ?, 3.0, 'm', ?)", (lic_id, perfil, db.ahora()))
        if revision:
            db.fijar_revision(self.con, lic_id, estado=revision,
                              motivo_descarte="otro" if revision == "descartado" else None)
        self.con.commit()
        return lic_id

    def objetos(self, **filtros):
        """Los objetos de la lista, sin «solo abiertas»: aquí casi todo está cerrado."""
        filtros.setdefault("solo_vivas", False)
        r = consultas.bandeja(self.con, **filtros)
        self.assertEqual(r["total"], consultas.contar(self.con, **filtros), filtros)
        return sorted(it["objeto"] for it in r["items"])


class TestCadaFiltro(Base):
    def test_organismo_sin_tildes_ni_mayusculas_y_con_sus_firmantes(self):
        self.alta("a", objeto="A", organo="Diputación Foral de Bizkaia - Hacienda")
        self.alta("b", objeto="B", organo="DIPUTACION FORAL DE BIZKAIA")
        self.alta("c", objeto="C", organo="Ayuntamiento de Bilbao")
        self.assertEqual(self.objetos(organo="diputacion foral"), ["A", "B"])
        self.assertEqual(self.objetos(organo="  Bilbao "), ["C"])
        self.assertEqual(self.objetos(organo="nadie"), [])

    def test_empresa_con_sus_razones_sociales_y_sus_lotes_compartidos(self):
        self.alta("a", objeto="A", adjudicatario="Acme Seguridad S.L.", estado="adjudicada")
        self.alta("b", objeto="B", adjudicatario="ACME SEGURIDAD SL", estado="adjudicada")
        self.alta("c", objeto="C", adjudicatario="Beta SA · ACME SEGURIDAD, S.L.",
                  estado="adjudicada")
        self.alta("d", objeto="D", adjudicatario="Beta SA", estado="adjudicada")
        self.alta("e", objeto="E")
        self.assertEqual(self.objetos(empresa="Acme Seguridad S.L."), ["A", "B", "C"])
        self.assertEqual(self.objetos(empresa="acme"), ["A", "B", "C"])
        self.assertEqual(self.objetos(empresa="Beta"), ["C", "D"])

    def test_cpv_por_division_o_por_codigo_sin_confundir_prefijos(self):
        self.alta("a", objeto="A", cpv=["72000000", "48000000"])
        self.alta("b", objeto="B", cpv=["79417000"])
        self.alta("c", objeto="C", cpv=["17200000"])        # «72» dentro, no delante
        self.alta("d", objeto="D", cpv=[])
        self.assertEqual(self.objetos(cpv="72"), ["A"])
        self.assertEqual(self.objetos(cpv="48"), ["A"])
        self.assertEqual(self.objetos(cpv="79417000"), ["B"])

    def test_procedimiento_en_castellano_junta_el_catalan(self):
        self.alta("a", objeto="A", procedimiento="Abierto")
        self.alta("b", objeto="B", procedimiento="Obert")
        self.alta("c", objeto="C", procedimiento="Restringido")
        self.assertEqual(self.objetos(procedimiento="Abierto"), ["A", "B"])
        self.assertEqual(self.objetos(procedimiento="Diálogo competitivo"), [])

    def test_importe_maximo_y_minimo_juntos(self):
        for n, importe in enumerate((10_000, 60_000, 200_000)):
            self.alta(f"i{n}", objeto=f"I{n}", importe_sin_iva=importe)
        self.assertEqual(self.objetos(importe_max=60_000), ["I0", "I1"])
        self.assertEqual(self.objetos(importe_min=50_000, importe_max=100_000), ["I1"])

    def test_fuente(self):
        self.alta("a", objeto="A", fuente="ted")
        self.alta("b", objeto="B", fuente="placsp:agregadas")
        self.assertEqual(self.objetos(fuente="ted"), ["A"])
        self.assertEqual(self.objetos(fuente="placsp:agregadas"), ["B"])

    def test_las_fechas_son_las_de_la_primera_publicacion(self):
        """Un pliego de 2024 adjudicado en 2026 sigue siendo de 2024: es la fecha de la
        píldora «publicada» y la de la Analítica."""
        self.alta("viejo", objeto="Viejo", grupo="g1", fecha_publicacion="2024-05-01")
        self.alta("viejo-adj", objeto="Viejo", grupo="g1", fecha_publicacion="2026-02-01",
                  estado="adjudicada")
        self.alta("nuevo", objeto="Nuevo", fecha_publicacion="2026-01-15")
        self.assertEqual(self.objetos(publicada_desde="2026-01-01"), ["Nuevo"])
        self.assertEqual(self.objetos(publicada_hasta="2024-12-31"), ["Viejo"])
        self.assertEqual(self.objetos(publicada_desde="2024-05-01",
                                      publicada_hasta="2024-05-01"), ["Viejo"])


class TestJuntos(Base):
    def setUp(self):
        super().setUp()
        organos = ["Diputación Foral", "Ayuntamiento de Bilbao", "Consejería de Hacienda"]
        empresas = [None, "Acme S.L.", "ACME SL", "Beta SA · Acme S.L.", "Gamma"]
        procedimientos = ["Abierto", "Obert", "Restringido", None]
        n = 0
        for o, e, p, cpv, imp, mes, fuente in itertools.product(
                organos, empresas, procedimientos, (["72000000"], ["79417000"], []),
                (20_000, 400_000), ("2024-06", "2026-03"), ("ted", "catalunya")):
            n += 1
            if n % 3:
                continue
            self.alta(f"x{n}", objeto=f"X{n}", organo=o, adjudicatario=e, procedimiento=p,
                      cpv=cpv, importe_sin_iva=imp, fecha_publicacion=f"{mes}-10",
                      fuente=fuente, estado="adjudicada" if e else "publicada",
                      revision="descartado" if n % 7 == 0 else None)

    def test_la_cabecera_y_la_lista_cuentan_lo_mismo_con_cualquier_combinacion(self):
        valores = dict(organo=[None, "diputación"], empresa=[None, "acme"],
                       cpv=[None, "72"], procedimiento=[None, "Abierto"],
                       importe_max=[None, 100_000], fuente=[None, "ted"],
                       publicada_desde=[None, "2025-01-01"])
        claves = list(valores)
        algun_resultado = 0
        for combinacion in itertools.product(*valores.values()):
            filtros = {k: v for k, v in zip(claves, combinacion) if v is not None}
            algun_resultado += bool(self.objetos(**filtros))
        self.assertGreater(algun_resultado, 20, "la base de prueba no ejercita los filtros")

    def test_el_csv_baja_lo_que_se_ve(self):
        filtros = dict(solo_vivas=False, empresa="acme", procedimiento="Abierto",
                       publicada_desde="2026-01-01")
        _, filas = consultas.para_csv(self.con, **filtros)
        self.assertEqual(len(filas), consultas.contar(self.con, **filtros))
        self.assertGreater(len(filas), 0)


class TestOpciones(Base):
    def test_cuentan_expedientes_y_juntan_variantes(self):
        self.alta("a1", grupo="g1", organo="Diputación Foral", adjudicatario="Acme S.L.",
                  procedimiento="Obert", cpv=["72000000"], fuente="ted", estado="adjudicada")
        self.alta("a2", grupo="g1", organo="DIPUTACIÓN FORAL", adjudicatario="ACME SL",
                  procedimiento="Abierto", cpv=["72100000"], fuente="ted", estado="adjudicada")
        self.alta("b", organo="Diputación Foral", adjudicatario="Beta SA · Acme S.L.",
                  procedimiento="Abierto", cpv=["79417000"], fuente="catalunya",
                  estado="adjudicada")
        self.alta("fuera", organo="Otro", procedimiento="Restringido", revision="descartado")
        o = consultas.opciones_bandeja(self.con)
        por = {k: {x["valor"]: x["expedientes"] for x in v} for k, v in o.items()}
        self.assertEqual(len(o["organos"]), 1, "las mayúsculas no hacen otro órgano")
        self.assertEqual(o["organos"][0]["expedientes"], 2)
        # Las razones sociales de Acme se juntan, con la variante más larga, y los lotes
        # compartidos se parten: Beta sale sola.
        self.assertEqual(por["empresas"], {"Acme S.L.": 2, "Beta SA": 1})
        self.assertEqual(por["procedimientos"], {"Abierto": 2})
        self.assertEqual(por["cpv"], {"72": 1, "79": 1, "79417000": 1})
        self.assertEqual(por["fuentes"], {"ted": 1, "catalunya": 1})
        self.assertNotIn("Otro", [x["valor"] for x in o["organos"]], "lo descartado no")

    def test_lo_que_ofrecen_los_desplegables_es_lo_que_trae_la_lista(self):
        for n, (proc, cpv, fuente) in enumerate(itertools.product(
                ("Abierto", "Obert", "Restringido", None),
                (["72000000"], ["80510000", "72500000"], ["79417000"], []),
                ("ted", "catalunya", "placsp:agregadas"))):
            self.alta(f"x{n}", procedimiento=proc, cpv=cpv, fuente=fuente,
                      grupo=f"g{n // 2}", revision="descartado" if n % 9 == 0 else None)
        o = consultas.opciones_bandeja(self.con)
        for campo, filtro in (("cpv", "cpv"), ("procedimientos", "procedimiento"),
                              ("fuentes", "fuente")):
            for op in o[campo]:
                self.assertEqual(
                    consultas.contar(self.con, solo_vivas=False, **{filtro: op["valor"]}),
                    op["expedientes"], (campo, op["valor"]))
        for campo, filtro in (("organos", "organo"), ("empresas", "empresa")):
            for op in o[campo]:
                self.assertGreaterEqual(
                    consultas.contar(self.con, solo_vivas=False, **{filtro: op["valor"]}),
                    op["expedientes"], (campo, op["valor"]))


class TestRuta(Base):
    def setUp(self):
        super().setUp()
        self.alta("a", objeto="A", organo="Diputación Foral", cpv=["72000000"])
        self.srv = server.arrancar(0, self.bd)
        hilo = threading.Thread(target=self.srv.serve_forever, daemon=True)
        hilo.start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def pedir(self, ruta, **params):
        url = self.base + ruta + ("?" + urllib.parse.urlencode(params) if params else "")
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as exc:
            cuerpo = exc.read()
            exc.close()
            return exc.code, cuerpo

    def test_la_lista_y_el_csv_aplican_los_filtros(self):
        codigo, cuerpo = self.pedir("/api/bandeja", vivas="0", organo="diputacion", cpv="72")
        self.assertEqual((codigo, json.loads(cuerpo)["total"]), (200, 1))
        codigo, cuerpo = self.pedir("/api/bandeja", vivas="0", organo="nadie")
        self.assertEqual(json.loads(cuerpo)["total"], 0)
        codigo, cuerpo = self.pedir("/api/export.csv", vivas="0", cpv="48")
        self.assertEqual(codigo, 200)
        self.assertEqual(len(cuerpo.decode("utf-8-sig").strip().splitlines()), 1, "solo cabecera")

    def test_lo_mal_escrito_es_un_400(self):
        for params in ({"publicada_desde": "2026-13-01"}, {"publicada_hasta": "ayer"},
                       {"cpv": "7"}, {"cpv": "72x"}, {"importe_max": "mucho"}):
            with self.subTest(**params):
                self.assertEqual(self.pedir("/api/bandeja", **params)[0], 400)
                self.assertEqual(self.pedir("/api/export.csv", **params)[0], 400)

    def test_opciones(self):
        codigo, cuerpo = self.pedir("/api/bandeja/opciones")
        d = json.loads(cuerpo)
        self.assertEqual(codigo, 200)
        self.assertEqual(d["organos"][0]["nombre"], "Diputación Foral")
        self.assertEqual(d["cpv"][0], {"valor": "72", "nombre": "72 · servicios de TI",
                                       "expedientes": 1})


if __name__ == "__main__":
    unittest.main()
