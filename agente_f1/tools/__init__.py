"""Tools del agente.

| Tool                           | Dónde                      | Para qué                                       |
|--------------------------------|----------------------------|------------------------------------------------|
| openf1_calendario              | MCP f1-data (OpenF1)       | rondas de la temporada: nombre, lugar, fechas  |
| openf1_buscar_piloto           | MCP f1-data (OpenF1)       | nombre -> número de auto / equipo              |
| openf1_mensajes_race_control   | MCP f1-data (OpenF1)       | secuencia en vivo de Race Control              |
| fia_decisiones_de_piloto       | MCP f1-data (FIA)          | decisiones oficiales: carrera o temporada      |
| fia_decisiones_de_carrera      | MCP f1-data (FIA)          | todas las decisiones de una carrera            |
| fia_ultima_decision_de_piloto  | MCP f1-data (FIA)          | sanción más reciente de un piloto              |
| sanciones_de_piloto_completo   | MCP f1-data (OpenF1 + FIA) | piloto + decisiones + Race Control, en una     |
| buscar_en_reglamento           | local, RAG (Chroma)        | texto del artículo y glosario                  |
| generar_informe                | local, propia              | resultado tangible: informe PDF/HTML           |
"""
from .informe_tools import generar_informe
from .reglamento_tools import buscar_en_reglamento


def construir_tools() -> list:
    """Tools de datos de F1 (servidor MCP propio) + tools locales del agente."""
    from ..mcp_f1.cliente import tools_f1
    return [*tools_f1(), buscar_en_reglamento, generar_informe]
