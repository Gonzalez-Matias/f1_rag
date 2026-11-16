"""Descubrimiento dinámico de modelos por proveedor en tiempo real.

Consulta el endpoint oficial de cada proveedor (Gemini, OpenAI, Claude, DeepSeek,
Ollama, LM Studio) utilizando la clave o URL proporcionada, filtrando modelos no
conversacionales (audio, embeddings, moderación), y haciendo fallback a un catálogo
base cuando la red no está disponible o no se ingresó clave aún.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from .providers import PROVEEDORES

_NON_CHAT_KEYWORDS = (
    "embedding",
    "embed",
    "audio",
    "tts",
    "whisper",
    "dall-e",
    "imagen",
    "moderation",
    "text-embedding",
    "realtime",
    "babbage",
    "davinci",
    "curie",
    "ada",
    "vision-preview",
    "transcription",
    "tts-1",
    "rerank",
    "aqa",
)


def _clave_parece_real(clave: str | None) -> bool:
    clean = (clave or "").strip()
    if not clean:
        return False
    lower = clean.lower()
    return not (
        lower.startswith("your_")
        or lower.startswith("tu_clave")
        or lower.startswith("missing-")
    )


def listar_modelos_proveedor(
    nombre: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float = 4.0,
) -> dict[str, Any]:
    """Consulta el endpoint oficial del proveedor en tiempo real.

    Devuelve un diccionario con:
      - proveedor: id normalizado del proveedor.
      - fuente: 'api_en_vivo', 'fallback_catalogo' o 'desconocido'.
      - modelos: lista de identificadores de modelos utilizables.
    """
    prov_id = (nombre or "").strip().lower()
    if prov_id not in PROVEEDORES:
        return {"proveedor": prov_id, "fuente": "desconocido", "modelos": []}

    clase = PROVEEDORES[prov_id]
    catalogo_base = list(getattr(clase, "modelos_fallback", ()) or (clase.modelo_default,))
    clave = (
        api_key
        if api_key is not None
        else (os.getenv(clase.env_api_key, "") if clase.env_api_key else "")
    ).strip()

    # Si requiere API Key y la clave está vacía o parece un placeholder, devolver fallback directo
    if not clase.local and not _clave_parece_real(clave):
        return {
            "proveedor": prov_id,
            "fuente": "fallback_catalogo",
            "modelos": catalogo_base,
        }

    try:
        if prov_id == "gemini":
            resp = httpx.get(
                f"{clase.models_url}?key={clave}",
                timeout=timeout,
            )
            if resp.status_code == 200:
                payload = resp.json()
                modelos_vivos: list[str] = []
                for item in payload.get("models", []):
                    metodos = item.get("supportedGenerationMethods") or []
                    nom = str(item.get("name", "")).replace("models/", "").strip()
                    if not nom:
                        continue
                    if metodos and "generateContent" not in metodos:
                        continue
                    if any(k in nom.lower() for k in _NON_CHAT_KEYWORDS):
                        continue
                    modelos_vivos.append(nom)
                if modelos_vivos:
                    return {
                        "proveedor": prov_id,
                        "fuente": "api_en_vivo",
                        "modelos": modelos_vivos,
                    }

        elif prov_id == "anthropic":
            resp = httpx.get(
                clase.models_url,
                headers={
                    "x-api-key": clave,
                    "anthropic-version": "2023-06-01",
                },
                timeout=timeout,
            )
            if resp.status_code == 200:
                payload = resp.json()
                modelos_vivos = [
                    str(item.get("id", "")).strip()
                    for item in payload.get("data", [])
                    if item.get("id")
                ]
                if modelos_vivos:
                    return {
                        "proveedor": prov_id,
                        "fuente": "api_en_vivo",
                        "modelos": modelos_vivos,
                    }

        elif prov_id == "ollama":
            url_base = (
                base_url
                or os.getenv(clase.env_base_url, "")
                or clase.base_url_default
                or "http://localhost:11434"
            ).rstrip("/")
            resp = httpx.get(f"{url_base}/api/tags", timeout=timeout)
            if resp.status_code == 200:
                payload = resp.json()
                modelos_vivos = [
                    str(item.get("name", "")).strip()
                    for item in payload.get("models", [])
                    if item.get("name")
                ]
                if modelos_vivos:
                    return {
                        "proveedor": prov_id,
                        "fuente": "api_en_vivo",
                        "modelos": modelos_vivos,
                    }

        elif prov_id == "lmstudio":
            url_base = (
                base_url
                or os.getenv(clase.env_base_url, "")
                or clase.base_url_default
                or "http://localhost:1234/v1"
            ).rstrip("/")
            resp = httpx.get(f"{url_base}/models", timeout=timeout)
            if resp.status_code == 200:
                payload = resp.json()
                modelos_vivos = [
                    str(item.get("id", "")).strip()
                    for item in payload.get("data", [])
                    if item.get("id")
                ]
                if modelos_vivos:
                    return {
                        "proveedor": prov_id,
                        "fuente": "api_en_vivo",
                        "modelos": modelos_vivos,
                    }

        else:
            # openai, deepseek u otros endpoints compatibles con /v1/models
            url_models = clase.models_url or "https://api.openai.com/v1/models"
            headers = {"Authorization": f"Bearer {clave}"} if clave else {}
            resp = httpx.get(url_models, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                payload = resp.json()
                modelos_vivos = []
                for item in payload.get("data", []):
                    mid = str(item.get("id", "")).strip()
                    if not mid:
                        continue
                    if any(k in mid.lower() for k in _NON_CHAT_KEYWORDS):
                        continue
                    modelos_vivos.append(mid)
                if modelos_vivos:
                    return {
                        "proveedor": prov_id,
                        "fuente": "api_en_vivo",
                        "modelos": modelos_vivos,
                    }

    except Exception:
        pass

    return {
        "proveedor": prov_id,
        "fuente": "fallback_catalogo",
        "modelos": catalogo_base,
    }
