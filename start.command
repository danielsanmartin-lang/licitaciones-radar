#!/bin/bash
# Doble clic en este fichero: actualiza los datos y abre la bandeja.
cd "$(dirname "$0")" || exit 1

falta_python() {
  echo "No encuentro un Python 3 utilizable, y sin él esto no arranca."
  echo
  echo "macOS no siempre lo trae: desde Catalina, Apple retiró Python del sistema, así"
  echo "que en un Mac recién estrenado hay que instalarlo. Se hace una sola vez:"
  echo
  echo "  1. Abre https://www.python.org/downloads/macos"
  echo "  2. Descarga el instalador de la última versión de Python 3 y ábrelo."
  echo "  3. Siguiente, siguiente, instalar — como cualquier programa."
  echo "  4. Cierra esta ventana y vuelve a hacer doble clic en start.command."
  echo
  echo "Si usas Homebrew, basta con: brew install python3"
  echo
  echo "Pulsa Enter para cerrar."; read -r; exit 1
}

# No basta con que el comando exista. macOS trae en /usr/bin/python3 un lanzador que
# está ahí aunque Python no lo esté: al invocarlo abre el instalador de las
# herramientas de Xcode y falla. Así que se comprueba que además ARRANCA y que llega
# a la versión mínima, en vez de fiarnos de `command -v`.
if ! command -v python3 >/dev/null 2>&1; then
  falta_python
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
  version=$(python3 --version 2>&1)
  if [ -n "$version" ] && printf '%s' "$version" | grep -q '^Python 3'; then
    echo "Tu Python es demasiado antiguo ($version) y hace falta 3.9 o superior."
    echo "Actualízalo desde https://www.python.org/downloads/macos"
    echo
    echo "Pulsa Enter para cerrar."; read -r; exit 1
  fi
  falta_python
fi

echo "== Radar de Licitaciones =="
echo

# ¿Instalación nueva? Importa distinguirlo. Con la base vacía, un `ingest` normal solo
# trae la ventana de los últimos días —unas 50 coincidencias— y deja el cursor en la
# posición de hoy, así que a partir de ahí la ingesta incremental solo mira hacia
# delante y ese hueco no lo rellena nadie. Para eso está la carga inicial.
nuevo=$(python3 - <<'PY'
import sqlite3
from pathlib import Path

bd = Path("data/radar.db")
total = 0
if bd.exists():
    try:
        con = sqlite3.connect(f"file:{bd}?mode=ro", uri=True)
        total = con.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        con.close()
    except sqlite3.Error:
        total = 0
print("si" if total == 0 else "no")
PY
)

if [ "$nuevo" = "si" ]; then
  echo "Es la primera vez. Voy a construir el histórico en varias etapas:"
  echo
  echo "  1. Anuncios europeos y de Cataluña — unos minutos. Al terminar esta se"
  echo "     abre la aplicación, ya con unas 1.400 licitaciones que encajan."
  echo "  2. Histórico de plataformas agregadas — unos 15 minutos y ~500 MB."
  echo "  3. Histórico de la Plataforma del Estado — un par de horas y ~4 GB."
  echo
  echo "Las etapas 2 y 3 siguen descargando por detrás mientras trabajas: la"
  echo "aplicación lo avisa arriba, con una barra, y las licitaciones van"
  echo "apareciendo solas sin recargar la página."
  echo
  # -u desactiva el buffer de stdout: sin él la línea de estado se queda retenida
  # y vuelve a parecer que no pasa nada.
  python3 -u radar.py ingest --primera-carga --etapas 1 \
    || echo "(algo ha fallado en esta etapa; se abre la aplicación con lo que haya)"
  echo
  echo "Sigo con el resto en segundo plano."
  python3 - <<'PY'
from radar import busqueda

try:
    datos = busqueda.lanzar(primera_carga=True, etapas=[2, 3, 4])
    print(f"  Descargando (pid {datos['pid']}). El registro queda en data/busqueda.log")
    print("  Se puede cerrar la terminal: el proceso sigue por su cuenta.")
except (RuntimeError, OSError) as exc:
    print(f"  No se ha podido lanzar: {exc}")
    print("  Puedes hacerlo cuando quieras con:")
    print("    python3 radar.py ingest --primera-carga --etapas 2 3 4")
PY
else
  echo "Descargando novedades. Puede tardar varios minutos: PLACSP va lento a"
  echo "ratos y cada intento espera hasta 2 minutos. Mientras la línea de abajo"
  echo "se mueva, está trabajando; no hace falta cerrar nada."
  echo
  python3 -u radar.py ingest || echo "(alguna fuente ha fallado; se abre la bandeja con lo que hay)"
fi

echo
python3 -u radar.py serve
