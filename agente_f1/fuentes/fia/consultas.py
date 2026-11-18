"""Consultas de sanciones sobre el índice local (las usan las tools del agente).

La búsqueda es local: se filtra por el título de cada documento ("Infringement -
Car 87 - ...") y solo se baja el PDF de los candidatos que todavía no estén procesados.
"""
import re

from ...util import normalizar
from .. import calendario
from . import scraper
from .cache import conectar
from .sync import auto_actualizar

# La FIA también publica "Corrected Race - Infringement", "Corrected - Sprint Infringement",
# "Replacement for Document 47 - Offence", "(Infringement" e incluso "Infringment".
TITULO_SANCION_RE = re.compile(
    r"^(?:Doc\s*\d+\s*[-–]\s*)?\(?\s*(?:Replacement for Document\s*\d+\s*-\s*)?(?:Corrected\s*(?:-\s*)?)?"
    r"(?:(?:Race|Sprint|Qualifying)\s*(?:-\s*)?)?(Infringe?ment|Offence|Decision)\b\s*(?:\(Corrected\)\s*)?-?\s*", re.I)
TITULO_AUTOS_RE = re.compile(r"^Cars?\s+((?:\d+|\s|,|&|and)+)", re.I)
VUELTAS_BORRADAS_RE = re.compile(r"deleted\s+lap\s+time", re.I)
SIN_SANCION_RE = re.compile(r"no\s+further\s+action", re.I)
PRIMERA_TEMPORADA = 2019  # desde acá hay documentos indexados


# ---------------------------------------------------------------- helpers

def _por_nombre(carreras: list[dict], nombre: str) -> dict | None:
    """Carrera del índice de la FIA por su nombre oficial (o parte). None si ninguna coincide."""
    q = normalizar(nombre)
    coinciden = [c for c in carreras if q and q in normalizar(c["name"])]
    exactas = [c for c in coinciden if normalizar(c["name"]) == q]
    gp = [c for c in coinciden if "grand prix" in normalizar(c["name"])]
    if exactas:
        return exactas[0]
    if len(coinciden) == 1:
        return coinciden[0]
    if len(gp) == 1:
        return gp[0]
    if coinciden:
        raise ValueError(f"'{nombre}' coincide con más de una carrera: {[c['name'] for c in coinciden]}")
    return None


def _buscar_carrera(con, año: int, nombre: str | int) -> dict:
    """Carrera del índice por nombre oficial, número de ronda ("5"), lugar, país o circuito.

    El índice de la FIA solo tiene el nombre oficial: la ronda y los alias ("Monza",
    "Brazil") se resuelven con el calendario (OpenF1).
    """
    carreras = scraper.carreras(con, año)
    if calendario.ronda_de(nombre) is None:
        carrera = _por_nombre(carreras, str(nombre))
        if carrera:
            return carrera
    entrada = calendario.resolver(año, nombre)
    if entrada:
        carrera = _por_nombre(carreras, entrada["carrera"])
        if carrera:
            return carrera
        raise ValueError(f"'{entrada['carrera']}' ({año}) todavía no tiene documentos de la FIA.")
    raise ValueError(f"No se pudo identificar la carrera '{nombre}' en {año}. "
                     f"Opciones: {[c['name'] for c in carreras]}")


def es_sancion(titulo: str) -> bool:
    return bool(TITULO_SANCION_RE.match(titulo))


def autos_del_titulo(titulo: str) -> list[int]:
    """'Doc 41 - Infringement - Car 87 - Reversing...' -> [87]"""
    m = TITULO_AUTOS_RE.match(TITULO_SANCION_RE.sub("", titulo, count=1))
    return [int(n) for n in re.findall(r"\d+", m.group(1))] if m else []


def _clave_documento(titulo: str) -> str:
    """Lo que describe el título, sin el encabezado ni la marca de corregido."""
    resto = re.sub(r"\(?\bcorrected\b\)?\s*-?", " ", TITULO_SANCION_RE.sub("", titulo, count=1), flags=re.I)
    return re.sub(r"[^a-z0-9]+", " ", normalizar(resto)).strip()


