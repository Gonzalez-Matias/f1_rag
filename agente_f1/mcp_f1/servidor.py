"""Servidor MCP "f1-data": datos de sanciones de Fórmula 1.

Expone, para cualquier cliente compatible con MCP (nuestro agente, Claude Desktop,
Claude Code...), las consultas sobre las dos fuentes de datos:
  - decisiones de los comisarios de la FIA (índice local + PDFs de fia.com)
  - OpenF1 (pilotos y mensajes de Race Control)

Correr:  python -m agente_f1.mcp_f1          (transporte stdio)
"""
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..fuentes import openf1
from ..fuentes.fia import consultas
from ..util import seguro

mcp = FastMCP(
    "f1-data",
    log_level="WARNING",  # stdout es el canal MCP; los logs van a stderr y solo los importantes
    instructions="Datos de sanciones de Fórmula 1: decisiones oficiales de los comisarios de la FIA "
                 "(con artículo infringido y motivo) y datos de OpenF1 (pilotos, Race Control). "
                 "Las decisiones identifican al piloto por número de auto: usar buscar_piloto primero.",
)

Año = Annotated[int, Field(description="Temporada, ej. 2026.")]
Carrera = Annotated[str, Field(description='Nombre de la carrera en inglés, ej. "São Paulo Grand Prix" o "Sao Paulo".')]
NumeroAuto = Annotated[int, Field(description="Número de auto del piloto en esa temporada (obtenerlo con buscar_piloto).")]
Apellido = Annotated[str | None, Field(description="Apellido del piloto, para verificar que el número es suyo (los números cambian entre temporadas).")]


def _compacto(rec: dict) -> dict:
    """Saca campos que no aportan al agente y ocupan contexto."""
    return {k: v for k, v in rec.items() if k not in ("comisarios", "publicado") and v not in (None, [], "")}


@mcp.tool()
@seguro
def buscar_piloto(nombre: Annotated[str, Field(description='Nombre, apellido o abreviatura, ej. "Bearman", "BEA".')],
                  año: Año):
    """Busca un piloto y devuelve su número de auto y equipo en esa temporada. Usala antes de
    consultar sanciones: las decisiones de la FIA identifican al piloto por número de auto."""
    pilotos = openf1.buscar_piloto(nombre, año)
    return pilotos or {"error": f"No se encontró a '{nombre}' en la temporada {año}."}


@mcp.tool()
@seguro
def sanciones_de_piloto(año: Año, carrera: Carrera, numero_auto: NumeroAuto, nombre_piloto: Apellido = None):
    """Decisiones de los comisarios FIA sobre un piloto en una carrera (puede haber más de una):
    sesión, hecho, infracción, artículos citados, decisión, motivo, fecha y URL del documento oficial."""
    return [_compacto(r) for r in consultas.sanciones_piloto(año, carrera, numero_auto, nombre_piloto)]


@mcp.tool()
@seguro
def sanciones_de_carrera(año: Año, carrera: Carrera):
    """Todas las sanciones de los comisarios FIA en una carrera. Excluye vueltas borradas por
    límites de pista y decisiones "No further action"."""
    return [_compacto(r) for r in consultas.sanciones_carrera(año, carrera)]


@mcp.tool()
@seguro
def ultima_sancion(numero_auto: NumeroAuto, nombre_piloto: Apellido = None):
    """La sanción más reciente de un piloto, buscando hacia atrás desde la temporada actual."""
    rec = consultas.ultima_sancion(numero_auto, nombre_piloto)
    return _compacto(rec) if rec else {"resultado": "No se encontraron sanciones para ese piloto."}


@mcp.tool()
@seguro
def incidentes_en_carrera(año: Año,
                          carrera: Annotated[str, Field(description='Carrera o lugar, ej. "Sao Paulo", "Monza".')],
                          numero_auto: Annotated[int | None, Field(description="Si se indica, solo los mensajes de ese auto.")] = None):
    """Mensajes de Race Control de los comisarios en una carrera (incidente anotado, investigado,
    sanción anunciada). Sirve para contar la secuencia; no trae el motivo ni los artículos."""
    meeting = openf1.buscar_meeting(año, carrera)
    if not meeting:
        return {"error": f"No se encontró la carrera '{carrera}' en {año} en OpenF1."}
    return {"carrera": meeting.get("meeting_name"),
            "mensajes": openf1.mensajes_comisarios(meeting["meeting_key"], numero_auto)}
