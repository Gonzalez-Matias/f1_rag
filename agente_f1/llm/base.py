"""Interfaz común de los proveedores de LLM (patrón adaptador).

Cada proveedor (Gemini, OpenAI, DeepSeek, Anthropic, modelos locales) expone su modelo
de chat y su razonamiento de forma distinta. El resto de la aplicación (agente y UI)
solo habla con `LLMProvider`, así cambiar de proveedor es cambiar una variable.

"Traé tu propia clave": la clave puede venir del .env o pasarse al crear el adaptador
(la UI la pide y la guarda solo en la sesión del navegador, nunca en disco).
"""
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk


@dataclass
class Fragmento:
    """Lo que la UI necesita de cada chunk del streaming, ya normalizado."""
    razonamiento: str = ""
    texto: str = ""


class LLMProvider(ABC):
    nombre: str              # id usado en LLM_PROVIDER, ej. "gemini"
    etiqueta: str            # nombre para mostrar en la UI
    env_api_key: str | None  # variable de entorno con la clave (None: no necesita clave)
    modelo_default: str
    local: bool = False      # corre en la máquina del usuario (Ollama, LM Studio)
    env_base_url: str | None = None
    base_url_default: str | None = None

    def __init__(self, modelo: str | None = None, razonamiento: bool = True, max_retries: int = 6,
                 api_key: str | None = None, base_url: str | None = None):
        self.modelo = modelo or self.modelo_default
        self.razonamiento = razonamiento
        self.max_retries = max_retries  # reintentos con espera ante 429 / errores transitorios
        self._api_key = api_key
        self.base_url = base_url or (os.getenv(self.env_base_url) if self.env_base_url else None) \
            or self.base_url_default

    @property
    def api_key(self) -> str:
        """La clave pasada desde la UI, o la del .env."""
        if self._api_key:
            return self._api_key
        return os.getenv(self.env_api_key, "") if self.env_api_key else ""

    @property
    def necesita_clave(self) -> bool:
        return self.env_api_key is not None

    def disponible(self) -> bool:
        return self.local or bool(self.api_key)

    @abstractmethod
    def crear_chat_model(self) -> BaseChatModel:
        """Modelo de chat con tool calling (y razonamiento si el proveedor lo permite)."""

    def extraer(self, chunk: AIMessageChunk | AIMessage) -> Fragmento:
        """Separa razonamiento y texto de un chunk del streaming o de un mensaje completo
        (al reconstruir el historial de una conversación guardada).

        Usa los content_blocks estándar de LangChain v1, que normalizan el razonamiento de
        Gemini, OpenAI y Anthropic. DeepSeek y Ollama lo mandan en
        additional_kwargs["reasoning_content"]: se toma de ahí si no vino en los bloques.
        """
        frag = Fragmento()
        for block in chunk.content_blocks:
            if block["type"] == "reasoning":
                frag.razonamiento += block.get("reasoning") or ""
            elif block["type"] == "text":
                frag.texto += block.get("text") or ""
        if not frag.razonamiento:
            frag.razonamiento = chunk.additional_kwargs.get("reasoning_content") or ""
        return frag

    def __repr__(self) -> str:
        return f"{self.etiqueta} ({self.modelo})"
