"""Duración de contratos, vencimientos y agrupación del ciclo de vida.

Todo lo que hay aquí salió de datos reales: las unidades mezcladas de PLACSP, el
texto libre de Cataluña y el prefijo genérico de los títulos de TED.
"""

# Sin esto, la anotación `str | None` de `_añadir` se evalúa al definir la función y este
# fichero no se puede ni importar en Python 3.9, el mínimo que declara el proyecto.
from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from radar import consultas, db
from radar.model import Licitacion, duracion_a_meses, titulo_util_ted
from radar.sources.catalunya import parsear_duracion


class TestDuracion(unittest.TestCase):
    def test_unidades_de_placsp(self):
        """`unitCode` no es decorativo: MON, DAY y ANN aparecen mezclados en el
        mismo fichero, y un 48 sin unidad son cuatro años o mes y medio."""
        self.assertEqual(duracion_a_meses("48", "MON"), 48)
        self.assertEqual(duracion_a_meses("11", "ANN"), 132)
        self.assertAlmostEqual(duracion_a_meses("120", "DAY"), 3.94, places=1)

    def test_unidades_de_ted(self):
        self.assertEqual(duracion_a_meses("24", "MONTH"), 24)
        self.assertEqual(duracion_a_meses("3", "YEAR"), 36)

    def test_sin_unidad_asume_meses(self):
        """Es la unidad de la mayoría; asumir días convertiría 2 años en 24 días."""
        self.assertEqual(duracion_a_meses("12", None), 12)

    def test_valores_no_utilizables(self):
        for valor, unidad in [(None, "MON"), ("", "MON"), ("0", "MON"),
                              ("-5", "MON"), ("no consta", "MON")]:
            with self.subTest(valor=valor):
                self.assertIsNone(duracion_a_meses(valor, unidad))


class TestDuracionCatalunya(unittest.TestCase):
    """Cataluña no da meses: da texto libre con un rango de fechas."""

    def test_rango_de_fechas(self):
        meses, inicio, fin = parsear_duracion("10/07/2026 a 09/01/2027")
        self.assertEqual(inicio, "2026-07-10")
        self.assertEqual(fin, "2027-01-09")
        self.assertAlmostEqual(meses, 6.0, delta=0.3)

    def test_duracion_en_meses_o_anios(self):
        self.assertEqual(parsear_duracion("24 mesos")[0], 24)
        self.assertEqual(parsear_duracion("2 anys")[0], 24)
        self.assertEqual(parsear_duracion("18 meses")[0], 18)

    def test_texto_incomprensible_no_se_adivina(self):
        for texto in [None, "", "segons plec", "fins a la finalització"]:
            with self.subTest(texto=texto):
                self.assertEqual(parsear_duracion(texto), (None, None, None))

    def test_rango_invertido_se_descarta(self):
        self.assertEqual(parsear_duracion("09/01/2027 a 10/07/2026"), (None, None, None))


class TestFechaFinPrevista(unittest.TestCase):
    def test_se_calcula_desde_la_adjudicacion_y_la_duracion(self):
        l = Licitacion(fuente="p", id_externo="1", fecha_adjudicacion="2026-01-15",
                       duracion_meses=12)
        self.assertEqual(l.fecha_fin_prevista, "2027-01-15")

    def test_la_fecha_explicita_manda_sobre_el_calculo(self):
        l = Licitacion(fuente="p", id_externo="1", fecha_adjudicacion="2026-01-15",
                       duracion_meses=12, fecha_fin_prevista="2026-06-30")
        self.assertTrue(l.fecha_fin_prevista.startswith("2026-06-30"))

    def test_el_inicio_de_ejecucion_tiene_prioridad_sobre_la_adjudicacion(self):
        l = Licitacion(fuente="p", id_externo="1", fecha_adjudicacion="2026-01-15",
                       fecha_inicio_ejecucion="2026-03-01", duracion_meses=6)
        self.assertEqual(l.fecha_fin_prevista, "2026-09-01")

    def test_sin_datos_no_se_inventa_una_fecha(self):
        """Peor que no tener el dato es llamar a un cliente con una fecha inventada."""
        l = Licitacion(fuente="p", id_externo="1", fecha_adjudicacion="2026-01-15")
        self.assertIsNone(l.fecha_fin_prevista)
        l2 = Licitacion(fuente="p", id_externo="2", duracion_meses=12)
        self.assertIsNone(l2.fecha_fin_prevista)

    def test_no_desborda_a_final_de_mes(self):
        l = Licitacion(fuente="p", id_externo="1", fecha_adjudicacion="2026-01-31",
                       duracion_meses=1)
        self.assertEqual(l.fecha_fin_prevista, "2026-02-28")


