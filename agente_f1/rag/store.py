"""Base vectorial del reglamento (Chroma en data/chroma) y búsqueda por similitud del coseno.

Chroma usa distancia euclídea (L2) por defecto; la colección se crea con
"hnsw:space": "cosine", así la distancia que devuelve es 1 - similitud del coseno.
"""
import re
import threading
import time
from datetime import datetime

from langchain_chroma import Chroma

from .. import config
from .embeddings import get_embeddings

_store = None
_lock = threading.Lock()
MAX_EXACTOS = 12  # tope de párrafos al pedir un artículo completo (cuida el contexto)


def get_vectorstore() -> Chroma:
    """Conexión única a Chroma.

    El agente puede pedir varias búsquedas en el mismo paso y LangGraph las ejecuta en
    hilos paralelos: sin el lock, dos hilos crean el cliente a la vez y Chroma falla.
    """
    global _store
    with _lock:
        if _store is None:
            _store = Chroma(
                collection_name=config.CHROMA_COLLECTION,
                embedding_function=get_embeddings(),
                persist_directory=str(config.CHROMA_DIR),
                collection_metadata={"hnsw:space": "cosine"},
            )
    return _store


def motivo_no_disponible() -> str | None:
    """Por qué el RAG no puede usarse en esta instalación (None si está todo bien)."""
    if not config.GOOGLE_API_KEY:
        return "falta GOOGLE_API_KEY en .env (se usa para los embeddings)."
    if not config.CHROMA_DIR.exists() or get_vectorstore()._collection.count() == 0:
        return "la base del reglamento está vacía; correr scripts/ingestar_reglamento.py."
    return None


def partir_cita(cita: str) -> tuple[str, str]:
    """'B1.6.3b' -> ('B1.6.3', 'b');  '12.1.1.i' -> ('12.1.1', 'i');  'B1.6.3' -> ('B1.6.3', '');
    'Appendix L Chapter IV Article 2 d)' o 'Ap. L, cap. IV, art. 2 d)' -> ('L-IV-2', 'd')."""
    ap = re.search(r"(?:appendix|ap\.?|anexo|apéndice)\s*L\b.*?(?:chapter|cap(?:[íi]tulo)?\.?)\s*([IVX]+)"
                   r".*?(?:article|art(?:[íi]culo)?\.?)\s*(\d+)\s*([a-z])?", cita, re.I)
    if ap:
        return f"L-{ap.group(1).upper()}-{ap.group(2)}", (ap.group(3) or "").lower()
    m = re.search(r"([A-F]?\d+(?:\.\d+)*)\.?\s?([a-z])?\)?\b", cita.strip())
    return (m.group(1), m.group(2) or "") if m else (cita.strip(), "")


def _where(*condiciones: dict | None) -> dict | None:
    conds = [c for c in condiciones if c]
    return None if not conds else conds[0] if len(conds) == 1 else {"$and": conds}


def vigente_desde(reglamento: str | None) -> str | None:
    """'... Issue 09 (01 October 2026)' -> '2026-10-01' (fecha de esa versión del reglamento)."""
    m = re.search(r"\((\d{1,2} \w+ \d{4})\)", reglamento or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%d %B %Y").date().isoformat()
    except ValueError:
        return None


def reglamentos_cargados(año: int | None) -> list[str]:
    """Nombres de los reglamentos que hay en la base para ese año."""
    res = get_vectorstore().get(where={"año": año} if año else None, include=["metadatas"])
    return sorted({m.get("reglamento") or m.get("fuente") for m in res["metadatas"]})


def _resultado(texto: str, meta: dict, coincidencia: str, similitud: float | None) -> dict:
    reglamento = meta.get("reglamento") or meta.get("fuente")  # nombre oficial para citar
    return {
        "cita": meta.get("cita"),
        "titulo": meta.get("titulo"),
        "reglamento": reglamento,
        "vigente_desde": vigente_desde(reglamento),
        "año": meta.get("año"),
        "coincidencia": coincidencia,
        "similitud": None if similitud is None else round(similitud, 3),
        "texto": texto.split("\n", 1)[-1],  # sin la línea de cita/título (ya va en los campos)
    }


def buscar(consulta: str, año: int | None = None, cita: str | None = None,
           k: int = config.RAG_TOP_K, min_similitud: float = config.RAG_MIN_SIMILITUD) -> list[dict]:
    """Párrafos del reglamento relevantes para la consulta.

    1. Si viene `cita` (ej. "B1.6.3b"), trae ese párrafo exacto por metadata.
    2. Completa con los párrafos más parecidos por similitud del coseno (>= min_similitud),
       filtrados por año.
    """
    store = get_vectorstore()
    por_año = {"año": año} if año else None
    out, vistos = [], set()

    if cita:
        # Búsqueda por metadatos (sin embeddings): "B1.6.3b" -> articulo B1.6.3, inciso b.
        # Sin inciso ("B1.6.3") trae el artículo completo, todos sus incisos en orden.
        articulo, inciso = partir_cita(cita)
        res = store.get(where=_where(por_año, {"articulo": articulo}, {"inciso": inciso} if inciso else None))
        if not res["ids"] and inciso:  # el inciso puede no existir como párrafo propio
            res = store.get(where=_where(por_año, {"articulo": articulo}))
        exactos = sorted(zip(res["ids"], res["documents"], res["metadatas"]),
                         key=lambda r: (r[2].get("inciso", ""), r[2].get("parte", 0)))
        for id_, texto, meta in exactos[:MAX_EXACTOS]:
            vistos.add(id_)
            out.append(_resultado(texto, meta, "exacta", None))
        if not exactos:
            # Decirlo explícitamente: si no, el modelo recibe párrafos "parecidos" y sigue
            # buscando el artículo con otras palabras.
            out.append({
                "aviso": f"El artículo {cita} no está en el reglamento cargado para {año} "
                         f"({'; '.join(reglamentos_cargados(año)) or 'ninguno'}). Puede ser de otro "
                         "reglamento (por ejemplo el Código Deportivo Internacional) o de las notas "
                         "del director de carrera. No lo vuelvas a buscar.",
                "no_esta_en_corpus": True,
            })

    # La similitud también busca en el glosario propio (año 0: vale para todas las temporadas).
    con_glosario = {"$or": [{"año": año}, {"año": 0}]} if año else None
    try:
        parecidos = _con_reintento(lambda: store.similarity_search_with_score(consulta, k=k, filter=con_glosario))
    except Exception as exc:
        if not out or not _es_limite(exc):
            raise
        # Sin cupo de embeddings: igual sirven los párrafos exactos (no usan embeddings).
        out.append({"aviso": "Búsqueda por similitud no disponible ahora (límite de la API de "
                             "embeddings); solo se devuelven los párrafos citados."})
        return out
    for doc, distancia in parecidos:
        similitud = 1 - distancia  # colección en espacio coseno
        if doc.id in vistos or similitud < min_similitud:
            continue
        vistos.add(doc.id)
        out.append(_resultado(doc.page_content, doc.metadata, "similitud", similitud))
    return out


def _es_limite(exc: Exception) -> bool:
    return "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)


def es_limite_diario(exc: Exception) -> bool:
    return "per day" in str(exc) or "PerDay" in str(exc)


def _con_reintento(fn, espera: float = 35):
    """El tier gratuito permite 100 embeddings por minuto: ante un 429 espera y reintenta una vez.
    Si el límite es el diario, esperar no sirve: falla enseguida."""
    try:
        return fn()
    except Exception as exc:
        if not _es_limite(exc) or es_limite_diario(exc):
            raise
        time.sleep(espera)
        return fn()
