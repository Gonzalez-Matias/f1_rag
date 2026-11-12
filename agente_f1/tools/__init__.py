"""Tools del agente.

| Tool                  | Dónde                     | Para qué                                        |
|-----------------------|---------------------------|-------------------------------------------------|
| buscar_piloto         | MCP f1-data (OpenF1)      | nombre -> número de auto / equipo               |
| incidentes_en_carrera | MCP f1-data (OpenF1)      | secuencia de Race Control                       |
| sanciones_de_piloto   | MCP f1-data (FIA, propia) | decisión oficial de los comisarios              |
| sanciones_de_carrera  | MCP f1-data (FIA, propia) | todos los sancionados de una carrera            |
| ultima_sancion        | MCP f1-data (FIA, propia) | sanción más reciente de un piloto               |
| buscar_en_reglamento  | local, RAG (Chroma)       | texto del artículo y glosario                   |
| generar_informe       | local, propia             | resultado tangible: informe PDF/HTML            |
"""
from .informe_tools import generar_informe
from .reglamento_tools import buscar_en_reglamento


def construir_tools() -> list:
    """Tools de datos de F1 (servidor MCP propio) + tools locales del agente."""
    from ..mcp_f1.cliente import tools_f1
    return [*tools_f1(), buscar_en_reglamento, generar_informe]
