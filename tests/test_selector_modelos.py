"""Tests para el descubrimiento dinámico y fallback de modelos por proveedor."""
import httpx
import pytest

from agente_f1.llm import PROVEEDORES, listar_modelos_proveedor


@pytest.mark.parametrize("nombre", list(PROVEEDORES))
def test_fallback_catalogo_todos_los_proveedores(nombre, monkeypatch):
    # Simulamos desconexión/offline para probar el fallback garantizado
    def mock_get(url, **kwargs):
        raise httpx.ConnectError("Offline")

    monkeypatch.setattr(httpx, "get", mock_get)
    resultado = listar_modelos_proveedor(nombre, api_key="")
    assert resultado["proveedor"] == nombre
    assert resultado["fuente"] == "fallback_catalogo"
    assert isinstance(resultado["modelos"], list)
    assert len(resultado["modelos"]) > 0
    # El modelo default del proveedor debe estar incluido en la lista
    assert PROVEEDORES[nombre].modelo_default in resultado["modelos"]


def test_proveedor_desconocido():
    resultado = listar_modelos_proveedor("inexistente")
    assert resultado["fuente"] == "desconocido"
    assert resultado["modelos"] == []


def test_gemini_api_en_vivo_mock(monkeypatch):
    def mock_get(url, **kwargs):
        assert "generativelanguage.googleapis.com" in str(url)
        payload = {
            "models": [
                {
                    "name": "models/gemini-2.5-flash",
                    "supportedGenerationMethods": ["generateContent"],
                },
                {
                    "name": "models/text-embedding-004",
                    "supportedGenerationMethods": ["embedContent"],
                },
                {
                    "name": "models/gemini-3.8-pro",
                    "supportedGenerationMethods": ["generateContent"],
                },
            ]
        }
        return httpx.Response(200, json=payload, request=httpx.Request("GET", str(url)))

    monkeypatch.setattr(httpx, "get", mock_get)
    resultado = listar_modelos_proveedor("gemini", api_key="AIza-clave-real")
    assert resultado["fuente"] == "api_en_vivo"
    assert resultado["modelos"] == ["gemini-2.5-flash", "gemini-3.8-pro"]
    assert "text-embedding-004" not in resultado["modelos"]


def test_openai_api_en_vivo_mock(monkeypatch):
    def mock_get(url, **kwargs):
        assert "api.openai.com" in str(url)
        payload = {
            "data": [
                {"id": "gpt-5-mini"},
                {"id": "text-embedding-3-small"},
                {"id": "dall-e-3"},
                {"id": "gpt-6.1-astra"},
            ]
        }
        return httpx.Response(200, json=payload, request=httpx.Request("GET", str(url)))

    monkeypatch.setattr(httpx, "get", mock_get)
    resultado = listar_modelos_proveedor("openai", api_key="sk-real-test-key")
    assert resultado["fuente"] == "api_en_vivo"
    assert resultado["modelos"] == ["gpt-5-mini", "gpt-6.1-astra"]
    assert "text-embedding-3-small" not in resultado["modelos"]


def test_anthropic_api_en_vivo_mock(monkeypatch):
    def mock_get(url, **kwargs):
        assert "api.anthropic.com" in str(url)
        payload = {
            "data": [
                {"id": "claude-sonnet-5-5"},
                {"id": "claude-haiku-5-5"},
            ]
        }
        return httpx.Response(200, json=payload, request=httpx.Request("GET", str(url)))

    monkeypatch.setattr(httpx, "get", mock_get)
    resultado = listar_modelos_proveedor("anthropic", api_key="sk-ant-real-test-key")
    assert resultado["fuente"] == "api_en_vivo"
    assert resultado["modelos"] == ["claude-sonnet-5-5", "claude-haiku-5-5"]


def test_ollama_api_en_vivo_mock(monkeypatch):
    def mock_get(url, **kwargs):
        assert "/api/tags" in str(url)
        payload = {
            "models": [
                {"name": "qwen3:8b"},
                {"name": "llama3.2:latest"},
            ]
        }
        return httpx.Response(200, json=payload, request=httpx.Request("GET", str(url)))

    monkeypatch.setattr(httpx, "get", mock_get)
    resultado = listar_modelos_proveedor("ollama")
    assert resultado["fuente"] == "api_en_vivo"
    assert resultado["modelos"] == ["qwen3:8b", "llama3.2:latest"]


def test_error_red_hace_fallback(monkeypatch):
    def mock_get(url, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx, "get", mock_get)
    resultado = listar_modelos_proveedor("gemini", api_key="AIza-clave-real")
    assert resultado["fuente"] == "fallback_catalogo"
    assert len(resultado["modelos"]) > 0
