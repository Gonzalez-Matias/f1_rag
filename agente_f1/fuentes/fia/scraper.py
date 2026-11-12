"""Lectura de fia.com: temporadas, carreras, listas de documentos y PDFs.

Todo lo que se lee queda en el caché (cache.py). Cada pedido respeta el
Crawl-delay de 10 s que pide el robots.txt del sitio.
"""
import html
import json
import re
import tempfile
import time
import urllib.parse
import urllib.request

from ... import config
from .cache import ahora
from .parser import parse, pdf_to_text

BASE = "https://www.fia.com"
F1_PATH = "/documents/championships/fia-formula-one-world-championship-14"
USER_AGENT = "fia-decisions-scraper/0.1"

_ultimo_pedido = 0.0


def get(ruta: str) -> bytes:
    """GET a fia.com respetando el crawl-delay entre pedidos."""
    global _ultimo_pedido
    espera = _ultimo_pedido + config.FIA_CRAWL_DELAY - time.monotonic()
    if espera > 0:
        time.sleep(espera)
    url = ruta if ruta.startswith("http") else BASE + ruta
    url = urllib.parse.quote(url, safe=":/%()?=&")  # los PDFs viejos tienen espacios en el nombre
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    finally:
        _ultimo_pedido = time.monotonic()


# ---------------------------------------------------------------- temporadas y carreras

def temporadas(con) -> dict[int, str]:
    """{año: URL de la temporada}. Se lee de fia.com una sola vez."""
    rows = con.execute("SELECT year, url FROM seasons").fetchall()
    if rows:
        return {r["year"]: r["url"] for r in rows}
    page = get(F1_PATH).decode("utf-8", "replace")
    select = re.search(r'<select[^>]*facet_form_3.*?</select>', page, re.S)
    seasons = {int(año): html.unescape(url) for url, año in
               re.findall(r'value="([^"]*)"[^>]*>\s*SEASON\s+(\d{4})', select.group(0) if select else "")}
    if not seasons:
        raise RuntimeError("No se encontró la lista de temporadas en fia.com")
    con.executemany("INSERT OR REPLACE INTO seasons VALUES (?, ?)", seasons.items())
    con.commit()
    return seasons


def año_actual(con) -> int:
    return max(temporadas(con))


def carreras(con, año: int, ttl: float | None = config.FIA_LIVE_TTL) -> list[dict]:
    """Carreras de una temporada, de la más reciente a la más vieja.

    Se leen de fia.com si no están en el caché, o si es la temporada actual y
    pasaron más de `ttl` segundos (ttl=0 fuerza la lectura).
    """
    seasons = temporadas(con)
    if año not in seasons:
        raise ValueError(f"No hay documentos FIA para la temporada {año}. Disponibles: {sorted(seasons)}")
    row = con.execute("SELECT fetched_at FROM season_events WHERE year=?", (año,)).fetchone()
    vencido = row is None or (ttl is not None and año == año_actual(con) and ahora() - row["fetched_at"] > ttl)
    if vencido:
        page = get(seasons[año]).decode("utf-8", "replace")
        # La carrera activa viene sin link (su ID está en el contenedor); el resto, como links.
        encontrados = re.findall(
            r'<div class="event-title active">\s*(.*?)\s*</div>\s*<ul class="document-type-wrapper[^"]*data-id-(\d+)"'
            r'|<a href="/decision-document-list/nojs/(\d+)" class="event-title[^"]*">\s*(.*?)\s*</a>',
            page, re.S)
        for pos, (nombre_activa, id_activa, eid, nombre) in enumerate(encontrados):
            con.execute(
                "INSERT INTO events (event_id, year, name, position) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(event_id) DO UPDATE SET year=excluded.year, name=excluded.name, position=excluded.position",
                (int(id_activa or eid), año, html.unescape(nombre_activa or nombre).strip(), pos))
        con.execute("INSERT OR REPLACE INTO season_events VALUES (?, ?)", (año, ahora()))
        con.commit()
    return [dict(r) for r in con.execute(
        "SELECT event_id, year, name, position FROM events WHERE year=? ORDER BY position", (año,))]


# ---------------------------------------------------------------- documentos

def documentos(con, carrera: dict, ttl: float | None = config.FIA_LIVE_TTL, recientes: int = 1,
               forzar: bool = False) -> list[dict]:
    """Documentos de una carrera (título, URL, fecha; sin bajar los PDFs).

    Al volver a listar solo se agregan los documentos nuevos: los que ya estaban
    conservan su PDF procesado. `recientes` = cuántas carreras de la temporada
    actual se consideran abiertas (pueden recibir documentos nuevos).
    """
    row = con.execute("SELECT docs_fetched_at FROM events WHERE event_id=?", (carrera["event_id"],)).fetchone()
    abierta = carrera["year"] == año_actual(con) and carrera["position"] < recientes
    if forzar or row["docs_fetched_at"] is None or (
            abierta and ttl is not None and ahora() - row["docs_fetched_at"] > ttl):
        payload = json.loads(get(f"/decision-document-list/ajax/{carrera['event_id']}"))
        markup = "".join(c.get("data") or "" for c in payload if c.get("command") == "insert")
        # En años viejos hay un <div> extra entre el <li> y el <a>.
        filas = re.findall(r'<li class="document-row[^"]*">.*?<a href="([^"]+)"(.*?)</a>', markup, re.S)
        if not filas and "document-row" in markup:
            raise RuntimeError(f"No se pudo leer la lista de documentos del evento {carrera['event_id']}")
        for pos, (href, cuerpo) in enumerate(filas):  # la FIA los lista del más nuevo al más viejo
            titulo = re.search(r'<div class="title">(.*?)(?:<div class="published">|$)', cuerpo, re.S)
            titulo = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", titulo.group(1) if titulo else "")))
            publicado = re.search(r'date-display-single">([^<]+)', cuerpo)
            con.execute(
                "INSERT INTO documents (url, event_id, position, title, published) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(url) DO UPDATE SET position=excluded.position, title=excluded.title, "
                "published=excluded.published",
                (urllib.parse.urljoin(BASE, html.unescape(href)), carrera["event_id"], pos, titulo.strip(),
                 publicado.group(1).strip() if publicado else None))
        con.execute("UPDATE events SET docs_fetched_at=? WHERE event_id=?", (ahora(), carrera["event_id"]))
        con.commit()
    return [dict(r) for r in con.execute(
        "SELECT url, title, published, data, error FROM documents WHERE event_id=? ORDER BY position",
        (carrera["event_id"],))]


def procesar(con, doc: dict) -> dict | None:
    """Datos de un documento: del caché, o bajando y procesando el PDF (una sola vez)."""
    if doc["data"]:
        return json.loads(doc["data"])
    if doc["error"]:
        return None
    try:
        pdf = get(doc["url"])
        if not pdf.startswith(b"%PDF"):
            raise ValueError("la respuesta no es un PDF")
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
            tmp.write(pdf)
            tmp.flush()
            data = parse(pdf_to_text(tmp.name))
        con.execute("UPDATE documents SET data=? WHERE url=?", (json.dumps(data, ensure_ascii=False), doc["url"]))
        con.commit()
        return data
    except Exception as exc:  # se guarda para no reintentar en cada consulta
        con.execute("UPDATE documents SET error=? WHERE url=?", (str(exc), doc["url"]))
        con.commit()
        return None
