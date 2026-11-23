"""El desglose: de una barra, una baldosa o una celda a los expedientes que cuenta.

Lo que se protege aquí es una sola promesa, la que hace que pulsar un gráfico sirva de
algo: **el número del gráfico y el de su lista son el mismo**. Si la columna de febrero
dice 11 y la lista enseña 12, ya no se puede creer ni a una ni a otra.

Por eso las pruebas no comprueban casos sueltos sino que recorren TODOS los elementos de
TODOS los gráficos desglosables sobre una base variada —varios años, tramos, comunidades,
contratos de más de 50 M€, lotes, procedimientos en catalán, empresas con dos razones
sociales, renovaciones, consultas previas, algo descartado— y, para cada uno, piden su
desglose y lo cuentan. Con un perfil, con todos, con una temática, con y sin rango.
"""

from __future__ import annotations

import random
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from radar import consultas, db, desglose
from radar.model import Licitacion

HOY = date.today()
ORGANOS = ["Ayuntamiento de Prueba", "Consejería de Hacienda", "Agencia de Ciberseguridad",
           "Diputación Foral", "Universidad Pública", "Ministerio de Pruebas"]
EMPRESAS = ["Acme Seguridad S.L.", "ACME SEGURIDAD SL", "Beta Formación S.A.",
            "Gamma Consultores", "Delta Ciber S.L.", "Epsilon Sistemas", "Zeta Redes S.A.",
            "Eta Software", "Theta Servicios"]
PROCEDIMIENTOS = ["Abierto", "Obert", "Abierto simplificado", "Restringido",
                  "Negociado sin publicidad", "Contrato menor", "Normas internas",
                  "Diálogo competitivo", "Licitación con negociación", "Concurso de proyectos"]
COMUNIDADES = ["Madrid", "Cataluña", "País Vasco", "Andalucía", None]
CPVS = ["72000000", "48000000-8", "79417000", "80510000-2", "30200000", "64200000"]
OBJETOS = ["Servicio de concienciación en ciberseguridad para el personal",
           "Simulación de phishing y formación del personal",
           "Protección del correo electrónico corporativo",
           "Licencias de antivirus para puestos de trabajo"]


def dia(desplazamiento: int) -> str:
    return (HOY + timedelta(days=desplazamiento)).isoformat()


