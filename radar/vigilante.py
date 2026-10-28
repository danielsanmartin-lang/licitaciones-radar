"""Vigilante de la ingesta: corta lo que se ha quedado clavado de verdad.

Por qué existe: hasta ahora lo único que podía poner fin a una ingesta atascada era el
timeout de 120 s de cada lectura de red. Si el proceso se quedaba bloqueado en otro
sitio, el cerrojo de `busqueda.py` seguía tomado, nadie podía lanzar otra búsqueda y la
pantalla de arranque esperaba sin límite.

Lo que NO hace es cortar una búsqueda lenta. La que motivó esto —1h45 bajando de
PLACSP a 0,05 MB/s— avanzaba todo el rato, y cortarla habría sido peor: lo pendiente de
PLACSP se vuelve a pedir entero la vez siguiente, así que con una línea así no se
pondría al día nunca. Se mira `progreso.sin_avance()`, que solo crece cuando no se mueve
NADA de lo que cuenta el indicador —bytes, fichas, páginas, fase—. Los reintentos
cambian la fase y las descargas lentas suman bytes, así que ninguna de las dos cosas
parece un atasco.

Cómo corta: manda `SIGUSR1` al hilo principal, cuyo manejador lanza `Atascada`. Eso
interrumpe incluso una lectura de socket bloqueada (PEP 475: si el manejador lanza, la
llamada al sistema no se reintenta), y `pipeline.ingerir` la recoge por fuente, como
cualquier otro fallo, para seguir con las demás. Si el hilo principal no reacciona —un
bloqueo dentro de código en C, donde los manejadores de Python no llegan a ejecutarse—,
al cabo de un minuto se termina el proceso a lo bruto. El cerrojo huérfano lo limpia
`busqueda.en_marcha()` al ver que el pid ya no existe.

Como `progreso`, es inocuo si nadie lo ha iniciado o si el indicador no está activo
(`RADAR_SIN_PROGRESO` en los tests): sin indicador no hay avance que medir.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time

from . import progreso

log = logging.getLogger(__name__)


def _umbral_por_defecto() -> float:
    """15 minutos, salvo que `RADAR_SIN_AVANCE_MAX` diga otra cosa (en segundos).

    Quince y no menos: el peor caso legítimo de la red —cuatro intentos de 120 s más sus
    esperas— ronda los ocho, y durante ese rato al menos la fase sí cambia. La variable
    está para poder ver el vigilante en acción sin esperar un cuarto de hora.
    """
    try:
        return float(os.environ.get("RADAR_SIN_AVANCE_MAX") or 15 * 60)
    except ValueError:
        return 15 * 60.0


SIN_AVANCE_MAX = _umbral_por_defecto()
COMPROBAR_CADA = 10.0   # s entre miradas del vigilante
GRACIA = 60.0           # s que se le dan al hilo principal para soltar antes de salir
CODIGO_SALIDA = 3


class Atascada(BaseException):
    """La ingesta lleva demasiado sin avanzar.

    Hereda de BaseException, como KeyboardInterrupt, a propósito: los `except Exception`
    de las fuentes y los `except OSError` de la capa de red se la tragarían, y entonces
    lo único que conseguiría es que el bucle de reintentos volviera a empezar.
    """


class _Vigilante:
    def __init__(self) -> None:
        self._hilo: threading.Thread | None = None
        self._parada = threading.Event()
        self._principal: int | None = None
        self._anterior = None
        self._con_senal = False
        self.umbral = SIN_AVANCE_MAX
        self._salir = os._exit
        self._cada = COMPROBAR_CADA
        self._gracia = GRACIA

    def iniciar(self, *, sin_avance_max: float | None = None, salir=None,
                comprobar_cada: float | None = None, gracia: float | None = None) -> None:
        """Arranca la vigilancia. Se llama desde el hilo principal, después de
        `progreso.iniciar()`. Se puede llamar dos veces sin romper nada."""
        if self._hilo is not None:
            return
        self.umbral = sin_avance_max if sin_avance_max is not None else SIN_AVANCE_MAX
        self._salir = salir or os._exit
        self._cada = comprobar_cada if comprobar_cada is not None else COMPROBAR_CADA
        self._gracia = gracia if gracia is not None else GRACIA
        self._principal = threading.get_ident()
        try:
            self._anterior = signal.signal(signal.SIGUSR1, self._manejador)
            self._con_senal = True
        except (ValueError, AttributeError):
            # Fuera del hilo principal no se pueden instalar manejadores. Queda solo la
            # salida a lo bruto, que es peor pero sigue soltando el cerrojo.
            self._con_senal = False
        self._parada.clear()
        self._hilo = threading.Thread(target=self._bucle, name="vigilante", daemon=True)
        self._hilo.start()

    def parar(self) -> None:
        hilo = self._hilo
        self._parada.set()
        if hilo is not None:
            hilo.join(timeout=1.0)
        self._hilo = None
        if self._con_senal:
            try:
                signal.signal(signal.SIGUSR1, self._anterior or signal.SIG_DFL)
            except (ValueError, TypeError):
                pass
            self._con_senal = False

    def _manejador(self, signum, frame) -> None:  # noqa: ARG002 - firma de signal
        raise Atascada(
            f"sin avanzar desde hace {progreso._dur(self.umbral)}"
            f" ({progreso.instantanea().get('resumen', '')})"
        )

    def _bucle(self) -> None:
        disparada: float | None = None
        while not self._parada.wait(self._cada):
            callado = progreso.sin_avance()
            if callado < self.umbral:
                # Ha vuelto a moverse —lo normal tras abortar una fuente: la siguiente
                # empieza y el indicador cambia—, así que se rearma.
                disparada = None
                continue
            ahora = time.monotonic()
            if disparada is None:
                disparada = ahora
                log.error(
                    "La búsqueda lleva %s sin avanzar (%s). Se aborta esta fuente para "
                    "no dejar la aplicación esperando; la próxima búsqueda la retoma.",
                    progreso._dur(callado), progreso.instantanea().get("resumen", ""),
                )
                if self._con_senal and self._principal is not None:
                    try:
                        signal.pthread_kill(self._principal, signal.SIGUSR1)
                    except (OSError, ValueError, AttributeError):
                        pass
                continue
            if ahora - disparada >= self._gracia:
                log.critical(
                    "No ha respondido en %s después de avisarle. Se termina el proceso "
                    "para soltar el cerrojo.", progreso._dur(self._gracia),
                )
                for manejador in logging.getLogger().handlers:
                    try:
                        manejador.flush()
                    except Exception:  # noqa: BLE001 - se va a salir de todas formas
                        pass
                self._salir(CODIGO_SALIDA)
                return


_VIG = _Vigilante()

iniciar = _VIG.iniciar
parar = _VIG.parar
