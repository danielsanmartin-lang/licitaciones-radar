#!/usr/bin/env python3
"""Radar de Licitaciones — buscador de licitaciones públicas españolas.

Herramienta autónoma: no se conecta a ningún CRM, vault ni sistema personal.
Todo vive en esta carpeta (base SQLite en data/radar.db).

    python3 radar.py ingest                    # incremental, todas las fuentes
    python3 radar.py ingest --primera-carga    # instalación nueva: trae el histórico
    python3 radar.py ingest --fuente placsp    # una fuente
    python3 radar.py ingest --backfill 2025    # histórico de un año
    python3 radar.py match                     # reevalúa perfiles sin descargar
    python3 radar.py serve                     # bandeja en http://127.0.0.1:8811
    python3 radar.py export licitaciones.csv
    python3 radar.py vencimientos              # contratos que vencen pronto
    python3 radar.py adjudicatarios            # quién gana estos contratos
    python3 radar.py programar                 # descarga automática cada mañana
    python3 radar.py estado                    # salud de las fuentes
    python3 radar.py doctor                    # autodiagnóstico: ¿está todo en su sitio?
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import webbrowser
from datetime import date
from pathlib import Path

from radar import consultas, db, pipeline, progreso
from radar.matching import cargar_perfiles, reevaluar

RAIZ = Path(__file__).resolve().parent


def _log(verboso: bool) -> None:
    # El manejador es el del indicador de progreso: borra la línea de estado
    # antes de escribir para que los mensajes no salgan con restos pegados.
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO,
        format="%(message)s",
        handlers=[progreso.ManejadorLog(sys.stdout)],
    )


def cmd_ingest(args) -> int:
    from radar import busqueda

    # El cerrojo lo toma la ingesta, no quien la lanza: la tarea programada de cada
    # mañana ejecuta este comando directamente y dos ingestas a la vez se pelean por
    # el bloqueo de escritura de SQLite.
    if not busqueda.adquirir("cli"):
        activa = busqueda.en_marcha() or {}
        print(f"Ya hay una búsqueda en marcha (desde {activa.get('iniciada', '?')}). "
              "No se lanza otra.", file=sys.stderr)
        return 1
    progreso.iniciar()
    try:
        return _ingest(args)
    finally:
        progreso.parar()
        busqueda.liberar()


def _evaluar_perfiles(con, perfiles, *, incremental: bool = False) -> None:
    """Reevalúa y cuenta. Se imprime con progreso.imprimir: hay una línea de estado
    viva en la terminal y un print() a secas la dejaría a medio borrar.

    Con `incremental` solo se miran las fichas nuevas o modificadas de verdad. La
    reevaluación puede acabar siendo completa igualmente si los perfiles han cambiado
    —lo decide `reevaluar`—, y entonces se dice por qué: «no ha cambiado nada» y «lo he
    reevaluado todo porque tocaste los términos» son dos cosas distintas.
    """
    progreso.imprimir("\nEvaluando perfiles...")
    stats = reevaluar(con, perfiles, incremental=incremental)
    if stats["completa"]:
        progreso.imprimir(
            f"  {stats['evaluadas']} licitaciones evaluadas · "
            f"{stats['matches']} coincidencias"
        )
    else:
        progreso.imprimir(
            f"  {stats['evaluadas']} nuevas o modificadas evaluadas · "
            f"{stats['matches']} coincidencias en total"
        )
    if stats["motivo"]:
        progreso.imprimir(f"  (pasada completa: {stats['motivo']})")
    for perfil, n in sorted(stats["por_perfil"].items(), key=lambda x: -x[1]):
        progreso.imprimir(f"    {perfil}: {n}")


def _aviso_fallidas(fallidas) -> int:
    if fallidas:
        progreso.imprimir(
            f"\nFuentes con error: {', '.join(sorted(set(fallidas)))}. "
            "Detalle en 'radar.py estado'."
        )
        return 1
    return 0


def _primera_carga(args) -> int:
    """Construye el histórico por etapas, de la más barata a la más cara.

    Existe porque una instalación nueva no puede llegar al histórico por sí sola: el
    conector de PLACSP trae una sola página del feed diario cuando no hay cursor, y en
    cuanto se escribe ese cursor la ingesta incremental —con razón— solo mira hacia
    delante. Sin esto, una copia recién descomprimida se queda en unas 50 coincidencias
    para siempre y parece que la herramienta no funciona.
    """
    perfiles = cargar_perfiles(args.perfiles)
    con = db.conectar(args.bd)
    etapas = pipeline.ETAPAS_PRIMERA_CARGA
    pedidas = sorted(set(args.etapas)) if args.etapas else list(range(1, len(etapas) + 1))
    anios = pipeline.anios_primera_carga(date.today())
    fallidas = []

    for numero in pedidas:
        etapa = etapas[numero - 1]
        # El coste y el detalle no son solo para esta línea impresa: la aplicación los
        # enseña durante toda la etapa, que es lo que distingue «tarda dos horas» de
        # «se ha quedado colgada».
        progreso.etapa(numero, len(etapas), etapa["etiqueta"],
                       etapa["coste"], etapa["detalle"])
        progreso.imprimir(
            f"\n[{numero}/{len(etapas)}] {etapa['etiqueta']}\n"
            f"    {etapa['coste']} · {etapa['detalle']}"
        )
        fuentes = pipeline.construir_fuentes(
            etapa["fuentes"], perfiles, dias_ventana=args.dias,
            paginas_primera_vez=pipeline.PAGINAS_CIERRE,
        )
        resumen = pipeline.ingerir(
            con, fuentes, anios=anios if etapa["historico"] else None
        )
        fallidas += [f for f, r in resumen.items() if r["error"]]

        # Se reevalúa al final de CADA etapa, no una sola vez al terminar todo: es lo
        # que hace que los contadores de la bandeja suban a la vista mientras el resto
        # sigue descargando por detrás.
        #
        # Incremental, porque cada etapa solo tiene que mirar lo que ella misma acaba de
        # traer: lo de las etapas anteriores ya está evaluado. Evaluándolo todo, la
        # cuarta etapa recorría por cuarta vez la base entera para no cambiar nada.
        _evaluar_perfiles(con, perfiles, incremental=True)

    pendientes = [n for n in range(1, len(etapas) + 1) if n not in pedidas]
    if pendientes:
        progreso.imprimir("\nEtapas que no se han hecho:")
        for n in pendientes:
            progreso.imprimir(f"  [{n}] {etapas[n - 1]['etiqueta']} — {etapas[n - 1]['coste']}")
        progreso.imprimir(
            "  Para traerlas: python3 radar.py ingest --primera-carga --etapas "
            + " ".join(str(n) for n in pendientes)
        )

    return _aviso_fallidas(fallidas)


def _ingest(args) -> int:
    if args.primera_carga:
        return _primera_carga(args)

    perfiles = cargar_perfiles(args.perfiles)
    fuentes = pipeline.construir_fuentes(args.fuente, perfiles, dias_ventana=args.dias)

    anios = None
    if args.backfill:
        anios = sorted({int(a) for parte in args.backfill for a in parte.split(",")})
        progreso.imprimir(f"Backfill de {anios}. La primera vez puede tardar bastante.\n")

    con = db.conectar(args.bd)
    resumen = pipeline.ingerir(
        con, fuentes, anios=anios, reiniciar_cursor=args.reiniciar_cursor
    )

    # Incremental: esto se ejecuta cada mañana sobre una base que casi no cambia.
    _evaluar_perfiles(con, perfiles, incremental=True)
    return _aviso_fallidas([f for f, r in resumen.items() if r["error"]])


def cmd_match(args) -> int:
    perfiles = cargar_perfiles(args.perfiles)
    con = db.conectar(args.bd)
    progreso.iniciar()
    try:
        stats = reevaluar(con, perfiles)
    finally:
        progreso.parar()
    print(f"{stats['evaluadas']} licitaciones evaluadas · {stats['matches']} coincidencias")
    for perfil, n in sorted(stats["por_perfil"].items(), key=lambda x: -x[1]):
        print(f"  {perfil}: {n}")
    if stats["evaluadas"] == 0:
        print("\nLa base está vacía. Lanza primero: python3 radar.py ingest")
    return 0


def cmd_serve(args) -> int:
    from radar import server

    con = db.conectar(args.bd)
    total = con.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    con.close()
    if total == 0:
        print("Aviso: no hay coincidencias todavía. Lanza 'python3 radar.py ingest' primero.\n")

    servidor = server.arrancar(args.puerto, args.bd)
    url = f"http://127.0.0.1:{args.puerto}/"
    print(f"Bandeja en {url}   (Ctrl+C para parar)")
    if not args.sin_navegador:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nParado.")
    finally:
        servidor.server_close()
    return 0


def cmd_export(args) -> int:
    con = db.conectar(args.bd)
    columnas, filas = consultas.para_csv(
        con, perfil=args.perfil, estado_revision=args.estado, solo_vivas=not args.todas
    )
    destino = Path(args.destino)
    with destino.open("w", newline="", encoding="utf-8-sig") as fh:
        escritor = csv.writer(fh)
        escritor.writerow(columnas)
        escritor.writerows(filas)
    print(f"{len(filas)} filas -> {destino}")
    return 0


def cmd_vencimientos(args) -> int:
    con = db.conectar(args.bd)
    v = consultas.vencimientos(con, meses=args.meses, limite=args.limite)
    if not v["items"]:
        print(f"Nada vence en los próximos {args.meses} meses.")
        print("Necesitas histórico de adjudicaciones:")
        print("  python3 radar.py ingest --primera-carga")
        return 0
    print(f"Contratos que vencen en los próximos {args.meses} meses ({v['total']} en total)\n")
    for it in v["items"]:
        imp = f"{it['importe']:,.0f} €" if it["importe"] else "s/i"
        print(f"  {it['fecha_fin_prevista'][:10]}  ({it['dias_para_vencer']:>4} d)  {imp:>14}  "
              f"{(it['objeto'] or '')[:58]}")
        print(f"{'':16}incumbente: {(it['adjudicatario'] or '(no publicado)')[:60]}")
        print(f"{'':16}{(it['organo'] or '')[:70]}")
    print("\nSolo aparecen los que publican fecha de fin o duración; si la fuente no")
    print("la da, la licitación no se lista en lugar de estimarla a ojo.")
    return 0


def cmd_adjudicatarios(args) -> int:
    con = db.conectar(args.bd)
    filas = consultas.competencia(con, limite=args.limite)
    if not filas:
        print("Todavía no hay adjudicaciones en la base. Prueba con:")
        print("  python3 radar.py ingest --primera-carga")
        return 0
    print("Quién se lleva estos contratos\n")
    print(f"{'contratos':>9}  {'importe total':>16}  {'organismos':>10}  empresa")
    for f in filas:
        print(f"{f['contratos']:>9}  {f['importe']:>14,.0f} €  {f['organos']:>10}  {f['empresa'][:52]}")
    print("\nImportes de adjudicación cuando se publican; si no, el de licitación.")
    return 0


def cmd_programar(args) -> int:
    from radar import programar

    if args.desinstalar:
        if programar.desinstalar():
            print(f"Tarea eliminada: {programar.PLIST}")
        else:
            print("No había ninguna tarea instalada.")
        return 0

    if args.ver:
        e = programar.estado()
        print(f"Instalada: {'sí' if e['instalada'] else 'no'}"
              f" · cargada en launchd: {'sí' if e['cargada'] else 'no'}")
        print(f"  fichero: {e['plist']}")
        print(f"  registro: {e['log']}")
        return 0

    # Se avisa antes de escribir: es el único fichero que el proyecto crea fuera
    # de su carpeta.
    print(f"Voy a crear {programar.PLIST}")
    print(f"para ejecutar la descarga cada día a las {args.hora:02d}:{args.minuto:02d}.")
    print(f"El registro quedará en {programar.LOG}")
    print("Para deshacerlo: python3 radar.py programar --desinstalar\n")
    try:
        ruta = programar.instalar(args.hora, args.minuto)
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Listo. Tarea instalada en {ruta}")
    return 0


def cmd_actualizar(args) -> int:
    """Comprueba si hay versión nueva y, si se pide, la instala.

    `--json` existe para que la aplicación pueda leer el resultado: el botón de la
    interfaz lanza este mismo comando en un proceso aparte, igual que hace con la
    descarga, en lugar de tener su propio camino de ejecución.
    """
    from radar import actualizacion

    if args.solo_comprobar:
        info = actualizacion.comprobar()
        if args.json:
            print(json.dumps(info, ensure_ascii=False))
            return 0 if not info["error"] else 1
        if info["error"]:
            print(f"No se ha podido comprobar: {info['error']}", file=sys.stderr)
            return 1
        if info["hay_nueva"]:
            print(f"Hay una versión nueva: {info['version_nueva']} "
                  f"(tienes la {info['version_actual']})")
            print("Para instalarla: python3 radar.py actualizar")
        else:
            print(f"Estás en la última versión ({info['version_actual']}).")
        return 0

    resultado = actualizacion.aplicar()
    if args.json:
        print(json.dumps(resultado, ensure_ascii=False))
    else:
        print(resultado["mensaje"])
    return 0 if resultado["ok"] else 1


# Cuatro caracteres las cuatro, para que la columna del mensaje quede alineada.
MARCAS_DIAGNOSTICO = {"ok": "[ok ]", "omitida": "[-- ]", "aviso": "[!! ]", "error": "[ERR]"}


def cmd_doctor(args) -> int:
    """Autodiagnóstico. Aquí solo se pinta: las comprobaciones viven en el módulo.

    Devuelve 1 solo si hay algún error. Los avisos pueden ser decisiones legítimas —no
    tener la tarea diaria, no haber construido el histórico— y si contaran como fallo el
    código de salida no serviría para nada.
    """
    from radar import diagnostico

    comprobaciones = diagnostico.diagnosticar(
        bd=args.bd, perfiles=args.perfiles,
        con_red=args.con_red, integridad=args.integridad,
    )
    fallos = diagnostico.hay_errores(comprobaciones)

    if args.json:
        print(json.dumps(diagnostico.a_json(comprobaciones), ensure_ascii=False))
        return 1 if fallos else 0

    for c in comprobaciones:
        print(f"{MARCAS_DIAGNOSTICO[c.estado]} {c.nombre:22} {c.mensaje}")
        if c.remedio and c.estado != "ok":
            print(f"       → {c.remedio}")

    avisos = sum(1 for c in comprobaciones if c.estado == "aviso")
    errores = sum(1 for c in comprobaciones if c.estado == "error")
    print()
    if errores:
        print(f"{errores} cosa(s) que hay que arreglar y {avisos} aviso(s).")
    elif avisos:
        print(f"Nada roto. {avisos} aviso(s), por si te interesan.")
    else:
        print("Todo en su sitio.")
    return 1 if fallos else 0


def cmd_estado(args) -> int:
    if args.limpiar_cache:
        cache = RAIZ / "data" / "cache"
        borrados = 0
        # También los `.parcial`: una descarga cortada deja ahí lo que llevaba bajado
        # para poder reanudarla, y con el glob a secas de `*.zip` un resto de 900 MB
        # quedaba invisible en el informe e imborrable desde la herramienta.
        for patron in ("*.zip", "*.zip.parcial*"):
            for f in sorted(cache.glob(patron)):
                tam = f.stat().st_size
                f.unlink()
                borrados += tam
                print(f"  borrado {f.name} ({tam / 1e6:.0f} MB)")
        print(f"Liberados {borrados / 1e6:.0f} MB." if borrados else "La caché ya estaba vacía.")
        return 0

    from radar import busqueda

    con = db.conectar(args.bd)
    # Si hay una ingesta corriendo ahora mismo, su fila de registro está abierta y no
    # debe leerse como una fuente rota.
    r = consultas.resumen(con, en_marcha=busqueda.en_marcha() is not None)
    # Todas las cifras son expedientes agrupados, las mismas que muestra la
    # aplicación. No se lista el total descargado: es un número que no se puede
    # consultar en ninguna vista y solo despista.
    print(f"Coincidencias        : {r['coincidencias']:,}")
    print(f"Abiertas (en plazo)  : {r['en_plazo']:,}")
    print(f"Cierran en 7 días    : {r['cierran_7_dias']:,}")
    print(f"Sin revisar          : {r['sin_revisar']:,}")
    print(f"En seguimiento       : {r['siguiendo']:,}")
    print(f"Presentadas          : {r['presentadas']:,}")
    if r["ultima_busqueda"]:
        print(f"Última búsqueda      : {r['ultima_busqueda'][:16].replace('T', ' ')}")

    print("\nPor perfil:")
    for p in r["por_perfil"]:
        print(f"  {p['perfil']:42} {p['total']:6,}  ({p['nuevos']} sin revisar)")

    print("\nFuentes:")
    if not r["fuentes"]:
        print("  (ninguna ingesta ejecutada todavía)")
    for f in r["fuentes"]:
        marca = "..." if f["en_curso"] else ("ok " if f["ok"] else "ERR")
        print(f"  [{marca}] {f['fuente']:28} {f['iniciado_en'][:16]}  "
              f"{f['vistos']:6,} vistas  {f['nuevos']:5,} nuevas")
        if f["aviso"]:
            print(f"         ¡atención! {f['aviso']}")
        if f["error"]:
            print(f"         {f['error'][:160]}")

    # Los ZIP del histórico se guardan para no volver a descargarlos, pero ocupan
    # y nadie los encuentra si no se dicen. La cuenta la hace el diagnóstico, que es el
    # que ya sabe distinguir un ZIP bueno de uno a medias: duplicar el glob aquí es cómo
    # se acaba con dos cifras distintas del mismo disco.
    from radar import diagnostico

    cache = diagnostico.cache_de_historicos()
    if cache.datos.get("ficheros") or cache.datos.get("parciales"):
        print(f"\nCaché de históricos: {cache.mensaje}")
        if cache.remedio:
            print(f"  {cache.remedio}")
        else:
            print("  Se pueden borrar sin perder nada: "
                  "python3 radar.py estado --limpiar-cache")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="radar.py",
        description="Radar de licitaciones públicas (concienciación y seguridad).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--bd", default=None, help="ruta de la base (por defecto data/radar.db)")
    p.add_argument("--perfiles", default=None, help="ruta de perfiles.json")
    p.add_argument("-v", "--verboso", action="store_true")
    sub = p.add_subparsers(dest="comando", required=True)

    s = sub.add_parser("ingest", help="descarga y normaliza licitaciones")
    s.add_argument("--fuente", action="append",
                   help=f"repetible. Disponibles: {', '.join(pipeline.FUENTES_DISPONIBLES)}")
    s.add_argument("--backfill", action="append", metavar="AÑO",
                   help="año o años separados por coma, p.ej. 2024,2025")
    s.add_argument("--primera-carga", action="store_true",
                   help="construye el histórico por etapas, de la más barata a la más "
                        "cara. Es lo que necesita una instalación nueva")
    s.add_argument("--etapas", nargs="+", type=int, metavar="N",
                   choices=range(1, len(pipeline.ETAPAS_PRIMERA_CARGA) + 1),
                   help="etapas de --primera-carga que se quieren lanzar (por defecto "
                        "todas). Permite abrir la aplicación con la primera hecha y "
                        "dejar el resto descargando por detrás")
    s.add_argument("--dias", type=int, default=30,
                   help="ventana en días para TED y Cataluña la primera vez (30)")
    s.add_argument("--reiniciar-cursor", action="store_true",
                   help="olvida por dónde se quedó y vuelve a pedir la ventana completa "
                        "(necesario tras cambiar perfiles.json o un conector)")
    s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("match", help="reevalúa los perfiles sobre lo ya descargado")
    s.set_defaults(func=cmd_match)

    s = sub.add_parser("serve", help="abre la bandeja en el navegador")
    s.add_argument("--puerto", type=int, default=8811)
    s.add_argument("--sin-navegador", action="store_true")
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("export", help="exporta a CSV")
    s.add_argument("destino")
    s.add_argument("--perfil")
    s.add_argument("--estado", choices=db.ESTADOS_REVISION)
    s.add_argument("--todas", action="store_true", help="incluye cerradas y adjudicadas")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("vencimientos", help="contratos adjudicados que vencen pronto")
    s.add_argument("--meses", type=int, default=6)
    s.add_argument("--limite", type=int, default=200)
    s.set_defaults(func=cmd_vencimientos)

    # `competencia` era el nombre anterior de la pestaña y del comando. Se mantiene
    # como alias porque está escrito en el README de quien ya lo tenía instalado.
    s = sub.add_parser("adjudicatarios", aliases=["competencia"],
                       help="ranking de adjudicatarios en el nicho")
    s.add_argument("--limite", type=int, default=20)
    s.set_defaults(func=cmd_adjudicatarios)

    s = sub.add_parser("programar", help="descarga automática cada mañana")
    s.add_argument("--hora", type=int, default=8)
    s.add_argument("--minuto", type=int, default=30)
    s.add_argument("--desinstalar", action="store_true")
    s.add_argument("--ver", action="store_true", help="solo consultar el estado")
    s.set_defaults(func=cmd_programar)

    s = sub.add_parser("estado", help="cifras y salud de las fuentes")
    s.add_argument("--limpiar-cache", action="store_true",
                   help="borra los ZIP de históricos descargados (no pierde datos)")
    s.set_defaults(func=cmd_estado)

    s = sub.add_parser("doctor", help="autodiagnóstico: certificados, base, caché y tarea")
    s.add_argument("--integridad", action="store_true",
                   help="comprueba también que la base no esté dañada (lee los 3 GB "
                        "enteros: casi un minuto)")
    s.add_argument("--con-red", action="store_true",
                   help="pregunta a GitHub si hay una versión más nueva")
    s.add_argument("--json", action="store_true",
                   help="salida para la aplicación, no para leer")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("actualizar", help="trae la última versión publicada del programa")
    s.add_argument("--solo-comprobar", action="store_true",
                   help="mira si hay versión nueva, sin instalar nada")
    s.add_argument("--json", action="store_true",
                   help="salida para la aplicación, no para leer")
    s.set_defaults(func=cmd_actualizar)

    args = p.parse_args(argv)
    _log(args.verboso)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
