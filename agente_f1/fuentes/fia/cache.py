"""Caché local (SQLite) del índice de documentos de la FIA.

Tablas:
  seasons        temporada -> URL de su página en fia.com
  season_events  cuándo se listaron por última vez las carreras de cada temporada
  events         carreras (ID de la FIA, año, nombre, orden; 0 = la más reciente)
  documents      título, URL y fecha de cada documento; `data` = PDF ya procesado (JSON)
  meta           última sincronización / último chequeo con OpenF1
"""
import sqlite3
import time

from ... import config

_ESQUEMA = """
    CREATE TABLE IF NOT EXISTS seasons (
        year INTEGER PRIMARY KEY, url TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS season_events (
        year INTEGER PRIMARY KEY, fetched_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS events (
        event_id INTEGER PRIMARY KEY, year INTEGER NOT NULL, name TEXT NOT NULL,
        position INTEGER NOT NULL,
        docs_fetched_at REAL);
    CREATE TABLE IF NOT EXISTS documents (
        url TEXT PRIMARY KEY, event_id INTEGER NOT NULL, position INTEGER NOT NULL,
        title TEXT NOT NULL, published TEXT,
        data TEXT, error TEXT);
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY, value TEXT);
"""


def conectar() -> sqlite3.Connection:
    config.FIA_CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.FIA_CACHE_DB)
    con.row_factory = sqlite3.Row
    con.executescript(_ESQUEMA)
    return con


def ahora() -> float:
    return time.time()


def meta(con, clave: str, valor=None):
    """Lee (sin `valor`) o escribe un valor de la tabla meta."""
    if valor is None:
        row = con.execute("SELECT value FROM meta WHERE key=?", (clave,)).fetchone()
        return row["value"] if row else None
    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (clave, str(valor)))
    con.commit()
