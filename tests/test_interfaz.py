"""La interfaz: que el marcado, el JavaScript y la hoja de estilo sigan hablando entre sí.

No hay navegador en las pruebas, así que esto no mira cómo se ve nada. Protege lo que se
rompe en silencio al mover marcado o renombrar una clase:

- `app.js` busca los elementos por id. Si un id desaparece de `index.html`, la llamada
  devuelve `null` y la vista entera deja de pintarse, sin error en ninguna prueba.
- Las clases son una API entre `app.js` y `styles.css` (lo dice la cabecera de la hoja):
  una clase que se genera y no tiene regla sale sin estilo.
- Hay valores que viven en dos sitios a propósito y tienen que coincidir: la franja de
  la barra de título integrada (CSS y Swift) y el ancho a partir del cual la ficha deja
  de caber al lado de la lista (CSS y JavaScript).
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
HTML = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
JS = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
CSS = (RAIZ / "web" / "styles.css").read_text(encoding="utf-8")
SWIFT = (RAIZ / "macos" / "Radar.swift").read_text(encoding="utf-8")

CSS_SIN_COMENTARIOS = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
HTML_SIN_COMENTARIOS = re.sub(r"<!--.*?-->", "", HTML, flags=re.S)

# Clases que `app.js` pone como enganche y no como aspecto: no necesitan regla.
CLASES_SIN_ESTILO = {"principal", "titulo"}


def _clases_del_css() -> set[str]:
    return set(re.findall(r"\.([a-zA-Z][\w-]*)", CSS_SIN_COMENTARIOS))


def _clases_del_js() -> set[str]:
    clases: set[str] = set()
    for m in re.findall(r'class="([^"$]*)"', JS):
        clases |= set(m.split())
    for m in re.findall(r"className\s*=\s*'([^'$]*)'", JS):
        clases |= set(m.split())
    for m in re.findall(r"classList\.(?:add|toggle|remove)\('([^']+)'", JS):
        clases.add(m)
    for m in re.findall(r"\bclase:\s*'([^']+)'", JS):
        clases |= set(m.split())
    return clases


class TestIds(unittest.TestCase):
    def test_todo_id_que_busca_app_js_existe(self):
        pedidos = set(re.findall(r"\$\('([\w-]+)'\)", JS))
        pedidos |= set(re.findall(r"getElementById\('([\w-]+)'\)", JS))
        # Los que crea el propio `app.js` al pintar (la ficha, sobre todo) también valen.
        definidos = set(re.findall(r'\bid="([\w-]+)"', HTML_SIN_COMENTARIOS))
        definidos |= set(re.findall(r'\bid="([\w-]+)"', JS))
        self.assertEqual(sorted(pedidos - definidos), [])

    def test_los_ids_no_se_repiten(self):
        ids = re.findall(r'\bid="([\w-]+)"', HTML_SIN_COMENTARIOS)
        repetidos = sorted({i for i in ids if ids.count(i) > 1})
        self.assertEqual(repetidos, [])


class TestVistas(unittest.TestCase):
    def setUp(self):
        self.en_lateral = re.findall(r'data-vista="([\w-]+)"', HTML_SIN_COMENTARIOS)

    def test_cada_vista_de_la_barra_lateral_tiene_su_seccion_y_su_cabecera(self):
        simbolos = set(re.findall(r'<symbol id="([\w-]+)"', HTML))
        tonos = {c[len("tono-"):] for c in _clases_del_css() if c.startswith("tono-")}
        for vista in self.en_lateral:
            with self.subTest(vista=vista):
                m = re.search(rf'<section id="vista-{vista}"([^>]*)>', HTML)
                self.assertIsNotNone(m, f"falta <section id='vista-{vista}'>")
                atributos = m.group(1)
                self.assertRegex(atributos, r'data-titulo="[^"]+"')
                icono = re.search(r'data-icono="([\w-]+)"', atributos)
                self.assertIsNotNone(icono)
                self.assertIn(icono.group(1), simbolos, "el icono no está en el sprite")
                tono = re.search(r'data-tono="([\w-]+)"', atributos)
                self.assertIsNotNone(tono)
                self.assertIn(tono.group(1), tonos, "el tono no tiene clase en styles.css")

    def test_el_orden_de_los_atajos_es_el_de_la_barra_lateral(self):
        """⌘1…⌘7 van por `VISTAS`; si no coincide con la barra lateral, ⌘3 abriría
        una vista distinta de la tercera que se ve."""
        m = re.search(r"const VISTAS = \[([^\]]+)\]", JS)
        self.assertIsNotNone(m)
        vistas = re.findall(r"'([\w-]+)'", m.group(1))
        self.assertEqual(vistas, self.en_lateral)


class TestEstilos(unittest.TestCase):
    def test_las_clases_que_genera_app_js_tienen_regla(self):
        sin_regla = _clases_del_js() - _clases_del_css() - CLASES_SIN_ESTILO
        self.assertEqual(sorted(sin_regla), [])

    def test_las_clases_del_marcado_tienen_regla(self):
        clases: set[str] = set()
        for m in re.findall(r'class="([^"]*)"', HTML_SIN_COMENTARIOS):
            clases |= set(m.split())
        self.assertEqual(sorted(clases - _clases_del_css() - CLASES_SIN_ESTILO), [])

    def test_los_tokens_usados_fuera_de_la_hoja_existen(self):
        """`app.js` escribe alguno en línea; renombrar el token los dejaría sin color."""
        definidos = set(re.findall(r"(--[\w-]+)\s*:", CSS_SIN_COMENTARIOS))
        usados = set(re.findall(r"var\((--[\w-]+)\)", JS + HTML))
        self.assertEqual(sorted(usados - definidos), [])


class TestValoresCompartidos(unittest.TestCase):
    def test_la_franja_de_la_barra_de_titulo_mide_lo_mismo_en_css_y_en_swift(self):
        css = re.search(r"html\.nativa\s*\{\s*--franja:\s*(\d+)px", CSS_SIN_COMENTARIOS)
        swift = re.search(r"arrastre\.heightAnchor\.constraint\(equalToConstant:\s*(\d+)\)",
                          SWIFT)
        self.assertIsNotNone(css)
        self.assertIsNotNone(swift)
        self.assertEqual(css.group(1), swift.group(1))

    def test_la_ficha_flota_con_el_mismo_corte_en_css_y_en_js(self):
        js = re.search(r"matchMedia\('\(max-width:\s*(\d+)px\)'\)", JS)
        self.assertIsNotNone(js)
        self.assertRegex(CSS_SIN_COMENTARIOS,
                         rf"@media \(max-width:\s*{js.group(1)}px\)\s*\{{\s*\.panel\b")


if __name__ == "__main__":
    unittest.main()
