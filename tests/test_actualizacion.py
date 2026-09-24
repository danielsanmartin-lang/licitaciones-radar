"""Traer una versión nueva sin llevarse por delante los datos de nadie.

Este módulo sustituye ficheros del propio programa a partir de algo descargado de
internet, así que lo que se prueba aquí no es tanto que funcione como que **se niegue a
funcionar** cuando algo no cuadra: si el paquete no es lo que dice ser, lo correcto es
quedarse en la versión vieja, no instalar media.

Y hay dos cosas que jamás puede tocar, porque son el trabajo de la persona y no del
programa: `data/` (la base, el triaje, las notas) y `config/perfiles.json` (los términos
de búsqueda que cada uno ha ido afinando).
"""

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from radar import actualizacion, net


def zip_de_release(destino: Path, version: str, sin=(), extra=None) -> Path:
    """Un zipball como el que sirve GitHub: todo dentro de una carpeta «repo-sha»."""
    base = "danielsanmartin-lang-licitaciones-radar-abc1234"
    contenido = {
        "radar/__init__.py": f'__version__ = "{version}"\n',
        "radar/db.py": "# nuevo\n",
        "web/app.js": "// nuevo\n",
        "radar.py": "# nuevo\n",
        "config/certs/ca-bundle.pem": "# certificados nuevos\n",
        # Ojo: el zip TRAE perfiles.json, como el repositorio real. Que no se instale es
        # justamente lo que hay que comprobar.
        "config/perfiles.json": '{"perfiles": "los de fábrica"}',
    }
    for ruta in sin:
        contenido.pop(ruta, None)
    contenido.update(extra or {})
    with zipfile.ZipFile(destino, "w") as zf:
        for ruta, texto in contenido.items():
            zf.writestr(f"{base}/{ruta}", texto)
    return destino


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.raiz = Path(self.dir.name) / "proyecto"
        (self.raiz / "radar").mkdir(parents=True)
        (self.raiz / "radar" / "__init__.py").write_text('__version__ = "1.0.0"\n')
        (self.raiz / "radar" / "db.py").write_text("# viejo\n")
        (self.raiz / "web").mkdir()
        (self.raiz / "web" / "app.js").write_text("// viejo\n")
        (self.raiz / "radar.py").write_text("# viejo\n")
        (self.raiz / "config").mkdir()
        (self.raiz / "config" / "perfiles.json").write_text('{"mios": "afinados a mano"}')
        (self.raiz / "data").mkdir()
        (self.raiz / "data" / "radar.db").write_text("mi base de 3 GB")

        self.zip = Path(self.dir.name) / "release.zip"
        parches = [
            mock.patch.object(actualizacion, "RAIZ", self.raiz),
            mock.patch.object(actualizacion, "__version__", "1.0.0"),
            # Que no haya ninguna ingesta en marcha: eso tiene su propia prueba.
            mock.patch("radar.busqueda.en_marcha", return_value=None),
        ]
        for p in parches:
            p.start()
            self.addCleanup(p.stop)

    def _release(self, version="1.1.0", notas=""):
        return {"tag_name": version, "body": notas,
                "zipball_url": f"https://api.github.com/x/{version}"}

    def _aplicar(self, release=None, version_del_zip=None, **kw):
        """Simula la descarga entregando el zip que se le haya preparado."""
        release = release or self._release()
        zip_de_release(self.zip, version_del_zip or release["tag_name"], **kw)

        def descarga(url, destino, **_):
            destino.write_bytes(self.zip.read_bytes())
            return destino

        with mock.patch.object(net, "descargar_json", return_value=release), \
             mock.patch.object(net, "descargar_a_fichero", side_effect=descarga) as bajar:
            self.bajar = bajar
            return actualizacion.aplicar()


class TestComparacionDeVersiones(unittest.TestCase):
    def test_se_comparan_como_numeros_y_no_como_texto(self):
        """El fallo clásico: como texto, «1.10» es anterior a «1.9» y el actualizador se
        quedaría clavado para siempre en la versión vieja."""
        self.assertGreater(actualizacion._tupla("1.10.0"), actualizacion._tupla("1.9.0"))

    def test_la_v_de_la_etiqueta_da_igual(self):
        self.assertEqual(actualizacion._tupla("v2.0.1"), actualizacion._tupla("2.0.1"))

    def test_una_version_rara_no_revienta(self):
        self.assertEqual(actualizacion._tupla("1.0-beta"), (1, 0))


