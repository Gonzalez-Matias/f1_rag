"""Configuración central: rutas del proyecto y variables de entorno (.env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _ruta(var: str, defecto: Path) -> Path:
    """Ruta desde el .env (relativa a la raíz del proyecto) o la ruta por defecto."""
    valor = os.getenv(var)
    return (ROOT / valor).resolve() if valor else defecto


# ---------------------------------------------------------------- LLM
# Proveedor de chat: gemini | openai | deepseek | anthropic (ver agente_f1/llm/)
# Las API keys las lee cada adaptador: GOOGLE_API_KEY, OPENAI_API_KEY, DEEPSEEK_API_KEY, ANTHROPIC_API_KEY
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
LLM_MODEL = os.getenv("LLM_MODEL", "")  # vacío = modelo por defecto del proveedor
LLM_REASONING = os.getenv("LLM_REASONING", "true").lower() in ("1", "true", "yes", "si", "sí")
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "6"))  # reintentos ante 429 / errores transitorios

# ---------------------------------------------------------------- rutas
DATA_DIR = ROOT / "data"
INFORMES_DIR = ROOT / "informes"                                   # informes generados por el agente
CONVERSACIONES_DB = _ruta("CONVERSACIONES_DB", DATA_DIR / "conversaciones.sqlite")

# ---------------------------------------------------------------- fuentes: FIA
FIA_CACHE_DB = _ruta("FIA_CACHE_DB", DATA_DIR / "fia_cache.sqlite")
FIA_CRAWL_DELAY = float(os.getenv("FIA_CRAWL_DELAY", "10"))       # segundos entre pedidos (robots.txt)
# Si se define (segundos), las consultas también refrescan la carrera en curso con esa frecuencia.
FIA_LIVE_TTL = float(os.environ["FIA_LIVE_TTL"]) if os.getenv("FIA_LIVE_TTL") else None

# ---------------------------------------------------------------- RAG del reglamento
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")                  # embeddings (siempre Gemini)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
REGLAMENTO_DIR = DATA_DIR / "reglamento"                          # PDFs del reglamento (corpus)
CHROMA_DIR = _ruta("CHROMA_DIR", DATA_DIR / "chroma")             # base vectorial persistida
CHROMA_COLLECTION = "reglamento_f1"
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))                       # párrafos por búsqueda
RAG_MIN_SIMILITUD = float(os.getenv("RAG_MIN_SIMILITUD", "0.63"))  # coseno mínimo (calibrado: relevantes 0.66-0.83, ruido <= 0.62)
RAG_MAX_CHARS_PARRAFO = int(os.getenv("RAG_MAX_CHARS_PARRAFO", "1200"))  # tamaño máximo de un párrafo
