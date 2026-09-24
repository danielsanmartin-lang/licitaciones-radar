"""Traer una versión nueva del código sin salir de la aplicación.

Hoy una versión nueva se distribuye mandando un zip por correo, y no hay manera de
saber qué versión tiene cada compañero ni de pedirle que actualice. Esto hace que no haga
falta pedírselo: la pantalla de arranque pregunta a GitHub cada vez que se abre la
aplicación y, si hay algo más nuevo, lo instala y se vuelve a abrir sola, antes de
buscar licitaciones. No hay botón de «más tarde» —una versión que nadie instala es una
versión que no existe—; lo único que deja pasar sin ella es que no haya respuesta.

Hay dos maneras de instalar, según dónde esté el código:

- **Copia de trabajo** (la carpeta del repositorio): se sustituyen los ficheros de
  `REEMPLAZABLES` y se reinicia el servidor.
- **App empaquetada** (el `.app` que lleva el programa dentro): no hay ficheros que
  sustituir, así que se baja el `.app` adjunto a la release, se comprueba y se deja
  preparado en `data/actualizacion/`. El cambio de un bundle por otro lo hace la ventana
  de macOS después de cerrarse, porque un programa no puede reemplazarse mientras corre.

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
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import net, progreso, rutas
from . import __version__

RAIZ = rutas.CODIGO
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
    # El fuente del envoltorio de macOS y su binario prefabricado. Lo que NO se sustituye
    # es «Radar de Licitaciones.app»: un bundle no se puede cambiar por debajo de sí
    # mismo mientras se está ejecutando, y no hace falta, porque se reconstruye desde
    # esto. La propia app detecta al abrirse que su versión ya no cuadra con
    # `radar/__init__.py` y ofrece rehacerse.
    "macos",
)

# Sin estas tres no hay aplicación: si el zip descargado no las trae, no es lo que
# esperábamos y no se sustituye nada.
#
# `macos` NO está aquí a propósito, aunque esté en REEMPLAZABLES: la ventana nativa es
# una comodidad y `start.command` sigue haciendo lo mismo sin ella. Exigirla haría que
# una release publicada sin el binario prefabricado se negara a instalarse para todo el
# mundo, incluido quien nunca ha usado la app.
IMPRESCINDIBLES = ("radar", "web", "radar.py")

# La instalación corre en un proceso aparte (ver `lanzar()`), así que lo que cuenta la
# pantalla de arranque tiene que pasar por disco, igual que el progreso de la ingesta.
# Ficheros propios y no los de la búsqueda: las dos cosas pueden coincidir en el tiempo
# y no deben pisarse la barra.
CERROJO = rutas.DIR_DATOS / "actualizacion.lock"
REGISTRO = rutas.DIR_DATOS / "actualizacion.log"
PROGRESO = rutas.DIR_DATOS / "actualizacion-progreso.json"

# Donde se deja preparada la app nueva de la copia empaquetada. Fuera del bundle, por
# supuesto: es la carpeta de datos, en `~/Library/Application Support`.
DIR_APP = rutas.DIR_DATOS / "actualizacion"
# Lo escribe el script que cambia un bundle por otro si no lo consigue (típicamente, la
# app está en /Applications y el usuario no es administrador). Sin él, la app vieja se
# reabriría, volvería a ver la versión nueva, volvería a intentarlo y así en bucle.
FALLO_APP = DIR_APP / "fallo.txt"
HORAS_TRAS_UN_FALLO = 24

# El de `herramientas/construir_app.py`. Un `.app` con otro identificador no es nuestro,
# venga de donde venga.
IDENTIFICADOR_APP = "app.zepo.licitaciones-radar"

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

    Solo se aplica al `.app` adjunto, y solo si GitHub no da su `digest`: es la suma que
    imprime `construir_app.py --zip` y que se pega en las notas. Al zipball de la copia de
    trabajo no, aunque al principio se hacía: ese zip lo genera GitHub al vuelo desde el
    tag y su suma puede cambiar sin que cambie el código, y además el único SHA que llevan
    las notas es el del `.app`. Comparar uno con otro bloqueaba la instalación de la
    v1.5.0 en toda copia de trabajo. Ahí la defensa es HTTPS contra este repositorio.
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
        # Para la app empaquetada: de dónde se baja el .app nuevo, y la página de la
        # release como recurso si la release no trae el adjunto.
        "url_app": None,
        # El SHA-256 que calcula GitHub del adjunto al subirlo (`digest`). Es el que se
        # exige a la app descargada.
        "sha_app": None,
        "url_release": None,
        "empaquetada": rutas.empaquetada(),
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
    respuesta["url_app"] = _app_publicada(datos)
    respuesta["sha_app"] = _sha_del_adjunto(datos)
    respuesta["url_release"] = datos.get("html_url")
    respuesta["hay_nueva"] = _tupla(datos["tag_name"]) > _tupla(__version__)
    return respuesta


def _app_publicada(datos: dict) -> str | None:
    """La URL del `.app` comprimido que viaje como fichero adjunto de la release.

    Es lo que necesita la app empaquetada, que no puede actualizarse sustituyendo
    ficheros: su código va dentro del bundle. Se busca por nombre y no por posición
    porque una release puede llevar varios adjuntos.
    """
    for adjunto in datos.get("assets") or []:
        nombre = (adjunto.get("name") or "").lower()
        if nombre.endswith(".zip") and "radar" in nombre:
            return adjunto.get("browser_download_url")
    return None


def _sha_del_adjunto(datos: dict) -> str | None:
    """El `digest` que publica GitHub del adjunto de la app: «sha256:…»."""
    for adjunto in datos.get("assets") or []:
        if adjunto.get("browser_download_url") != _app_publicada(datos):
            continue
        digest = (adjunto.get("digest") or "").lower()
        if digest.startswith("sha256:"):
            return digest.split(":", 1)[1] or None
    return None


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


def _fallo_reciente(version: str) -> str | None:
    """El motivo por el que no se pudo cambiar la app por la `version`, si fue hace poco.

    Lo deja escrito el script de la ventana de macOS: primera línea, la versión; el resto,
    lo que dijo `mv`. Pasado un día se vuelve a intentar, por si alguien ha arreglado los
    permisos o ha movido la app.
    """
    try:
        texto = FALLO_APP.read_text(encoding="utf-8")
        edad = time.time() - FALLO_APP.stat().st_mtime
    except OSError:
        return None
    primera, _, resto = texto.partition("\n")
    if _tupla(primera) != _tupla(version) or edad > HORAS_TRAS_UN_FALLO * 3600:
        return None
    return (
        f"La última vez no se pudo cambiar la aplicación por la {version}: "
        f"{resto.strip() or 'sin detalle'}.\n\nSuele ser porque la app está en una "
        "carpeta en la que tu usuario no puede escribir, como Aplicaciones sin ser "
        "administrador. Se volverá a intentar mañana; mientras tanto puedes bajarla de "
        "la página de la release y arrastrarla encima de la vieja."
    )


def _descomprimir_app(zip_app: Path, destino: Path) -> None:
    """Con `ditto`, que es con lo que se comprimió.

    `zipfile` no sirve aquí: pierde el bit de ejecución del binario y los enlaces
    simbólicos, y lo que saldría sería un `.app` que no abre.
    """
    subprocess.run(["ditto", "-x", "-k", str(zip_app), str(destino)],
                   check=True, capture_output=True, timeout=300)


def _app_del_arbol(destino: Path) -> Path | None:
    apps = [h for h in destino.iterdir() if h.suffix == ".app" and h.is_dir()]
    return apps[0] if len(apps) == 1 else None


def _problema_de_la_app(app: Path | None, version: str) -> str | None:
    """Por qué NO hay que instalar esta app, o None si es la que se esperaba."""
    if app is None:
        return "El zip adjunto no trae una aplicación dentro. No se toca nada."
    try:
        plist = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException):
        return "La aplicación descargada no trae un Info.plist legible. No se toca nada."
    if plist.get("CFBundleIdentifier") != IDENTIFICADOR_APP:
        return ("La aplicación descargada no es el Radar de Licitaciones "
                f"({plist.get('CFBundleIdentifier')}). No se toca nada.")
    dice = str(plist.get("CFBundleShortVersionString") or "")
    if _tupla(dice) != _tupla(version):
        return (f"La release dice {version} pero la aplicación que trae dice {dice}. "
                "No se toca nada.")
    for rel in ("Contents/MacOS/radar", "Contents/Resources/radar.py",
                "Contents/Resources/radar", "Contents/Resources/web"):
        if not (app / rel).exists():
            return f"A la aplicación descargada le falta {rel}. No se toca nada."
    return None


def _preparar_app(info: dict, timeout: int) -> dict:
    """Baja el `.app` de la release, lo comprueba y lo deja listo para el cambio.

    No lo pone en su sitio: eso lo hace la ventana de macOS cuando se cierra (ver
    `instalarAppNueva()` en `macos/Radar.swift`). Devuelve en `app_nueva` dónde está.
    """
    version = info["version_nueva"]
    fallo = _fallo_reciente(version)
    if fallo:
        return {"ok": False, "mensaje": fallo, "url": info.get("url_release")}
    if not info.get("url_app"):
        return {"ok": False, "url": info.get("url_release"), "mensaje": (
            f"La release {version} no trae adjunta la aplicación de macOS, así que esta "
            "copia no se puede actualizar sola. Descárgala de la página de la release y "
            "arrástrala encima de la vieja."
        )}

    preparada = DIR_APP / "nueva"
    _borrar(preparada)
    DIR_APP.mkdir(parents=True, exist_ok=True)
    zip_app = DIR_APP / "nueva.zip"
    try:
        log.info("Descargando la aplicación %s...", version)
        net.descargar_a_fichero(info["url_app"], zip_app, timeout=timeout, intentos=2)

        progreso.fase("verificando")
        esperado = info.get("sha_app") or _sha_publicado(info.get("notas") or "")
        if esperado:
            real = _sha256(zip_app)
            if real != esperado:
                return {"ok": False, "mensaje": (
                    "La aplicación descargada no coincide con el SHA-256 publicado. No "
                    f"se ha tocado nada.\n  esperado: {esperado}\n  descargado: {real}"
                )}
        if not zipfile.is_zipfile(zip_app):
            return {"ok": False, "mensaje": "Lo descargado no es un ZIP. No se toca nada."}

        progreso.fase("descomprimiendo")
        preparada.mkdir(parents=True)
        _descomprimir_app(zip_app, preparada)
        app = _app_del_arbol(preparada)
        problema = _problema_de_la_app(app, version)
        if problema:
            _borrar(preparada)
            return {"ok": False, "mensaje": problema}

        log.info("Aplicación %s preparada en %s", version, app)
        return {
            "ok": True,
            "version_nueva": version,
            "app_nueva": str(app),
            "mensaje": (
                f"La versión {version} está descargada y comprobada. La aplicación se "
                "cierra, se cambia por la nueva y se vuelve a abrir sola. Tu base de "
                "datos, tu triaje y tus términos de búsqueda no se tocan."
            ),
        }
    except net.ErrorRed as exc:
        return {"ok": False, "mensaje": f"No se ha podido descargar: {exc}"}
    except subprocess.CalledProcessError as exc:
        _borrar(preparada)
        detalle = (exc.stderr or b"").decode("utf-8", "replace").strip()
        return {"ok": False, "mensaje": f"No se ha podido descomprimir la app: {detalle}"}
    except (OSError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        _borrar(preparada)
        return {"ok": False, "mensaje": f"Falló la actualización: {exc}. No se toca nada."}
    finally:
        zip_app.unlink(missing_ok=True)


def aplicar(timeout: int = 600) -> dict:
    """Descarga la última release y la instala. Devuelve qué ha pasado.

    El orden importa: se descarga y se verifica TODO en un temporal, y solo cuando está
    comprobado se mueve a su sitio. Descomprimir encima de la carpeta viva dejaría, si
    algo falla a mitad, una instalación mezclada, que es bastante peor que una versión
    vieja. Y lo que se sustituye se guarda como «.anterior» para poder volver atrás.

    Va contando por dónde va con `progreso`, que es lo que pinta la pantalla de arranque
    mientras tanto: la descarga la narra `net` sola, y aquí se marcan las fases que no
    son descarga.
    """
    from . import busqueda

    progreso.fuente("actualizacion", "la versión nueva")
    progreso.fase("comprobando")

    # Antes de nada y en las dos maneras de instalar: cambiar el código —o el bundle
    # entero— por debajo de una carga que dura horas es pedir que la mitad de la ingesta
    # corra con una versión y la otra mitad con otra.
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
    progreso.fuente("actualizacion", f"la versión {info['version_nueva']}")

    if rutas.empaquetada():
        # Sustituir ficheros aquí sería escribir DENTRO del .app, y eso invalida la
        # firma y no se puede hacer si la app está en /Applications, que no es del
        # usuario. Así que se prepara la app entera y la cambia la ventana al cerrarse.
        return _preparar_app(info, timeout)

    if not info["url_zip"]:
        return {"ok": False, "mensaje": "La release no trae fichero que descargar."}

    temporal = Path(tempfile.mkdtemp(prefix="radar-actualizacion-"))
    try:
        zip_nuevo = temporal / "nueva.zip"
        log.info("Descargando la versión %s...", info["version_nueva"])
        # Dos intentos y no los cuatro por defecto: con cuatro pasadas de 600 s de
        # timeout, el peor caso tiene la pantalla de arranque parada cuarenta minutos
        # por un zipball de unos pocos MB.
        net.descargar_a_fichero(info["url_zip"], zip_nuevo, timeout=timeout, intentos=2)

        progreso.fase("verificando")
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

        progreso.fase("sustituyendo")
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
                f"Actualizado a la versión {info['version_nueva']}. La aplicación se "
                "reinicia sola para empezar a usarla. Tu base de datos, tu triaje y tus "
                "términos de búsqueda no se han tocado."
            ),
        }
    except net.ErrorRed as exc:
        return {"ok": False, "mensaje": f"No se ha podido descargar: {exc}"}
    except (OSError, zipfile.BadZipFile) as exc:
        return {"ok": False, "mensaje": f"Falló la actualización: {exc}. No se toca nada."}
    finally:
        shutil.rmtree(temporal, ignore_errors=True)


# --- En segundo plano -------------------------------------------------------
#
# La pantalla de arranque no puede quedarse colgada de una petición HTTP de minutos sin
# saber nada: tiene que poder contar cuántos megas lleva y, sobre todo, notar si se ha
# atascado, que es lo único que le da derecho a quien espera a entrar sin la versión
# nueva. Así que la instalación se lanza como la búsqueda: un proceso aparte que escribe
# su progreso a disco, y la interfaz pregunta.


def _proceso_vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# El proceso lanzado por ESTE servidor. Hace falta para recogerlo al terminar: un hijo
# que acaba y nadie recoge se queda de zombi, y a un zombi `kill(pid, 0)` le sigue
# contestando que está vivo. Sin esto, la pantalla de arranque se quedaba para siempre
# en «Instalando» con la instalación ya terminada.
_HIJO: subprocess.Popen | None = None


def en_marcha() -> dict | None:
    """Los datos de la instalación en curso, o None. Limpia un cerrojo huérfano."""
    try:
        datos = json.loads(CERROJO.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (ValueError, OSError):
        CERROJO.unlink(missing_ok=True)
        return None
    pid = datos.get("pid")
    if _HIJO is not None and _HIJO.pid == pid:
        vivo = _HIJO.poll() is None
    else:
        vivo = isinstance(pid, int) and _proceso_vivo(pid)
    if not vivo:
        CERROJO.unlink(missing_ok=True)
        return None
    return datos


def soltar_cerrojo() -> None:
    """Lo llama la propia instalación al acabar, sea como sea.

    Es la otra mitad de `_HIJO`: si el servidor se ha reiniciado mientras tanto, ya no
    tiene el objeto con el que recoger al hijo, y ese hijo —que sigue siendo suyo, porque
    `execv` conserva el proceso— se quedaría de zombi con el cerrojo puesto.
    """
    try:
        datos = json.loads(CERROJO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if datos.get("pid") == os.getpid():
        CERROJO.unlink(missing_ok=True)


def lanzar() -> dict:
    """Arranca `radar.py actualizar --json` en segundo plano. No espera.

    Va en un proceso aparte a propósito, por el mismo motivo que la ingesta: quien
    sustituye el código no debería ser el proceso que está ejecutando ese código. Y
    reutilizar la CLI deja un único camino de ejecución para la pantalla y la terminal.

    Si ya hay una en marcha —dos ventanas abiertas a la vez— se engancha a esa.
    """
    global _HIJO

    activa = en_marcha()
    if activa:
        return {"ok": True, "ya_en_marcha": True, **activa}

    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    PROGRESO.unlink(missing_ok=True)
    orden = [sys.executable, "-u", str(rutas.ENTRADA_CLI), "actualizar", "--json"]
    try:
        with REGISTRO.open("w", encoding="utf-8") as registro:
            proceso = subprocess.Popen(
                orden, cwd=str(RAIZ), stdout=registro, stderr=subprocess.STDOUT,
                # Que sobreviva al reinicio del servidor, que llega justo después.
                start_new_session=True,
            )
    except OSError as exc:
        return {"ok": False, "mensaje": f"No se ha podido lanzar la actualización: {exc}"}
    _HIJO = proceso
    # Lo escribe el padre y no el hijo para que no haya un instante en que la instalación
    # ya está lanzada y el cerrojo todavía no dice nada: la pantalla lo leería como
    # «terminada sin resultado».
    datos = {"pid": proceso.pid,
             "iniciada": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    CERROJO.write_text(json.dumps(datos), encoding="utf-8")
    return {"ok": True, **datos}


def _resultado() -> dict | None:
    """La última línea JSON del registro: lo que imprime `radar.py actualizar --json`."""
    try:
        lineas = REGISTRO.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for linea in reversed(lineas):
        try:
            datos = json.loads(linea)
        except ValueError:
            continue
        if isinstance(datos, dict) and "ok" in datos:
            return datos
    if lineas:
        # Terminó sin decir nada en JSON: una excepción, casi seguro. Lo que haya
        # escrito es lo único que explica qué ha pasado.
        return {"ok": False, "mensaje": "\n".join(lineas)[-2000:]}
    return None


def estado() -> dict:
    """Cómo va la instalación lanzada con `lanzar()`. Lo pregunta la pantalla cada segundo.

    `version` es la del código que está ejecutando ESTE servidor, y es con lo que la
    pantalla sabe que el reinicio ha terminado: cuando deja de ser la vieja.
    """
    activa = en_marcha()
    detalle = None
    if activa:
        try:
            detalle = json.loads(PROGRESO.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            detalle = None
    return {
        "version": __version__,
        "en_marcha": activa is not None,
        "detalle": detalle,
        "resultado": None if activa else _resultado(),
    }


def orden_de_reinicio(argv: list[str] | None = None) -> list[str]:
    """Con qué volver a ejecutar el servidor para que cargue el código nuevo.

    Lo mismo que se lanzó, con dos cuidados: `-B` si se arrancó sin bytecode (la app lo
    exige, ver `Radar.swift`), y `--sin-navegador`, porque `start.command` lo arranca sin
    él y cada reinicio abriría otra pestaña.
    """
    argv = list(sys.argv if argv is None else argv)
    orden = [sys.executable]
    if sys.flags.dont_write_bytecode:
        orden.append("-B")
    orden.append("-u")
    orden.append(str(Path(argv[0]).resolve()))
    resto = argv[1:]
    if "serve" in resto and "--sin-navegador" not in resto:
        resto.append("--sin-navegador")
    return orden + resto


def reiniciar_servidor(espera: float = 0.5) -> None:
    """Sustituye este proceso por uno nuevo con el mismo PID. No vuelve.

    `execv` y no «salir y que alguien lo relance»: no hay nadie que lo relance cuando se
    arrancó desde `start.command`, y la ventana de macOS sigue viendo el mismo proceso
    —mismo PID— y lo para al cerrarse como siempre. El socket se suelta solo: Python lo
    crea no heredable, y el servidor nuevo lo vuelve a abrir con `SO_REUSEADDR`.

    Se espera un momento antes para que la respuesta HTTP que lo ha pedido llegue a
    salir.
    """
    time.sleep(espera)
    sys.stdout.flush()
    sys.stderr.flush()
    orden = orden_de_reinicio()
    log.info("Reiniciando el servidor: %s", " ".join(orden))
    os.execv(orden[0], orden)
