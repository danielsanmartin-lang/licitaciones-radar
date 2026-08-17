"""La herramienta tiene que ser replicable por cualquier compañero.

Eso significa dos cosas comprobables automáticamente: que no toca el sistema
personal de nadie (vault, CRM, credenciales) y que no arrastra dependencias que
haya que instalar. Si alguien añade un `import requests` o una ruta a ~/Obsidian,
estos tests lo cazan antes de que el proyecto deje de arrancar en otro equipo.
"""

import ast
import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

PROHIBIDO = re.compile(
    r"obsidian|hermes|hubspot|~/\.hermes|notas\.db|obsidian_vault", re.IGNORECASE
)

# Todo lo que se importa tiene que venir en la biblioteca estándar.
STDLIB_PERMITIDA = {
    "__future__", "argparse", "ast", "csv", "dataclasses", "datetime", "gzip",
    "hashlib", "http", "io", "json", "logging", "os", "pathlib", "re", "sqlite3",
    "ssl", "sys", "tempfile", "threading", "time", "typing", "unicodedata",
    "unittest", "urllib", "webbrowser", "xml", "zipfile", "collections",
    "functools", "itertools", "shutil", "textwrap", "plistlib", "subprocess",
    "getpass", "signal",
}
# certifi solo se usa en la herramienta de regeneración del bundle, que es
# opcional y se ejecuta a mano una vez al año.
EXCEPCIONES = {"herramientas/regenerar_ca_bundle.py": {"certifi"}}


def ficheros(*patrones):
    salida = []
    for patron in patrones:
        for p in RAIZ.glob(patron):
            if "__pycache__" in p.parts or "data" in p.parts:
                continue
            salida.append(p)
    return salida


class TestSinAtaduras(unittest.TestCase):
    def test_no_referencia_el_sistema_personal(self):
        for fichero in ficheros("*.py", "radar/**/*.py", "web/*", "config/perfiles.json",
                               "*.command", "*.md"):
            texto = fichero.read_text(encoding="utf-8", errors="replace")
            for n, linea in enumerate(texto.splitlines(), 1):
                if PROHIBIDO.search(linea):
                    self.fail(
                        f"{fichero.relative_to(RAIZ)}:{n} referencia un sistema "
                        f"personal: {linea.strip()[:90]}"
                    )

    def test_no_hay_rutas_absolutas_del_autor(self):
        for fichero in ficheros("*.py", "radar/**/*.py", "*.command"):
            texto = fichero.read_text(encoding="utf-8")
            self.assertNotIn("/Users/", texto,
                             f"{fichero.relative_to(RAIZ)} lleva una ruta absoluta")

    def test_todo_es_biblioteca_estandar(self):
        for fichero in ficheros("*.py", "radar/**/*.py", "tests/*.py", "herramientas/*.py"):
            rel = str(fichero.relative_to(RAIZ))
            permitidas = STDLIB_PERMITIDA | {"radar", "tests"} | EXCEPCIONES.get(rel, set())
            arbol = ast.parse(fichero.read_text(encoding="utf-8"))
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.Import):
                    nombres = [a.name.split(".")[0] for a in nodo.names]
                elif isinstance(nodo, ast.ImportFrom):
                    nombres = [(nodo.module or "").split(".")[0]] if nodo.level == 0 else []
                else:
                    continue
                for nombre in nombres:
                    if nombre and nombre not in permitidas:
                        self.fail(
                            f"{rel} importa '{nombre}', que no está en la "
                            "biblioteca estándar: un compañero tendría que instalarlo"
                        )

    def test_la_base_vive_dentro_del_proyecto(self):
        from radar import db
        self.assertTrue(str(db.BD_POR_DEFECTO).startswith(str(RAIZ)))

    def test_el_servidor_solo_escucha_en_local(self):
        texto = (RAIZ / "radar" / "server.py").read_text(encoding="utf-8")
        self.assertIn('"127.0.0.1"', texto)
        self.assertNotIn('"0.0.0.0"', texto)


if __name__ == "__main__":
    unittest.main()