def _documentos_de_sancion(con, carrera: dict) -> list[dict]:
    """Documentos de sanción vigentes: si la FIA corrigió uno, queda solo la versión nueva.

    La lista viene del más nuevo al más viejo, así que se conserva el primero de cada título.
    """
    vistos, out = set(), []
    for doc in scraper.documentos(con, carrera):
        if not es_sancion(doc["title"]):
            continue
        clave = _clave_documento(doc["title"])
        if clave and clave in vistos:
            continue
        vistos.add(clave)
        out.append(doc)
    return out


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
    for doc in _documentos_de_sancion(con, carrera):
        if VUELTAS_BORRADAS_RE.search(doc["title"]):
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

def sanciones_piloto(año: int, carrera: str | int | None, numero_auto: int, nombre_piloto: str | None = None,
                     incluir_sin_sancion: bool = False) -> list[dict]:
    """Sanciones de un auto/piloto en una carrera, o en toda la temporada si `carrera` es None.

    Puede haber más de una. La temporada completa va en orden cronológico; la primera vez
    puede tardar, porque baja las decisiones de ese auto que no estén procesadas.
    """
    con = conectar()
    auto_actualizar(con)
    if carrera is None or not str(carrera).strip():
        carreras = list(reversed(scraper.carreras(con, año)))  # el índice va de la más nueva a la más vieja
    else:
        carreras = [_buscar_carrera(con, año, carrera)]
    out = []
    for c in carreras:
        # dentro de una carrera los documentos vienen del más nuevo al más viejo
        out += reversed(_sanciones_del_piloto(con, c, int(numero_auto), nombre_piloto, incluir_sin_sancion))
    return out


def sanciones_carrera(año: int, carrera: str, incluir_sin_sancion: bool = False) -> list[dict]:
    """Todas las sanciones de una carrera (procesa todos sus documentos de sanción)."""
    con = conectar()
    auto_actualizar(con)
    c = _buscar_carrera(con, año, carrera)
    out = []
    for doc in _documentos_de_sancion(con, c):
        if VUELTAS_BORRADAS_RE.search(doc["title"]):
            continue
        data = scraper.procesar(con, doc)
        if not data:
            continue
        rec = _registro(c, doc, data)
        if not rec["sin_sancion"] or incluir_sin_sancion:
            out.append(rec)
    return out


def decisiones(año: int, carrera: str, numeros: list) -> dict[str, dict]:
    """Decisiones por número de documento (ej. "41"): {número pedido: datos oficiales}."""
    con = conectar()
    c = _buscar_carrera(con, año, carrera)
    docs = [d for d in scraper.documentos(con, c) if es_sancion(d["title"])]
    out = {}
    for pedido in numeros:
        numero = str(pedido).strip().lstrip("0") or "0"
        # Desde ~2020 el título empieza con "Doc 41 - ..."; antes hay que procesar el PDF para saberlo.
        por_titulo = [d for d in docs if re.match(rf"^Doc\s*0*{numero}\b", d["title"])]
        for doc in por_titulo or docs:
            data = scraper.procesar(con, doc)
            if data and str(data.get("document", "")).lstrip("0") == numero:
                out[str(pedido)] = _registro(c, doc, data)
                break
    return out


def ultima_sancion(numero_auto: int, nombre_piloto: str | None = None) -> dict | None:
    """Última sanción de un auto/piloto, buscando hacia atrás desde la temporada actual.

    Conviene pasar `nombre_piloto`: los números de auto pueden cambiar de piloto entre temporadas.
    """
    con = conectar()
    auto_actualizar(con)
    for y in sorted((s for s in scraper.temporadas(con) if s >= PRIMERA_TEMPORADA), reverse=True):
        for carrera in scraper.carreras(con, y):
            encontradas = _sanciones_del_piloto(con, carrera, int(numero_auto), nombre_piloto, False)
            if encontradas:
                return encontradas[0]  # los documentos vienen del más nuevo al más viejo
    return None
