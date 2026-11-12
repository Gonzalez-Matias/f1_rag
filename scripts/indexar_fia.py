"""Índice de documentos de la FIA (títulos y URLs, sin PDFs) en data/fia_cache.sqlite.

Se corre una vez (~35 min, respeta el Crawl-delay de 10 s de fia.com). Después,
las consultas del agente actualizan solas las carreras nuevas usando OpenF1.

Uso (desde la raíz del proyecto):
    python scripts/indexar_fia.py            # desde 2019
    python scripts/indexar_fia.py 2024       # desde 2024
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agente_f1.fuentes.fia.sync import indexar  # noqa: E402

if __name__ == "__main__":
    desde = int(sys.argv[1]) if len(sys.argv) > 1 else 2019
    indexar(desde, log=lambda m: print(m, flush=True))
