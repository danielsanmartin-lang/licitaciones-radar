"""La búsqueda cada N horas y los avisos de lo que trae (`radar/automatica.py`).

Lo que se protege:

- Cuándo busca: nunca con «nunca», nunca encima de otra búsqueda, de una actualización o
  de una carga inicial a medias, y no en los primeros minutos (la pantalla de arranque
  hace la suya). Sin red no reintenta cada minuto: cuenta su propio intento.
- Qué avisa: lo que han traído las búsquedas terminadas desde el último aviso, por
  expediente y sin lo descartado; nada del histórico la primera vez, nada de la carga
  inicial, y una sola vez (la marca solo avanza).
- Las preferencias: valores por defecto, validación y que el endpoint no escriba nada
  que no sea suyo.
"""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from radar import automatica, db, server
from radar.model import Licitacion

PERFILES = ["Concienciación y phishing", "Protección del correo electrónico"]
HORA = 3600


def decide(**cambios) -> bool:
    datos = dict(intervalo_min=120, ahora=10 * HORA, arrancado=0.0, ultima=None,
                 ultimo_intento=None, hay_busqueda=False, hay_actualizacion=False,
                 etapas_pendientes=False)
    datos.update(cambios)
    return automatica.toca_buscar(**datos)


class TestCuandoToca(unittest.TestCase):
    def test_sin_busquedas_previas_toca(self):
        self.assertTrue(decide())

    def test_nunca_es_nunca(self):
        self.assertFalse(decide(intervalo_min=0))

    def test_espera_al_intervalo_desde_la_ultima(self):
        self.assertFalse(decide(ultima=10 * HORA - 119 * 60))
        self.assertTrue(decide(ultima=10 * HORA - 120 * 60))

    def test_cuenta_su_propio_intento_aunque_la_busqueda_no_quedara_apuntada(self):
        # Sin red la búsqueda puede no llegar ni a apuntarse en `busquedas`.
        self.assertFalse(decide(ultima=0.0, ultimo_intento=10 * HORA - 60))

    def test_no_se_pisa_con_nada(self):
        self.assertFalse(decide(hay_busqueda=True))
        self.assertFalse(decide(hay_actualizacion=True))
        self.assertFalse(decide(etapas_pendientes=True))

    def test_deja_los_primeros_minutos_a_la_pantalla_de_arranque(self):
        self.assertFalse(decide(arrancado=10 * HORA - 60))
        self.assertTrue(decide(arrancado=10 * HORA - automatica.GRACIA_ARRANQUE))


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.ruta = Path(self.dir.name) / "t.db"
        self.con = db.conectar(self.ruta)
        self.addCleanup(self.con.close)

    def alta(self, ide, *, perfil=PERFILES[0], grupo=None) -> int:
        db.guardar(self.con, Licitacion(
            fuente="prueba", id_externo=ide, objeto=f"Objeto {ide}", organo="Órgano",
            fecha_publicacion=(date.today() - timedelta(days=1)).isoformat(),
            clave_grupo=grupo or f"g-{ide}",
        ))
        lic_id = self.con.execute(
            "SELECT id FROM licitaciones WHERE id_externo = ?", (ide,)).fetchone()[0]
        if perfil:
            self.con.execute(
                """INSERT INTO matches (licitacion_id, perfil, puntuacion, motivo, creado_en)
                   VALUES (?, ?, 3.0, 'prueba', ?)""", (lic_id, perfil, db.ahora()))
        self.con.commit()
        return lic_id

    def busqueda(self, *ides, primera_carga=False, **kw) -> int:
        b = db.abrir_busqueda(self.con, primera_carga=primera_carga)
        for ide in ides:
            self.alta(ide, **kw)
        db.cerrar_busqueda(self.con, b, "completa")
        return b

    def avisos(self):
        return automatica.avisos_pendientes(self.con, perfiles_activos=PERFILES)


