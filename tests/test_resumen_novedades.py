"""El resumen de lo nuevo: el que sale al terminar la búsqueda y en la pestaña «Resumen».

Lo que se protege: que cuente expedientes y no anuncios —el anuncio de TED que se suma a
un expediente que ya tenías no es una licitación nueva—, que cada periodo mida lo que
dice (lo que ha ENTRADO en el radar, o lo PUBLICADO en el plazo), que lo descartado no
cuente y que un perfil sin nada nuevo salga con su cero.
"""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from radar import busqueda, consultas, db, server
from radar.model import Licitacion

PERFILES = ["Concienciación y phishing", "Protección del correo electrónico"]


def hace(dias: int) -> str:
    return (date.today() - timedelta(days=dias)).isoformat() + "T00:00:00"


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.con = db.conectar(Path(self.dir.name) / "t.db")
        self.addCleanup(self.con.close)

    def alta(self, ide, *, perfil=None, temas=(), publicada=0, grupo=None,
             fuente="prueba") -> int:
        db.guardar(self.con, Licitacion(
            fuente=fuente, id_externo=ide, objeto=f"Objeto {ide}", organo="Órgano",
            fecha_publicacion=hace(publicada), clave_grupo=grupo or f"g-{ide}",
        ))
        lic_id = self.con.execute(
            "SELECT id FROM licitaciones WHERE id_externo = ?", (ide,)).fetchone()[0]
        for p in ([perfil] if isinstance(perfil, str) else (perfil or [])):
            self.con.execute(
                """INSERT INTO matches (licitacion_id, perfil, puntuacion, motivo, creado_en)
                   VALUES (?, ?, 3.0, 'prueba', ?)""", (lic_id, p, db.ahora()))
        for t in temas:
            self.con.execute("INSERT INTO categorias VALUES (?, ?)", (lic_id, t))
        self.con.commit()
        return lic_id

    def resumen(self, periodo):
        return consultas.resumen_novedades(self.con, periodo, perfiles_activos=PERFILES)

    @staticmethod
    def por_perfil(r):
        return {p["perfil"]: p["total"] for p in r["por_perfil"]}


class TestUltimaBusqueda(Base):
    def test_sin_busquedas_lo_dice_en_lugar_de_contar_cero(self):
        r = self.resumen("busqueda")
        self.assertTrue(r["sin_datos"])
        self.assertEqual(self.por_perfil(r), {p: 0 for p in PERFILES})

    def test_cuenta_solo_lo_que_trajo_esa_busqueda(self):
        self.alta("de-ayer", perfil=PERFILES[0], grupo="viejo")
        b = db.abrir_busqueda(self.con)
        self.alta("nueva-1", perfil=PERFILES[0], temas=["ciberseguridad"])
        self.alta("nueva-2", perfil=[PERFILES[0], PERFILES[1]])
        # El anuncio de TED del expediente que ya estaba: no es una licitación nueva.
        self.alta("ted-del-viejo", perfil=PERFILES[0], grupo="viejo", fuente="ted")
        db.cerrar_busqueda(self.con, b, "completa")

        r = self.resumen("busqueda")
        self.assertFalse(r["sin_datos"])
        self.assertEqual(r["total"], 2)
        self.assertEqual(self.por_perfil(r), {PERFILES[0]: 2, PERFILES[1]: 1})
        self.assertEqual(r["busqueda"]["motivo"], "completa")
        self.assertEqual({it["objeto"] for it in r["items"]}, {"Objeto nueva-1", "Objeto nueva-2"})

    def test_lo_descartado_no_cuenta(self):
        b = db.abrir_busqueda(self.con)
        lic = self.alta("descartada", perfil=PERFILES[0])
        self.alta("buena", perfil=PERFILES[0])
        db.cerrar_busqueda(self.con, b, "completa")
        db.fijar_revision(self.con, lic, estado="descartado", motivo_descarte="otro")
        self.con.commit()
        self.assertEqual(self.resumen("busqueda")["total"], 1)

    def test_las_tematicas_cuentan_aunque_no_casen_y_sin_resto(self):
        b = db.abrir_busqueda(self.con)
        self.alta("cloud-suelta", temas=["cloud"])
        self.alta("obra", temas=["resto"])
        db.cerrar_busqueda(self.con, b, "completa")
        r = self.resumen("busqueda")
        temas = {t["clave"]: t["total"] for t in r["por_tematica"]}
        self.assertEqual(temas["cloud"], 1)
        self.assertNotIn("resto", temas)
        self.assertEqual(r["total"], 0, "en la bandeja no ha entrado nada")

    def test_dice_que_fuentes_fallaron_en_esa_busqueda(self):
        b = db.abrir_busqueda(self.con)
        log = db.abrir_ingest(self.con, "placsp:licitaciones")
        db.cerrar_ingest(self.con, log, error="atascada: sin avanzar")
        db.cerrar_busqueda(self.con, b, "con_errores")
        fallos = self.resumen("busqueda")["busqueda"]["fallos"]
        self.assertEqual([f["fuente"] for f in fallos], ["placsp:licitaciones"])