class TestClaveGrupo(unittest.TestCase):
    def test_quita_el_prefijo_generico_de_ted(self):
        """TED titula «España – <etiqueta CPV> – <título real>» y los dos primeros
        tramos son idénticos en cientos de anuncios."""
        self.assertEqual(
            titulo_util_ted("España – Servicios de formación informática – "
                            "Servicio de oficina de concienciación en ciberseguridad"),
            "Servicio de oficina de concienciación en ciberseguridad",
        )

    def test_no_toca_los_titulos_que_no_son_de_ted(self):
        t = "Servei integral de formació i conscienciació en ciberseguretat"
        self.assertEqual(titulo_util_ted(t), t)

    def test_dos_licitaciones_distintas_del_mismo_organo_no_se_fusionan(self):
        """El bug que ocultaba licitaciones: usar el título completo de TED metía en
        el mismo grupo contratos que solo compartían el prefijo genérico."""
        a = Licitacion(fuente="ted", id_externo="1", organo="Ayuntamiento X",
                       objeto="España – Paquetes de software y sistemas de información – "
                              "Suministro de licencias de antivirus")
        b = Licitacion(fuente="ted", id_externo="2", organo="Ayuntamiento X",
                       objeto="España – Paquetes de software y sistemas de información – "
                              "Plataforma de simulación de phishing")
        self.assertNotEqual(a.clave_grupo, b.clave_grupo)

    def test_el_anuncio_y_su_adjudicacion_caen_en_el_mismo_grupo(self):
        anuncio = Licitacion(fuente="ted", id_externo="580823-2024", organo="LANTIK",
                             objeto="España – Servicios de formación informática – "
                                    "Servicio de oficina de concienciación en ciberseguridad",
                             estado="publicada")
        adjudicacion = Licitacion(fuente="ted", id_externo="570954-2025", organo="LANTIK",
                                  objeto="España – Servicios de seguridad – "
                                         "Servicio de oficina de concienciación en ciberseguridad",
                                  estado="adjudicada")
        self.assertEqual(anuncio.clave_grupo, adjudicacion.clave_grupo)

    def test_en_placsp_agrupa_por_expediente(self):
        a = Licitacion(fuente="placsp:licitaciones", id_externo="1", organo="Órgano",
                       expediente="EXP/2026/001", objeto="Licitación")
        b = Licitacion(fuente="placsp:licitaciones", id_externo="2", organo="Órgano",
                       expediente="EXP/2026/001", objeto="Adjudicación del expediente")
        self.assertEqual(a.clave_grupo, b.clave_grupo)