class TestPlanificador(Base):
    def setUp(self):
        super().setUp()
        # Una base sin historia tiene la carga inicial entera por hacer, y con etapas
        # pendientes no se busca (ver `test_no_se_pisa_con_nada`).
        db.apuntar_etapas_pendientes(self.con, [])

    def test_con_la_carga_inicial_a_medias_no_busca(self):
        db.apuntar_etapas_pendientes(self.con, [3])
        reloj = [1e9]
        p, lanzadas = self.planificador(reloj)
        p.arrancado = 0.0
        with mock.patch("radar.busqueda.en_marcha", return_value=None), \
             mock.patch("radar.actualizacion.en_marcha", return_value=None):
            self.assertFalse(p.tic())
        self.assertEqual(lanzadas, [])

    def planificador(self, reloj):
        lanzadas = []
        p = automatica.Planificador(self.ruta, reloj=lambda: reloj[0],
                                    lanzar=lambda **kw: lanzadas.append(kw))
        return p, lanzadas

    def test_lanza_al_cumplirse_el_intervalo_y_no_dos_veces(self):
        reloj = [1_000_000.0]
        p, lanzadas = self.planificador(reloj)
        with mock.patch("radar.busqueda.en_marcha", return_value=None), \
             mock.patch("radar.actualizacion.en_marcha", return_value=None):
            self.assertFalse(p.tic())  # gracia de arranque
            reloj[0] += automatica.GRACIA_ARRANQUE
            self.assertTrue(p.tic())
            self.assertFalse(p.tic())  # su propio intento cuenta
            reloj[0] += 120 * 60
            self.assertTrue(p.tic())
        self.assertEqual(len(lanzadas), 2)

    def test_respeta_nunca_y_la_busqueda_en_marcha(self):
        reloj = [1_000_000.0 + automatica.GRACIA_ARRANQUE]
        p, lanzadas = self.planificador(reloj)
        p.arrancado = 0.0
        with mock.patch("radar.busqueda.en_marcha", return_value={"pid": 1}), \
             mock.patch("radar.actualizacion.en_marcha", return_value=None):
            self.assertFalse(p.tic())
        automatica.fijar_preferencias(self.con, {"intervalo_min": 0})
        with mock.patch("radar.busqueda.en_marcha", return_value=None), \
             mock.patch("radar.actualizacion.en_marcha", return_value=None):
            self.assertFalse(p.tic())
        self.assertEqual(lanzadas, [])

    def test_si_otra_se_adelanta_no_rompe(self):
        p = automatica.Planificador(self.ruta, reloj=lambda: 1e9,
                                    lanzar=mock.Mock(side_effect=RuntimeError("ya hay una")))
        p.arrancado = 0.0
        with mock.patch("radar.busqueda.en_marcha", return_value=None), \
             mock.patch("radar.actualizacion.en_marcha", return_value=None):
            self.assertFalse(p.tic())


class TestPreferencias(Base):
    def test_por_defecto_cada_dos_horas_con_avisos_y_sonido(self):
        self.assertEqual(automatica.preferencias(self.con),
                         {"intervalo_min": 120, "avisos": True, "sonido": True})

    def test_guarda_solo_lo_que_viene(self):
        automatica.fijar_preferencias(self.con, {"sonido": False})
        self.assertEqual(automatica.preferencias(self.con),
                         {"intervalo_min": 120, "avisos": True, "sonido": False})

    def test_rechaza_lo_que_no_vale_sin_guardar_nada(self):
        for malo in ({"intervalo_min": 7}, {"intervalo_min": "x"}, {"avisos": "sí"},
                     {"intervalo_min": 60, "sonido": 1}):
            with self.subTest(malo=malo):
                with self.assertRaises(ValueError):
                    automatica.fijar_preferencias(self.con, malo)
        self.assertEqual(automatica.preferencias(self.con)["intervalo_min"], 120)


