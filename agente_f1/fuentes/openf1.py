"""Cliente mínimo de la API pública de OpenF1 (https://openf1.org)."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ..util import normalizar

BASE = "https://api.openf1.org/v1"
USER_AGENT = "agente-sanciones-f1/0.1"


def get(endpoint: str, filtros: str = "", **params) -> list:
    """GET a OpenF1. Devuelve [] si no hay resultados (OpenF1 responde 404 en ese caso).

    `filtros` es para comparaciones que urlencode no sabe armar, ej. "date_end>=2026-11-01".
    """
    partes = [p for p in (urllib.parse.urlencode(params), filtros) if p]
    url = f"{BASE}/{endpoint}" + ("?" + "&".join(partes) if partes else "")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise
    return data if isinstance(data, list) else []


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def carreras_con_actividad(desde: float, hasta: float) -> list[dict]:
    """Carreras con alguna sesión que terminó después de `desde` y empezó antes de `hasta`.

    Devuelve [{"año": 2026, "nombre": "São Paulo Grand Prix"}, ...].
    """
    sesiones = get("sessions", f"date_end>={_iso(desde)}&date_start<={_iso(hasta)}")
    out = []
    for año, key in sorted({(s["year"], s["meeting_key"]) for s in sesiones}):
        meeting = get("meetings", meeting_key=key)
        if meeting:
            out.append({"año": int(año), "nombre": meeting[0].get("meeting_name")})
    return out


def buscar_meeting(año: int, carrera: str) -> dict | None:
    """Busca una carrera por nombre (ej. 'Sao Paulo', 'Monaco') en una temporada."""
    q = normalizar(carrera)
    for m in get("meetings", year=año):
        campos = (m.get("meeting_name"), m.get("location"), m.get("country_name"), m.get("circuit_short_name"))
        if any(q in normalizar(c) for c in campos if c):
            return m
    return None


def buscar_piloto(nombre: str, año: int) -> list[dict]:
    """Pilotos que coinciden con el nombre en la temporada (número, equipo, nombre completo)."""
    q = normalizar(nombre)
    sesiones = get("sessions", year=año)
    sesion = sesiones[-1]["session_key"] if sesiones else "latest"
    vistos, out = set(), []
    for d in get("drivers", session_key=sesion):
        nombre_completo = d.get("full_name") or ""
        if q in normalizar(nombre_completo) or q == normalizar(d.get("name_acronym")):
            if d.get("driver_number") not in vistos:
                vistos.add(d.get("driver_number"))
                out.append({
                    "numero_auto": d.get("driver_number"),
                    "nombre": nombre_completo,
                    "abreviatura": d.get("name_acronym"),
                    "equipo": d.get("team_name"),
                })
    return out


def mensajes_comisarios(meeting_key: int, numero_auto: int | None = None) -> list[dict]:
    """Mensajes de los comisarios en Race Control (investigaciones y sanciones en vivo).

    En estos mensajes el campo driver_number viene vacío: el auto se busca en el texto.
    """
    out = []
    for m in get("race_control", meeting_key=meeting_key):
        texto = m.get("message") or ""
        if "STEWARDS" not in texto and "PENALTY" not in texto:
            continue
        if numero_auto is not None and not re.search(rf"\bCARS?\b[^-]*\b{numero_auto}\b \(", texto):
            continue
        out.append({"fecha": m.get("date"), "mensaje": texto})
    return out
