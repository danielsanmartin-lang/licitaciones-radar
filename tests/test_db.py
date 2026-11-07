"""Deduplicación, historial de versiones y triaje.

La ingesta se ejecuta a diario y PLACSP republica una licitación cada vez que se
toca cualquier cosa: si el dedup falla, la bandeja se llena de duplicados y la
herramienta se vuelve inservible en una semana.
"""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from radar import db
from radar.model import Licitacion


def lic(**kw):
    base = dict(
        fuente="prueba",
        id_externo="X1",
        objeto="Servicio de concienciación en ciberseguridad",
        organo="Ayuntamiento de Prueba",
        valor_estimado=120000,
        cpv="80533100-3",
        estado="publicada",
        fecha_limite_presentacion="2026-12-01T13:00:00",
    )
    base.update(kw)
    return Licitacion(**base)


class TestGuardar(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = db.conectar(Path(self.dir.name) / "t.db")

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def test_insercion_y_dedup(self):
        self.assertEqual(db.guardar(self.con, lic()), "nueva")
        self.assertEqual(db.guardar(self.con, lic()), "igual")
        self.assertEqual(db.guardar(self.con, lic()), "igual")
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM licitaciones").fetchone()[0], 1
        )
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM licitaciones_versiones").fetchone()[0], 1,
            "una republicación idéntica no debe crear versión nueva",
        )

    def test_la_fecha_de_actualizacion_no_cuenta_como_cambio(self):
        """PLACSP cambia <updated> en cada republicación aunque el fondo sea igual."""
        db.guardar(self.con, lic(fecha_actualizacion="2026-08-01T10:00:00"))
        estado = db.guardar(self.con, lic(fecha_actualizacion="2026-08-05T18:30:00"))
        self.assertEqual(estado, "igual")

    def _fila(self, *columnas):
        return self.con.execute(
            f"SELECT {', '.join(columnas)} FROM licitaciones WHERE id_externo = 'X1'"
        ).fetchone()

    def test_una_version_anterior_no_pisa_la_guardada(self):
        """`ingest --backfill` sobre una base con datos: el ZIP del año en curso llega
        hasta el mes pasado y devolvía a «publicada» lo que el feed diario ya había visto
        adjudicado. 285 de 188.000 fichas en la base real."""
        db.guardar(self.con, lic(estado="adjudicada", adjudicatario="Empresa SA",
                                 importe_adjudicacion=99000,
                                 fecha_actualizacion="2026-10-20T10:00:00+02:00"))
        self.con.execute("UPDATE licitaciones SET visto_ultima_vez = '2000-01-01'")
        versiones = self.con.execute(
            "SELECT COUNT(*) FROM licitaciones_versiones").fetchone()[0]

        estado = db.guardar(self.con, lic(fecha_actualizacion="2026-09-01T10:00:00+02:00"))

        self.assertEqual(estado, "anterior")
        f = self._fila("estado", "adjudicatario", "fecha_actualizacion", "visto_ultima_vez")
        self.assertEqual((f["estado"], f["adjudicatario"]), ("adjudicada", "Empresa SA"))
        self.assertTrue(f["fecha_actualizacion"].startswith("2026-10-20"))
        self.assertNotEqual(f["visto_ultima_vez"], "2000-01-01", "la ficha sí se ha visto")
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM licitaciones_versiones").fetchone()[0],
            versiones, "una versión vieja no es un cambio que anotar en el historial")

    def test_una_version_posterior_si_se_escribe(self):
        db.guardar(self.con, lic(fecha_actualizacion="2026-09-01T10:00:00+02:00"))
        estado = db.guardar(self.con, lic(estado="adjudicada", adjudicatario="Empresa SA",
                                          fecha_actualizacion="2026-10-20T10:00:00+02:00"))
        self.assertEqual(estado, "actualizada")
        self.assertEqual(self._fila("estado")["estado"], "adjudicada")

    def test_compara_instantes_y_no_texto(self):
        """Las 09:30+01:00 son las 08:30 UTC, media hora DESPUÉS de las 10:00+02:00, y
        como texto van delante. PLACSP cambia de zona dos veces al año."""
        db.guardar(self.con, lic(estado="adjudicada", adjudicatario="Empresa SA",
                                 fecha_actualizacion="2026-10-25T09:30:00+01:00"))
        estado = db.guardar(self.con, lic(fecha_actualizacion="2026-10-25T10:00:00+02:00"))
        self.assertEqual(estado, "anterior")
        self.assertEqual(self._fila("estado")["estado"], "adjudicada")

    def test_sin_fecha_de_actualizacion_se_escribe_como_siempre(self):
        """TED no publica ninguna y Cataluña solo en lo adjudicado: sin las dos fechas no
        se puede saber cuál es más nueva, y se hace lo de siempre."""
        for guardada, llega in ((None, "2026-01-01T00:00:00"),
                                ("2026-12-01T00:00:00", None)):
            with self.subTest(guardada=guardada, llega=llega):
                self.con.execute("DELETE FROM licitaciones")
                self.con.execute("DELETE FROM licitaciones_fts")
                db.guardar(self.con, lic(fecha_actualizacion=guardada))
                estado = db.guardar(self.con, lic(estado="adjudicada",
                                                  fecha_actualizacion=llega))
                self.assertEqual(estado, "actualizada")
                self.assertEqual(self._fila("estado")["estado"], "adjudicada")

    def test_la_misma_fecha_se_escribe(self):
        """Releer un fichero ya visto con un radar que lee un campo más es como se
        rellenan los campos nuevos: con la misma `<updated>` tiene que escribirse."""
        db.guardar(self.con, lic(fecha_actualizacion="2026-09-01T10:00:00+02:00"))
        estado = db.guardar(self.con, lic(lugar="Madrid",
                                          fecha_actualizacion="2026-09-01T10:00:00+02:00"))
        self.assertEqual(estado, "actualizada")

    def test_la_version_anterior_solo_rellena_las_fechas_que_faltan(self):
        """La formalización de una versión vieja vale si la guardada no la tiene (la leyó
        un radar que aún no la leía), y con ella se recalcula el fin estimado. Lo que la
        guardada sí tiene no se toca."""
        sin_formalizar = dict(estado="adjudicada", adjudicatario="Empresa SA",
                              duracion_meses=12, fecha_publicacion="2025-06-01")
        db.guardar(self.con, lic(**sin_formalizar,
                                 fecha_actualizacion="2026-10-20T10:00:00+02:00"))
        self.con.execute("UPDATE licitaciones SET fecha_formalizacion = NULL,"
                         " fecha_fin_estimada = NULL, fin_origen = NULL, fin_base = NULL")

        estado = db.guardar(self.con, lic(**sin_formalizar,
                                          fecha_formalizacion="2025-09-15",
                                          fecha_actualizacion="2026-09-01T10:00:00+02:00"))
        self.assertEqual(estado, "anterior")
        f = self._fila("fecha_formalizacion", "fecha_fin_estimada", "fin_base")
        self.assertTrue(f["fecha_formalizacion"].startswith("2025-09-15"))
        self.assertTrue(f["fecha_fin_estimada"].startswith("2026-09-15"))
        self.assertEqual(f["fin_base"], "formalizacion:2025-09-15")

        # Una segunda versión vieja, con otra formalización: la que ya hay se queda.
        db.guardar(self.con, lic(**sin_formalizar, fecha_formalizacion="2025-01-01",
                                 fecha_actualizacion="2026-08-01T10:00:00+02:00"))
        self.assertTrue(self._fila("fecha_formalizacion")[0].startswith("2025-09-15"))

    def test_la_version_anterior_no_borra_el_fin_estimado(self):
        """Con la misma huella, la rama «igual» copia `CAMPOS_FIN` de lo que llega. Una
        versión vieja sin adjudicatario no tiene fin estimado, y lo borraba."""
        db.guardar(self.con, lic(estado="adjudicada", adjudicatario="Empresa SA",
                                 duracion_meses=12, fecha_formalizacion="2025-09-15",
                                 fecha_actualizacion="2026-10-20T10:00:00+02:00"))
        self.assertIsNotNone(self._fila("fecha_fin_estimada")[0])
        db.guardar(self.con, lic(duracion_meses=12,
                                 fecha_actualizacion="2026-03-01T10:00:00+01:00"))
        self.assertIsNotNone(self._fila("fecha_fin_estimada")[0])

    def test_cambio_real_crea_version_con_transicion(self):
        db.guardar(self.con, lic())
        estado = db.guardar(self.con, lic(estado="adjudicada", adjudicatario="Empresa X",
                                         importe_adjudicacion=98000))
        self.assertEqual(estado, "actualizada")
        versiones = self.con.execute(
            "SELECT estado_anterior, estado, adjudicatario FROM licitaciones_versiones ORDER BY id"
        ).fetchall()
        self.assertEqual(len(versiones), 2)
        self.assertEqual(versiones[-1]["estado_anterior"], "publicada")
        self.assertEqual(versiones[-1]["estado"], "adjudicada")
        self.assertEqual(versiones[-1]["adjudicatario"], "Empresa X")

    def test_la_version_se_fecha_con_la_fecha_de_la_fuente(self):
        """El historial cuenta cuándo pasó, no cuándo lo descargamos.

        Es la regresión que hacía inútil el bloque: en la carga inicial las cuatro
        republicaciones de un expediente de 2024 se leen del mismo ZIP en el mismo
        minuto, y las cuatro salían fechadas hoy.
        """
        db.guardar(self.con, lic(fecha_publicacion="2024-04-23"))
        db.guardar(self.con, lic(estado="adjudicada", adjudicatario="Empresa X",
                                 fecha_publicacion="2024-04-23",
                                 fecha_actualizacion="2024-06-10T09:00:00"))
        fechas = [
            f["fecha_cambio"] for f in self.con.execute(
                "SELECT fecha_cambio FROM licitaciones_versiones ORDER BY id"
            )
        ]
        self.assertEqual(fechas[0][:10], "2024-04-23")
        self.assertEqual(fechas[1][:10], "2024-06-10")
        hoy = date.today().isoformat()
        self.assertNotIn(hoy, [f[:10] for f in fechas])

    def test_sin_fechas_en_la_fuente_la_version_queda_sin_fecha_de_cambio(self):
        """NULL es lo que hace que la interfaz diga «visto el …» en vez de inventarse
        una fecha oficial."""
        db.guardar(self.con, lic())
        fila = self.con.execute(
            "SELECT detectado_en, fecha_cambio FROM licitaciones_versiones"
        ).fetchone()
        self.assertIsNone(fila["fecha_cambio"])
        self.assertTrue(fila["detectado_en"])

    def test_fuentes_distintas_no_colisionan(self):
        db.guardar(self.con, lic(fuente="placsp:licitaciones", id_externo="1"))
        db.guardar(self.con, lic(fuente="ted", id_externo="1"))
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM licitaciones").fetchone()[0], 2
        )

    def test_fts_se_mantiene_sincronizado(self):
        db.guardar(self.con, lic())
        db.guardar(self.con, lic(objeto="Suministro de plataforma de phishing simulado"))
        n_fts = self.con.execute("SELECT COUNT(*) FROM licitaciones_fts").fetchone()[0]
        self.assertEqual(n_fts, 1, "actualizar no debe dejar filas huérfanas en el índice")
        hit = self.con.execute(
            "SELECT COUNT(*) FROM licitaciones_fts WHERE licitaciones_fts MATCH 'phishing'"
        ).fetchone()[0]
        self.assertEqual(hit, 1)
        viejo = self.con.execute(
            "SELECT COUNT(*) FROM licitaciones_fts WHERE licitaciones_fts MATCH 'concienciacion'"
        ).fetchone()[0]
        self.assertEqual(viejo, 0, "el texto antiguo no debe seguir indexado")

    def test_busqueda_ignora_acentos(self):
        db.guardar(self.con, lic())
        for termino in ("concienciacion", "concienciación", "CIBERSEGURIDAD"):
            with self.subTest(termino=termino):
                n = self.con.execute(
                    "SELECT COUNT(*) FROM licitaciones_fts WHERE licitaciones_fts MATCH ?",
                    (termino,),
                ).fetchone()[0]
                self.assertEqual(n, 1)


