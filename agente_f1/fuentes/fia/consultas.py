"""Consultas de sanciones sobre el índice local (las usan las tools del agente).

La búsqueda es local: se filtra por el título de cada documento ("Infringement -
Car 87 - ...") y solo se baja el PDF de los candidatos que todavía no estén procesados.
"""
import re

from ...util import normalizar
from . import scraper
from .cache import conectar
from .sync import auto_actualizar

TITULO_SANCION_RE = re.compile(r"^(?:Doc\s*\d+\s*-\s*)?(Infringement|Offence|Decision)\b\s*-?\s*", re.I)
TITULO_AUTOS_RE = re.compile(r"^Cars?\s+((?:\d+|\s|,|&|and)+)", re.I)
VUELTAS_BORRADAS_RE = re.compile(r"deleted\s+lap\s+time", re.I)
SIN_SANCION_RE = re.compile(r"no\s+further\s+action", re.I)


# ---------------------------------------------------------------- helpers

def _buscar_carrera(con, año: int, nombre: str) -> dict:
    carreras = scraper.carreras(con, año)
    q = normalizar(nombre)
    coinciden = [c for c in carreras if q in normalizar(c["name"])]
    exactas = [c for c in coinciden if normalizar(c["name"]) == q]
    gp = [c for c in coinciden if "grand prix" in normalizar(c["name"])]
    if exactas:
        return exactas[0]
    if len(coinciden) == 1:
        return coinciden[0]
    if len(gp) == 1:
        return gp[0]
    opciones = [c["name"] for c in (coinciden or carreras)]
    raise ValueError(f"No se pudo identificar la carrera '{nombre}' en {año}. Opciones: {opciones}")


def es_sancion(titulo: str) -> bool:
    return bool(TITULO_SANCION_RE.match(titulo))


def autos_del_titulo(titulo: str) -> list[int]:
    """'Doc 41 - Infringement - Car 87 - Reversing...' -> [87]"""
    m = TITULO_AUTOS_RE.match(TITULO_SANCION_RE.sub("", titulo, count=1))
    return [int(n) for n in re.findall(r"\d+", m.group(1))] if m else []


def _coincide_nombre(nombre: str | None, buscado: str | None) -> bool:
    if not buscado:
        return True
    palabras = normalizar(nombre).split()
    return any(p in palabras for p in normalizar(buscado).split())  # alcanza con el apellido


def _es_del_piloto(data: dict, auto: int, nombre: str | None) -> bool:
    if data.get("car_number") == auto:
        return _coincide_nombre(data.get("driver_name"), nombre)
    return any(str(f.get("Car", "")).strip() == str(auto) and _coincide_nombre(f.get("Driver"), nombre)
               for f in data.get("cars") or [])


def _registro(carrera: dict, doc: dict, data: dict) -> dict:
    """Formato de salida de una sanción."""
    rec = {
        "año": carrera["year"],
        "carrera": carrera["name"],
        "documento": data.get("document"),
        "titulo": doc["title"],
        "publicado": doc["published"],
        "fecha": data.get("date"),
        "sesion": data.get("session"),
        "numero_auto": data.get("car_number"),
        "piloto": data.get("driver_name"),
        "equipo": data.get("competitor"),
        "hecho": data.get("fact"),
        "infraccion": data.get("infringement"),
        "articulos": data.get("articles"),
        "decision": data.get("decision"),
        "motivo": data.get("reason"),
        "sin_sancion": bool(SIN_SANCION_RE.search(data.get("decision") or "")),
        "comisarios": data.get("stewards"),
        "url": doc["url"],
    }
    if data.get("cars"):
        rec["autos"] = data["cars"]
    return rec


def _sanciones_del_piloto(con, carrera, auto, nombre, incluir_sin_sancion):
    out = []
    for doc in scraper.documentos(con, carrera):
        if not es_sancion(doc["title"]) or VUELTAS_BORRADAS_RE.search(doc["title"]):
            continue
        autos = autos_del_titulo(doc["title"])
        # Si el título nombra autos y no está el nuestro, no hace falta bajarlo.
        # Si no nombra ninguno (ej. sanción a un equipo), se baja para revisar.
        if autos and auto not in autos:
            continue
        data = scraper.procesar(con, doc)
        if not data or not _es_del_piloto(data, auto, nombre):
            continue
        rec = _registro(carrera, doc, data)
        if rec["sin_sancion"] and not incluir_sin_sancion:
            continue
        out.append(rec)
    return out


# ---------------------------------------------------------------- consultas

def listar_carreras(año: int) -> list[dict]:
    """Carreras con documentos FIA en una temporada, de la más reciente a la más vieja."""
    return [{"carrera": c["name"], "año": c["year"]} for c in scraper.carreras(conectar(), año)]


def sanciones_piloto(año: int, carrera: str, numero_auto: int, nombre_piloto: str | None = None,
                     incluir_sin_sancion: bool = False) -> list[dict]:
    """Sanciones de un auto/piloto en una carrera. Puede haber más de una."""
    con = conectar()
    auto_actualizar(con)
    return _sanciones_del_piloto(con, _buscar_carrera(con, año, carrera), int(numero_auto),
                                 nombre_piloto, incluir_sin_sancion)


def sanciones_carrera(año: int, carrera: str, incluir_vueltas_borradas: bool = False,
                      incluir_sin_sancion: bool = False) -> list[dict]:
    """Todas las sanciones de una carrera (procesa todos sus documentos de sanción)."""
    con = conectar()
    auto_actualizar(con)
    c = _buscar_carrera(con, año, carrera)
    out = []
    for doc in scraper.documentos(con, c):
        if not es_sancion(doc["title"]):
            continue
        if VUELTAS_BORRADAS_RE.search(doc["title"]) and not incluir_vueltas_borradas:
            continue
        data = scraper.procesar(con, doc)
        if not data:
            continue
        rec = _registro(c, doc, data)
        if not rec["sin_sancion"] or incluir_sin_sancion:
            out.append(rec)
    return out


def decision(año: int, carrera: str, documento: str | int) -> dict | None:
    """Una decisión por su número de documento (ej. 41), con todos sus datos oficiales."""
    con = conectar()
    c = _buscar_carrera(con, año, carrera)
    numero = str(documento).strip().lstrip("0") or "0"
    docs = [d for d in scraper.documentos(con, c) if es_sancion(d["title"])]
    # Desde ~2020 el título empieza con "Doc 41 - ..."; antes hay que procesar el PDF para saberlo.
    por_titulo = [d for d in docs if re.match(rf"^Doc\s*0*{numero}\b", d["title"])]
    for doc in por_titulo or docs:
        data = scraper.procesar(con, doc)
        if data and str(data.get("document", "")).lstrip("0") == numero:
            return _registro(c, doc, data)
    return None


def ultima_sancion(numero_auto: int, nombre_piloto: str | None = None, desde_año: int | None = None,
                   hasta_año: int = 2019) -> dict | None:
    """Última sanción de un auto/piloto, buscando hacia atrás desde `desde_año`.

    Conviene pasar `nombre_piloto`: los números de auto pueden cambiar de piloto entre temporadas.
    """
    con = conectar()
    auto_actualizar(con)
    año = desde_año or scraper.año_actual(con)
    for y in sorted((s for s in scraper.temporadas(con) if hasta_año <= s <= año), reverse=True):
        for carrera in scraper.carreras(con, y):
            encontradas = _sanciones_del_piloto(con, carrera, int(numero_auto), nombre_piloto, False)
            if encontradas:
                return encontradas[0]  # los documentos vienen del más nuevo al más viejo
    return None