class TestComprobar(Base):
    def test_trae_el_sha_que_calcula_github_del_adjunto(self):
        release = {**self._release("1.2.0"), "assets": [
            {"name": "notas.txt", "browser_download_url": "otro", "digest": "sha256:" + "1" * 64},
            {"name": "Radar.de.Licitaciones.1.2.0.zip",
             "browser_download_url": "https://github.com/x/Radar.zip",
             "digest": "sha256:" + "a" * 64},
        ]}
        with mock.patch.object(net, "descargar_json", return_value=release):
            info = actualizacion.comprobar()
        self.assertEqual(info["url_app"], "https://github.com/x/Radar.zip")
        self.assertEqual(info["sha_app"], "a" * 64)

    def test_avisa_cuando_hay_una_mas_nueva(self):
        with mock.patch.object(net, "descargar_json", return_value=self._release("1.2.0")):
            info = actualizacion.comprobar()
        self.assertTrue(info["hay_nueva"])
        self.assertEqual(info["version_nueva"], "1.2.0")

    def test_la_misma_version_no_es_una_nueva(self):
        with mock.patch.object(net, "descargar_json", return_value=self._release("1.0.0")):
            self.assertFalse(actualizacion.comprobar()["hay_nueva"])

    def test_una_release_mas_vieja_no_cuenta(self):
        """Si alguien publica una release antigua, no se degrada la instalación."""
        with mock.patch.object(net, "descargar_json", return_value=self._release("0.9.0")):
            self.assertFalse(actualizacion.comprobar()["hay_nueva"])

    def test_un_404_se_explica_en_castellano(self):
        """Es el caso de hoy: repositorio privado o sin releases. La interfaz llama a
        esto al abrirse, así que no puede lanzar excepciones ni soltar un traceback."""
        error = net.ErrorRed("no existe", codigo=404)
        with mock.patch.object(net, "descargar_json", side_effect=error):
            info = actualizacion.comprobar()
        self.assertFalse(info["hay_nueva"])
        self.assertIn("privado", info["error"])

    def test_sin_internet_devuelve_error_no_excepcion(self):
        with mock.patch.object(net, "descargar_json",
                              side_effect=net.ErrorRed("falló tras 2 intentos")):
            info = actualizacion.comprobar()
        self.assertIsNotNone(info["error"])
        self.assertFalse(info["hay_nueva"])


