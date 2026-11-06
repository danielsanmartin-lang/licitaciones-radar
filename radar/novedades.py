"""Qué ha cambiado desde la versión con la que se abrió la aplicación la última vez.

La aplicación se actualiza sola al abrirse (ver `actualizacion.py`), y eso tenía una
pega: la versión nueva entraba sin decir nada. La pestaña «Otras licitaciones» apareció
de un día para otro sin que nadie supiera de dónde salía ni para qué servía. Esto es lo
que permite a la pantalla de arranque decir «te has actualizado a la 1.8.0, y esto es
lo nuevo desde la 1.6.0 que tenías».

Dos piezas:

- **Desde qué versión.** Se apunta en la base (`preferencias.version_vista`) la versión
  con la que se terminó de abrir la aplicación. Si la que corre ahora es más nueva, se ha
  actualizado. La base es el sitio porque es lo único que sobrevive a la actualización en
  las dos maneras de instalar: la copia de trabajo cambia `radar/` y la app empaquetada
  cambia el bundle entero, pero los datos se quedan.
  Sin ninguna versión apuntada es una instalación nueva, y se le enseña lo que trae la
  versión con la que empieza.
- **Qué ha cambiado.** Las notas de las releases de GitHub, que son las que ya se
  escriben para cada versión. Copiarlas además a un fichero del repositorio sería
  escribirlas dos veces y que acabaran diciendo cosas distintas.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time

from . import __version__, actualizacion, net
from .actualizacion import REPO, _tupla
from .db import escribir_preferencia, leer_preferencia

log = logging.getLogger(__name__)

CLAVE_VISTA = "version_vista"
API_RELEASES = f"https://api.github.com/repos/{REPO}/releases?per_page=50"
PAGINA_RELEASES = f"https://github.com/{REPO}/releases"

# Cuántas versiones se enseñan como mucho. Quien vuelve tras meses sin abrir la
# aplicación no necesita la historia entera en una pantalla de espera: las últimas, y
# el enlace al resto.
MAXIMO_VERSIONES = 6


def _version_anterior_en_disco() -> str | None:
    """La versión que había antes, leída de la copia que guarda el actualizador.

    Solo existe en la copia de trabajo, que aparta el código viejo como `radar.anterior/`
    antes de poner el nuevo. La app empaquetada cambia el bundle entero y no deja nada.
    """
    anterior = actualizacion.RAIZ / "radar.anterior" / "__init__.py"
    try:
        texto = anterior.read_text(encoding="utf-8")
    except OSError:
        return None
    for linea in texto.splitlines():
        if linea.startswith("__version__"):
            return linea.split("=", 1)[1].strip().strip("\"'") or None
    return None


def recien_actualizada(con: sqlite3.Connection) -> dict | None:
    """`{"desde": …, "hasta": …}` si esta versión todavía no se ha estrenado; si no, None.

    `desde` puede ser None: se sabe que se ha actualizado, pero no desde dónde. En una
    instalación nueva sale además `"bienvenida": True`.
    """
    vista = leer_preferencia(con, CLAVE_VISTA)
    if vista:
        if _tupla(vista) < _tupla(__version__):
            return {"desde": vista, "hasta": __version__}
        return None

    # Sin constancia de ninguna versión: o la base viene de una versión que todavía no la
    # apuntaba —la primera actualización a esta—, o es una instalación nueva. Lo primero
    # lo dice el registro del actualizador, que apunta qué instaló la última vez.
    resultado = actualizacion._resultado()
    if (resultado and resultado.get("ok") and not resultado.get("sin_cambios")
            and resultado.get("version_nueva")
            and _tupla(resultado["version_nueva"]) == _tupla(__version__)):
        return {"desde": _version_anterior_en_disco(), "hasta": __version__}

    # Lo segundo: quien acaba de descargarla de GitHub. Antes no se le contaba nada, y la
    # pantalla de arranque se pasaba los minutos de la primera carga sin decir qué hace
    # la herramienta. Se le enseñan las notas de la versión con la que empieza: no las de
    # las anteriores, que nunca ha tenido.
    return {"desde": None, "hasta": __version__, "bienvenida": True}


def marcar_vista(con: sqlite3.Connection) -> None:
    """Esta versión ya se ha estrenado: la próxima vez no hay nada que contar.

    Solo escribe si cambia, y no es por ahorrar una fila. `/api/novedades` lo llama cada
    vez que se abre la aplicación, y casi siempre se abre con una búsqueda escribiendo
    por detrás: una escritura tiene que esperar a que la búsqueda suelte la base, hasta
    los 30 s de `db.conectar`. Medido el 28/10/2026: la pantalla de arranque esperó 15 s
    para apuntar una versión que ya estaba apuntada, y si la espera pasa de 30 la
    respuesta es un error y las novedades de una versión nueva no se enseñan.
    """
    if leer_preferencia(con, CLAVE_VISTA) == __version__:
        return
    escribir_preferencia(con, CLAVE_VISTA, __version__)
    con.commit()


# --- Las notas ----------------------------------------------------------------

_HASH = re.compile(r"\b[0-9a-f]{64}\b", re.IGNORECASE)
_ENLACE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_LISTA = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")


def bloques(markdown: str) -> list[dict]:
    """Convierte las notas de una release en bloques que la pantalla sabe pintar.

    Se hace aquí y no en el navegador por dos motivos: se puede probar, y la pantalla
    no tiene que interpretar nada que venga de fuera como HTML. Salen tres tipos
    —`titulo`, `punto` y `parrafo`— y el texto conserva `**negrita**` y `` `código` ``,
    que la pantalla pinta con `textContent`.

    Lo que no es para quien usa la herramienta se queda fuera: la línea del SHA-256 del
    zip, que está para verificar la descarga, no para leerla.
    """
    salida: list[dict] = []
    parrafo: list[str] = []

    def cerrar_parrafo() -> None:
        if parrafo:
            salida.append({"tipo": "parrafo", "texto": " ".join(parrafo)})
            parrafo.clear()

    for bruta in (markdown or "").replace("\r\n", "\n").split("\n"):
        linea = _ENLACE.sub(r"\1", bruta.rstrip())
        if not linea.strip():
            cerrar_parrafo()
            continue
        if _HASH.search(linea):
            cerrar_parrafo()
            continue
        if linea.lstrip().startswith("#"):
            cerrar_parrafo()
            texto = linea.lstrip().lstrip("#").strip()
            if texto:
                salida.append({"tipo": "titulo", "texto": texto})
            continue
        if _LISTA.match(linea):
            cerrar_parrafo()
            salida.append({"tipo": "punto", "texto": _LISTA.sub("", linea).strip()})
            continue
        # Una línea sangrada justo después de un punto es la continuación de ese punto.
        if linea.startswith((" ", "\t")) and salida and salida[-1]["tipo"] == "punto" \
                and not parrafo:
            salida[-1]["texto"] += " " + linea.strip()
            continue
        parrafo.append(linea.strip())
    cerrar_parrafo()
    return salida


def _traer(timeout: int) -> tuple[list[dict], str | None]:
    """Las releases publicadas de GitHub (sin borradores ni previas), o el error."""
    try:
        datos = net.descargar_json(API_RELEASES, timeout=timeout, intentos=1)
    except (net.ErrorRed, ValueError, TypeError) as exc:
        return [], f"No se han podido traer las novedades de GitHub: {exc}"
    if not isinstance(datos, list):
        return [], "GitHub no ha devuelto la lista de versiones."
    return [r for r in datos
            if isinstance(r, dict) and r.get("tag_name")
            and not r.get("draft") and not r.get("prerelease")], None


def _version(r: dict) -> dict:
    return {
        "version": r["tag_name"].lstrip("vV"),
        "titulo": _titulo(r),
        "fecha": (r.get("published_at") or "")[:10] or None,
        "url": r.get("html_url"),
        "bloques": bloques(r.get("body") or ""),
    }


# El historial se pide cada vez que se abre su vista, y la API de GitHub sin cuenta
# admite 60 preguntas por hora y por IP —compartidas con el actualizador—. Las releases
# cambian una vez cada varios días: con diez minutos de memoria basta.
SEGUNDOS_MEMORIA_HISTORIAL = 600
_memoria_historial: dict = {}


def historial(*, timeout: int = 10, ahora: float | None = None) -> dict:
    """Todas las versiones publicadas, de la más nueva a la más antigua, con sus notas.

    Es lo que enseña «Historial de versiones», al pie de la barra lateral. Marca cuál es
    la que corre ahora y si hay alguna más nueva todavía sin instalar. Nunca lanza: sin
    red se dice, con el enlace a la página de versiones.
    """
    ahora = time.monotonic() if ahora is None else ahora
    guardado = _memoria_historial.get("respuesta")
    if guardado and ahora - _memoria_historial["cuando"] < SEGUNDOS_MEMORIA_HISTORIAL:
        return guardado

    releases, error = _traer(timeout)
    releases.sort(key=lambda r: _tupla(r["tag_name"]), reverse=True)
    actual = _tupla(__version__)
    versiones = []
    for r in releases:
        v = _version(r)
        v["instalada"] = _tupla(r["tag_name"]) == actual
        v["sin_instalar"] = _tupla(r["tag_name"]) > actual
        versiones.append(v)
    respuesta = {"version": __version__, "versiones": versiones, "error": error,
                 "url": PAGINA_RELEASES}
    # Un fallo no se recuerda: en cuanto vuelva la red, se tiene que poder ver.
    if not error:
        _memoria_historial.update(respuesta=respuesta, cuando=ahora)
    return respuesta


def notas(desde: str | None, hasta: str, *, timeout: int = 10) -> dict:
    """Las releases posteriores a `desde` y hasta `hasta`, la más nueva primero.

    Sin `desde` se sabe que hubo actualización pero no desde dónde, así que se enseña
    solo la versión a la que se ha llegado. Nunca lanza: sin red, la pantalla dice que
    se ha actualizado y enlaza a la página de las releases.
    """
    respuesta = {"versiones": [], "mas_antiguas": 0, "error": None, "url": PAGINA_RELEASES}
    datos, error = _traer(timeout)
    if error:
        respuesta["error"] = error
        return respuesta

    techo = _tupla(hasta)
    suelo = _tupla(desde) if desde else None
    elegidas = []
    for r in datos:
        v = _tupla(r["tag_name"])
        if v > techo:
            continue
        if suelo is None:
            if v != techo:
                continue
        elif v <= suelo:
            continue
        elegidas.append(r)
    elegidas.sort(key=lambda r: _tupla(r["tag_name"]), reverse=True)

    respuesta["mas_antiguas"] = max(0, len(elegidas) - MAXIMO_VERSIONES)
    respuesta["versiones"] = [_version(r) for r in elegidas[:MAXIMO_VERSIONES]]
    return respuesta


def _titulo(release: dict) -> str:
    """«v1.7.0 — Otras licitaciones por temática» → «Otras licitaciones por temática».

    La versión ya la pinta la pantalla aparte; repetida en el título solo estorba.
    """
    nombre = (release.get("name") or "").strip()
    etiqueta = release.get("tag_name") or ""
    for prefijo in (etiqueta, etiqueta.lstrip("vV")):
        if prefijo and nombre.startswith(prefijo):
            nombre = nombre[len(prefijo):].lstrip(" —–-:·").strip()
            break
    return nombre