class TestMigracion(unittest.TestCase):
    """La base de cada compañero se autocorrige al arrancar.

    `CREATE TABLE IF NOT EXISTS` no toca una tabla que ya existe, así que sin la
    migración las bases en uso —con su triaje y sus notas dentro— se quedan sin las
    columnas nuevas y la aplicación falla al consultarlas.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.ruta = Path(self.dir.name) / "vieja.db"

    def test_una_base_de_una_version_anterior_recibe_columna_e_indice(self):
        import sqlite3

        # El esquema de antes es el de ahora sin la columna nueva. Se construye quitando
        # sus dos líneas en lugar de con DROP COLUMN, que pide SQLite 3.35 y aquí se
        # soporta más atrás; el assert de abajo avisa si el recorte deja de aplicar.
        viejo = db.ESQUEMA.replace(
            "    -- Huella con la que se evaluaron los perfiles la última vez. "
            "Ver COLUMNAS_NUEVAS.\n"
            "    huella_evaluada           TEXT,\n",
            "",
        )
        self.assertNotIn("huella_evaluada", viejo, "el recorte del esquema ya no aplica")

        con = sqlite3.connect(self.ruta)
        con.executescript(viejo)
        con.execute(
            "INSERT INTO licitaciones (fuente, id_externo, huella, texto_busqueda, "
            "visto_primera_vez, visto_ultima_vez) VALUES ('prueba', 'X1', 'hhh', "
            "'texto', '2026-01-01', '2026-01-01')"
        )
        con.commit()
        con.close()

        con = db.conectar(self.ruta)
        self.addCleanup(con.close)
        columnas = {f["name"] for f in con.execute("PRAGMA table_info(licitaciones)")}
        self.assertIn("huella_evaluada", columnas)
        indices = {
            f[0] for f in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        self.assertIn("idx_lic_pendientes", indices)
        # Y la ficha que ya estaba queda pendiente de evaluar, no dada por evaluada:
        # darla por buena esconderla para siempre si nunca llegó a evaluarse.
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM licitaciones "
                        "WHERE huella_evaluada IS NOT huella").fetchone()[0], 1)


class TestSnapshots(unittest.TestCase):
    """El snapshot de cada versión guarda solo lo que se usa.

    Guardar una copia de todos los campos suponía 534 MB de las 269.000 versiones
    —el 46% de la base— de datos que la aplicación no lee en ningún sitio.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = db.conectar(Path(self.dir.name) / "t.db")

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def test_el_snapshot_es_compacto(self):
        db.guardar(self.con, lic(descripcion="x" * 4000, objeto="y" * 2000))
        snapshot = self.con.execute(
            "SELECT snapshot FROM licitaciones_versiones"
        ).fetchone()[0]
        self.assertLess(len(snapshot), 400, "el snapshot no debe copiar el objeto entero")
        import json
        datos = json.loads(snapshot)
        self.assertEqual(set(datos), set(db.CAMPOS_SNAPSHOT))

    def test_conserva_lo_necesario_para_auditar(self):
        db.guardar(self.con, lic())
        db.guardar(self.con, lic(estado="adjudicada", adjudicatario="Empresa X",
                                 importe_adjudicacion=50000))
        import json
        ultimo = json.loads(self.con.execute(
            "SELECT snapshot FROM licitaciones_versiones ORDER BY id DESC LIMIT 1"
        ).fetchone()[0])
        self.assertEqual(ultimo["estado"], "adjudicada")
        self.assertEqual(ultimo["adjudicatario"], "Empresa X")
        self.assertEqual(ultimo["importe_adjudicacion"], 50000)

    def test_el_recorte_de_snapshots_antiguos_es_idempotente(self):
        db.guardar(self.con, lic())
        self.assertEqual(db.recortar_snapshots(self.con), 0,
                         "los nuevos ya vienen compactos")