class TestAvisos(Base):
    def test_la_primera_vez_no_avisa_del_historico(self):
        self.busqueda("vieja-1", "vieja-2")
        r = self.avisos()
        self.assertEqual(r["total"], 0)
        self.assertIsNone(r["hasta"])

    def test_avisa_de_lo_nuevo_una_sola_vez(self):
        automatica.preparar_marca(self.con)
        b = self.busqueda("nueva-1", "nueva-2")
        r = self.avisos()
        self.assertEqual(r["total"], 2)
        self.assertEqual(r["hasta"], b)
        self.assertEqual(r["titulo"], "2 licitaciones nuevas")
        self.assertIn(f"{PERFILES[0]} 2", r["cuerpo"])
        self.assertIn("Objeto nueva-", r["cuerpo"])
        automatica.marcar_entregados(self.con, r["hasta"])
        self.assertEqual(self.avisos()["total"], 0)

    def test_junta_las_busquedas_que_corrieron_con_la_ventana_cerrada(self):
        automatica.preparar_marca(self.con)
        self.busqueda("a")
        b2 = self.busqueda("b")
        r = self.avisos()
        self.assertEqual((r["total"], r["hasta"]), (2, b2))
        self.assertEqual(r["titulo"], "2 licitaciones nuevas")

    def test_cuenta_expedientes_y_deja_fuera_lo_descartado_y_lo_que_no_casa(self):
        self.alta("expediente-viejo", grupo="viejo")
        automatica.preparar_marca(self.con)
        b = db.abrir_busqueda(self.con)
        self.alta("otro-anuncio-del-viejo", grupo="viejo")
        self.alta("no-casa", perfil=None)
        descartada = self.alta("descartada")
        db.fijar_revision(self.con, descartada, estado="descartado",
                          motivo_descarte="fuera de nicho")
        self.alta("buena")
        db.cerrar_busqueda(self.con, b, "completa")
        r = self.avisos()
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["titulo"], "1 licitación nueva")

    def test_la_carga_inicial_no_se_avisa(self):
        automatica.preparar_marca(self.con)
        b = self.busqueda("historico-1", "historico-2", primera_carga=True)
        r = self.avisos()
        self.assertEqual((r["total"], r["hasta"]), (0, b))

    def test_la_marca_no_retrocede(self):
        automatica.preparar_marca(self.con)
        b = self.busqueda("x")
        automatica.marcar_entregados(self.con, b)
        self.assertEqual(automatica.marcar_entregados(self.con, 0), b)

    def test_sin_avisos_activos_lo_dice_para_que_la_ventana_no_lo_ponga(self):
        automatica.fijar_preferencias(self.con, {"avisos": False})
        automatica.preparar_marca(self.con)
        self.busqueda("y")
        r = self.avisos()
        self.assertEqual(r["total"], 1)
        self.assertFalse(r["avisos"])


class TestEndpoints(Base):
    def setUp(self):
        super().setUp()
        self.servidor = server.arrancar(0, self.ruta)
        self.puerto = self.servidor.server_address[1]
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.addCleanup(self.servidor.server_close)
        self.addCleanup(self.servidor.shutdown)

    def pedir(self, ruta, cuerpo=None):
        datos = None if cuerpo is None else json.dumps(cuerpo).encode()
        peticion = urllib.request.Request(
            f"http://127.0.0.1:{self.puerto}{ruta}", data=datos,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(peticion, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_preferencias_ida_y_vuelta(self):
        codigo, d = self.pedir("/api/preferencias")
        self.assertEqual((codigo, d["intervalo_min"], d["intervalos"]),
                         (200, 120, [0, 60, 120, 240, 480]))
        codigo, d = self.pedir("/api/preferencias", {"intervalo_min": 240, "avisos": False})
        self.assertEqual((codigo, d["intervalo_min"], d["avisos"]), (200, 240, False))
        codigo, d = self.pedir("/api/preferencias", {"intervalo_min": 5})
        self.assertEqual(codigo, 400)

    def test_avisos_y_entregados(self):
        # El servidor deja la marca puesta al arrancar: lo de antes no se avisa.
        b = self.busqueda("tras-arrancar")
        codigo, d = self.pedir("/api/avisos")
        self.assertEqual((codigo, d["total"], d["hasta"]), (200, 1, b))
        codigo, d = self.pedir("/api/avisos/entregados", {"hasta": b})
        self.assertEqual((codigo, d["marca"]), (200, b))
        self.assertEqual(self.pedir("/api/avisos")[1]["total"], 0)
        self.assertEqual(self.pedir("/api/avisos/entregados", {})[0], 400)


if __name__ == "__main__":
    unittest.main()
