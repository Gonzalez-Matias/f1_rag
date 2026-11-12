"""Embeddings del RAG.

Son independientes del proveedor de chat: si cambiaran, habría que reindexar
todo el corpus. Se usa gemini-embedding-001 (tier gratuito de Google).
"""
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from .. import config


def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    if not config.GOOGLE_API_KEY:
        raise RuntimeError("Falta GOOGLE_API_KEY en .env (se usa para los embeddings del reglamento).")
    return GoogleGenerativeAIEmbeddings(model=config.EMBEDDING_MODEL, google_api_key=config.GOOGLE_API_KEY)