class TestAplicar(Base):
    def test_sustituye_el_codigo_y_guarda_lo_anterior(self):
        r = self._aplicar(self._release("1.1.0"))
        self.assertTrue(r["ok"], r["mensaje"])
        self.assertEqual((self.raiz / "radar" / "db.py").read_text(), "# nuevo\n")
        self.assertEqual((self.raiz / "web" / "app.js").read_text(), "// nuevo\n")
        # Poder volver atrás importa más que ahorrar 600 kB.
        self.assertEqual((self.raiz / "radar.anterior" / "db.py").read_text(), "# viejo\n")

    def test_no_toca_la_base_ni_el_triaje(self):
        self._aplicar()
        self.assertEqual((self.raiz / "data" / "radar.db").read_text(), "mi base de 3 GB")

    def test_el_zipball_se_baja_con_dos_intentos_y_no_con_cuatro(self):
        """`aplicar_en_subproceso` mata el proceso a los 900 s. Con los cuatro intentos
        por defecto de `descargar_a_fichero` (600 s de timeout cada uno) el peor caso se
        come el plazo y la actualización muere a mitad."""
        self._aplicar()
        self.assertEqual(self.bajar.call_args.kwargs["intentos"], 2)

    def test_no_toca_los_terminos_de_busqueda(self):
        """La prueba que justifica la lista blanca: el zip trae `perfiles.json` con los
        valores de fábrica, y aun así los del usuario tienen que seguir ahí. Perderlos
        sería borrarle meses de ajuste fino a cada compañero."""
        self._aplicar()
        self.assertEqual(json.loads((self.raiz / "config" / "perfiles.json").read_text()),
                         {"mios": "afinados a mano"})

    def test_los_certificados_si_se_actualizan(self):
        """Caducan, y si se quedan atrás PLACSP deja de validar."""
        self._aplicar()
        self.assertIn("nuevos",
                      (self.raiz / "config" / "certs" / "ca-bundle.pem").read_text())

    def test_estar_al_dia_no_toca_nada(self):
        with mock.patch.object(net, "descargar_json", return_value=self._release("1.0.0")):
            r = actualizacion.aplicar()
        self.assertTrue(r["ok"])
        self.assertTrue(r["sin_cambios"])
        self.assertEqual((self.raiz / "radar" / "db.py").read_text(), "# viejo\n")

    def test_si_la_etiqueta_y_el_codigo_no_coinciden_no_se_instala(self):
        """Defensa contra un paquete que no es lo que dice ser: la release anuncia 1.1.0
        y dentro viene otra cosa."""
        r = self._aplicar(self._release("1.1.0"), version_del_zip="9.9.9")
        self.assertFalse(r["ok"])
        self.assertIn("no se toca nada", r["mensaje"].lower())
        self.assertEqual((self.raiz / "radar" / "db.py").read_text(), "# viejo\n")

    def test_un_zip_al_que_le_falta_media_aplicacion_no_se_instala(self):
        r = self._aplicar(sin=("web/app.js",))
        self.assertFalse(r["ok"])
        self.assertIn("web", r["mensaje"])
        self.assertEqual((self.raiz / "web" / "app.js").read_text(), "// viejo\n")

    def test_el_zipball_no_se_compara_con_el_sha_de_las_notas(self):
        """El único SHA que llevan las notas es el del .app adjunto, y el zipball lo
        genera GitHub al vuelo. Compararlos bloqueaba la v1.5.0 en toda copia de
        trabajo: la descarga era buena y el actualizador se negaba igual."""
        otro = "560d4eca52d6434fa2e53a908d4afcc974364ba2b771ce6aa99c8fc2c370bf35"
        r = self._aplicar(self._release("1.1.0", notas=f"SHA-256 del zip: `{otro}`"))
        self.assertTrue(r["ok"], r["mensaje"])
        self.assertEqual((self.raiz / "radar" / "db.py").read_text(), "# nuevo\n")

    def test_cuenta_por_donde_va(self):
        """La pantalla de arranque pinta lo que se publica con `progreso`: sin fases,
        una instalación que está sustituyendo ficheros se vería parada."""
        fases = []
        with mock.patch.object(actualizacion.progreso, "fase", side_effect=fases.append):
            r = self._aplicar()
        self.assertTrue(r["ok"], r["mensaje"])
        self.assertEqual(fases, ["comprobando", "verificando", "sustituyendo"])

    def test_lo_descargado_que_no_es_un_zip_no_se_instala(self):
        def descarga(url, destino, **_):
            destino.write_text("<html>error del proxy</html>")
            return destino

        with mock.patch.object(net, "descargar_json", return_value=self._release()), \
             mock.patch.object(net, "descargar_a_fichero", side_effect=descarga):
            r = actualizacion.aplicar()
        self.assertFalse(r["ok"])
        self.assertEqual((self.raiz / "radar" / "db.py").read_text(), "# viejo\n")

    def test_no_se_actualiza_con_una_descarga_en_marcha(self):
        """Cambiar el código por debajo de una carga inicial de dos horas es pedir que
        la mitad de la ingesta corra con una versión y la otra mitad con otra."""
        with mock.patch("radar.busqueda.en_marcha",
                        return_value={"pid": 123, "iniciada": "2026-08-17T09:34:06+00:00"}):
            r = actualizacion.aplicar()
        self.assertFalse(r["ok"])
        self.assertIn("descarga en marcha", r["mensaje"])

    def test_si_falla_a_mitad_se_deshace_lo_hecho(self):
        """Media instalación es peor que una versión vieja: si el intercambio revienta
        con `web` ya movido, hay que devolver todo a su sitio."""
        real = actualizacion.shutil.move
        llamadas = []

        def move_que_falla(origen, destino):
            llamadas.append(destino)
            if len(llamadas) == 2:
                raise OSError("disco lleno")
            return real(origen, destino)

        zip_de_release(self.zip, "1.1.0")

        def descarga(url, destino, **_):
            destino.write_bytes(self.zip.read_bytes())
            return destino

        with mock.patch.object(net, "descargar_json", return_value=self._release("1.1.0")), \
             mock.patch.object(net, "descargar_a_fichero", side_effect=descarga), \
             mock.patch.object(actualizacion.shutil, "move", side_effect=move_que_falla):
            r = actualizacion.aplicar()

        self.assertFalse(r["ok"])
        self.assertIn("como estaba", r["mensaje"])
        self.assertEqual((self.raiz / "radar" / "db.py").read_text(), "# viejo\n")
        self.assertEqual((self.raiz / "web" / "app.js").read_text(), "// viejo\n")
        self.assertFalse((self.raiz / "radar.anterior").exists(),
                         "el respaldo tiene que volver a su sitio, no quedarse suelto")