class TestVistaVencimientos(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = db.conectar(Path(self.dir.name) / "t.db")
        hoy = date.today()
        casos = [
            ("vence-pronto", (hoy + timedelta(days=40)).isoformat(), "Incumbente SL", 90000),
            ("vence-tarde", (hoy + timedelta(days=400)).isoformat(), "Otra SL", 50000),
            ("ya-vencido", (hoy - timedelta(days=30)).isoformat(), "Antigua SL", 20000),
            ("sin-fecha-fin", None, "Sin Datos SL", 70000),
        ]
        for nombre, fin, adj, importe in casos:
            db.guardar(self.con, Licitacion(
                fuente="prueba", id_externo=nombre, objeto=f"Concienciación {nombre}",
                organo="Órgano", estado="adjudicada", adjudicatario=adj,
                importe_adjudicacion=importe, fecha_fin_prevista=fin,
            ))
        for f in self.con.execute("SELECT id FROM licitaciones"):
            self.con.execute(
                """INSERT INTO matches (licitacion_id, perfil, puntuacion, motivo, creado_en)
                   VALUES (?, 'p', 3.0, 'm', ?)""", (f["id"], db.ahora()))
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def _ids(self, **kw):
        return [i["id"] for i in consultas.vencimientos(self.con, **kw)["items"]]

    def test_solo_los_que_vencen_en_la_ventana(self):
        v = consultas.vencimientos(self.con, meses=6)
        objetos = [i["objeto"] for i in v["items"]]
        self.assertEqual(len(objetos), 1)
        self.assertIn("vence-pronto", objetos[0])

    def test_ventana_mas_amplia_incluye_los_lejanos(self):
        objetos = [i["objeto"] for i in consultas.vencimientos(self.con, meses=24)["items"]]
        self.assertEqual(len(objetos), 2)

    def test_los_sin_fecha_de_fin_no_aparecen(self):
        todos = " ".join(
            i["objeto"] for i in consultas.vencimientos(self.con, meses=60)["items"]
        )
        self.assertNotIn("sin-fecha-fin", todos)

    def test_incluye_al_incumbente_y_el_importe(self):
        it = consultas.vencimientos(self.con, meses=6)["items"][0]
        self.assertEqual(it["adjudicatario"], "Incumbente SL")
        self.assertEqual(it["importe"], 90000)
        self.assertGreater(it["dias_para_vencer"], 0)

    def test_lo_descartado_no_aparece(self):
        lic_id = self.con.execute(
            "SELECT id FROM licitaciones WHERE id_externo = 'vence-pronto'"
        ).fetchone()[0]
        db.fijar_revision(self.con, lic_id, estado="descartado",
                          motivo_descarte="incumbente atado")
        self.con.commit()
        self.assertEqual(consultas.vencimientos(self.con, meses=6)["items"], [])


class TestVentanaDeVencimiento(unittest.TestCase):
    """Los bordes de la ventana, y que los recuentos cuadren con la lista.

    La condición se escribió comparando `fecha_fin_prevista` sin envolverla en
    `substr(..., 1, 10)`, para que el índice sirva. Eso obliga a cerrar la ventana
    con `< fin + 1 día`, porque las fechas reales traen hora: un contrato que vence
    el último día de la ventana a las 10:00 desaparecía con un `<= fin` a secas.
    Y los cuatro recuentos de la cabecera salen de una sola pasada, así que hay que
    comprobar que dicen lo mismo que la consulta de la lista.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = db.conectar(Path(self.dir.name) / "t.db")

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def _sqlite_fecha(self, *modificadores) -> str:
        """La frontera se pregunta al mismo motor que la calcula en la consulta;
        sumar meses a mano en Python daría un día distinto a fin de mes."""
        args = ", ".join(f"'{m}'" for m in ("now",) + modificadores)
        return self.con.execute(f"SELECT date({args})").fetchone()[0]

    def _añadir(self, nombre: str, fin: str | None, *, perfiles=("p",)):
        db.guardar(self.con, Licitacion(
            fuente="prueba", id_externo=nombre, objeto=f"Concienciación {nombre}",
            organo="Órgano", estado="adjudicada", adjudicatario="Incumbente SL",
            importe_adjudicacion=1000, fecha_fin_prevista=fin,
        ))
        lic_id = self.con.execute(
            "SELECT id FROM licitaciones WHERE id_externo = ?", (nombre,)
        ).fetchone()[0]
        for perfil in perfiles:
            self.con.execute(
                """INSERT INTO matches (licitacion_id, perfil, puntuacion, motivo, creado_en)
                   VALUES (?, ?, 3.0, 'm', ?)""", (lic_id, perfil, db.ahora()))
        self.con.commit()
        return lic_id

    def _objetos(self, meses=6):
        return [i["objeto"] for i in consultas.vencimientos(self.con, meses=meses)["items"]]

    def test_el_que_vence_hoy_entra(self):
        self._añadir("hoy", self._sqlite_fecha() + "T09:00:00")
        self.assertEqual(len(self._objetos()), 1)

    def test_el_ultimo_dia_de_la_ventana_con_hora_entra(self):
        """El caso que justifica el `+1 day`: cerrar en `<= date('now','+6 months')`
        dejaba fuera lo que vence ese mismo día a cualquier hora."""
        self._añadir("justo-al-borde", self._sqlite_fecha("+6 months") + "T10:00:00")
        self.assertEqual(len(self._objetos()), 1)

    def test_el_dia_siguiente_al_borde_no_entra(self):
        self._añadir("pasado-el-borde",
                     self._sqlite_fecha("+6 months", "+1 day") + "T00:00:00")
        self.assertEqual(self._objetos(), [])

    def test_las_ventanas_cuadran_con_la_lista(self):
        """Los cuatro recuentos salen de una sola consulta con agregación
        condicional; si se desincronizan de la lista, la cabecera miente."""
        self._añadir("en-3-meses", self._sqlite_fecha("+2 months"))
        self._añadir("en-6-meses", self._sqlite_fecha("+5 months") + "T10:00:00")
        self._añadir("en-12-meses", self._sqlite_fecha("+11 months"))
        self._añadir("en-24-meses", self._sqlite_fecha("+23 months"))
        self._añadir("muy-lejano", self._sqlite_fecha("+40 months"))
        self._añadir("ya-vencido", self._sqlite_fecha("-2 months"))
        self._añadir("sin-fecha", None)

        por_ventana = {v["meses"]: v for v in
                       consultas.vencimientos(self.con)["por_ventana"]}
        self.assertEqual([por_ventana[m]["total"] for m in (3, 6, 12, 24)], [1, 2, 3, 4])

        for meses in (3, 6, 12, 24):
            with self.subTest(meses=meses):
                v = consultas.vencimientos(self.con, meses=meses)
                self.assertEqual(v["total"], por_ventana[meses]["total"])
                self.assertEqual(v["importe_total"], por_ventana[meses]["importe"])
                self.assertEqual(len(v["items"]), v["total"])

    def test_dos_perfiles_no_cuentan_dos_veces(self):
        """Sin deduplicar por licitación, la de dos perfiles inflaba el recuento y
        el importe de las ventanas."""
        self._añadir("doble", self._sqlite_fecha("+2 months"), perfiles=("p", "q"))
        v = consultas.vencimientos(self.con)
        self.assertEqual(v["total"], 1)
        self.assertEqual(v["importe_total"], 1000)
        self.assertEqual(v["por_ventana"][0]["total"], 1)
        self.assertEqual(v["por_ventana"][0]["importe"], 1000)

    def test_lo_descartado_tampoco_cuenta_en_las_ventanas(self):
        lic_id = self._añadir("descartada", self._sqlite_fecha("+2 months"))
        db.fijar_revision(self.con, lic_id, estado="descartado",
                          motivo_descarte="incumbente atado")
        self.con.commit()
        v = consultas.vencimientos(self.con)
        self.assertEqual(v["items"], [])
        self.assertEqual([x["total"] for x in v["por_ventana"]], [0, 0, 0, 0])
        self.assertEqual([x["importe"] for x in v["por_ventana"]], [0, 0, 0, 0])


class TestMotivoDescarte(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = db.conectar(Path(self.dir.name) / "t.db")
        db.guardar(self.con, Licitacion(fuente="p", id_externo="1", objeto="Concienciación"))
        self.lic_id = self.con.execute("SELECT id FROM licitaciones").fetchone()[0]

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def test_se_guarda_y_se_agrega(self):
        db.fijar_revision(self.con, self.lic_id, estado="descartado",
                          motivo_descarte="importe bajo")
        self.con.commit()
        resumen = consultas.motivos_descarte(self.con)
        self.assertEqual(resumen, [{"motivo": "importe bajo", "total": 1}])

    def test_motivo_invalido_se_rechaza(self):
        with self.assertRaises(ValueError):
            db.fijar_revision(self.con, self.lic_id, estado="descartado",
                              motivo_descarte="porque no me gusta")

    def test_el_motivo_sobrevive_a_un_cambio_de_notas(self):
        db.fijar_revision(self.con, self.lic_id, estado="descartado",
                          motivo_descarte="fuera de nicho")
        db.fijar_revision(self.con, self.lic_id, notas="revisar el año que viene")
        self.con.commit()
        f = self.con.execute(
            "SELECT motivo_descarte, notas, estado FROM revisiones"
        ).fetchone()
        self.assertEqual(f["motivo_descarte"], "fuera de nicho")
        self.assertEqual(f["estado"], "descartado")


class TestNovedades(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = db.conectar(Path(self.dir.name) / "t.db")

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def _añadir(self, nombre):
        db.guardar(self.con, Licitacion(fuente="p", id_externo=nombre,
                                        objeto=f"Concienciación {nombre}"))
        lic_id = self.con.execute(
            "SELECT id FROM licitaciones WHERE id_externo = ?", (nombre,)
        ).fetchone()[0]
        self.con.execute(
            """INSERT INTO matches (licitacion_id, perfil, puntuacion, motivo, creado_en)
               VALUES (?, 'p', 3.0, 'm', ?)""", (lic_id, db.ahora()))
        self.con.commit()

    def _marcar_visita(self):
        """Marca por id, no por hora: las marcas de tiempo tienen resolución de
        segundo y una ingesta en el mismo segundo se quedaría fuera."""
        ultimo = self.con.execute("SELECT COALESCE(MAX(id), 0) FROM licitaciones").fetchone()[0]
        db.escribir_preferencia(self.con, "ultima_visita_id", str(ultimo))
        self.con.commit()

    def test_sin_visita_previa_no_hay_novedades(self):
        self._añadir("a")
        self.assertEqual(consultas.resumen(self.con)["novedades"], 0)

    def test_cuenta_lo_llegado_despues_de_la_visita(self):
        self._añadir("a")
        self._marcar_visita()
        self.assertEqual(consultas.resumen(self.con)["novedades"], 0)
        self._añadir("b")
        self._añadir("c")
        self.assertEqual(consultas.resumen(self.con)["novedades"], 2)

    def test_el_filtro_devuelve_solo_las_novedades(self):
        self._añadir("a")
        self._marcar_visita()
        self._añadir("b")
        ids = [i["id_externo"] for i in
               consultas.bandeja(self.con, solo_vivas=False, solo_novedades=True)["items"]]
        self.assertEqual(ids, ["b"])


class TestProspeccion(unittest.TestCase):
    """Vencimientos como lista de prospección: un expediente por fila, los vencidos hace
    poco y los que no publican fin, y el punto en que está cada llamada."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = db.conectar(Path(self.dir.name) / "t.db")

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def _fecha(self, mod: str) -> str:
        return self.con.execute("SELECT date('now', ?)", (mod,)).fetchone()[0]

    def _añadir(self, nombre, *, fin=None, perfil="p", expediente=None, adjudicada=None,
                publicada="2024-01-10", organo="Órgano", nif="Q1"):
        db.guardar(self.con, Licitacion(
            fuente="prueba", id_externo=nombre, objeto=f"Concienciación {nombre}",
            expediente=expediente or nombre, organo=organo, nif_organo=nif,
            estado="adjudicada", adjudicatario="Incumbente SL", importe_adjudicacion=1000,
            fecha_fin_prevista=fin, fecha_adjudicacion=adjudicada,
            fecha_publicacion=publicada + "T00:00:00",
        ))
        lic_id = self.con.execute("SELECT id FROM licitaciones WHERE id_externo = ?",
                                  (nombre,)).fetchone()[0]
        self.con.execute(
            """INSERT INTO matches (licitacion_id, perfil, puntuacion, motivo, creado_en)
               VALUES (?, ?, 3.0, 'm', ?)""", (lic_id, perfil, db.ahora()))
        self.con.commit()
        return lic_id

    def test_un_expediente_con_prorroga_sale_una_vez_con_el_fin_mas_tardio(self):
        self._añadir("original", fin=self._fecha("+2 months"), expediente="E-1")
        self._añadir("prorroga", fin=self._fecha("+5 months"), expediente="E-1")
        v = consultas.vencimientos(self.con, meses=6)
        self.assertEqual(v["total"], 1)
        self.assertEqual(v["items"][0]["fecha_fin_prevista"][:10], self._fecha("+5 months"))

    def test_los_vencidos_hace_poco_van_aparte(self):
        self._añadir("hace-poco", fin=self._fecha("-2 months"))
        self._añadir("hace-mucho", fin=self._fecha("-10 months"))
        v = consultas.vencimientos(self.con)
        self.assertEqual([e["objeto"] for e in v["vencidos"]], ["Concienciación hace-poco"])
        self.assertLess(v["vencidos"][0]["dias_para_vencer"], 0)
        self.assertEqual(v["items"], [])

    def test_los_sin_fecha_de_fin_van_aparte_de_la_mas_antigua_a_la_mas_reciente(self):
        self._añadir("reciente", adjudicada=self._fecha("-3 months"))
        self._añadir("antigua", adjudicada=self._fecha("-3 years"))
        self._añadir("prehistorica", adjudicada=self._fecha("-6 years"))
        v = consultas.vencimientos(self.con)
        self.assertEqual([e["objeto"] for e in v["sin_fecha"]],
                         ["Concienciación antigua", "Concienciación reciente"])

    def test_filtrar_por_perfil(self):
        self._añadir("de-p", fin=self._fecha("+1 months"), perfil="p")
        self._añadir("de-q", fin=self._fecha("+1 months"), perfil="q")
        v = consultas.vencimientos(self.con, perfil="q")
        self.assertEqual([e["objeto"] for e in v["items"]], ["Concienciación de-q"])
        self.assertEqual(v["por_ventana"][0]["total"], 1)

    def test_el_estado_y_la_nota_se_guardan_por_expediente(self):
        self._añadir("a", fin=self._fecha("+1 months"))
        clave = consultas.vencimientos(self.con)["items"][0]["clave"]
        consultas.fijar_prospeccion(self.con, clave, estado="siguiendo")
        consultas.fijar_prospeccion(self.con, clave, nota="Llamar a Marta en enero")
        p = consultas.vencimientos(self.con)["items"][0]["prospeccion"]
        self.assertEqual((p["estado"], p["nota"]), ("siguiendo", "Llamar a Marta en enero"))

    def test_lo_descartado_en_la_prospeccion_se_cuenta_pero_no_se_lista(self):
        self._añadir("a", fin=self._fecha("+1 months"))
        self._añadir("b", fin=self._fecha("+1 months"))
        clave = consultas.vencimientos(self.con)["items"][0]["clave"]
        consultas.fijar_prospeccion(self.con, clave, estado="descartado")
        v = consultas.vencimientos(self.con)
        self.assertEqual((v["total"], v["descartados_ocultos"]), (1, 1))
        self.assertEqual(v["por_ventana"][0]["total"], 1)
        self.assertEqual(consultas.vencimientos(self.con, ver_descartados=True)["total"], 2)

    def test_cambiar_el_estado_no_borra_la_nota(self):
        """Cambiar de estado justo después de escribir la nota manda las dos peticiones
        a la vez; con lectura y escritura de la fila entera, la del estado pisaba la nota."""
        consultas.fijar_prospeccion(self.con, "k", nota="Llamar en diciembre")
        consultas.fijar_prospeccion(self.con, "k", estado="siguiendo")
        self.assertEqual(consultas.fijar_prospeccion(self.con, "k"),
                         {"clave": "k", "estado": "siguiendo", "nota": "Llamar en diciembre"})
        consultas.fijar_prospeccion(self.con, "k", nota="  ")
        self.assertIsNone(consultas.fijar_prospeccion(self.con, "k")["nota"])

    def test_estado_no_valido(self):
        for viejo in ("ganado", "contactado", "reunion"):
            with self.assertRaises(ValueError):
                consultas.fijar_prospeccion(self.con, "x", estado=viejo)
        with self.assertRaises(ValueError):
            consultas.fijar_prospeccion(self.con, "", estado="siguiendo")

    def test_avisa_de_lo_que_el_organo_publico_despues(self):
        self._añadir("viejo", fin=self._fecha("+1 months"), publicada="2023-01-10")
        nuevo = self._añadir("nuevo", fin=self._fecha("+30 months"), publicada="2025-06-01")
        self._añadir("de-otro", fin=self._fecha("+30 months"), publicada="2025-07-01",
                     organo="Otro", nif="Q2")
        v = consultas.vencimientos(self.con)
        self.assertEqual(v["items"][0]["renovacion"]["id"], nuevo)

    def _hojas_excel(self, **kw) -> dict:
        """{nombre de hoja: número de filas de datos} del Excel de Vencimientos."""
        import io
        import re
        import zipfile
        libro = zipfile.ZipFile(io.BytesIO(consultas.prospeccion_excel(self.con, **kw)))
        nombres = re.findall(r'<sheet name="([^"]+)"', libro.read("xl/workbook.xml").decode())
        return {n: libro.read(f"xl/worksheets/sheet{i}.xml").decode().count("<row ") - 1
                for i, n in enumerate(nombres, start=1)}

    def test_el_excel_lleva_la_ventana_elegida_y_los_otros_dos_apartados(self):
        self._añadir("en-2-meses", fin=self._fecha("+2 months"))
        self._añadir("en-5-meses", fin=self._fecha("+5 months"))
        self._añadir("vencido", fin=self._fecha("-1 months"))
        self._añadir("sin-fin", adjudicada=self._fecha("-1 years"))
        self.assertEqual(self._hojas_excel(meses=3),
                         {"Vencen en 3 meses": 1, "Vencidos (6 meses)": 1, "Sin fecha": 1})
        self.assertEqual(self._hojas_excel(meses=6)["Vencen en 6 meses"], 2)

    def test_el_excel_no_recorta_a_cien_ni_lleva_lo_descartado_salvo_que_se_pida(self):
        for i in range(consultas.LIMITE_SECCION_PROSPECCION + 5):
            self._añadir(f"sin-fin-{i}", adjudicada=self._fecha("-1 years"))
        self.assertEqual(len(consultas.vencimientos(self.con)["sin_fecha"]),
                         consultas.LIMITE_SECCION_PROSPECCION)
        self.assertEqual(self._hojas_excel()["Sin fecha"],
                         consultas.LIMITE_SECCION_PROSPECCION + 5)
        clave = consultas.vencimientos(self.con)["sin_fecha"][0]["clave"]
        consultas.fijar_prospeccion(self.con, clave, estado="descartado")
        self.assertEqual(self._hojas_excel()["Sin fecha"], consultas.LIMITE_SECCION_PROSPECCION + 4)
        self.assertEqual(self._hojas_excel(ver_descartados=True)["Sin fecha"],
                         consultas.LIMITE_SECCION_PROSPECCION + 5)

    def test_contactado_y_reunion_pasan_a_siguiendo_al_abrir_la_base(self):
        """Vencimientos dejó de tener «Contactado» y «Reunión»: lo que estaba en marcha se
        sigue, con su nota."""
        self.con.execute("INSERT INTO prospeccion (clave, estado, nota, actualizado_en)"
                         " VALUES ('a', 'contactado', 'Llamar', 'x'), ('b', 'reunion', NULL, 'x'),"
                         " ('c', 'descartado', NULL, 'x')")
        self.con.commit()
        db.migrar(self.con)
        self.assertEqual(
            dict(self.con.execute("SELECT clave, estado FROM prospeccion").fetchall()),
            {"a": "siguiendo", "b": "siguiendo", "c": "descartado"})
        self.assertEqual(consultas.fijar_prospeccion(self.con, "a")["nota"], "Llamar")

    def test_lo_seguido_va_a_su_grupo_de_siguiendo(self):
        self._añadir("vence", fin=self._fecha("+2 months"))
        self._añadir("otro", fin=self._fecha("+3 months"))
        clave = consultas.vencimientos(self.con)["items"][0]["clave"]
        self.assertEqual(consultas.siguiendo(self.con)["vencimientos"], [])
        consultas.fijar_prospeccion(self.con, clave, estado="siguiendo")
        d = consultas.siguiendo(self.con)
        self.assertEqual([e["objeto"] for e in d["vencimientos"]], ["Concienciación vence"])
        self.assertEqual((d["en_plazo"], d["vencidas"], d["total"]), ([], [], 1))
        self.assertEqual(consultas.resumen(self.con)["siguiendo_en_plazo"], 1)


class TestFechaFinEstimada(unittest.TestCase):
    """Cuando la fuente no da con qué calcular el fin, se estima con la duración y se
    dice cómo. Nunca pasa por publicada: `fecha_fin_prevista` sigue vacía."""

    def _lic(self, **kw) -> Licitacion:
        base = dict(fuente="prueba", id_externo="x", duracion_meses=18,
                    adjudicatario="Incumbente SL", fecha_publicacion="2024-06-11")
        base.update(kw)
        return Licitacion(**base)

    def test_con_fecha_publicada_no_se_estima(self):
        l = self._lic(fecha_adjudicacion="2024-07-01", fecha_formalizacion="2024-08-01")
        self.assertEqual(l.fecha_fin_prevista, "2026-01-01")
        self.assertEqual((l.fecha_fin_estimada, l.fin_origen, l.fin_base), (None, None, None))

    def test_formalizacion_antes_que_anuncio_de_adjudicacion(self):
        l = self._lic(fecha_formalizacion="2024-08-01", fecha_anuncio_adjudicacion="2024-07-20")
        self.assertIsNone(l.fecha_fin_prevista)
        self.assertEqual((l.fecha_fin_estimada, l.fin_origen, l.fin_base),
                         ("2026-02-01", "estimada", "formalizacion:2024-08-01"))

    def test_anuncio_de_adjudicacion(self):
        l = self._lic(fecha_anuncio_adjudicacion="2024-07-20")
        self.assertEqual((l.fecha_fin_estimada, l.fin_origen, l.fin_base),
                         ("2026-01-20", "estimada", "anuncio_adjudicacion:2024-07-20"))

    def test_publicacion_solo_si_ya_hay_adjudicatario(self):
        l = self._lic()
        self.assertEqual((l.fecha_fin_estimada, l.fin_origen, l.fin_base),
                         ("2025-12-11", "aproximada", "publicacion:2024-06-11"))
        # Una licitación todavía abierta no tiene contrato que venza.
        self.assertIsNone(self._lic(adjudicatario=None).fecha_fin_estimada)

    def test_una_duracion_imposible_no_tumba_la_ficha(self):
        """Una entrada real de 2025 traía 120.000 meses: sumar daba el año 12025 y la
        ficha entera se saltaba por ilegible."""
        l = self._lic(duracion_meses=120_000, fecha_formalizacion="2025-01-01")
        self.assertEqual((l.fecha_fin_estimada, l.fin_origen), (None, None))

    def test_sin_duracion_no_se_estima(self):
        l = self._lic(duracion_meses=None, fecha_formalizacion="2024-08-01")
        self.assertEqual((l.fecha_fin_estimada, l.fin_origen, l.fin_base), (None, None, None))

    def test_la_estimacion_no_cambia_la_huella(self):
        """Si cambiara, la primera ingesta tras actualizar daría por modificadas cientos de
        miles de licitaciones y re-evaluaría todos los perfiles."""
        sin = self._lic()
        con = self._lic(fecha_formalizacion="2024-08-01", fecha_anuncio_adjudicacion="2024-07-20")
        self.assertEqual(sin.huella(), con.huella())

    def test_releer_lo_ya_guardado_rellena_la_estimacion(self):
        """Lo que permite rellenarla volviendo a leer los ficheros descargados: la huella
        es la misma, así que es «igual», pero las columnas de la estimación se escriben."""
        with tempfile.TemporaryDirectory() as d:
            con = db.conectar(Path(d) / "t.db")
            self.assertEqual(db.guardar(con, self._lic()), "nueva")
            self.assertEqual(db.guardar(con, self._lic(fecha_formalizacion="2024-08-01")), "igual")
            fila = con.execute("SELECT fecha_fin_estimada, fin_origen, fecha_fin_prevista,"
                               " fecha_formalizacion FROM licitaciones").fetchone()
            self.assertEqual(tuple(fila), ("2026-02-01", "estimada", None, "2024-08-01T00:00:00"))
            con.close()

    def test_la_busqueda_calcula_la_estimada_de_lo_que_ya_habia(self):
        with tempfile.TemporaryDirectory() as d:
            con = db.conectar(Path(d) / "t.db")
            db.guardar(con, self._lic())
            con.execute("UPDATE licitaciones SET fecha_fin_estimada = NULL, fin_origen = NULL")
            db.escribir_preferencia(con, "version_fin_estimado", "0")
            con.commit()
            db.migrar(con)  # al abrir no se toca: va con la búsqueda
            self.assertIsNone(con.execute("SELECT fecha_fin_estimada FROM licitaciones")
                              .fetchone()[0])
            self.assertEqual(db.rellenar_fin_estimado_si_toca(con), 1)
            self.assertIsNone(db.rellenar_fin_estimado_si_toca(con))
            self.assertEqual(
                tuple(con.execute("SELECT fecha_fin_estimada, fin_origen FROM licitaciones")
                      .fetchone()), ("2025-12-11", "aproximada"))
            con.close()

    def test_releer_un_zip_viejo_solo_completa_las_fechas_y_no_pisa_nada_mas(self):
        """`ingest --backfill` guarda la ficha entera, y el ZIP anual puede traer una
        versión anterior a la guardada. Para estimar solo hacen falta dos fechas."""
        with tempfile.TemporaryDirectory() as d:
            con = db.conectar(Path(d) / "t.db")
            db.guardar(con, self._lic(estado="adjudicada", fecha_anuncio_adjudicacion="2024-07-20"))
            vieja = self._lic(estado="publicada", adjudicatario=None,
                              fecha_formalizacion="2024-08-01")
            self.assertEqual(db.completar_fechas_para_estimar(con, [vieja]), 1)
            db.rellenar_fin_estimado(con)
            fila = con.execute("SELECT estado, adjudicatario, fecha_formalizacion,"
                               " fecha_anuncio_adjudicacion, fin_origen FROM licitaciones"
                               ).fetchone()
            self.assertEqual(tuple(fila), ("adjudicada", "Incumbente SL", "2024-08-01T00:00:00",
                                           "2024-07-20T00:00:00", "estimada"))
            con.close()

    def test_vencimientos_prefiere_la_publicada_y_explica_la_estimada(self):
        with tempfile.TemporaryDirectory() as d:
            con = db.conectar(Path(d) / "t.db")
            hoy = date.today()
            formalizada = date(hoy.year - 1, hoy.month, 1).isoformat()
            db.guardar(con, self._lic(id_externo="est", expediente="E", organo="O",
                                      fecha_publicacion=formalizada,
                                      fecha_formalizacion=formalizada, duracion_meses=14))
            lic = con.execute("SELECT id FROM licitaciones").fetchone()[0]
            con.execute("INSERT INTO matches (licitacion_id, perfil, puntuacion, motivo,"
                        " creado_en) VALUES (?, 'p', 3.0, 'm', ?)", (lic, db.ahora()))
            con.commit()
            e = consultas.vencimientos(con, meses=6)["items"][0]
            self.assertEqual(e["fin_origen"], "estimada")
            self.assertTrue(consultas.explicar_fin(e).startswith("Formalización del contrato ("))
            con.close()


if __name__ == "__main__":
    unittest.main()
