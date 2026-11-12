"""Selección del proveedor de LLM.

    from agente_f1.llm import get_provider
    provider = get_provider()                                  # LLM_PROVIDER / LLM_MODEL del .env
    provider = get_provider("anthropic", api_key="sk-...")     # clave traída por el usuario
    provider = get_provider("ollama", modelo="qwen3:8b")       # modelo local
    model = provider.crear_chat_model()
"""
from .. import config
from .base import Fragmento, LLMProvider
from .discovery import listar_modelos_proveedor
from .providers import PROVEEDORES


def get_provider(nombre: str | None = None, modelo: str | None = None, api_key: str | None = None,
                 base_url: str | None = None) -> LLMProvider:
    nombre = (nombre or config.LLM_PROVIDER).lower()
    if nombre not in PROVEEDORES:
        raise ValueError(f"Proveedor '{nombre}' no soportado. Opciones: {sorted(PROVEEDORES)}")
    # LLM_MODEL solo aplica al proveedor configurado por defecto.
    if not modelo and nombre == config.LLM_PROVIDER:
        modelo = config.LLM_MODEL or None
    return PROVEEDORES[nombre](modelo=modelo, razonamiento=config.LLM_REASONING,
                               max_retries=config.LLM_MAX_RETRIES, api_key=api_key, base_url=base_url)


__all__ = ["Fragmento", "LLMProvider", "PROVEEDORES", "get_provider", "listar_modelos_proveedor"]
