"""Cliente mínimo de la API pública de OpenF1 (https://openf1.org)."""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ..util import normalizar

BASE = "https://api.openf1.org/v1"
USER_AGENT = "agente-sanciones-f1/0.1"
REINTENTOS_429 = 3

# "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 23 (ALB) - REJOINING UNSAFELY (14:50:05)"
# "FIA STEWARDS: PENALTY SERVED - 5 SECOND TIME PENALTY FOR CAR 23 (ALB) (14:50:05)"
SANCION_RE = re.compile(r"^FIA STEWARDS: (?P<cumplida>PENALTY SERVED - )?(?P<sancion>.+?) FOR CARS? "
                        r"(?P<autos>.+?)(?: - (?P<motivo>.+?))?(?: \(\d\d:\d\d:\d\d\))?$")
TIPO_SANCION_RE = re.compile(r"PENALTY|REPRIMAND|WARNING|DISQUALIF|BLACK FLAG")
BANDERA_RE = re.compile(r"^BLACK AND WHITE FLAG FOR CARS? (?P<autos>.+?)(?: - (?P<motivo>.+))?$")


def get(endpoint: str, filtros: str = "", _timeout: float = 20, **params) -> list:
    """GET a OpenF1. Devuelve [] si no hay resultados (OpenF1 responde 404 en ese caso).

    `filtros` es para comparaciones que urlencode no sabe armar, ej. "date_end>=2026-11-01".
    Si OpenF1 corta por exceso de pedidos (429), espera y reintenta.
    """
    partes = [p for p in (urllib.parse.urlencode(params), filtros) if p]
    url = f"{BASE}/{endpoint}" + ("?" + "&".join(partes) if partes else "")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for intento in range(REINTENTOS_429 + 1):
        try:
            with urllib.request.urlopen(req, timeout=_timeout) as resp:
                data = json.loads(resp.read())
            return data if isinstance(data, list) else []
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return []
            if exc.code != 429 or intento == REINTENTOS_429:
                raise
            time.sleep(1.5 * (intento + 1))
    return []


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


def carreras(año: int) -> list[dict]:
    """Meetings de una temporada que son carreras, en orden cronológico.

    Saca los tests de pretemporada y las carreras canceladas: así la posición en la
    lista (empezando en 1) es el número de ronda del campeonato.
    """
    meetings = [m for m in get("meetings", year=año)
                if not m.get("is_cancelled") and "testing" not in normalizar(m.get("meeting_name"))]
    return sorted(meetings, key=lambda m: m.get("date_start") or "")


def buscar_meeting(año: int, carrera: str) -> dict | None:
    """Busca una carrera por nombre (ej. 'Sao Paulo', 'Monaco') en una temporada."""
    q = normalizar(carrera)
    for m in carreras(año):
        campos = (m.get("meeting_name"), m.get("location"), m.get("country_name"), m.get("circuit_short_name"))
        if any(q in normalizar(c) for c in campos if c):
            return m
    return None


def buscar_piloto(nombre: str, año: int, meeting_key: int | None = None) -> list[dict]:
    """Pilotos que coinciden con el nombre (número, equipo, nombre completo).

    Con `meeting_key` se busca entre los que corrieron esa carrera (sirve para reemplazos a
    mitad de temporada); si no, entre los de la última sesión de la temporada.
    """
    q = normalizar(nombre)
    if meeting_key is not None:
        pilotos = get("drivers", meeting_key=meeting_key)
    else:
        sesiones = get("sessions", year=año)
        pilotos = get("drivers", session_key=sesiones[-1]["session_key"] if sesiones else "latest")
    vistos, out = set(), []
    for d in pilotos:
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