def zip_de_app(destino: Path, version: str, identificador="app.zepo.licitaciones-radar",
               sin=()) -> Path:
    """Un «Radar de Licitaciones X.zip» como el que deja `construir_app.py --zip`."""
    import plistlib

    base = "Radar de Licitaciones.app/Contents"
    contenido = {
        f"{base}/Info.plist": plistlib.dumps({
            "CFBundleIdentifier": identificador,
            "CFBundleShortVersionString": version,
        }),
        f"{base}/MacOS/radar": b"binario",
        f"{base}/Resources/radar.py": b"# nuevo",
        f"{base}/Resources/radar/__init__.py": f'__version__ = "{version}"'.encode(),
        f"{base}/Resources/web/app.js": b"// nuevo",
    }
    with zipfile.ZipFile(destino, "w") as zf:
        for ruta, datos in contenido.items():
            if not any(ruta.endswith(q) for q in sin):
                zf.writestr(ruta, datos)
    return destino


class TestAppEmpaquetada(unittest.TestCase):
    """La app que lleva el programa dentro se actualiza cambiándola entera.

    Python la baja y la comprueba; el cambio de un bundle por otro lo hace la ventana al
    cerrarse. Lo que se prueba aquí es la primera mitad, y sobre todo que se niegue a
    dejar preparado cualquier cosa que no sea exactamente la versión anunciada.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.datos = Path(self.dir.name) / "Application Support" / "actualizacion"
        self.zip = Path(self.dir.name) / "adjunto.zip"
        parches = [
            mock.patch.object(actualizacion.rutas, "empaquetada", return_value=True),
            mock.patch.object(actualizacion, "DIR_APP", self.datos),
            mock.patch.object(actualizacion, "FALLO_APP", self.datos / "fallo.txt"),
            mock.patch("radar.busqueda.en_marcha", return_value=None),
            # `ditto` no existe en el Linux de la integración continua; para lo que se
            # prueba aquí da igual con qué se descomprima.
            mock.patch.object(actualizacion, "_descomprimir_app",
                              side_effect=lambda z, d: zipfile.ZipFile(z).extractall(d)),
        ]
        for p in parches:
            p.start()
            self.addCleanup(p.stop)

    def _info(self, **cambios):
        info = {"version_actual": "1.0.0", "version_nueva": "v1.1.0", "hay_nueva": True,
                "error": None, "notas": "", "url_zip": "https://api.github.com/zipball",
                "url_app": "https://github.com/x/Radar.zip", "sha_app": None,
                "url_release": "https://github.com/x/releases/tag/v1.1.0"}
        info.update(cambios)
        return info

    def _aplicar(self, info=None, version_del_zip="1.1.0", **kw):
        zip_de_app(self.zip, version_del_zip, **kw)

        def descarga(url, destino, **_):
            destino.write_bytes(self.zip.read_bytes())
            return destino

        with mock.patch.object(actualizacion, "comprobar", return_value=info or self._info()), \
             mock.patch.object(net, "descargar_a_fichero", side_effect=descarga) as bajar:
            self.bajar = bajar
            return actualizacion.aplicar()

    def test_deja_la_app_preparada_y_dice_donde(self):
        r = self._aplicar()
        self.assertTrue(r["ok"], r["mensaje"])
        app = Path(r["app_nueva"])
        self.assertEqual(app.name, "Radar de Licitaciones.app")
        self.assertTrue((app / "Contents" / "MacOS" / "radar").exists())
        self.assertTrue(str(app).startswith(str(self.datos)),
                        "la app nueva se prepara en la carpeta de datos, fuera del bundle")
        self.assertFalse((self.datos / "nueva.zip").exists(), "el zip no se queda tirado")
        self.assertEqual(self.bajar.call_args.args[0], "https://github.com/x/Radar.zip")

    def test_no_baja_el_zipball(self):
        """El zipball es código suelto: a una app empaquetada no le sirve de nada."""
        self._aplicar()
        self.assertNotIn("zipball", self.bajar.call_args.args[0])

    def test_el_sha_de_github_manda(self):
        r = self._aplicar(self._info(sha_app="0" * 64))
        self.assertFalse(r["ok"])
        self.assertIn("SHA-256", r["mensaje"])
        self.assertFalse((self.datos / "nueva").exists())

    def test_sin_digest_vale_el_sha_de_las_notas(self):
        zip_de_app(self.zip, "1.1.0")
        sha = actualizacion._sha256(self.zip)
        r = self._aplicar(self._info(notas=f"SHA-256 del zip: `{sha}`"))
        self.assertTrue(r["ok"], r["mensaje"])
        r = self._aplicar(self._info(notas=f"SHA-256 del zip: `{'f' * 64}`"))
        self.assertFalse(r["ok"])

    def test_una_app_con_otra_version_no_se_prepara(self):
        r = self._aplicar(version_del_zip="1.0.9")
        self.assertFalse(r["ok"])
        self.assertIn("1.0.9", r["mensaje"])
        self.assertFalse((self.datos / "nueva").exists())

    def test_una_app_que_no_es_esta_no_se_prepara(self):
        r = self._aplicar(identificador="com.otro.programa")
        self.assertFalse(r["ok"])
        self.assertIn("com.otro.programa", r["mensaje"])

    def test_una_app_a_medias_no_se_prepara(self):
        r = self._aplicar(sin=("Resources/radar.py",))
        self.assertFalse(r["ok"])
        self.assertIn("radar.py", r["mensaje"])

    def test_sin_adjunto_se_dice_y_se_da_la_pagina(self):
        """Si alguien publica una versión y se olvida de subir el .app, esta copia no
        puede actualizarse sola: al menos se dice por qué y dónde está."""
        r = self._aplicar(self._info(url_app=None))
        self.assertFalse(r["ok"])
        self.assertEqual(r["url"], "https://github.com/x/releases/tag/v1.1.0")
        self.bajar.assert_not_called()

    def test_tras_un_fallo_reciente_no_se_reintenta_en_bucle(self):
        """Si la ventana no pudo cambiar el bundle —/Applications sin ser
        administrador—, reabre la vieja. Sin esto la vieja vería la versión nueva, la
        prepararía, se cerraría, fallaría otra vez… para siempre."""
        self.datos.mkdir(parents=True)
        (self.datos / "fallo.txt").write_text("v1.1.0\nmv: Permission denied\n")
        r = self._aplicar()
        self.assertFalse(r["ok"])
        self.assertIn("Permission denied", r["mensaje"])
        self.bajar.assert_not_called()

    def test_el_fallo_de_otra_version_o_de_hace_dias_no_cuenta(self):
        import os
        self.datos.mkdir(parents=True)
        fallo = self.datos / "fallo.txt"
        fallo.write_text("1.0.5\nmv: Permission denied\n")
        self.assertTrue(self._aplicar()["ok"])

        fallo.write_text("1.1.0\nmv: Permission denied\n")
        viejo = fallo.stat().st_mtime - 2 * 24 * 3600
        os.utime(fallo, (viejo, viejo))
        self.assertTrue(self._aplicar()["ok"])

    def test_con_una_descarga_en_marcha_tampoco(self):
        """Cambiar el bundle entero debajo de una ingesta que corre desde él es lo
        mismo que cambiarle los ficheros."""
        with mock.patch("radar.busqueda.en_marcha", return_value={"pid": 1, "iniciada": "hoy"}):
            r = self._aplicar()
        self.assertFalse(r["ok"])
        self.bajar.assert_not_called()


class TestSegundoPlano(unittest.TestCase):
    """La pantalla de arranque lanza la instalación y va preguntando cómo va."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        d = Path(self.dir.name)
        for nombre, valor in (("CERROJO", d / "actualizacion.lock"),
                              ("REGISTRO", d / "actualizacion.log"),
                              ("PROGRESO", d / "actualizacion-progreso.json"),
                              ("_HIJO", None)):
            p = mock.patch.object(actualizacion, nombre, valor)
            p.start()
            self.addCleanup(p.stop)
        self.d = d

    def test_lanza_la_cli_y_no_espera(self):
        proceso = mock.Mock(pid=4321)
        with mock.patch.object(actualizacion.subprocess, "Popen", return_value=proceso) as popen:
            r = actualizacion.lanzar()
        self.assertTrue(r["ok"])
        orden = popen.call_args.args[0]
        self.assertEqual(orden[-2:], ["actualizar", "--json"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"],
                        "tiene que sobrevivir al reinicio del servidor")
        self.assertEqual(json.loads((self.d / "actualizacion.lock").read_text())["pid"], 4321)

    def test_un_hijo_terminado_no_cuenta_como_en_marcha(self):
        """Un hijo que acaba y nadie recoge es un zombi, y `kill(pid, 0)` dice que un
        zombi está vivo. La pantalla se quedaba en «Instalando» para siempre."""
        import sys
        proceso = actualizacion.subprocess.Popen([sys.executable, "-c", "pass"])
        proceso.wait()
        (self.d / "actualizacion.lock").write_text(json.dumps({"pid": proceso.pid}))
        with mock.patch.object(actualizacion, "_HIJO", proceso):
            self.assertIsNone(actualizacion.en_marcha())

    def test_la_instalacion_suelta_su_propio_cerrojo(self):
        import os
        (self.d / "actualizacion.lock").write_text(json.dumps({"pid": os.getpid()}))
        actualizacion.soltar_cerrojo()
        self.assertFalse((self.d / "actualizacion.lock").exists())

    def test_y_no_el_de_otro(self):
        (self.d / "actualizacion.lock").write_text(json.dumps({"pid": 1}))
        actualizacion.soltar_cerrojo()
        self.assertTrue((self.d / "actualizacion.lock").exists())

    def test_dos_ventanas_no_lanzan_dos_instalaciones(self):
        import os
        (self.d / "actualizacion.lock").write_text(json.dumps({"pid": os.getpid()}))
        with mock.patch.object(actualizacion.subprocess, "Popen") as popen:
            r = actualizacion.lanzar()
        self.assertTrue(r["ya_en_marcha"])
        popen.assert_not_called()

    def test_en_marcha_da_el_progreso(self):
        import os
        (self.d / "actualizacion.lock").write_text(json.dumps({"pid": os.getpid()}))
        (self.d / "actualizacion-progreso.json").write_text(
            json.dumps({"fase": "descargando", "bytes": 10}))
        e = actualizacion.estado()
        self.assertTrue(e["en_marcha"])
        self.assertEqual(e["detalle"]["bytes"], 10)
        self.assertIsNone(e["resultado"])
        self.assertEqual(e["version"], actualizacion.__version__)

    def test_al_terminar_da_lo_que_dijo_la_cli(self):
        """Un cerrojo de un proceso que ya no existe es una instalación terminada: el
        resultado es la última línea JSON de lo que imprimió."""
        (self.d / "actualizacion.lock").write_text(json.dumps({"pid": 999999}))
        (self.d / "actualizacion.log").write_text(
            "Descargando la versión 1.6.0...\n  ... progreso\n"
            + json.dumps({"ok": True, "version_nueva": "1.6.0"}) + "\n")
        with mock.patch.object(actualizacion, "_proceso_vivo", return_value=False):
            e = actualizacion.estado()
        self.assertFalse(e["en_marcha"])
        self.assertEqual(e["resultado"], {"ok": True, "version_nueva": "1.6.0"})
        self.assertFalse((self.d / "actualizacion.lock").exists())

    def test_si_revienta_sin_json_se_cuenta_lo_que_escribio(self):
        (self.d / "actualizacion.log").write_text("Traceback...\nKeyError: 'x'\n")
        e = actualizacion.estado()
        self.assertFalse(e["resultado"]["ok"])
        self.assertIn("KeyError", e["resultado"]["mensaje"])


class TestReinicio(unittest.TestCase):
    def test_el_servidor_vuelve_sin_abrir_otra_pestana(self):
        """`start.command` arranca `serve` sin `--sin-navegador`: sin añadirlo, cada
        actualización abriría otra pestaña con la bandeja."""
        orden = actualizacion.orden_de_reinicio(["radar.py", "serve"])
        self.assertEqual(orden[-2:], ["serve", "--sin-navegador"])
        self.assertTrue(orden[-3].endswith("radar.py"))
        self.assertTrue(Path(orden[-3]).is_absolute())

    def test_no_duplica_lo_que_ya_llevaba(self):
        orden = actualizacion.orden_de_reinicio(
            ["radar.py", "serve", "--sin-navegador", "--puerto", "8811"])
        self.assertEqual(orden.count("--sin-navegador"), 1)
        self.assertEqual(orden[-2:], ["--puerto", "8811"])


if __name__ == "__main__":
    unittest.main()
