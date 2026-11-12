"""Línea de comandos para probar las consultas sin el agente.

    python -m agente_f1.fuentes.fia carreras 2026
    python -m agente_f1.fuentes.fia piloto 2026 "Sao Paulo" 87 --nombre Bearman
    python -m agente_f1.fuentes.fia carrera 2026 "Sao Paulo"
    python -m agente_f1.fuentes.fia ultima 87 --nombre Bearman
    python -m agente_f1.fuentes.fia indexar --desde 2019
"""
import argparse
import json
import sys

from . import consultas, sync


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("carreras", help="carreras de una temporada")
    p.add_argument("año", type=int)
    p = sub.add_parser("piloto", help="sanciones de un auto en una carrera")
    p.add_argument("año", type=int)
    p.add_argument("carrera")
    p.add_argument("numero_auto", type=int)
    p.add_argument("--nombre")
    p.add_argument("--sin-sancion", action="store_true", help="incluir decisiones 'No further action'")
    p = sub.add_parser("carrera", help="todas las sanciones de una carrera")
    p.add_argument("año", type=int)
    p.add_argument("carrera")
    p.add_argument("--vueltas-borradas", action="store_true")
    p.add_argument("--sin-sancion", action="store_true")
    p = sub.add_parser("ultima", help="última sanción de un auto/piloto")
    p.add_argument("numero_auto", type=int)
    p.add_argument("--nombre")
    p.add_argument("--desde", type=int)
    p = sub.add_parser("indexar", help="guardar títulos y URLs de todos los documentos (sin PDFs)")
    p.add_argument("--desde", type=int, default=2019)
    p.add_argument("--hasta", type=int)
    a = ap.parse_args()

    if a.cmd == "indexar":
        sync.indexar(a.desde, a.hasta, log=lambda m: print(m, flush=True))
        return
    if a.cmd == "carreras":
        res = consultas.listar_carreras(a.año)
    elif a.cmd == "piloto":
        res = consultas.sanciones_piloto(a.año, a.carrera, a.numero_auto, a.nombre, a.sin_sancion)
    elif a.cmd == "carrera":
        res = consultas.sanciones_carrera(a.año, a.carrera, a.vueltas_borradas, a.sin_sancion)
    else:
        res = consultas.ultima_sancion(a.numero_auto, a.nombre, a.desde)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        sys.exit(f"Error: {exc}")