class TestRevisiones(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = db.conectar(Path(self.dir.name) / "t.db")
        db.guardar(self.con, lic())
        self.lic_id = self.con.execute("SELECT id FROM licitaciones").fetchone()[0]

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def _estado(self):
        f = self.con.execute(
            "SELECT estado, notas FROM revisiones WHERE licitacion_id = ?", (self.lic_id,)
        ).fetchone()
        return (f["estado"], f["notas"]) if f else (None, None)

    def test_guardar_notas_no_borra_el_estado(self):
        """Regresión: escribir una nota sacaba la licitación del seguimiento."""
        db.fijar_revision(self.con, self.lic_id, estado="siguiendo")
        self.assertEqual(self._estado()[0], "siguiendo")

        db.fijar_revision(self.con, self.lic_id, notas="llamar al CISO")
        estado, notas = self._estado()
        self.assertEqual(estado, "siguiendo", "las notas no deben tocar el estado")
        self.assertEqual(notas, "llamar al CISO")

    def test_cambiar_estado_no_borra_las_notas(self):
        db.fijar_revision(self.con, self.lic_id, notas="pendiente de hablar con compras")
        db.fijar_revision(self.con, self.lic_id, estado="presentada")
        estado, notas = self._estado()
        self.assertEqual(estado, "presentada")
        self.assertEqual(notas, "pendiente de hablar con compras")

    def test_estado_invalido_se_rechaza(self):
        with self.assertRaises(ValueError):
            db.fijar_revision(self.con, self.lic_id, estado="inventado")

    def test_el_triaje_sobrevive_a_una_actualizacion_de_la_licitacion(self):
        db.fijar_revision(self.con, self.lic_id, estado="siguiendo", notas="mía")
        db.guardar(self.con, lic(estado="adjudicada", adjudicatario="Otra Empresa"))
        self.assertEqual(self._estado(), ("siguiendo", "mía"))


class TestTriajePorExpediente(unittest.TestCase):
    """El triaje pertenece al expediente, no al anuncio.

    La bandeja colapsa los anuncios de un expediente en una tarjeta y muestra solo el
    más reciente, así que guardar el triaje únicamente en la fila que se tenía delante
    no bastaba: el filtro quitaba ese anuncio y la tarjeta volvía a salir con el
    siguiente, otra vez «sin revisar». Y la republicación del día siguiente entraba
    como fila nueva sin triaje, con el mismo efecto.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = db.conectar(Path(self.dir.name) / "t.db")

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def _anuncio(self, id_externo, expediente="EXP-1", **kw):
        db.guardar(self.con, lic(id_externo=id_externo, expediente=expediente, **kw))
        return self.con.execute(
            "SELECT id FROM licitaciones WHERE id_externo = ?", (id_externo,)
        ).fetchone()["id"]

    def _triaje(self):
        return {
            f["licitacion_id"]: f["estado"]
            for f in self.con.execute("SELECT licitacion_id, estado FROM revisiones")
        }

    def test_descartar_marca_todos_los_anuncios_del_expediente(self):
        primero = self._anuncio("A1")
        correccion = self._anuncio("A2")
        db.fijar_revision(self.con, correccion, estado="descartado",
                          motivo_descarte="fuera de nicho")
        self.assertEqual(self._triaje(), {primero: "descartado", correccion: "descartado"})

    def test_no_se_lleva_por_delante_otro_expediente(self):
        propio = self._anuncio("A1")
        ajeno = self._anuncio("B1", expediente="EXP-2")
        db.fijar_revision(self.con, propio, estado="descartado")
        self.assertEqual(self._triaje(), {propio: "descartado"})
        self.assertNotIn(ajeno, self._triaje())

    def test_un_anuncio_nuevo_hereda_el_triaje_del_expediente(self):
        """La republicación de mañana no puede devolver a la bandeja lo descartado hoy."""
        db.fijar_revision(self.con, self._anuncio("A1"), estado="descartado",
                          motivo_descarte="importe bajo")
        nuevo = self._anuncio("A2")  # PLACSP republica el expediente al corregirlo
        f = self.con.execute(
            "SELECT estado, motivo_descarte FROM revisiones WHERE licitacion_id = ?",
            (nuevo,),
        ).fetchone()
        self.assertEqual((f["estado"], f["motivo_descarte"]), ("descartado", "importe bajo"))

    def test_un_expediente_sin_triar_no_genera_filas_de_revision(self):
        """Heredar no significa crear triajes 'nuevo' que no dicen nada."""
        self._anuncio("A1")
        self._anuncio("A2")
        self.assertEqual(self._triaje(), {})

    def test_la_fusion_con_ted_arrastra_el_triaje(self):
        """El anuncio europeo entra con grupo propio y se fusiona después.

        Sin propagar detrás de la fusión, el expediente descartado volvía a la bandeja
        por la puerta de atrás: el anuncio de TED seguía marcado como «sin revisar».
        """
        placsp = self._anuncio(
            "P1", fuente="placsp:licitaciones", expediente="J260047",
            organo="Junta de Contratación del Ministerio de Cultura",
            valor_estimado=1031857.23, fecha_limite_presentacion="2026-09-28T19:00:00")
        ted = self._anuncio(
            "T1", fuente="ted", expediente="548701-2026", organo="Ministerio de Cultura",
            objeto="España – Servicios – Servicio de oficina de ciberseguridad",
            valor_estimado=1031857.23,
            fecha_limite_presentacion="2026-09-28T19:00:00+02:00")
        db.fijar_revision(self.con, placsp, estado="descartado")
        self.assertNotIn(ted, self._triaje())

        db.fusionar_grupos_ted(self.con)
        self.assertEqual(db.propagar_revisiones_en_grupos(self.con), 1)
        self.assertEqual(self._triaje(), {placsp: "descartado", ted: "descartado"})

    def test_propagar_no_pisa_una_decision_ya_tomada(self):
        """Solo rellena huecos. En un empate de triajes no elige por la persona."""
        primero = self._anuncio("A1")
        segundo = self._anuncio("A2")
        # Se simula una base anterior a este cambio, con triajes distintos por anuncio.
        self.con.execute("DELETE FROM revisiones")
        for lic_id, estado in ((primero, "descartado"), (segundo, "siguiendo")):
            self.con.execute(
                """INSERT INTO revisiones (licitacion_id, estado, actualizado_en)
                   VALUES (?, ?, ?)""", (lic_id, estado, db.ahora()))
        self.assertEqual(db.propagar_revisiones_en_grupos(self.con), 0)
        self.assertEqual(self._triaje(), {primero: "descartado", segundo: "siguiendo"})


class TestFusionTedPlacsp(unittest.TestCase):
    """Una licitación sobre el umbral europeo se publica en PLACSP y en TED.

    Las dos filas tienen que acabar en el mismo grupo para no ocupar dos sitios de la
    bandeja ni pedir dos triajes.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = db.conectar(Path(self.dir.name) / "t.db")

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def _grupo(self, id_externo):
        return self.con.execute(
            "SELECT clave_grupo FROM licitaciones WHERE id_externo = ?", (id_externo,)
        ).fetchone()["clave_grupo"]

    def test_une_el_anuncio_de_ted_con_su_expediente_de_placsp(self):
        # Mismo contrato, órgano escrito distinto y título traducido: solo coinciden
        # el importe y el día de cierre, que es justo lo que usa la fusión.
        db.guardar(self.con, lic(
            fuente="placsp:licitaciones", id_externo="P1", expediente="J260047",
            organo="Junta de Contratación del Ministerio de Cultura",
            objeto="Servicio de oficina de ciberseguridad en el ministerio de cultura",
            valor_estimado=1031857.23, fecha_limite_presentacion="2026-09-28T19:00:00"))
        db.guardar(self.con, lic(
            fuente="ted", id_externo="T1", expediente="548701-2026",
            organo="Ministerio de Cultura",
            objeto="España – Servicios de gestión de instalaciones – Servicio de oficina",
            valor_estimado=1031857.23, fecha_limite_presentacion="2026-09-28T19:00:00+02:00"))
        self.assertNotEqual(self._grupo("P1"), self._grupo("T1"))

        stats = db.fusionar_grupos_ted(self.con)
        self.assertEqual(stats["anuncios_fusionados"], 1)
        self.assertEqual(self._grupo("T1"), self._grupo("P1"))

        # Idempotente: volver a pasar no cambia nada ni vuelve a contar.
        self.assertEqual(db.fusionar_grupos_ted(self.con)["anuncios_fusionados"], 0)

    def test_no_fusiona_cuando_el_importe_y_la_fecha_son_ambiguos(self):
        """Dos licitaciones distintas con importe redondo y el mismo cierre.

        Se midieron 10 casos reales así sobre 629. Preferimos dos filas separadas a
        fusionar la equivocada, que mezclaría el triaje de dos expedientes.
        """
        for i in (1, 2):
            db.guardar(self.con, lic(
                fuente="placsp:licitaciones", id_externo=f"P{i}", expediente=f"EXP{i}",
                objeto=f"Contrato distinto número {i}", valor_estimado=400000,
                fecha_limite_presentacion="2026-09-15T12:00:00"))
        db.guardar(self.con, lic(
            fuente="ted", id_externo="T1", expediente="999-2026",
            objeto="España – Servicios – Alguno de los dos, no se sabe cuál",
            valor_estimado=400000, fecha_limite_presentacion="2026-09-15T12:00:00"))

        antes = self._grupo("T1")
        stats = db.fusionar_grupos_ted(self.con)
        self.assertEqual(stats["anuncios_fusionados"], 0)
        self.assertEqual(stats["ambiguos"], 1)
        self.assertEqual(self._grupo("T1"), antes, "no debía tocar el grupo ambiguo")

    def test_no_fusiona_sin_importe_o_sin_fecha_limite(self):
        """Sin las dos mitades de la clave no hay identificación posible."""
        db.guardar(self.con, lic(
            fuente="placsp:licitaciones", id_externo="P1", expediente="EXP1",
            valor_estimado=None, importe_sin_iva=None, importe_adjudicacion=None,
            fecha_limite_presentacion=None))
        db.guardar(self.con, lic(
            fuente="ted", id_externo="T1", expediente="999-2026",
            valor_estimado=None, importe_sin_iva=None, importe_adjudicacion=None,
            fecha_limite_presentacion=None))
        self.assertEqual(db.fusionar_grupos_ted(self.con)["anuncios_fusionados"], 0)


class TestFusionTedPorOrgano(unittest.TestCase):
    """La segunda regla: TED sin importe, unido por órgano, día de cierre y título.

    El caso real: la homologación de formación del Ens d'Abastament d'Aigua Ter-Llobregat
    salía dos veces en la Bandeja, el anuncio catalán y el de TED en castellano. TED no
    publica su importe, así que la regla del importe no podía unirlos.
    """

    ATL = "Ens d'Abastament d'Aigua Ter-Llobregat (ATL)"

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = db.conectar(Path(self.dir.name) / "t.db")

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def _grupo(self, id_externo):
        return self.con.execute(
            "SELECT clave_grupo FROM licitaciones WHERE id_externo = ?", (id_externo,)
        ).fetchone()["clave_grupo"]

    def _ted(self, objeto, *, organo=ATL, limite="2029-05-06T13:00:00+01:00", ident="T1"):
        db.guardar(self.con, lic(
            fuente="ted", id_externo=ident, expediente=f"{ident}-2026", organo=organo,
            objeto=f"España – Servicios de formación en materia de seguridad – {objeto}",
            valor_estimado=None, importe_sin_iva=None, importe_adjudicacion=None,
            fecha_limite_presentacion=limite))

    def _de_casa(self, ident, objeto, *, fuente="catalunya", organo=ATL,
                 expediente="2025RTSE0300", limite="2029-05-06T13:00:00", **kw):
        db.guardar(self.con, lic(
            fuente=fuente, id_externo=ident, expediente=expediente, organo=organo,
            objeto=objeto, fecha_limite_presentacion=limite, **kw))

    def test_une_el_anuncio_de_ted_sin_importe_con_el_catalan(self):
        self._de_casa("C1", "Homologació de proveïdors pel servei de formació pel personal"
                            " de l'Ens d'Abastament Ter-Llobregat en matèries recurrents i"
                            " necessitats formatives específiques", lote_num="3")
        self._de_casa("P1", "Tramitación del Sistema Dinámico de Adquisición para la"
                            " homologación de proveedores de formación",
                      fuente="placsp:agregadas", valor_estimado=1_100_000)
        self._ted("Homologación de proveedores para el servicio de formación para el"
                  " personal del Ens d'Abastament Ter-Llobregat en materias recurrentes y"
                  " necesidades formativas específicas")
        self.assertEqual(self._grupo("C1"), self._grupo("P1"), "ya compartían expediente")
        self.assertNotEqual(self._grupo("T1"), self._grupo("C1"))

        stats = db.fusionar_grupos_ted(self.con)
        self.assertEqual(stats["por_organo"], 1)
        self.assertEqual(stats["anuncios_fusionados"], 1)
        self.assertEqual(self._grupo("T1"), self._grupo("C1"))
        # Idempotente.
        self.assertEqual(db.fusionar_grupos_ted(self.con)["anuncios_fusionados"], 0)

    def test_no_une_otro_contrato_del_mismo_organo_que_cierra_el_mismo_dia(self):
        """Medido: con solo el órgano y el día, casi la mitad de las 113 parejas eran
        otro contrato. «Desarrollo de aplicaciones Java» contra unas obras en la sede."""
        self._de_casa("P1", "Obras de adecuación del edificio de la sede",
                      fuente="placsp:licitaciones")
        self._ted("Servicios de desarrollo de aplicaciones Java")
        antes = self._grupo("T1")
        self.assertEqual(db.fusionar_grupos_ted(self.con)["anuncios_fusionados"], 0)
        self.assertEqual(self._grupo("T1"), antes)

    def test_no_cuenta_las_palabras_del_nombre_del_organo(self):
        """«Soporte informático a los centros de MC MUTUAL» se unía por «mutual» con una
        auditoría de MC Mutual que cerraba el mismo día."""
        mutua = "Dirección General de la Mutual Midat Cyclops, Mutua Colaboradora"
        self._de_casa("P1", "Servicio de auditoría externa de las certificaciones"
                            " existentes en los centros de MC MUTUAL",
                      fuente="placsp:licitaciones", organo=mutua)
        self._ted("Servicio de Soporte Informático a los centros de MC MUTUAL.",
                  organo=mutua)
        self.assertEqual(db.fusionar_grupos_ted(self.con)["anuncios_fusionados"], 0)

    def test_otro_organo_o_otro_dia_no_se_une(self):
        titulo = "Homologación de proveedores de formación del personal"
        self._de_casa("P1", titulo, fuente="placsp:licitaciones", organo="Otro órgano")
        self._de_casa("P2", titulo, fuente="placsp:licitaciones", expediente="E2",
                      limite="2029-05-07T13:00:00")
        self._ted(titulo)
        self.assertEqual(db.fusionar_grupos_ted(self.con)["anuncios_fusionados"], 0)

    def test_si_dos_expedientes_se_parecen_no_elige(self):
        titulo = "Homologación de proveedores de formación del personal"
        self._de_casa("P1", titulo, fuente="placsp:licitaciones", expediente="E1")
        self._de_casa("P2", titulo + " técnico", fuente="placsp:licitaciones",
                      expediente="E2")
        self._ted(titulo)
        antes = self._grupo("T1")
        stats = db.fusionar_grupos_ted(self.con)
        self.assertEqual(stats["anuncios_fusionados"], 0)
        self.assertEqual(stats["ambiguos_por_organo"], 1)
        self.assertEqual(self._grupo("T1"), antes)

    def test_lo_que_ya_unio_el_importe_no_se_vuelve_a_mirar(self):
        """Solo entra lo que la primera regla ha dejado suelto."""
        self._de_casa("P1", "Homologación de proveedores de formación",
                      fuente="placsp:licitaciones", valor_estimado=50_000)
        db.guardar(self.con, lic(
            fuente="ted", id_externo="T1", expediente="T1-2026", organo=self.ATL,
            objeto="España – Servicios – Homologación de proveedores de formación",
            valor_estimado=50_000, fecha_limite_presentacion="2029-05-06T13:00:00"))
        stats = db.fusionar_grupos_ted(self.con)
        self.assertEqual((stats["anuncios_fusionados"], stats["por_organo"]), (1, 0))
        self.assertEqual(db.parejas_ted_por_organo(self.con), ([], 0))


if __name__ == "__main__":
    unittest.main()
