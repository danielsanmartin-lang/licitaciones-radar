"""Lanzar una búsqueda desde la interfaz sin bloquearla.

Una ingesta completa tarda alrededor de un minuto (o mucho más con histórico), así
que no puede correr dentro de la petición HTTP: se lanza `radar.py ingest` como
proceso aparte y la interfaz va preguntando cómo va.

Se reutiliza la CLI en lugar de llamar al pipeline directamente. Así hay un único
camino de ejecución —el mismo que usa la tarea programada de cada mañana— y no dos
implementaciones que puedan divergir.

El bloqueo importa: la tarea de las 8:30 y el botón pueden coincidir, y dos ingestas
a la vez sobre el mismo SQLite se pelean por el bloqueo de escritura.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import progreso

from . import rutas

RAIZ = rutas.CODIGO
CERROJO = rutas.DIR_DATOS / "busqueda.lock"
SALIDA = rutas.DIR_DATOS / "busqueda.log"


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _proceso_vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def en_marcha() -> dict | None:
    """Devuelve los datos de la búsqueda en curso, o None si no hay ninguna.

    Si el cerrojo apunta a un proceso que ya no existe (un cierre a lo bruto, un
    reinicio), se limpia solo en lugar de dejar la aplicación bloqueada para
    siempre.
    """
    if not CERROJO.exists():
        return None
    try:
        datos = json.loads(CERROJO.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        CERROJO.unlink(missing_ok=True)
        return None

    pid = datos.get("pid")
    if not isinstance(pid, int) or not _proceso_vivo(pid):
        CERROJO.unlink(missing_ok=True)
        return None
    return datos


def adquirir(origen: str = "cli") -> bool:
    """Toma el cerrojo de forma atómica. False si ya lo tiene otro.

    Lo llama `radar.py ingest`, no solo el botón: la tarea programada de cada mañana
    ejecuta la CLI directamente y también tiene que respetarlo. La creación
    exclusiva del fichero es lo que evita que dos arranques simultáneos crean los
    dos que el cerrojo es suyo.
    """
    en_marcha()  # limpia un cerrojo huérfano si lo hubiera
    CERROJO.parent.mkdir(parents=True, exist_ok=True)
    datos = json.dumps({"pid": os.getpid(), "iniciada": _ahora(), "origen": origen})
    try:
        fd = os.open(CERROJO, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(datos)
    return True


def liberar() -> None:
    """Suelta el cerrojo si es de este proceso."""
    activa = None
    if CERROJO.exists():
        try:
            activa = json.loads(CERROJO.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            activa = None
    if activa is None or activa.get("pid") == os.getpid():
        CERROJO.unlink(missing_ok=True)


def detalle_progreso() -> dict | None:
    """La instantánea que publica la ingesta, o None si todavía no hay ninguna.

    Es lo único que ve la aplicación de una carga que corre en segundo plano: los
    contadores viven en el proceso de la ingesta, no en el del servidor.
    """
    try:
        return json.loads(progreso.ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def lanzar(*, reiniciar_cursor: bool = False, dias: int | None = None,
           fuentes: list | None = None, backfill: list | None = None,
           primera_carga: bool = False, etapas: list | None = None) -> dict:
    """Arranca la ingesta en segundo plano. Lanza RuntimeError si ya hay una.

    El cerrojo definitivo lo toma el proceso hijo; esta comprobación solo sirve
    para dar un mensaje claro en lugar de arrancar un proceso que se va a rendir.
    """
    activa = en_marcha()
    if activa:
        raise RuntimeError(
            f"Ya hay una búsqueda en marcha desde {activa.get('iniciada', '?')}."
        )

    # -u desactiva el buffer del hijo: sin él, las líneas del registro que lee la
    # aplicación llegarían a ráfagas en lugar de a medida que pasan las cosas.
    orden = [sys.executable, "-u", str(rutas.ENTRADA_CLI), "ingest"]
    if primera_carga:
        orden.append("--primera-carga")
        if etapas:
            orden += ["--etapas"] + [str(int(e)) for e in etapas]
    for fuente in fuentes or []:
        orden += ["--fuente", str(fuente)]
    if backfill:
        orden += ["--backfill", ",".join(str(int(a)) for a in backfill)]
    if reiniciar_cursor:
        orden.append("--reiniciar-cursor")
    if dias:
        orden += ["--dias", str(int(dias))]

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    # El descriptor se cierra en cuanto arranca el hijo: él ya tiene su propia copia.
    # Dejarlo abierto filtraba un descriptor por búsqueda en el proceso del servidor,
    # que se queda encendido durante días.
    with SALIDA.open("w", encoding="utf-8") as registro:
        proceso = subprocess.Popen(
            orden,
            cwd=str(RAIZ),
            stdout=registro,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # que no muera al parar el servidor
        )
    return {
        "pid": proceso.pid,
        "iniciada": _ahora(),
        "reiniciar_cursor": reiniciar_cursor,
        "primera_carga": primera_carga,
    }


def cancelar() -> bool:
    activa = en_marcha()
    if not activa:
        return False
    try:
        os.kill(activa["pid"], signal.SIGTERM)
    except OSError:
        pass
    CERROJO.unlink(missing_ok=True)
    return True


def ultimas_lineas(n: int = 12) -> list[str]:
    """Las últimas líneas del registro, para ir mostrando el progreso.

    Se filtran las consultas a TED, que ocupan varios miles de caracteres y no
    dicen nada a quien está mirando la pantalla. Se emiten con dos encabezados
    distintos —`TED:` en la ingesta incremental y `TED histórico AAAA:` en el
    backfill—, y colar una de ellas en la cabecera de la aplicación llena la línea de
    paréntesis y códigos CPV.
    """
    if not SALIDA.exists():
        return []
    try:
        lineas = SALIDA.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    utiles = [
        l.strip() for l in lineas
        if l.strip() and "(buyer-country" not in l
    ]
    return utiles[-n:]


# A partir de cuánto sin moverse nada se deja de decir «va lenta» y se dice «parece
# atascada». Tres minutos, como el aviso que ya tenía la pantalla de arranque: un intento
# de conexión puede pasarse dos minutos callado y eso todavía es lentitud.
SIN_AVANCE_SOSPECHOSO = 180


def _dias_desde(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        cuando = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if cuando.tzinfo is None:
        cuando = cuando.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - cuando).days


def _ritmo_legible(bytes_por_s: float) -> str:
    """Como `progreso._ritmo`, pero sin el «0,0 MB/s» que no dice nada en una frase.

    El corte es el mismo redondeo de `_ritmo`: así, cuando la línea de progreso dice
    «0,1 MB/s», la explicación de debajo no dice «menos de 0,1».
    """
    if round(bytes_por_s / (1024 * 1024), 1) == 0:
        return "menos de 0,1 MB/s"
    return progreso._ritmo(bytes_por_s)


def _minutos(segundos: float) -> str:
    n = max(1, round(segundos / 60))
    return "1 minuto" if n == 1 else f"{n} minutos"


def explicar_lentitud(det: dict | None, ultima_busqueda: str | None = None) -> str | None:
    """Por qué está tardando la búsqueda, en dos o tres frases. None si no hay nada que contar.

    Se compone aquí y no en el JavaScript por lo mismo que `progreso._frase()`: se puede
    probar, y la pantalla solo tiene que pintarlo. La enseña la pantalla de arranque
    cuando la búsqueda pasa de un par de minutos, que es cuando alguien empieza a pensar
    que se ha colgado. La búsqueda que lo motivó tardó 1h45 avanzando todo el rato: no
    estaba colgada, pero nada en la pantalla lo decía.
    """
    if not det:
        return None
    from . import vigilante

    callado = det.get("sin_avance") or 0
    if callado >= SIN_AVANCE_SOSPECHOSO:
        return (
            f"Lleva {progreso._dur(callado)} sin avanzar nada, así que puede haberse "
            f"atascado. Si sigue así, a los {_minutos(vigilante.SIN_AVANCE_MAX)} se "
            "corta sola y sigue con las demás fuentes. Lo que ya ha llegado queda guardado."
        )

    fuente = det.get("fuente") or ""
    if fuente in ("evaluando perfiles", "clasificando por temática"):
        return ("Ya ha descargado todo: ahora está comparando lo nuevo con tus términos de "
                "búsqueda, que es lo último que queda.")

    fase = det.get("fase") or ""
    velocidad = det.get("bytes_por_s") or 0
    partes = []
    if fuente.startswith("placsp"):
        frase = ("La Plataforma de Contratación del Estado publica las novedades en páginas "
                 "de varios megas")
        if velocidad:
            frase += f", y ahora su servidor responde a {_ritmo_legible(velocidad)}"
            if velocidad < 512 * 1024:
                frase += ", así que cada página tarda varios minutos"
        partes.append(frase + ".")
    elif velocidad:
        quien = det.get("titulo") or fuente or "La fuente"
        partes.append(f"{quien[:1].upper()}{quien[1:]} está respondiendo a "
                      f"{_ritmo_legible(velocidad)}.")

    if fase.startswith(("falló el intento", "reconectando")):
        partes.append("Cuando el servidor no contesta se esperan hasta 2 minutos antes de "
                      "reintentar, y la página se vuelve a pedir entera.")

    dias = _dias_desde(ultima_busqueda)
    paginas = det.get("paginas") or 0
    if dias is not None and dias >= 2:
        partes.append(f"Han pasado {dias} días desde la última búsqueda, así que hay más "
                      "páginas que traer" + (f" (van {paginas})." if paginas else "."))
    elif paginas > 1:
        partes.append(f"Van {paginas} páginas.")

    if not partes:
        return None
    partes.append("Lo que ya ha llegado queda guardado.")
    return " ".join(partes)
