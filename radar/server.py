"""Servidor local: sirve la bandeja y una pequeña API JSON.

Usa `http.server` de la biblioteca estándar a propósito. No hay dependencias que
instalar, no hay build, no hay cuentas: un compañero clona la carpeta y arranca.

Escucha solo en 127.0.0.1. No es un servicio multiusuario ni pretende serlo.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import busqueda, consultas, db, pipeline
from .db import ESTADOS_REVISION

log = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parent.parent
WEB = RAIZ / "web"

TIPOS = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class Manejador(BaseHTTPRequestHandler):
    server_version = "licitaciones-radar"
    ruta_bd: Path = db.BD_POR_DEFECTO
    _local = threading.local()

    # --- utilidades ---------------------------------------------------------

    @property
    def con(self) -> sqlite3.Connection:
        # Una conexión por hilo: sqlite3 no admite compartirlas entre hilos.
        if getattr(self._local, "con", None) is None:
            self._local.con = db.conectar(self.ruta_bd)
        return self._local.con

    def _json(self, datos, codigo: int = 200) -> None:
        cuerpo = json.dumps(datos, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _error(self, mensaje: str, codigo: int = 400) -> None:
        self._json({"error": mensaje}, codigo)

    def _estatico(self, ruta: str) -> None:
        nombre = "index.html" if ruta in ("/", "") else ruta.lstrip("/")
        destino = (WEB / nombre).resolve()
        # Nada de servir fuera de web/.
        if not str(destino).startswith(str(WEB.resolve())) or not destino.is_file():
            self.send_error(404, "No encontrado")
            return
        cuerpo = destino.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", TIPOS.get(destino.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, formato, *args):  # silencia el log por petición
        log.debug(formato, *args)

    # --- rutas --------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        partes = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(partes.query).items()}

        if partes.path == "/api/resumen":
            self._json(consultas.resumen(
                self.con, en_marcha=busqueda.en_marcha() is not None
            ))

        elif partes.path == "/api/bandeja":
            try:
                self._json(consultas.bandeja(
                    self.con,
                    perfil=params.get("perfil") or None,
                    estado_revision=params.get("estado") or None,
                    solo_vivas=params.get("vivas", "1") == "1",
                    ccaa=params.get("ccaa") or None,
                    fuente=params.get("fuente") or None,
                    importe_min=float(params["importe_min"]) if params.get("importe_min") else None,
                    cierran_en_dias=(
                        int(params["cierran_en_dias"]) if params.get("cierran_en_dias") else None
                    ),
                    busqueda=params.get("q") or None,
                    solo_novedades=params.get("novedades") == "1",
                    orden=params.get("orden", "urgencia"),
                    limite=min(int(params.get("limite", 200)), 1000),
                    offset=int(params.get("offset", 0)),
                ))
            except sqlite3.OperationalError as exc:
                # Típico: sintaxis de FTS5 inválida en la caja de búsqueda.
                self._error(f"Búsqueda no válida: {exc}")
            except ValueError as exc:
                self._error(str(exc))

        elif partes.path == "/api/vencimientos":
            try:
                meses = max(1, min(int(params.get("meses", 6)), 60))
            except ValueError:
                return self._error("meses no válido")
            self._json(consultas.vencimientos(self.con, meses=meses))

        elif partes.path == "/api/adjudicatarios":
            try:
                limite = max(1, min(int(params.get("limite", 25)), 200))
            except ValueError:
                return self._error("limite no válido")
            self._json({"items": consultas.competencia(self.con, limite=limite)})

        elif partes.path == "/api/contratos-empresa":
            empresa = params.get("empresa")
            if not empresa:
                return self._error("falta empresa")
            self._json({"items": consultas.contratos_de(self.con, empresa)})

        elif partes.path == "/api/motivos-descarte":
            self._json({"items": consultas.motivos_descarte(self.con)})

        elif partes.path == "/api/perfiles":
            from .matching import leer_fichero_perfiles

            try:
                datos = leer_fichero_perfiles()
            except (OSError, ValueError) as exc:
                return self._error(f"No se pudo leer perfiles.json: {exc}", 500)
            self._json({
                "perfiles": datos.get("perfiles", []),
                "ayuda": datos.get("_ayuda", []),
                "motivos_descarte": list(db.MOTIVOS_DESCARTE),
            })

        elif partes.path == "/api/busqueda-estado":
            activa = busqueda.en_marcha()
            self._json({
                "en_marcha": activa is not None,
                "iniciada": (activa or {}).get("iniciada"),
                "progreso": busqueda.ultimas_lineas() if activa else [],
                # Etapa, fase, bytes y ficheros: es lo que pinta la barra. La
                # aplicación distingue una carga inicial de una búsqueda normal por
                # `detalle.etapas`, que solo es > 0 en la primera.
                "detalle": busqueda.detalle_progreso() if activa else None,
                "ultima_busqueda": consultas._ultima_busqueda(self.con),
            })

        elif partes.path == "/api/actualizacion":
            # Sale a internet, así que puede tardar unos segundos y puede fallar; por eso
            # `comprobar()` devuelve el error dentro y no como excepción: quedarse sin
            # red un rato no debe estropear la pantalla.
            from . import actualizacion

            self._json(actualizacion.comprobar())

        elif partes.path.startswith("/api/licitacion/"):
            try:
                lic_id = int(partes.path.rsplit("/", 1)[-1])
            except ValueError:
                return self._error("id no válido")
            # Se une con matches y revisiones: el panel necesita el motivo del
            # match y el estado de triaje, no solo los campos de la licitación.
            fila = self.con.execute(
                """SELECT l.*,
                          (SELECT group_concat(perfil, ' + ') FROM matches
                            WHERE licitacion_id = l.id) AS perfil,
                          (SELECT group_concat(motivo, '  ||  ') FROM matches
                            WHERE licitacion_id = l.id) AS motivo,
                          (SELECT MAX(puntuacion) FROM matches
                            WHERE licitacion_id = l.id) AS puntuacion,
                          COALESCE(r.estado, 'nuevo') AS estado_revision,
                          r.asignado_a, r.notas
                     FROM licitaciones l
                     LEFT JOIN revisiones r ON r.licitacion_id = l.id
                    WHERE l.id = ?""",
                (lic_id,),
            ).fetchone()
            if fila is None:
                return self._error("no encontrada", 404)
            d = dict(fila)
            d["cpv"] = (d.get("cpv") or "").split()
            d["urls_pliegos"] = json.loads(d.get("urls_pliegos") or "[]")
            d.pop("raw", None)
            d["historial"] = consultas.historial(self.con, lic_id)
            self._json(d)

        elif partes.path == "/api/export.csv":
            import csv
            import io

            columnas, filas = consultas.para_csv(
                self.con,
                perfil=params.get("perfil") or None,
                estado_revision=params.get("estado") or None,
                solo_vivas=params.get("vivas", "1") == "1",
                busqueda=params.get("q") or None,
            )
            buffer = io.StringIO()
            escritor = csv.writer(buffer)
            escritor.writerow(columnas)
            escritor.writerows(filas)
            cuerpo = buffer.getvalue().encode("utf-8-sig")  # BOM para que Excel respete acentos
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="licitaciones.csv"')
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        else:
            self._estatico(partes.path)

    def do_POST(self) -> None:  # noqa: N802
        partes = urlparse(self.path)
        longitud = int(self.headers.get("Content-Length") or 0)
        try:
            cuerpo = json.loads(self.rfile.read(longitud) or b"{}")
        except json.JSONDecodeError:
            return self._error("JSON no válido")

        if partes.path == "/api/actualizacion":
            # Se ejecuta la CLI en un proceso aparte, no `aplicar()` aquí dentro: quien
            # sustituye el código no puede ser el proceso que está ejecutando ese código.
            # Es el mismo razonamiento que hace que la búsqueda se lance por CLI.
            from . import actualizacion

            self._json(actualizacion.aplicar_en_subproceso())
            return

        if partes.path == "/api/revision":
            try:
                lic_id = int(cuerpo["licitacion_id"])
            except (KeyError, ValueError, TypeError):
                return self._error("falta licitacion_id")
            estado = cuerpo.get("estado")
            if estado is not None and estado not in ESTADOS_REVISION:
                return self._error(
                    f"estado no válido: {estado}. Válidos: {', '.join(ESTADOS_REVISION)}"
                )
            try:
                db.fijar_revision(
                    self.con, lic_id,
                    estado=estado,
                    asignado_a=cuerpo.get("asignado_a"),
                    notas=cuerpo.get("notas"),
                    motivo_descarte=cuerpo.get("motivo_descarte"),
                )
            except ValueError as exc:
                return self._error(str(exc))
            self.con.commit()
            self._json({"ok": True})

        elif partes.path == "/api/perfiles":
            from .matching import guardar_perfiles, previsualizar, reevaluar, validar_perfiles

            perfiles_json = cuerpo.get("perfiles")
            solo_previsualizar = bool(cuerpo.get("previsualizar"))
            try:
                validados = validar_perfiles(perfiles_json)
            except (ValueError, TypeError) as exc:
                return self._error(str(exc))

            if solo_previsualizar:
                # Nada se escribe: solo se dice qué cambiaría.
                return self._json(previsualizar(self.con, validados))

            try:
                guardar_perfiles(perfiles_json)
            except OSError as exc:
                return self._error(f"No se pudo escribir perfiles.json: {exc}", 500)

            stats = reevaluar(self.con, validados)
            self._json({
                "ok": True,
                "coincidencias": stats["matches"],
                "por_perfil": stats["por_perfil"],
            })

        elif partes.path == "/api/buscar":
            etapas = cuerpo.get("etapas")
            if etapas is not None:
                if not isinstance(etapas, list):
                    return self._error("etapas debe ser una lista de números")
                try:
                    etapas = [int(e) for e in etapas]
                except (TypeError, ValueError):
                    return self._error("etapas debe ser una lista de números")
                if not all(1 <= e <= len(pipeline.ETAPAS_PRIMERA_CARGA) for e in etapas):
                    return self._error(
                        f"etapas fuera de rango (1-{len(pipeline.ETAPAS_PRIMERA_CARGA)})"
                    )
            try:
                datos = busqueda.lanzar(
                    reiniciar_cursor=bool(cuerpo.get("reiniciar_cursor")),
                    dias=cuerpo.get("dias"),
                    primera_carga=bool(cuerpo.get("primera_carga")),
                    etapas=etapas,
                )
            except RuntimeError as exc:
                # 409: no es un error del usuario, es que ya se está haciendo.
                return self._error(str(exc), 409)
            except OSError as exc:
                return self._error(f"No se pudo lanzar la búsqueda: {exc}", 500)
            self._json({"ok": True, **datos})

        elif partes.path == "/api/cancelar-busqueda":
            self._json({"ok": busqueda.cancelar()})

        elif partes.path == "/api/visita":
            # Marca "he visto lo de hasta ahora": lo que llegue después cuenta como
            # novedad. Se llama al pulsar el contador, no al abrir la página, para
            # que abrir la bandeja sin mirar nada no borre las novedades.
            ultimo = self.con.execute(
                "SELECT COALESCE(MAX(id), 0) FROM licitaciones"
            ).fetchone()[0]
            db.escribir_preferencia(self.con, "ultima_visita_id", str(ultimo))
            db.escribir_preferencia(self.con, "ultima_visita", db.ahora())
            self.con.commit()
            self._json({"ok": True, "marca": ultimo})
        else:
            self._error("ruta no encontrada", 404)


def arrancar(puerto: int = 8811, ruta_bd: Path | None = None) -> ThreadingHTTPServer:
    Manejador.ruta_bd = ruta_bd or db.BD_POR_DEFECTO
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    return servidor