def mensajes_comisarios(meeting_key: int, numero_auto: int | None = None, mensajes: list | None = None) -> list[dict]:
    """Mensajes de los comisarios en Race Control (investigaciones y sanciones en vivo).

    En estos mensajes el campo driver_number viene vacío: el auto se busca en el texto.
    `mensajes`: los de Race Control de esa carrera, si ya se pidieron.
    """
    out = []
    for m in get("race_control", meeting_key=meeting_key) if mensajes is None else mensajes:
        texto = m.get("message") or ""
        if "STEWARDS" not in texto and "PENALTY" not in texto:
            continue
        if numero_auto is not None and not re.search(rf"\bCARS?\b[^-]*\b{numero_auto}\b \(", texto):
            continue
        out.append({"fecha": m.get("date"), "mensaje": texto})
    return out


def _autos(texto: str) -> list[tuple[int, str | None]]:
    """'23 (ALB), 31 (OCO)' -> [(23, 'ALB'), (31, 'OCO')]"""
    return [(int(n), a or None) for n, a in re.findall(r"\b(\d+)\b(?: \(([A-Z]{3})\))?", texto)]


def sanciones_en_pista(año: int, meeting_key: int | None = None, numero_auto: int | None = None,
                       mensajes: list | None = None) -> dict:
    """Sanciones anunciadas por Race Control, de una carrera o de toda la temporada.

    Devuelve {"sanciones": [...], "banderas": [...]}. Cada sanción trae sesión, vuelta, auto,
    sanción, motivo, si se cumplió y una `referencia` fija dentro de su carrera ("RC-3").
    Las banderas son las blanco y negro: un aviso de Race Control, no una sanción.
    `mensajes`: los de Race Control de esa carrera, si ya se pidieron.
    """
    if meeting_key is not None:
        if mensajes is None:
            mensajes = get("race_control", meeting_key=meeting_key)
        sesiones = get("sessions", meeting_key=meeting_key)
        nombres = {}
    else:
        # Una temporada entera son miles de mensajes: un solo pedido, con más tiempo de espera.
        mensajes = get("race_control", f"date>={año}-01-01&date<{año + 1}-01-01", _timeout=60)
        sesiones = get("sessions", year=año)
        nombres = {m.get("meeting_key"): m.get("meeting_name") for m in carreras(año)}
    nombre_sesion = {s.get("session_key"): s.get("session_name") for s in sesiones}

    sanciones, banderas, por_carrera = [], [], {}
    for m in sorted(mensajes, key=lambda x: x.get("date") or ""):
        texto = (m.get("message") or "").strip()
        base = {"sesion": nombre_sesion.get(m.get("session_key")), "vuelta": m.get("lap_number"), "fecha": m.get("date")}
        if m.get("meeting_key") in nombres:
            base["carrera"] = nombres[m["meeting_key"]]
        bandera = BANDERA_RE.match(texto)
        if bandera:
            banderas += [{**base, "numero_auto": n, "piloto": a, "motivo": bandera["motivo"]}
                         for n, a in _autos(bandera["autos"])]
            continue
        h = SANCION_RE.match(texto)
        if not h or not TIPO_SANCION_RE.search(h["sancion"]):
            continue
        for n, abreviatura in _autos(h["autos"]):
            if h["cumplida"]:  # "PENALTY SERVED": marca la sanción pendiente de ese auto
                pendiente = next((s for s in sanciones if s["numero_auto"] == n and s["sancion"] == h["sancion"]
                                  and not s["cumplida"] and s["_carrera"] == m.get("meeting_key")), None)
                if pendiente:
                    pendiente.update(cumplida=True, vuelta_cumplida=m.get("lap_number"))
                continue
            orden = por_carrera[m.get("meeting_key")] = por_carrera.get(m.get("meeting_key"), 0) + 1
            sanciones.append({"referencia": f"RC-{orden}", **base, "numero_auto": n, "piloto": abreviatura,
                              "sancion": h["sancion"], "motivo": h["motivo"], "cumplida": False,
                              "mensaje": texto, "_carrera": m.get("meeting_key")})
    for s in sanciones:
        del s["_carrera"]
    if numero_auto is not None:
        sanciones = [s for s in sanciones if s["numero_auto"] == numero_auto]
        banderas = [b for b in banderas if b["numero_auto"] == numero_auto]
    return {"sanciones": sanciones, "banderas": banderas}
