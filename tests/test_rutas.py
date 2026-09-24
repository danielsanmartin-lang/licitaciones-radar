"""Dónde está el código y dónde se escriben los datos.

Esto se separó para poder repartir el programa como **un solo fichero**: el `.app` lleva
`radar/`, `web/` y los certificados dentro, y por tanto el código vive en un sitio donde
no se puede escribir —puede estar en `/Applications`, puede estar firmado, y la
actualización lo sustituye entero—. La base de datos de alguien no puede vivir ahí.

Lo que se protege aquí son las dos mitades del trato:

1. Que una **copia de trabajo** no note nada: misma base, mismo `perfiles.json`, mismas
   rutas que antes. Nadie tiene que mover sus 3,5 GB.
2. Que la copia **empaquetada** no escriba jamás dentro del bundle.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

from radar import actualizacion, rutas

RAIZ = Path(__file__).resolve().parent.parent

APP = Path("/Applications/Radar de Licitaciones.app/Contents/Resources")
CHECKOUT = Path("/Users/alguien/proyectos/licitaciones-radar")


class TestDondeVanLosDatos(unittest.TestCase):
    def test_una_copia_de_trabajo_no_cambia_de_sitio(self):
        """La regla que protege lo que ya existe: si el código no está dentro de un
        `.app`, los datos siguen colgando de la carpeta del proyecto, exactamente como
        antes de que esto se pudiera empaquetar."""
        self.assertEqual(rutas.raiz_datos({}, CHECKOUT), CHECKOUT)

    def test_este_mismo_proyecto_es_una_copia_de_trabajo(self):
        """Y por tanto la base sigue en `data/radar.db` dentro del repositorio."""
        self.assertFalse(rutas.empaquetada())
        self.assertEqual(rutas.DATOS, RAIZ)
        self.assertEqual(rutas.BD, RAIZ / "data" / "radar.db")
        self.assertEqual(rutas.PERFILES, RAIZ / "config" / "perfiles.json")

    def test_dentro_de_un_app_los_datos_van_a_application_support(self):
        destino = rutas.raiz_datos({}, APP)
        self.assertEqual(destino.name, rutas.NOMBRE_APP)
        self.assertEqual(destino.parent.name, "Application Support")
        self.assertEqual(destino.parent.parent.name, "Library")

    def test_la_variable_de_entorno_manda_sobre_todo(self):
        """La usan estos tests y quien quiera llevarse la base a un disco externo."""
        self.assertEqual(
            rutas.raiz_datos({rutas.VAR_ENTORNO: "/tmp/otra"}, CHECKOUT), Path("/tmp/otra"))
        self.assertEqual(
            rutas.raiz_datos({rutas.VAR_ENTORNO: "/tmp/otra"}, APP), Path("/tmp/otra"),
            "también dentro del bundle")

    def test_una_variable_vacia_no_cuenta(self):
        """`RADAR_DATOS=` en el entorno no debe mandar los datos a la raíz del disco."""
        for vacia in ("", "   "):
            self.assertEqual(rutas.raiz_datos({rutas.VAR_ENTORNO: vacia}, CHECKOUT), CHECKOUT)


class TestDetectarElBundle(unittest.TestCase):
    """Se mira si hay un `.app` por encima, no si la carpeta es escribible.

    La versión «¿puedo escribir aquí?» de esta regla parece más lista y es peor: un
    `.app` en el Escritorio SÍ es escribible, así que dejaría la base dentro del bundle,
    donde la borra la primera actualización.
    """

    def test_reconoce_el_bundle_este_donde_este(self):
        for sitio in (
            "/Applications/Radar de Licitaciones.app/Contents/Resources",
            "/Users/alguien/Desktop/Radar de Licitaciones.app/Contents/Resources",
            "/Users/alguien/Downloads/Radar.app/Contents/Resources/radar",
        ):
            with self.subTest(sitio=sitio):
                self.assertTrue(rutas.empaquetada(Path(sitio)))

    def test_no_confunde_una_carpeta_normal(self):
        for sitio in ("/Users/alguien/proyectos/licitaciones-radar",
                      "/Users/alguien/apps/licitaciones",
                      "/opt/radar"):
            with self.subTest(sitio=sitio):
                self.assertFalse(rutas.empaquetada(Path(sitio)))


class TestLoQueSeLeeYLoQueSeEscribe(unittest.TestCase):
    def test_lo_de_solo_lectura_cuelga_del_codigo(self):
        """`web/`, los certificados y la plantilla van donde esté el código: dentro del
        bundle si está empaquetado."""
        for ruta in (rutas.WEB, rutas.CERTIFICADOS, rutas.PERFILES_PLANTILLA,
                     rutas.ENTRADA_CLI):
            self.assertTrue(str(ruta).startswith(str(rutas.CODIGO)), ruta)

    def test_lo_que_se_escribe_cuelga_de_los_datos(self):
        for ruta in (rutas.BD, rutas.CACHE, rutas.PERFILES):
            self.assertTrue(str(ruta).startswith(str(rutas.DATOS)), ruta)

    def test_los_perfiles_editables_no_son_la_plantilla(self):
        """La plantilla se lee y el fichero de cada uno se escribe: no pueden ser el
        mismo sitio, o actualizar la app le borraría a alguien sus términos."""
        self.assertNotEqual(rutas.PERFILES, rutas.PERFILES_PLANTILLA)

    def test_preparar_es_idempotente(self):
        rutas.preparar()
        rutas.preparar()
        self.assertTrue(rutas.DIR_DATOS.is_dir())
        self.assertTrue(rutas.DIR_CONFIG.is_dir())


class TestElBundleNoSeLlevaDatosDeNadie(unittest.TestCase):
    """Lo que se copia dentro del `.app` es una lista blanca, y esto lo vigila.

    Es el test más importante de este fichero. Si `config/perfiles.json` o `data/`
    entraran en el bundle, mandar la app a un compañero sería mandarle los términos
    afinados durante meses y, peor, el triaje y las notas de cada oportunidad.
    """

    def setUp(self):
        ruta = RAIZ / "herramientas" / "construir_app.py"
        esp = importlib.util.spec_from_file_location("construir_app", ruta)
        self.constructor = importlib.util.module_from_spec(esp)
        esp.loader.exec_module(self.constructor)

    def test_nunca_entra_la_base_ni_el_triaje(self):
        for entrada in self.constructor.DENTRO_DEL_BUNDLE:
            self.assertFalse(entrada == "data" or entrada.startswith("data/"), entrada)

    def test_nunca_entran_los_terminos_de_nadie(self):
        self.assertNotIn("config/perfiles.json", self.constructor.DENTRO_DEL_BUNDLE)
        self.assertNotIn("config", self.constructor.DENTRO_DEL_BUNDLE,
                         "«config» entero arrastraría perfiles.json dentro")

    def test_si_entra_lo_imprescindible_para_arrancar(self):
        for necesario in ("radar", "radar.py", "web"):
            self.assertIn(necesario, self.constructor.DENTRO_DEL_BUNDLE)

    def test_entra_la_plantilla_de_terminos(self):
        """Sin ella, un compañero no tendría de dónde crear su `perfiles.json`."""
        self.assertIn("config/perfiles.ejemplo.json", self.constructor.DENTRO_DEL_BUNDLE)

    def test_no_se_cuela_el_bytecode(self):
        self.assertIn("__pycache__", self.constructor.NO_COPIAR)


class TestActualizarLaAppEmpaquetada(unittest.TestCase):
    """Una app que lleva el código dentro no puede sustituirse a sí misma: se cambia
    entera. Cómo se prepara esa app nueva se prueba en `test_actualizacion`."""

    def test_empaquetada_y_al_dia_no_molesta(self):
        with mock.patch.object(rutas, "empaquetada", return_value=True), \
             mock.patch("radar.busqueda.en_marcha", return_value=None), \
             mock.patch.object(actualizacion, "comprobar", return_value={
                 "version_actual": "9.9.9", "hay_nueva": False, "error": None}):
            r = actualizacion.aplicar()
        self.assertTrue(r["ok"])
        self.assertTrue(r["sin_cambios"])

    def test_el_adjunto_se_busca_por_nombre(self):
        """Una release puede llevar varios ficheros adjuntos."""
        self.assertEqual(
            actualizacion._app_publicada({"assets": [
                {"name": "notas.txt", "browser_download_url": "no"},
                {"name": "checksums.sha256", "browser_download_url": "no"},
                {"name": "Radar-de-Licitaciones-1.4.0.zip", "browser_download_url": "sí"},
            ]}), "sí")
        self.assertIsNone(actualizacion._app_publicada({"assets": []}))
        self.assertIsNone(actualizacion._app_publicada({}))

    def test_una_copia_de_trabajo_sigue_actualizandose_en_su_sitio(self):
        """La otra mitad: quien trabaja con el repositorio sigue actualizándose
        sustituyendo ficheros, sin necesitar el .app adjunto."""
        self.assertFalse(rutas.empaquetada())
        self.assertEqual(actualizacion.RAIZ, rutas.CODIGO)


if __name__ == "__main__":
    unittest.main()