class TestDesdeLaUltimaVez(Base):
    def test_cuenta_desde_que_entraste_la_vez_anterior(self):
        self.alta("vieja", perfil=PERFILES[0])
        db.rotar_apertura(self.con)            # primera vez: aún no hay «anterior»
        self.alta("de-esta-vez", perfil=PERFILES[1])
        db.rotar_apertura(self.con)            # se entra otra vez: lo de antes rota
        r = self.resumen("visita")
        self.assertEqual(r["total"], 1)
        self.assertEqual(self.por_perfil(r)[PERFILES[1]], 1)
        self.assertIsNotNone(r["desde"])

    def test_recargar_sin_nada_nuevo_no_lo_vacia(self):
        self.alta("vieja", perfil=PERFILES[0])
        db.rotar_apertura(self.con)
        self.alta("nueva", perfil=PERFILES[0])
        db.rotar_apertura(self.con)
        db.rotar_apertura(self.con)            # una recarga: no ha entrado nada
        self.assertEqual(self.resumen("visita")["total"], 1)

    def test_sin_ninguna_marca_lo_dice(self):
        self.assertTrue(self.resumen("visita")["sin_datos"])


class TestPorPublicacion(Base):
    def test_cuenta_por_la_primera_publicacion_del_expediente(self):
        self.alta("de-ayer", perfil=PERFILES[0], publicada=1)
        self.alta("de-hace-20-dias", perfil=PERFILES[0], publicada=20)
        # Entra hoy, pero se publicó hace meses: no es «de la última semana».
        self.alta("antigua", perfil=PERFILES[0], publicada=200)
        # Anuncio reciente de un expediente que ya se publicó hace 40 días.
        self.alta("primer-anuncio", perfil=PERFILES[0], publicada=40, grupo="g")
        self.alta("correccion", perfil=PERFILES[0], publicada=2, grupo="g")

        self.assertEqual(self.resumen("semana")["total"], 1)
        self.assertEqual(self.resumen("mes")["total"], 2)
        self.assertEqual(self.resumen("trimestre")["total"], 3)

    def test_un_periodo_desconocido_se_rechaza(self):
        with self.assertRaises(ValueError):
            self.resumen("siempre")


class TestRutas(Base):
    """Las dos rutas nuevas, contra un servidor de verdad en un puerto libre."""

    def setUp(self):
        super().setUp()
        self.srv = server.arrancar(0, Path(self.dir.name) / "t.db")
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

    def test_un_periodo_no_valido_es_un_400(self):
        codigo, d = self.pedir("/api/resumen-novedades?periodo=siempre")
        self.assertEqual(codigo, 400)
        self.assertIn("periodo no válido", d["error"])

    def test_resumen_y_apertura(self):
        self.alta("una", perfil=PERFILES[0])
        codigo, d = self.pedir("/api/resumen-novedades?periodo=mes")
        self.assertEqual((codigo, d["total"]), (200, 1))
        codigo, d = self.pedir("/api/resumen/apertura", {})
        self.assertEqual((codigo, d["ok"]), (200, True))


class TestExplicarLentitud(unittest.TestCase):
    def test_placsp_lento_lo_explica_con_la_velocidad(self):
        texto = busqueda.explicar_lentitud(
            {"fuente": "placsp:licitaciones", "fase": "descargando",
             "bytes_por_s": 30_000, "paginas": 7},
            (datetime.now(timezone.utc) - timedelta(days=2)).isoformat())
        self.assertIn("Plataforma de Contratación del Estado", texto)
        self.assertIn("menos de 0,1 MB/s", texto)
        self.assertIn("varios minutos", texto)
        self.assertIn("2 días", texto)
        self.assertIn("van 7", texto)

    def test_los_reintentos_se_cuentan(self):
        texto = busqueda.explicar_lentitud(
            {"fuente": "placsp:agregadas", "fase": "falló el intento 2/4, reintento en 4s"})
        self.assertIn("2 minutos antes de reintentar", texto)

    def test_sin_avanzar_dice_que_puede_estar_atascada(self):
        texto = busqueda.explicar_lentitud({"fuente": "ted", "sin_avance": 400})
        self.assertIn("atascado", texto)
        self.assertIn("15 minutos", texto)

    def test_evaluando_ya_no_es_la_red(self):
        texto = busqueda.explicar_lentitud({"fuente": "evaluando perfiles"})
        self.assertIn("Ya ha descargado todo", texto)

    def test_sin_detalle_no_hay_nada_que_explicar(self):
        self.assertIsNone(busqueda.explicar_lentitud(None))


if __name__ == "__main__":
    unittest.main()