class Base(unittest.TestCase):
    def setUp(self):
        for memo in (consultas._MEMO, consultas._MEMO_FICHAS, desglose._MEMO,
                     desglose._MEMO_RECORRIDOS):
            memo.clear()
            self.addCleanup(memo.clear)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.con = db.conectar(Path(self.dir.name) / "t.db")
        self.addCleanup(self.con.close)
        db.crear_indices_diferidos(self.con)

    def alta(self, ide, *, perfiles=("p",), categoria="ciberseguridad", **campos) -> int:
        base = dict(fuente="prueba", id_externo=ide, objeto=f"Objeto {ide}",
                    organo=ORGANOS[0], estado="publicada", fecha_publicacion=dia(-100))
        base.update(campos)
        db.guardar(self.con, Licitacion(**base))
        lic_id = self.con.execute(
            "SELECT id FROM licitaciones WHERE id_externo = ?", (ide,)).fetchone()[0]
        for perfil in perfiles:
            self.con.execute(
                "INSERT INTO matches (licitacion_id, perfil, puntuacion, motivo, creado_en)"
                " VALUES (?, ?, 3.0, 'm', ?)", (lic_id, perfil, db.ahora()))
        if categoria:
            self.con.execute("INSERT INTO categorias (licitacion_id, categoria) VALUES (?, ?)",
                             (lic_id, categoria))
        return lic_id

    def version(self, lic_id, estado, fecha, anterior=None):
        self.con.execute(
            "INSERT INTO licitaciones_versiones (licitacion_id, huella, estado,"
            " estado_anterior, detectado_en, fecha_cambio, snapshot)"
            " VALUES (?, ?, ?, ?, ?, ?, '{}')",
            (lic_id, f"{estado}-{fecha}-{lic_id}", estado, anterior, db.ahora(), fecha))

    def poblar(self):
        """Unos doscientos expedientes que tocan cada rama de cada bloque."""
        azar = random.Random(20261123)
        inicio = date(2024, 1, 1)
        dias_hasta_hoy = (HOY - inicio).days
        for n in range(220):
            pub = inicio + timedelta(days=azar.randrange(dias_hasta_hoy))
            grupo = f"g{n}"
            perfiles = azar.choice([("p",), ("q",), ("p", "q")])
            categoria = azar.choice(["ciberseguridad", "ciberseguridad", "software"])
            organo = ORGANOS[n % len(ORGANOS)] if n % 7 else ORGANOS[0]
            ccaa = azar.choice(COMUNIDADES)
            presupuesto = azar.choice([8_000, 40_000, 90_000, 300_000, 800_000, 2_000_000])
            if n % 37 == 0:
                presupuesto = 75_000_000          # fuera de la escala del mapa
            comunes = dict(
                organo=organo, nif_organo=f"Q{n % len(ORGANOS)}", ccaa=ccaa,
                cpv=azar.sample(CPVS, azar.randint(0, 3)),
                procedimiento=azar.choice(PROCEDIMIENTOS + [None]),
                objeto=azar.choice(OBJETOS) if n % 3 else f"Objeto distinto {n}",
                clave_grupo=grupo, expediente=f"EXP-{n}",
            )
            limite = pub + timedelta(days=azar.choice([-3, 7, 15, 25, 40, 90, 500]))
            vivo = azar.random() < 0.15
            primero = self.alta(
                f"{n}-a", perfiles=perfiles, categoria=categoria,
                fecha_publicacion=pub.isoformat(),
                fecha_limite_presentacion=(dia(20) if vivo else limite.isoformat()),
                estado="publicada", importe_sin_iva=presupuesto,
                lote_num="1" if n % 11 == 0 else None, **comunes)
            if vivo:
                continue
            adjudicado = pub + timedelta(days=azar.randint(20, 200))
            if adjudicado > HOY:
                continue
            importe = azar.choice([presupuesto, presupuesto * 0.9, presupuesto * 0.7,
                                   presupuesto * 0.3, presupuesto * 1.1])
            ganador = EMPRESAS[azar.randrange(len(EMPRESAS))]
            fin = adjudicado + timedelta(days=azar.choice([300, 365, 400, 700]))
            segundo = self.alta(
                f"{n}-b", perfiles=perfiles, categoria=categoria,
                fecha_publicacion=adjudicado.isoformat(), estado="adjudicada",
                importe_sin_iva=presupuesto, importe_adjudicacion=importe,
                adjudicatario=ganador, fecha_adjudicacion=adjudicado.isoformat(),
                fecha_fin_prevista=fin.isoformat(),
                lote_num="2" if n % 11 == 0 else None, **comunes)
            self.version(primero, "publicada", pub.isoformat())
            self.version(primero, "adjudicada", adjudicado.isoformat(), anterior="publicada")
            if n % 23 == 0:
                db.fijar_revision(self.con, segundo, estado="descartado",
                                  motivo_descarte="fuera de nicho")
        # Consultas previas, con y sin licitación después.
        for n in range(8):
            pub = dia(-400 + n * 30)
            self.alta(f"c{n}", fuente="placsp:consultas_previas", estado="previo",
                      nif_organo=f"QC{n}", expediente=f"CP-{n}", fecha_publicacion=pub,
                      clave_grupo=f"c{n}", perfiles=())
            if n % 2 == 0:
                self.alta(f"c{n}-l", fuente="placsp:licitaciones", nif_organo=f"QC{n}",
                          expediente=f"cp-{n}", fecha_publicacion=dia(-400 + n * 30 + 20 * n + 10),
                          clave_grupo=f"c{n}-l", perfiles=())
        self.con.commit()


