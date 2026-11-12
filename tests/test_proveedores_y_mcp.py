"""Adaptadores de LLM ("traé tu propia clave", modelos locales) y servidor MCP f1-data."""
import asyncio

import pytest

from agente_f1.llm import PROVEEDORES, get_provider


@pytest.mark.parametrize("nombre", list(PROVEEDORES))
def test_cada_adaptador_crea_su_modelo(nombre):
    provider = get_provider(nombre, api_key="clave-de-prueba")
    assert provider.crear_chat_model() is not None


def test_clave_traida_por_el_usuario(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert not get_provider("openai").disponible()
    assert get_provider("openai", api_key="sk-x").disponible()


def test_modelos_locales_no_necesitan_clave():
    for nombre in ("ollama", "lmstudio"):
        p = get_provider(nombre)
        assert p.local and not p.necesita_clave and p.disponible() and p.base_url


def test_servidor_mcp_expone_las_tools_de_datos():
    from agente_f1.mcp_f1.servidor import mcp
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    assert set(tools) == {"buscar_piloto", "sanciones_de_piloto", "sanciones_de_carrera",
                          "ultima_sancion", "incidentes_en_carrera"}
    # cada argumento tiene descripción (lo pide la consigna para las tools)
    for t in tools.values():
        assert all(p.get("description") for p in t.inputSchema["properties"].values()), t.name
