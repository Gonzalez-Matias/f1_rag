"""Documentos de los comisarios FIA (fia.com).

cache.py      caché SQLite del índice y de los PDFs procesados
scraper.py    lectura de fia.com (respeta el crawl-delay)
parser.py     PDF de una decisión -> datos estructurados
sync.py       índice inicial y actualización automática vía OpenF1
consultas.py  sanciones_piloto / sanciones_carrera / ultima_sancion
__main__.py   línea de comandos (python -m agente_f1.fuentes.fia ...)
"""