class TestParidad(Base):
    """Cada elemento de cada gráfico contra su lista."""

    def setUp(self):
        super().setUp()
        self.poblar()

    def total(self, **kw):
        r = desglose.desglose(self.con, limite=desglose.LIMITE_MAXIMO, **kw)
        # Lo que dice `total` es lo que hay en la lista, página a página.
        vistos = len(r["items"])
        offset = vistos
        while r["hay_mas"]:
            r = desglose.desglose(self.con, limite=desglose.LIMITE_MAXIMO, offset=offset, **kw)
            vistos += len(r["items"])
            offset += len(r["items"])
        self.assertEqual(vistos, r["total"], kw)
        return r["total"]

    def grupos(self, **kw):
        r = desglose.desglose(self.con, **kw)
        return {g["clave"]: g["total"] for g in r["grupos"]}

    def comprobar_analitica(self, ambito: dict, desde: str | None):
        d = consultas.analitica(self.con, desde=desde, **ambito)
        base = dict(origen="analitica", desde=desde, **ambito)
        comprobados = 0

        def igual(esperado, **kw):
            nonlocal comprobados
            self.assertEqual(self.total(**base, **kw), esperado, (ambito, desde, kw))
            comprobados += 1

        # Cuándo sale el trabajo: un mes del año son ese mes de todos los años, y cada
        # año de la lista es el punto o la parte de la media de ese año.
        por_mes: dict = {}
        for m in d["calendario"]["meses"]:
            por_mes.setdefault(m["mes"][5:7], {})[m["mes"][:4]] = m["expedientes"]
        for mm, anios in por_mes.items():
            igual(sum(anios.values()), bloque="calendario", clave=mm)
            self.assertEqual(self.grupos(**base, bloque="calendario", clave=mm), anios)
        for bloque in ("importes", "baja", "plazo", "ciclo"):
            for i, tramo in enumerate(d[bloque]["tramos"]):
                igual(tramo["expedientes"], bloque=bloque, clave=str(i))
        for vista in ("adjudicadas", "activas"):
            x = d["comunidades"][vista]
            recuento = {c["ccaa"]: c["expedientes"] for c in x["recuento"]}
            for c in x["recuento"]:
                igual(c["expedientes"], bloque=f"comunidades-{vista}", clave=c["ccaa"])
            # La baldosa y la barra de importe cuentan lo que cabe en la escala; lo de más
            # de 50 M€ va en su propio grupo.
            for c in x["comunidades"]:
                g = self.grupos(**base, bloque=f"comunidades-{vista}", clave=c["ccaa"])
                self.assertEqual(g.get("dentro", 0), c["expedientes"])
                self.assertEqual(g.get("dentro", 0) + g.get("fuera", 0), recuento[c["ccaa"]])
        for x in d["cpv"]["divisiones"]:
            igual(x["expedientes"], bloque="cpv", clave=x["division"])
        for x in d["cpv"]["del_producto"]:
            igual(x["expedientes"], bloque="cpv", clave=x["codigo"])
        for x in d["procedimiento"]["procedimientos"]:
            igual(x["expedientes"], bloque="procedimiento", clave=x["procedimiento"])
        for o in d["estacionalidad"]["organos"]:
            for i, n in enumerate(o["meses"]):
                if n:
                    igual(n, bloque="estacionalidad", clave=f"{i + 1:02d}", nombre=o["organo"])
        cuota = d["cuota"]
        for i, anio in enumerate(cuota["anios"]):
            for e in cuota["empresas"]:
                igual(e["por_anio"][i]["expedientes"], bloque="cuota", clave=anio,
                      nombre=e["empresa"])
            igual(cuota["otros"][i]["expedientes"], bloque="cuota", clave=anio,
                  nombre=desglose.OTRAS_EMPRESAS)
        for i, tramo in enumerate(d["consultas"]["tramos"]):
            igual(tramo["expedientes"], bloque="consultas", clave=str(i))
        inc = d["incumbentes"]
        igual(inc["repite"], bloque="incumbentes", clave="repite")
        igual(inc["renovaciones"] - inc["repite"], bloque="incumbentes", clave="cambia")
        for m in d["renovaciones"]["por_mes"]:
            igual(m["contratos"], bloque="renovaciones", clave=m["mes"])
        return d, comprobados

    def test_cada_elemento_de_la_analitica_es_su_lista(self):
        total = 0
        for ambito in ({}, {"perfil": "p"}, {"categoria": "ciberseguridad"}):
            for desde in (None, "2024-01", f"{HOY.year}-01"):
                d, n = self.comprobar_analitica(ambito, desde)
                total += n
        # Que la base de prueba de verdad pase por todas partes: sin esto, una base que
        # dejara vacíos los bloques daría la prueba por buena sin probar nada.
        d = consultas.analitica(self.con)
        self.assertTrue(d["comunidades"]["adjudicadas"]["excluidos"], "falta un >50 M€")
        self.assertTrue(any(x["procedimiento"] == "el resto"
                            for x in d["procedimiento"]["procedimientos"]))
        self.assertGreater(len(d["cuota"]["empresas"]), 0)
        self.assertGreater(d["incumbentes"]["renovaciones"], 0)
        self.assertGreater(d["consultas"]["enlazadas"], 0)
        self.assertTrue(any(m["contratos"] for m in d["renovaciones"]["por_mes"]))
        self.assertGreater(total, 300)

    def test_cada_elemento_de_las_fichas_es_su_lista(self):
        for ambito in ({}, {"categoria": "ciberseguridad"}):
            amb = consultas.Ambito.de(**ambito)
            for organo in ORGANOS:
                f = consultas.ficha_organismo(self.con, organo, ambito=amb)
                if not f:
                    continue
                for m in f["meses"]:
                    if m["expedientes"]:
                        self.assertEqual(self.total(
                            origen="organismo", bloque="meses", clave=f"{m['mes']:02d}",
                            nombre=organo, **ambito), m["expedientes"])
                for p in f["como_compra"]["procedimientos"]:
                    self.assertEqual(self.total(
                        origen="organismo", bloque="procedimiento", clave=p["procedimiento"],
                        nombre=organo, **ambito), p["expedientes"])
            for empresa in EMPRESAS:
                f = consultas.ficha_competidor(self.con, empresa, ambito=amb)
                if not f:
                    continue
                for a in f["por_anio"]:
                    self.assertEqual(self.total(
                        origen="competidor", bloque="anios", clave=a["anio"],
                        nombre=empresa, **ambito), a["expedientes"])
                for c in f["comunidades"]:
                    self.assertEqual(self.total(
                        origen="competidor", bloque="comunidades", clave=c["ccaa"],
                        nombre=empresa, **ambito), c["expedientes"])

    def test_cada_mes_de_vencimientos_es_su_lista_con_la_tarjeta_de_prospeccion(self):
        for perfil in (None, "p"):
            v = consultas.vencimientos(self.con, perfil=perfil)
            self.assertTrue(any(m["contratos"] for m in v["por_mes"]))
            for m in v["por_mes"]:
                self.assertEqual(self.total(origen="vencimientos", bloque="meses",
                                            clave=m["mes"], perfil=perfil), m["contratos"])
                r = desglose.desglose(self.con, origen="vencimientos", bloque="meses",
                                      clave=m["mes"], perfil=perfil)
                for it in r["items"]:
                    self.assertEqual(it["forma"], "prospecto")
                    self.assertIn("prospeccion", it)
                    self.assertEqual(it["fecha_fin"][:7], m["mes"])


