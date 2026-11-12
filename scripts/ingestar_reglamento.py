"""Ingesta del corpus (RAG): data/reglamento/*.pdf y glosario.md -> data/chroma.

Es incremental: solo procesa los archivos que todavía no están cargados.

Uso (desde la raíz del proyecto):
    python scripts/ingestar_reglamento.py              # agrega los archivos nuevos
    python scripts/ingestar_reglamento.py --desde-cero # borra la base y carga todo
    python scripts/ingestar_reglamento.py --max 800    # carga como mucho 800 párrafos

El tier gratuito de embeddings permite 1000 por día (compartidos con las búsquedas del
agente): si se alcanza, la ingesta se detiene y se retoma al día siguiente.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agente_f1.rag.ingest import ingestar  # noqa: E402

if __name__ == "__main__":
    maximo = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else None
    total = ingestar(desde_cero="--desde-cero" in sys.argv, maximo=maximo, log=lambda m: print(m, flush=True))
    print(f"Listo: {total} párrafos indexados.")
