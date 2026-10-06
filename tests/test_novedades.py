"""Las novedades que enseña la pantalla de arranque después de actualizarse.

Lo que se protege: que se sepa cuándo la aplicación acaba de cambiar de versión —y solo
entonces—, que las notas sean las de las versiones que de verdad se han saltado, y que
lo que llega de GitHub se convierta en bloques de texto y no en HTML.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from radar import db, net, novedades


def release(tag: str, cuerpo: str = "", **kw) -> dict:
    base = {"tag_name": tag, "name": f"{tag} — Algo nuevo", "body": cuerpo,
            "published_at": "2026-10-06T13:10:41Z",
            "html_url": f"https://github.com/x/y/releases/tag/{tag}"}
    base.update(kw)
    return base


LISTA = [release("v1.8.0", "## Novedad\\n\\n- uno"), release("v1.7.0"),
         release("v1.6.0"), release("v1.5.0"),
         release("v1.9.0-rc", prerelease=True), release("v1.7.5", draft=True)]


class TestBloques(unittest.TestCase):
    def test_titulos_puntos_y_parrafos(self):
        b = novedades.bloques(
            "## Otras licitaciones\n\nUna pestaña **nueva** con\ntodo lo demás.\n\n"
            "- Ciberseguridad\n- Cloud y `hosting`\n\n### Arreglado\n1. Un fallo")
        self.assertEqual(b, [
            {"tipo": "titulo", "texto": "Otras licitaciones"},
            {"tipo": "parrafo", "texto": "Una pestaña **nueva** con todo lo demás."},
            {"tipo": "punto", "texto": "Ciberseguridad"},
            {"tipo": "punto", "texto": "Cloud y `hosting`"},
            {"tipo": "titulo", "texto": "Arreglado"},
            {"tipo": "punto", "texto": "Un fallo"},
        ])

    def test_la_linea_del_sha_no_se_ensena(self):
        b = novedades.bloques("Hola.\n\nSHA-256: `" + "a" * 64 + "`")
        self.assertEqual(b, [{"tipo": "parrafo", "texto": "Hola."}])

    def test_los_enlaces_se_quedan_en_su_texto(self):
        b = novedades.bloques("- Ver [la release](https://example.com)")
        self.assertEqual(b, [{"tipo": "punto", "texto": "Ver la release"}])

    def test_la_continuacion_sangrada_va_con_su_punto(self):
        b = novedades.bloques("- **Si usas la app**, se cambia\n  entera por la nueva.")
        self.assertEqual(b, [{"tipo": "punto",
                              "texto": "**Si usas la app**, se cambia entera por la nueva."}])

    def test_sin_notas_no_hay_bloques(self):
        self.assertEqual(novedades.bloques(""), [])
        self.assertEqual(novedades.bloques(None), [])


class TestNotas(unittest.TestCase):
    def notas(self, desde, hasta, lista=LISTA):
        with mock.patch.object(net, "descargar_json", return_value=lista):
            return novedades.notas(desde, hasta)

    def test_solo_las_versiones_saltadas_la_mas_nueva_primero(self):
        n = self.notas("1.6.0", "1.8.0")
        self.assertEqual([v["version"] for v in n["versiones"]], ["1.8.0", "1.7.0"])
        self.assertEqual(n["versiones"][0]["titulo"], "Algo nuevo")
        self.assertEqual(n["versiones"][0]["fecha"], "2026-10-06")
        self.assertIsNone(n["error"])

    def test_ni_borradores_ni_previas(self):
        n = self.notas("1.6.0", "2.0.0")
        self.assertNotIn("1.9.0-rc", [v["version"] for v in n["versiones"]])
        self.assertNotIn("1.7.5", [v["version"] for v in n["versiones"]])

    def test_sin_desde_solo_la_version_a_la_que_se_ha_llegado(self):
        n = self.notas(None, "1.7.0")
        self.assertEqual([v["version"] for v in n["versiones"]], ["1.7.0"])

    def test_se_corta_y_se_dice_cuantas_quedan(self):
        lista = [release(f"v1.{i}.0") for i in range(10)]
        with mock.patch.object(novedades, "MAXIMO_VERSIONES", 3):
            n = self.notas("1.0.0", "1.9.0", lista)
        self.assertEqual([v["version"] for v in n["versiones"]], ["1.9.0", "1.8.0", "1.7.0"])
        self.assertEqual(n["mas_antiguas"], 6)

    def test_sin_red_no_lanza_y_deja_el_enlace(self):
        with mock.patch.object(net, "descargar_json", side_effect=net.ErrorRed("caída")):
            n = novedades.notas("1.6.0", "1.8.0")
        self.assertEqual(n["versiones"], [])
        self.assertTrue(n["error"])
        self.assertTrue(n["url"].endswith("/releases"))


class TestRecienActualizada(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.con = db.conectar(Path(self.dir.name) / "t.db")
        self.addCleanup(self.con.close)
        for parche in (
            mock.patch.object(novedades, "__version__", "1.8.0"),
            mock.patch.object(novedades.actualizacion, "RAIZ", Path(self.dir.name)),
            mock.patch.object(novedades.actualizacion, "_resultado", return_value=None),
        ):
            parche.start()
            self.addCleanup(parche.stop)

    def test_una_version_vista_anterior_es_una_actualizacion(self):
        db.escribir_preferencia(self.con, novedades.CLAVE_VISTA, "1.6.0")
        self.assertEqual(novedades.recien_actualizada(self.con),
                         {"desde": "1.6.0", "hasta": "1.8.0"})

    def test_la_misma_version_no(self):
        db.escribir_preferencia(self.con, novedades.CLAVE_VISTA, "1.8.0")
        self.assertIsNone(novedades.recien_actualizada(self.con))

    def test_marcarla_la_da_por_vista(self):
        db.escribir_preferencia(self.con, novedades.CLAVE_VISTA, "1.6.0")
        novedades.marcar_vista(self.con)
        self.assertIsNone(novedades.recien_actualizada(self.con))

    def test_una_instalacion_nueva_no_tiene_novedades(self):
        self.assertIsNone(novedades.recien_actualizada(self.con))

    def test_la_primera_actualizacion_se_reconoce_por_el_registro(self):
        """La base viene de una versión que todavía no apuntaba la vista: lo que dice
        que ha habido actualización es el registro del actualizador."""
        resultado = {"ok": True, "version_nueva": "v1.8.0"}
        with mock.patch.object(novedades.actualizacion, "_resultado",
                               return_value=resultado):
            self.assertEqual(novedades.recien_actualizada(self.con),
                             {"desde": None, "hasta": "1.8.0"})

    def test_y_en_la_copia_de_trabajo_se_sabe_desde_cual(self):
        anterior = Path(self.dir.name) / "radar.anterior"
        anterior.mkdir()
        (anterior / "__init__.py").write_text('"""x"""\n\n__version__ = "1.6.0"\n')
        resultado = {"ok": True, "version_nueva": "1.8.0"}
        with mock.patch.object(novedades.actualizacion, "_resultado",
                               return_value=resultado):
            self.assertEqual(novedades.recien_actualizada(self.con)["desde"], "1.6.0")

    def test_un_registro_de_otra_version_o_fallido_no_cuenta(self):
        for resultado in ({"ok": True, "version_nueva": "1.7.0"},
                          {"ok": False, "version_nueva": "1.8.0"},
                          {"ok": True, "sin_cambios": True, "version_nueva": "1.8.0"}):
            with self.subTest(resultado=resultado), \
                 mock.patch.object(novedades.actualizacion, "_resultado",
                                   return_value=resultado):
                self.assertIsNone(novedades.recien_actualizada(self.con))


if __name__ == "__main__":
    unittest.main()