class TestLoQueDevuelve(Base):
    def test_las_tarjetas_llevan_el_dato_que_las_mete_en_el_tramo(self):
        """El importe de un tramo es el MAYOR publicado del expediente; la tarjeta enseña
        el de su último anuncio. Sin el dato al lado, una tarjeta de 40.000 € dentro de
        «más de un millón» parecería un error."""
        self.alta("a", importe_sin_iva=2_000_000, clave_grupo="g", fecha_publicacion=dia(-90))
        self.alta("b", importe_sin_iva=40_000, importe_adjudicacion=40_000, estado="adjudicada",
                  clave_grupo="g", fecha_publicacion=dia(-10))
        self.con.commit()
        r = desglose.desglose(self.con, origen="analitica", bloque="importes",
                              clave=str(len(consultas.TRAMOS_IMPORTE)))
        self.assertEqual(r["total"], 1)
        it = r["items"][0]
        self.assertEqual(it["dato"]["valor"], 2_000_000)
        self.assertEqual(it["anuncios"], 2)
        self.assertEqual(it["forma"], "tarjeta")

    def test_un_mes_del_anio_se_agrupa_por_anio_del_mas_reciente_al_mas_antiguo(self):
        for anio in (2024, 2025):
            for n in range(anio - 2022):
                self.alta(f"{anio}-{n}", clave_grupo=f"g{anio}{n}",
                          fecha_publicacion=f"{anio}-02-1{n}")
        self.con.commit()
        r = desglose.desglose(self.con, origen="analitica", bloque="calendario", clave="02")
        self.assertEqual([(g["clave"], g["total"]) for g in r["grupos"]],
                         [("2025", 3), ("2024", 2)])
        self.assertEqual([it["grupo"] for it in r["items"]], ["2025"] * 3 + ["2024"] * 2)
        self.assertEqual(r["grupos"][0]["titulo"], "febrero de 2025")

    def test_pagina_sin_perder_ni_repetir(self):
        for n in range(7):
            self.alta(f"x{n}", clave_grupo=f"g{n}", fecha_publicacion=f"2025-03-0{n + 1}")
        self.con.commit()
        vistos, offset = [], 0
        while True:
            r = desglose.desglose(self.con, origen="analitica", bloque="calendario",
                                  clave="03", limite=3, offset=offset)
            vistos += [it["id"] for it in r["items"]]
            offset += len(r["items"])
            if not r["hay_mas"]:
                break
        self.assertEqual(len(vistos), 7)
        self.assertEqual(len(set(vistos)), 7)

    def test_lo_descartado_no_sale_ni_en_el_grafico_ni_en_la_lista(self):
        fuera = self.alta("fuera", clave_grupo="g1", fecha_publicacion="2025-05-05")
        self.alta("dentro", clave_grupo="g2", fecha_publicacion="2025-05-06")
        db.fijar_revision(self.con, fuera, estado="descartado", motivo_descarte="fuera de nicho")
        self.con.commit()
        r = desglose.desglose(self.con, origen="analitica", bloque="calendario", clave="05")
        self.assertEqual([it["id"] for it in r["items"]],
                         [self.con.execute("SELECT id FROM licitaciones WHERE id_externo"
                                           " = 'dentro'").fetchone()[0]])

    def test_las_renovaciones_salen_como_parejas(self):
        organo = "Órgano que renueva"
        for i, (ganador, anio) in enumerate((("Acme S.L.", 2024), ("Acme S.L.", 2025))):
            self.alta(f"r{i}", organo=organo, clave_grupo=f"r{i}",
                      objeto="Servicio de concienciación en ciberseguridad",
                      fecha_publicacion=f"{anio}-01-10", estado="adjudicada",
                      adjudicatario=ganador, fecha_adjudicacion=f"{anio}-03-01")
        self.con.commit()
        r = desglose.desglose(self.con, origen="analitica", bloque="incumbentes", clave="repite")
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["items"][0]["forma"], "pareja")
        self.assertEqual(r["items"][0]["organo"], organo)

    def test_lo_que_no_existe_es_un_error_y_no_una_lista_vacia(self):
        for kw in ({"origen": "analitica", "bloque": "no-existe", "clave": "1"},
                   {"origen": "analitica", "bloque": "calendario", "clave": "13"},
                   {"origen": "analitica", "bloque": "importes", "clave": "9"},
                   {"origen": "analitica", "bloque": "cpv", "clave": "7x"},
                   {"origen": "analitica", "bloque": "incumbentes", "clave": "quizas"},
                   {"origen": "vencimientos", "bloque": "meses", "clave": "2026-13"},
                   {"origen": "organismo", "bloque": "meses", "clave": "01"}):
            with self.subTest(**kw):
                with self.assertRaises(ValueError):
                    desglose.desglose(self.con, **kw)


class TestRuta(Base):
    def setUp(self):
        super().setUp()
        import threading

        from radar import server

        self.alta("a", clave_grupo="g1", fecha_publicacion="2025-04-04")
        self.con.commit()
        self.srv = server.arrancar(0, Path(self.dir.name) / "t.db")
        hilo = threading.Thread(target=self.srv.serve_forever, daemon=True)
        hilo.start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def pedir(self, ruta):
        import json
        import urllib.error
        import urllib.request

        try:
            with urllib.request.urlopen(self.base + ruta, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_devuelve_la_lista_y_rechaza_lo_que_no_es(self):
        ruta = "/api/desglose?origen=analitica&bloque=calendario&clave=04"
        codigo, d = self.pedir(ruta)
        self.assertEqual((codigo, d["total"], d["items"][0]["forma"]), (200, 1, "tarjeta"))
        self.assertEqual(self.pedir(ruta + "&desde=2025-4")[0], 400)
        self.assertEqual(self.pedir(ruta + "&limite=x")[0], 400)
        codigo, d = self.pedir("/api/desglose?origen=analitica&bloque=nada&clave=04")
        self.assertEqual((codigo, "error" in d), (400, True))


if __name__ == "__main__":
    unittest.main()
