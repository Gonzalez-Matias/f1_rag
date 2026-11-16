"""Adaptadores concretos. Cada import del SDK va dentro del método para que
solo haga falta instalar el paquete del proveedor que se usa."""
from .base import LLMProvider


class GeminiProvider(LLMProvider):
    nombre = "gemini"
    etiqueta = "Google Gemini"
    env_api_key = "GOOGLE_API_KEY"
    modelo_default = "gemini-2.5-flash"
    models_url = "https://generativelanguage.googleapis.com/v1beta/models"
    modelos_fallback = (
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-3.8-flash",
        "gemini-3.8-pro",
        "gemini-4-argon",
    )

    def crear_chat_model(self):
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=self.modelo,
            google_api_key=self.api_key,
            include_thoughts=self.razonamiento,  # devuelve un resumen del razonamiento
            max_retries=self.max_retries,
            temperature=0.2,
        )


class OpenAIProvider(LLMProvider):
    nombre = "openai"
    etiqueta = "OpenAI (ChatGPT)"
    env_api_key = "OPENAI_API_KEY"
    modelo_default = "gpt-5-mini"
    models_url = "https://api.openai.com/v1/models"
    modelos_fallback = (
        "gpt-5-mini",
        "gpt-5",
        "gpt-6.1-astra",
        "gpt-6.1-terra",
        "gpt-6.1-sol",
        "o3-mini",
    )

    def crear_chat_model(self):
        from langchain_openai import ChatOpenAI
        kwargs = {}
        if self.razonamiento:
            # La Responses API devuelve un resumen del razonamiento de los modelos de razonamiento.
            kwargs = {"use_responses_api": True, "reasoning": {"effort": "medium", "summary": "auto"}}
        return ChatOpenAI(model=self.modelo, api_key=self.api_key, max_retries=self.max_retries, **kwargs)


class DeepSeekProvider(LLMProvider):
    nombre = "deepseek"
    etiqueta = "DeepSeek"
    env_api_key = "DEEPSEEK_API_KEY"
    # deepseek-reasoner soporta tool calling y devuelve razonamiento (verificado 2026-11-07).
    # deepseek-chat también anda con tools, pero no razona.
    modelo_default = "deepseek-reasoner"
    models_url = "https://api.deepseek.com/models"
    modelos_fallback = (
        "deepseek-reasoner",
        "deepseek-chat",
    )

    def crear_chat_model(self):
        from langchain_deepseek import ChatDeepSeek
        return ChatDeepSeek(model=self.modelo, api_key=self.api_key, max_retries=self.max_retries)


class AnthropicProvider(LLMProvider):
    nombre = "anthropic"
    etiqueta = "Anthropic (Claude)"
    env_api_key = "ANTHROPIC_API_KEY"
    modelo_default = "claude-sonnet-5-5"
    models_url = "https://api.anthropic.com/v1/models"
    modelos_fallback = (
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
        "claude-opus-5-5",
        "claude-3-5-sonnet-latest",
    )

    def crear_chat_model(self):
        from langchain_anthropic import ChatAnthropic
        kwargs = {}
        if self.razonamiento:
            # Extended thinking: la temperatura no se puede fijar con thinking activo.
            kwargs = {"thinking": {"type": "enabled", "budget_tokens": 2048}, "max_tokens": 8192}
        return ChatAnthropic(model=self.modelo, api_key=self.api_key, max_retries=self.max_retries, **kwargs)


class OllamaProvider(LLMProvider):
    """Modelo local con Ollama (https://ollama.com). Tiene que soportar tool calling,
    ej. qwen3, llama3.1, mistral-nemo. Con qwen3 también devuelve razonamiento."""
    nombre = "ollama"
    etiqueta = "Local · Ollama"
    env_api_key = None
    local = True
    modelo_default = "qwen3:8b"
    env_base_url = "OLLAMA_BASE_URL"
    base_url_default = "http://localhost:11434"
    modelos_fallback = (
        "qwen3:8b",
        "llama3.1",
        "mistral-nemo",
    )

    def crear_chat_model(self):
        from langchain_ollama import ChatOllama
        return ChatOllama(model=self.modelo, base_url=self.base_url, reasoning=self.razonamiento,
                          num_ctx=16384, temperature=0.2)


class LMStudioProvider(LLMProvider):
    """Modelo local con LM Studio (https://lmstudio.ai), que expone una API compatible con OpenAI.
    El razonamiento no se recupera por esta vía: solo se ven las tools."""
    nombre = "lmstudio"
    etiqueta = "Local · LM Studio"
    env_api_key = None
    local = True
    modelo_default = "qwen3-8b"
    env_base_url = "LMSTUDIO_BASE_URL"
    base_url_default = "http://localhost:1234/v1"
    modelos_fallback = (
        "qwen3-8b",
    )

    def crear_chat_model(self):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=self.modelo, base_url=self.base_url, api_key="lm-studio",
                          max_retries=self.max_retries, temperature=0.2)


PROVEEDORES: dict[str, type[LLMProvider]] = {
    p.nombre: p for p in (GeminiProvider, OpenAIProvider, DeepSeekProvider, AnthropicProvider,
                          OllamaProvider, LMStudioProvider)
}
