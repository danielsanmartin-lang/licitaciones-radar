"""Interfaz común de los conectores y utilidades compartidas.

Cada fuente es independiente a propósito: si Cataluña cambia su esquema o PLACSP
se cae, el resto de la ingesta sigue funcionando y la bandeja lo refleja en la
sección de salud de fuentes.
"""

from __future__ import annotations

from typing import Iterator, Protocol

from ..model import Licitacion


class Fuente(Protocol):
    """Un conector de datos."""

    nombre: str

    def incremental(self, cursor: str | None) -> Iterator[Licitacion]:
        """Devuelve lo publicado o modificado desde `cursor`."""

    def historico(self, anio: int) -> Iterator[Licitacion]:
        """Devuelve todo lo de un año concreto (backfill)."""

    def cursor_nuevo(self) -> str | None:
        """Cursor a guardar tras una ingesta correcta."""


# NUTS2 -> comunidad autónoma. Permite filtrar por territorio sin depender de que
# cada fuente escriba el nombre de la comunidad de la misma forma.
NUTS2_CCAA = {
    "ES11": "Galicia",
    "ES12": "Asturias",
    "ES13": "Cantabria",
    "ES21": "País Vasco",
    "ES22": "Navarra",
    "ES23": "La Rioja",
    "ES24": "Aragón",
    "ES30": "Madrid",
    "ES41": "Castilla y León",
    "ES42": "Castilla-La Mancha",
    "ES43": "Extremadura",
    "ES51": "Cataluña",
    "ES52": "Comunidad Valenciana",
    "ES53": "Islas Baleares",
    "ES61": "Andalucía",
    "ES62": "Murcia",
    "ES63": "Ceuta",
    "ES64": "Melilla",
    "ES70": "Canarias",
}


def ccaa_desde_nuts(nuts: str | None) -> str | None:
    if not nuts:
        return None
    codigo = nuts.strip().upper()
    return NUTS2_CCAA.get(codigo[:4])
