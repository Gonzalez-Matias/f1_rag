"""Calendario de una temporada: número de ronda, nombre oficial, lugar y fechas.

Sirve para dos cosas:
  - que el agente pueda resolver "la quinta carrera de 2025" o "la última carrera";
  - aceptar la carrera por lugar, país o circuito ("Monza", "Brazil", "Interlagos") en las
    consultas de la FIA, que solo conocen el nombre oficial ("Italian Grand Prix").

Fuente: OpenF1 (2023 en adelante). Para temporadas anteriores se usa el orden del índice
de la FIA, que solo da ronda y nombre (sin fechas ni lugar).
"""
import re

from ..util import normalizar
from . import openf1

RONDA_RE = re.compile(r"(?:ronda|round|fecha|carrera)?\s*(?:n[°ºo]?\.?\s*)?(\d{1,2})")
CAMPOS_ALIAS = ("carrera", "lugar", "pais", "circuito")


def _desde_fia(año: int) -> list[dict]:
    from .fia import scraper
    from .fia.cache import conectar
    # El índice de la FIA va de la carrera más nueva a la más vieja, e incluye los tests.
    nombres = [c["name"] for c in reversed(scraper.carreras(conectar(), año))
               if "grand prix" in normalizar(c["name"])]
    return [{"ronda": n, "carrera": nombre, "fuente": "FIA"} for n, nombre in enumerate(nombres, 1)]


def calendario(año: int) -> list[dict]:
    """Carreras de la temporada en orden, con su número de ronda (sin tests ni canceladas)."""
    try:
        meetings = openf1.carreras(año)
    except Exception:  # noqa: BLE001 - sin OpenF1 queda el orden del índice de la FIA
        meetings = []
    if not meetings:
        return _desde_fia(año)
    return [{
        "ronda": n,
        "carrera": m.get("meeting_name"),
        "lugar": m.get("location"),
        "pais": m.get("country_name"),
        "circuito": m.get("circuit_short_name"),
        "fecha_inicio": (m.get("date_start") or "")[:10],
        "fecha_fin": (m.get("date_end") or "")[:10],
        "meeting_key": m.get("meeting_key"),
        "fuente": "OpenF1",
    } for n, m in enumerate(meetings, 1)]


def ronda_de(texto: str | int) -> int | None:
    """'5', 5, 'ronda 5', 'round 5' -> 5. None si el texto no es un número de ronda."""
    m = RONDA_RE.fullmatch(normalizar(str(texto)))
    return int(m.group(1)) if m else None


def resolver(año: int, carrera: str | int) -> dict | None:
    """Entrada del calendario para un número de ronda, nombre, lugar, país o circuito.

    Devuelve None si nada coincide. Lanza ValueError si la ronda no existe o si el texto
    coincide con más de una carrera (ej. "Italy" en 2025: Imola y Monza).
    """
    entradas = calendario(año)
    ronda = ronda_de(carrera)
    if ronda is not None:
        if not 1 <= ronda <= len(entradas):
            raise ValueError(f"La temporada {año} tiene {len(entradas)} carreras: no existe la ronda {ronda}.")
        return entradas[ronda - 1]
    q = normalizar(str(carrera))
    if not q:
        return None
    por_nombre = [e for e in entradas if q in normalizar(e["carrera"])]
    exactas = [e for e in por_nombre if normalizar(e["carrera"]) == q]
    por_alias = [e for e in entradas if any(q in normalizar(e.get(c)) for c in CAMPOS_ALIAS)]
    for candidatas in (exactas, por_nombre, por_alias):
        if len(candidatas) == 1:
            return candidatas[0]
        if len(candidatas) > 1:
            opciones = [f"{e['carrera']} (ronda {e['ronda']})" for e in candidatas]
            raise ValueError(f"'{carrera}' coincide con más de una carrera de {año}: {opciones}")
    return None
