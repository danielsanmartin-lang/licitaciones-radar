"""Traer una versión nueva del código sin salir de la aplicación.

Hoy una versión nueva se distribuye mandando un zip por correo, y no hay manera de
saber qué versión tiene cada compañero ni de pedirle que actualice. Esto lo convierte
en un botón.

Es más sencillo aquí que en un proyecto normal por dos razones. Una: el proyecto no
tiene ni una dependencia externa —todo es biblioteca estándar—, así que actualizar es
literalmente sustituir ficheros, sin pip, ni entornos, ni versiones que resolver. Dos:
lo que de verdad rompe una actualización no es traer el código nuevo, es que el código
nuevo se encuentre una base de datos vieja, y de eso ya se encarga `db.migrar()` en cada
arranque.

Lo que NO se toca, nunca:

- `data/`, donde viven la base, el triaje y las notas de cada uno.
- `config/perfiles.json`, que es lo que cada persona ajusta desde la aplicación. Si
  algún día hay que añadir términos nuevos por defecto, se hará fusionando con un
  marcador de versión, como las migraciones de la base; sobrescribirlo le borraría a un
  compañero el trabajo de meses.

Y una advertencia que conviene tener presente: esto es, por diseño, ejecución de código
descargado de internet. Quien controle el repositorio controla el equipo de quien
actualiza. Por eso solo se acepta la release del repositorio de abajo, por HTTPS y con
el almacén de certificados propio del proyecto, y se comprueba el SHA-256 cuando las
notas de la release lo publican.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from . import net
from . import __version__

RAIZ = Path(__file__).resolve().parent.parent
REPO = "danielsanmartin-lang/licitaciones-radar"
API_ULTIMA = f"https://api.github.com/repos/{REPO}/releases/latest"

# Lo único que se sustituye. Es una lista blanca y no una negra a propósito: con una
# lista de exclusiones, cualquier carpeta nueva que apareciera en el repositorio pasaría
# a sobrescribir lo que hubiera en su sitio sin que nadie lo hubiera decidido.
REEMPLAZABLES = (
    "radar",
    "web",
    "tests",
    "docs",
    "herramientas",
    "radar.py",
    "start.command",
    "README.md",
    # El almacén de certificados sí se actualiza: caduca, y si se queda atrás PLACSP
    # deja de validar. `config/perfiles.json`, en cambio, no se toca jamás.
    "config/certs",
)

# Sin estas tres no hay aplicación: si el zip descargado no las trae, no es lo que
# esperábamos y no se sustituye nada.
IMPRESCINDIBLES = ("radar", "web", "radar.py")

log = logging.getLogger(__name__)


def _tupla(version: str) -> tuple[int, ...]:
    """«v1.4.2» -> (1, 4, 2). Lo que no sea número cuenta como 0.

    Comparar tuplas y no cadenas es lo que evita que «1.10» se considere anterior a
    «1.9», que es el fallo clásico de comparar versiones como texto.
    """
    partes = []
    for trozo in version.strip().lstrip("vV").split("."):
        digitos = "".join(c for c in trozo if c.isdigit())
        partes.append(int(digitos) if digitos else 0)
    return tuple(partes) or (0,)


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as fh:
        while trozo := fh.read(1 << 20):
            h.update(trozo)
    return h.hexdigest()


def _sha_publicado(notas: str) -> str | None:
    """Busca un SHA-256 en las notas de la release.

    Es opcional a propósito: una release sin él se instala igual, porque HTTPS contra el
    repositorio correcto ya es la defensa principal. Cuando está, se comprueba, y así
    una descarga corrompida a medio camino no llega a sustituir nada.
    """
    for palabra in (notas or "").replace("`", " ").split():
        limpia = palabra.strip().lower()
        if len(limpia) == 64 and all(c in "0123456789abcdef" for c in limpia):
            return limpia
    return None


def comprobar(timeout: int = 15) -> dict:
    """¿Hay publicada una versión más nueva que la instalada?

    Devuelve siempre un diccionario y nunca lanza: esto lo llama la interfaz al abrirse,
    y quedarse sin internet un rato no es motivo para estropear la pantalla.
    """
    respuesta = {
        "version_actual": __version__,
        "version_nueva": None,
        "hay_nueva": False,
        "notas": "",
        "url_zip": None,
        "error": None,
    }
    try:
        datos = net.descargar_json(API_ULTIMA, timeout=timeout, intentos=2)
    except net.ErrorRed as exc:
        if getattr(exc, "codigo", None) == 404:
            respuesta["error"] = (
                "GitHub dice que no hay ninguna release publicada (o el repositorio es "
                "privado y esta copia no tiene credenciales para verlo)."
            )
        else:
            respuesta["error"] = f"No se ha podido preguntar a GitHub: {exc}"
        return respuesta
    except (ValueError, TypeError) as exc:  # JSON inesperado
        respuesta["error"] = f"GitHub ha contestado algo que no se entiende: {exc}"
        return respuesta

    if not isinstance(datos, dict) or not datos.get("tag_name"):
        respuesta["error"] = "La respuesta de GitHub no trae ninguna versión."
        return respuesta

    respuesta["version_nueva"] = datos["tag_name"]
    respuesta["notas"] = datos.get("body") or ""
    respuesta["url_zip"] = datos.get("zipball_url")
    respuesta["hay_nueva"] = _tupla(datos["tag_name"]) > _tupla(__version__)
    return respuesta


def _raiz_del_zip(extraido: Path) -> Path:
    """GitHub empaqueta todo dentro de una carpeta «repo-sha», no en la raíz."""
    hijos = [h for h in extraido.iterdir() if h.is_dir()]
    return hijos[0] if len(hijos) == 1 else extraido


def _version_del_arbol(raiz: Path) -> str | None:
    """Lee `__version__` del código descargado sin importarlo.

    Importar el módulo nuevo dentro del proceso viejo mezclaría dos versiones del
    paquete en memoria; leer la línea es suficiente y no ejecuta nada de lo descargado.
    """
    init = raiz / "radar" / "__init__.py"
    if not init.exists():
        return None
    for linea in init.read_text(encoding="utf-8").splitlines():
        if linea.startswith("__version__"):
            return linea.split("=", 1)[1].strip().strip("\"'")
    return None


def _borrar(ruta: Path) -> None:
    if ruta.is_dir() and not ruta.is_symlink():
        shutil.rmtree(ruta, ignore_errors=True)
    else:
        ruta.unlink(missing_ok=True)


def aplicar(timeout: int = 600) -> dict:
    """Descarga la última release y sustituye el código. Devuelve qué ha pasado.

    El orden importa: se descarga y se verifica TODO en un temporal, y solo cuando está
    comprobado se mueve a su sitio. Descomprimir encima de la carpeta viva dejaría, si
    algo falla a mitad, una instalación mezclada, que es bastante peor que una versión
    vieja. Y lo que se sustituye se guarda como «.anterior» para poder volver atrás.
    """
    from . import busqueda

    activa = busqueda.en_marcha()
    if activa:
        return {"ok": False, "mensaje": (
            f"Hay una descarga en marcha desde {activa.get('iniciada', '?')}. "
            "Cambiar el código por debajo de una carga que dura horas es pedir "
            "problemas: espera a que termine."
        )}

    info = comprobar()
    if info["error"]:
        return {"ok": False, "mensaje": info["error"]}
    if not info["hay_nueva"]:
        return {"ok": True, "sin_cambios": True, "mensaje":
                f"Ya tienes la última versión ({info['version_actual']})."}
    if not info["url_zip"]:
        return {"ok": False, "mensaje": "La release no trae fichero que descargar."}

    temporal = Path(tempfile.mkdtemp(prefix="radar-actualizacion-"))
    try:
        zip_nuevo = temporal / "nueva.zip"
        log.info("Descargando la versión %s...", info["version_nueva"])
        # Dos intentos y no los cuatro por defecto: `aplicar_en_subproceso` mata este
        # proceso a los 900 s, y con cuatro pasadas de 600 s de timeout el peor caso se
        # come el plazo y muere a mitad. Un zipball de unos pocos MB no necesita más.
        net.descargar_a_fichero(info["url_zip"], zip_nuevo, timeout=timeout, intentos=2)

        esperado = _sha_publicado(info["notas"])
        if esperado:
            real = _sha256(zip_nuevo)
            if real != esperado:
                return {"ok": False, "mensaje": (
                    "El fichero descargado no coincide con el SHA-256 publicado en la "
                    f"release. No se ha tocado nada.\n  esperado: {esperado}\n  "
                    f"descargado: {real}"
                )}

        if not zipfile.is_zipfile(zip_nuevo):
            return {"ok": False, "mensaje": "Lo descargado no es un ZIP. No se toca nada."}
        destino = temporal / "nuevo"
        with zipfile.ZipFile(zip_nuevo) as zf:
            zf.extractall(destino)
        arbol = _raiz_del_zip(destino)

        faltan = [n for n in IMPRESCINDIBLES if not (arbol / n).exists()]
        if faltan:
            return {"ok": False, "mensaje":
                    f"El ZIP no trae {', '.join(faltan)}. No se toca nada."}

        version_real = _version_del_arbol(arbol)
        if version_real is None or _tupla(version_real) != _tupla(info["version_nueva"]):
            return {"ok": False, "mensaje": (
                f"La etiqueta de la release dice {info['version_nueva']} pero el código "
                f"que trae dice {version_real}. No se toca nada."
            )}

        cambiados, hechos = [], []
        try:
            for rel in REEMPLAZABLES:
                nuevo = arbol / rel
                if not nuevo.exists():
                    continue
                actual = RAIZ / rel
                anterior = actual.with_name(actual.name + ".anterior")
                _borrar(anterior)
                if actual.exists():
                    actual.rename(anterior)
                # Se anota ANTES de mover, no después: si el movimiento falla, este es
                # precisamente el que hay que devolver a su sitio, y anotándolo después
                # se quedaba fuera del deshacer con la carpeta ya renombrada. Resultado:
                # `web/` desaparecía del proyecto.
                hechos.append((actual, anterior))
                # `config/certs` cuelga de una carpeta que podría no existir en una
                # instalación vieja; sin esto el movimiento fallaría por el padre.
                actual.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(nuevo), str(actual))
                cambiados.append(rel)
        except OSError as exc:
            # Deshacer en orden inverso: mejor quedarse en la versión vieja entera que
            # en una mitad de cada.
            for actual, anterior in reversed(hechos):
                _borrar(actual)
                if anterior.exists():
                    anterior.rename(actual)
            return {"ok": False, "mensaje":
                    f"Falló al sustituir «{rel}»: {exc}. Se ha dejado como estaba."}

        log.info("Actualizado a %s: %s", info["version_nueva"], ", ".join(cambiados))
        return {
            "ok": True,
            "version_nueva": info["version_nueva"],
            "cambiados": cambiados,
            "mensaje": (
                f"Actualizado a la versión {info['version_nueva']}. Cierra la aplicación "
                "y vuelve a abrirla con start.command para que empiece a usarla. Tu base "
                "de datos, tu triaje y tus términos de búsqueda no se han tocado."
            ),
        }
    except net.ErrorRed as exc:
        return {"ok": False, "mensaje": f"No se ha podido descargar: {exc}"}
    except (OSError, zipfile.BadZipFile) as exc:
        return {"ok": False, "mensaje": f"Falló la actualización: {exc}. No se toca nada."}
    finally:
        shutil.rmtree(temporal, ignore_errors=True)


def aplicar_en_subproceso(timeout: int = 900) -> dict:
    """Lanza `radar.py actualizar` y espera a que termine.

    Va en un proceso aparte a propósito, por el mismo motivo que la ingesta: quien
    sustituye el código no debería ser el proceso que está ejecutando ese código. Y
    reutilizar la CLI deja un único camino de ejecución, en vez de una versión para el
    botón y otra para la terminal.
    """
    try:
        r = subprocess.run(
            [sys.executable, "-u", str(RAIZ / "radar.py"), "actualizar", "--json"],
            cwd=str(RAIZ), capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "mensaje": f"No se ha podido lanzar la actualización: {exc}"}

    for linea in reversed((r.stdout or "").splitlines()):
        try:
            return json.loads(linea)
        except ValueError:
            continue
    return {"ok": False, "mensaje":
            (r.stderr or r.stdout or "La actualización no ha dicho nada.").strip()[-2000:]}
