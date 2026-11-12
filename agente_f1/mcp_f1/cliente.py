"""Cliente del servidor MCP "f1-data" para el agente.

- Lanza el servidor como subproceso (stdio) y mantiene UNA sesión abierta mientras viva
  la app: así no se levanta un proceso nuevo en cada llamada.
- Las tools de MCP son asíncronas y la app es síncrona (Streamlit + checkpointer SQLite).
  La sesión vive en un hilo con su propio event loop y cada tool se expone al agente
  como una tool síncrona que delega en ese loop.
"""
import asyncio
import concurrent.futures
import json
import sys
import threading

from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .. import config

TIMEOUT_TOOL = 300  # s: la primera consulta de una carrera puede esperar el crawl-delay de fia.com


def _texto(resultado) -> str:
    """Resultado de una tool MCP -> texto (JSON), como el resto de las tools."""
    if isinstance(resultado, tuple):  # (contenido, artefacto)
        resultado = resultado[0]
    if isinstance(resultado, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in resultado)
    return resultado if isinstance(resultado, str) else json.dumps(resultado, ensure_ascii=False)


class ClienteF1:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, name="mcp-f1-data", daemon=True).start()
        listo: concurrent.futures.Future = concurrent.futures.Future()
        self._cerrar = None
        asyncio.run_coroutine_threadsafe(self._sesion(listo), self._loop)
        self._tools_mcp: list[BaseTool] = listo.result(timeout=60)

    async def _sesion(self, listo):
        """Abre la sesión y la mantiene abierta (los context managers de MCP tienen que
        abrirse y cerrarse en la misma tarea)."""
        self._cerrar = asyncio.Event()
        params = StdioServerParameters(command=sys.executable, args=["-m", "agente_f1.mcp_f1"],
                                       cwd=str(config.ROOT))
        try:
            async with stdio_client(params) as (leer, escribir), ClientSession(leer, escribir) as sesion:
                await sesion.initialize()
                listo.set_result(await load_mcp_tools(sesion))
                await self._cerrar.wait()
        except Exception as exc:  # noqa: BLE001
            if not listo.done():
                listo.set_exception(exc)

    def _sincronica(self, tool_mcp: BaseTool) -> BaseTool:
        def llamar(**kwargs) -> str:
            try:
                futuro = asyncio.run_coroutine_threadsafe(tool_mcp.ainvoke(kwargs), self._loop)
                return _texto(futuro.result(timeout=TIMEOUT_TOOL))
            except Exception as exc:  # noqa: BLE001 - ningún error corta el flujo del agente
                return json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)

        return StructuredTool.from_function(func=llamar, name=tool_mcp.name, description=tool_mcp.description,
                                            args_schema=tool_mcp.args_schema)

    def tools(self) -> list[BaseTool]:
        return [self._sincronica(t) for t in self._tools_mcp]

    def cerrar(self):
        if self._cerrar:
            self._loop.call_soon_threadsafe(self._cerrar.set)


_cliente: ClienteF1 | None = None
_lock = threading.Lock()


def tools_f1() -> list[BaseTool]:
    """Tools del servidor MCP f1-data (una sola conexión por proceso)."""
    global _cliente
    with _lock:
        if _cliente is None:
            _cliente = ClienteF1()
    return _cliente.tools()
