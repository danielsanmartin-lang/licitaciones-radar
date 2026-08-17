"""Capa de red: descargas con TLS verificado, reintentos y caché condicional.

Por qué existe este módulo en lugar de llamar a urlopen directamente:

Hay dos problemas de TLS que rompen la ingesta si se usa urlopen a pelo:

1. Sitios de la administración española (PLACSP, euskadi.eus) sirven cadenas
   firmadas por raíces ausentes del almacén de macOS/OpenSSL:
   `AC RAIZ FNMT-RCM SERVIDORES SEGUROS` (FNMT-RCM) e `Izenpe.com`. Sin ellas el
   handshake falla con "self signed certificate in certificate chain".
2. Los Python instalados desde python.org suelen venir con CERO raíces cargadas
   (`cert_store_stats() == {'x509': 0}`), así que depender del almacén del sistema
   hace que la herramienta funcione en un Mac y falle en el de al lado.

La solución NO es desactivar la verificación en ningún caso. Se usa el bundle
autocontenido `config/certs/ca-bundle.pem` (almacén de Mozilla, que ya incluye las
raíces españolas) y, de forma aditiva, lo que el sistema tenga cargado. Resultado:
comportamiento idéntico en cualquier equipo y verificación siempre activa.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import progreso

log = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parent.parent
BUNDLE_CA = RAIZ / "config" / "certs" / "ca-bundle.pem"

# Huellas SHA-256 de las raíces españolas que el bundle DEBE contener. No es una
# comprobación de integridad del bundle completo: es un canario para detectar que
# alguien lo ha regenerado desde una fuente que se dejó fuera estas CAs, que es
# el fallo que rompería PLACSP de forma silenciosa.
HUELLAS_ESPERADAS = {
    "554153b13d2cf9ddb753bfbe1a4e0ae08d0aa4187058fe60a2b862b2e4b87bcb",  # AC RAIZ FNMT-RCM SERVIDORES SEGUROS
    "ebc5570c29018c4d67b1aa127baf12f703b4611ebc17b7dab5573894179b93fa",  # AC RAIZ FNMT-RCM
    "2530cc8e98321502bad96f9b1fba1b099e2d299e0f4548bb914f363bc0d4531f",  # Izenpe.com
}

USER_AGENT = (
    "licitaciones-radar/1.0 (herramienta interna de seguimiento de licitaciones; "
    "+https://github.com/)"
)

_contexto: ssl.SSLContext | None = None


class ErrorRed(Exception):
    """Fallo de red no recuperable tras agotar los reintentos.

    `codigo` lleva el estado HTTP cuando lo hubo, y sirve para distinguir «esto no
    existe» de «esto se ha roto»: PLACSP no publica el ZIP anual de todos los años en
    todos los datasets, y un 404 ahí es información, no una avería.
    """

    def __init__(self, mensaje: str, *, codigo: int | None = None):
        super().__init__(mensaje)
        self.codigo = codigo


def _huellas_del_bundle(ruta: Path) -> set[str]:
    texto = ruta.read_text(encoding="utf-8")
    huellas = set()
    marca_ini = "-----BEGIN CERTIFICATE-----"
    marca_fin = "-----END CERTIFICATE-----"
    pos = 0
    while True:
        ini = texto.find(marca_ini, pos)
        if ini == -1:
            break
        fin = texto.find(marca_fin, ini)
        if fin == -1:
            break
        fin += len(marca_fin)
        pem = texto[ini:fin] + "\n"
        huellas.add(hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest())
        pos = fin
    return huellas


def contexto_ssl() -> ssl.SSLContext:
    """Contexto TLS con el bundle del repo MÁS lo que tenga cargado el sistema."""
    global _contexto
    if _contexto is not None:
        return _contexto

    if not BUNDLE_CA.exists():
        raise ErrorRed(
            f"Falta el bundle de CAs en {BUNDLE_CA}. Sin él PLACSP fallará el "
            "handshake TLS. Regenéralo con: python3 herramientas/regenerar_ca_bundle.py"
        )

    huellas = _huellas_del_bundle(BUNDLE_CA)
    if not HUELLAS_ESPERADAS.issubset(huellas):
        raise ErrorRed(
            "El bundle de CAs no incluye las raíces de la administración española "
            f"(faltan {len(HUELLAS_ESPERADAS - huellas)} de {len(HUELLAS_ESPERADAS)}). "
            "PLACSP fallaría. Regenera config/certs/ca-bundle.pem antes de seguir."
        )

    ctx = ssl.create_default_context(cafile=str(BUNDLE_CA))
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    # Aditivo: si el intérprete sí tiene raíces del sistema, las sumamos para no
    # quedarnos atrás cuando el bundle empaquetado envejezca.
    try:
        ctx.load_default_certs()
    except Exception:  # noqa: BLE001 - almacén del sistema ausente o ilegible
        log.debug("El sistema no aporta raíces adicionales; se usa solo el bundle del repo")

    _contexto = ctx
    return ctx


def _abrir(req: urllib.request.Request, timeout: int):
    return urllib.request.urlopen(req, timeout=timeout, context=contexto_ssl())


def _longitud(resp) -> int | None:
    try:
        return int(resp.headers.get("Content-Length") or 0) or None
    except (TypeError, ValueError):
        return None


def _leer_contando(resp) -> bytes:
    """Lee la respuesta a trozos, informando de lo que va llegando.

    `resp.read()` de una sentada daría el mismo resultado, pero deja el contador
    a cero hasta que termina: justo lo que hace que una descarga lenta parezca
    un cuelgue. Los trozos de 64 kB no cambian el rendimiento de forma medible
    en feeds de decenas de MB y sí permiten pintar el avance.
    """
    progreso.bytes_totales(_longitud(resp))
    trozos = []
    while trozo := resp.read(64 << 10):
        trozos.append(trozo)
        progreso.sumar_bytes(len(trozo))
    return b"".join(trozos)


def _esperar(segundos: int, etiqueta: str) -> None:
    """Duerme mostrando la cuenta atrás, para que la espera no parezca un cuelgue."""
    for restante in range(segundos, 0, -1):
        progreso.fase(f"{etiqueta}, reintento en {restante}s")
        time.sleep(1)


def descargar(
    url: str,
    *,
    datos: bytes | None = None,
    cabeceras: dict[str, str] | None = None,
    timeout: int = 120,
    intentos: int = 4,
    etag: str | None = None,
    modificado_desde: str | None = None,
) -> tuple[bytes, dict[str, str], int]:
    """Descarga una URL. Devuelve (cuerpo, cabeceras_respuesta, codigo).

    Con `etag` o `modificado_desde` puede devolver código 304 y cuerpo vacío:
    el llamante debe interpretarlo como "sin cambios" y no reprocesar nada.
    """
    cab = {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip",
    }
    if cabeceras:
        cab.update(cabeceras)
    if etag:
        cab["If-None-Match"] = etag
    if modificado_desde:
        cab["If-Modified-Since"] = modificado_desde

    ultimo_error: Exception | None = None
    for intento in range(1, intentos + 1):
        req = urllib.request.Request(url, data=datos, headers=cab)
        progreso.reiniciar_bytes()
        progreso.fase("conectando" if intento == 1 else f"reconectando ({intento}/{intentos})")
        try:
            with _abrir(req, timeout) as resp:
                progreso.fase("descargando")
                cuerpo = _leer_contando(resp)
                if resp.headers.get("Content-Encoding") == "gzip":
                    cuerpo = gzip.decompress(cuerpo)
                return cuerpo, dict(resp.headers), resp.status
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return b"", dict(exc.headers or {}), 304
            # 4xx (salvo 429) no se arregla reintentando.
            if 400 <= exc.code < 500 and exc.code != 429:
                # El cuerpo del 400 suele decir exactamente qué campo sobra o falta.
                # Sin él, depurar una consulta a TED es adivinar.
                try:
                    detalle = exc.read().decode("utf-8", "replace")[:800]
                except Exception:  # noqa: BLE001
                    detalle = ""
                raise ErrorRed(
                    f"{url} -> HTTP {exc.code} {exc.reason}"
                    + (f"\n  respuesta: {detalle}" if detalle else ""),
                    codigo=exc.code,
                ) from exc
            ultimo_error = exc
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
            ultimo_error = exc

        if intento < intentos:
            espera = min(2 ** intento, 30)
            log.warning(
                "Fallo al descargar %s (intento %d/%d): %s. Reintento en %ds",
                url, intento, intentos, ultimo_error, espera,
            )
            _esperar(espera, f"falló el intento {intento}/{intentos}")

    raise ErrorRed(f"{url} falló tras {intentos} intentos: {ultimo_error}")


def descargar_json(url: str, **kwargs) -> object:
    cuerpo, _, codigo = descargar(url, **kwargs)
    if codigo == 304:
        return None
    return json.loads(cuerpo.decode("utf-8"))


def post_json(url: str, payload: dict, *, timeout: int = 120, intentos: int = 4) -> object:
    cuerpo, _, _ = descargar(
        url,
        datos=json.dumps(payload).encode("utf-8"),
        cabeceras={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=timeout,
        intentos=intentos,
    )
    return json.loads(cuerpo.decode("utf-8"))


def descargar_a_fichero(url: str, destino: Path, *, timeout: int = 600) -> Path:
    """Descarga en streaming a disco. Para los ZIP anuales de PLACSP, que son grandes."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    parcial = destino.with_suffix(destino.suffix + ".parcial")
    progreso.reiniciar_bytes()
    progreso.fase("conectando")
    try:
        with _abrir(req, timeout) as resp, parcial.open("wb") as fh:
            progreso.fase("descargando")
            progreso.bytes_totales(_longitud(resp))
            while trozo := resp.read(1 << 20):
                fh.write(trozo)
                progreso.sumar_bytes(len(trozo))
    except urllib.error.HTTPError as exc:
        parcial.unlink(missing_ok=True)
        raise ErrorRed(f"{url} -> HTTP {exc.code} {exc.reason}", codigo=exc.code) from exc
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        parcial.unlink(missing_ok=True)
        raise ErrorRed(f"{url} falló: {exc}") from exc
    parcial.replace(destino)
    return destino
