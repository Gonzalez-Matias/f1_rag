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

from ..fuentes import calendario, openf1, sanciones
from ..fuentes.fia import consultas
from ..util import seguro

mcp = FastMCP(
    "f1-data",
    log_level="WARNING",  # stdout es el canal MCP; los logs van a stderr y solo los importantes
    instructions="Datos de sanciones de Fórmula 1 de dos fuentes complementarias. Las tools fia_* traen "
                 "las decisiones oficiales de los comisarios de la FIA (artículo infringido, sanción y "
                 "motivo). Las tools openf1_* traen datos de OpenF1: calendario, pilotos y lo anunciado por "
                 "Race Control (sanciones en pista, banderas, investigaciones). Las tools *_completo "
                 "unen las dos fuentes: la FIA publica antes y después de las sesiones y Race Control "
                 "anuncia durante, así que son la primera opción para preguntar por sanciones. "
                 "Las decisiones de la FIA identifican al piloto por número de auto: se obtiene con "
                 "openf1_buscar_piloto.",
)

Año = Annotated[int, Field(description="Temporada, ej. 2026.")]
Carrera = Annotated[str | int, Field(
    description='Carrera: nombre en inglés ("São Paulo Grand Prix", "Sao Paulo"), lugar, país o circuito '
                '("Monza", "Brazil", "Interlagos"), o número de ronda de la temporada (5 = quinta carrera).')]
NumeroAuto = Annotated[int, Field(description="Número de auto del piloto en esa temporada (obtenerlo con openf1_buscar_piloto).")]
Apellido = Annotated[str | None, Field(description="Apellido del piloto, para verificar que el número es suyo (los números cambian entre temporadas).")]
SinSancion = Annotated[bool, Field(
    description='True para incluir también las investigaciones que terminaron sin sanción ("No further '
                'action"). Usalo cuando pregunten por qué NO sancionaron a alguien.')]


def _compacto(rec: dict) -> dict:
    """Saca campos que no aportan al agente y ocupan contexto."""
    return {k: v for k, v in rec.items() if k not in ("comisarios", "publicado") and v not in (None, [], "")}


# ---------------------------------------------------------------- OpenF1

@mcp.tool()
@seguro
def openf1_calendario(año: Año):
    """[OpenF1] Calendario de la temporada en orden: número de ronda, nombre oficial de la carrera,
    lugar, país y fechas. Sin tests ni carreras canceladas. Usala para ubicar "la quinta carrera",
    "la última carrera" o "la carrera de abril". Antes de 2023 solo trae ronda y nombre."""
    return [{k: v for k, v in e.items() if k != "meeting_key"} for e in calendario.calendario(año)]


@mcp.tool()
@seguro
def openf1_buscar_piloto(nombre: Annotated[str, Field(description='Nombre, apellido o abreviatura, ej. "Bearman", "BEA".')],
                         año: Año):
    """[OpenF1] Busca un piloto y devuelve su número de auto y equipo en esa temporada. Hace falta
    antes de las tools fia_*: las decisiones de la FIA identifican al piloto por número de auto."""
    pilotos = openf1.buscar_piloto(nombre, año)
    return pilotos or {"error": f"No se encontró a '{nombre}' en la temporada {año}."}


@mcp.tool()
@seguro
def openf1_mensajes_race_control(año: Año, carrera: Carrera,
                                 numero_auto: Annotated[int | None, Field(description="Si se indica, solo los mensajes de ese auto.")] = None):
    """[OpenF1] Mensajes en vivo de Race Control sobre los comisarios en una carrera: incidente
    anotado, bajo investigación, sanción anunciada. Sirve para contar la secuencia. No es la
    decisión oficial: no trae el motivo ni los artículos (eso está en las tools fia_*)."""
    entrada = calendario.resolver(año, carrera)
    if not entrada or entrada.get("meeting_key") is None:
        return {"error": f"No se encontró la carrera '{carrera}' en {año} en OpenF1."}
    return {"carrera": entrada["carrera"], "ronda": entrada["ronda"],
            "mensajes": openf1.mensajes_comisarios(entrada["meeting_key"], numero_auto)}


@mcp.tool()
@seguro
def openf1_sanciones_en_pista(año: Año,
                              carrera: Annotated[str | int | None, Field(
                                  description="Carrera: nombre en inglés, lugar, país, circuito o número de ronda. "
                                              "Sin carrera, trae las de toda la temporada.")] = None,
                              numero_auto: Annotated[int | None, Field(description="Si se indica, solo ese auto.")] = None):
    """[OpenF1] Sanciones anunciadas por Race Control durante las sesiones: tipo de sanción, vuelta,
    motivo y si se cumplió, más las banderas blanco y negro. Pueden estar antes que el documento
    de la FIA. No traen los artículos ni la explicación de los comisarios."""
    if carrera is None or not str(carrera).strip():
        return {"temporada": año, **openf1.sanciones_en_pista(año, numero_auto=numero_auto)}
    entrada = calendario.resolver(año, carrera)
    if not entrada or entrada.get("meeting_key") is None:
        return {"error": f"No se encontró la carrera '{carrera}' en {año} en OpenF1."}
    return {"carrera": entrada["carrera"], "ronda": entrada["ronda"],
            **openf1.sanciones_en_pista(año, entrada["meeting_key"], numero_auto)}


# ---------------------------------------------------------------- FIA

@mcp.tool()
@seguro
def fia_decisiones_de_piloto(año: Año, numero_auto: NumeroAuto,
                             carrera: Annotated[str | int | None, Field(
                                 description='Carrera: nombre en inglés, lugar, país, circuito o número de ronda. '
                                             'Sin carrera, trae las de toda la temporada (la primera vez puede tardar).')] = None,
                             nombre_piloto: Apellido = None, incluir_sin_sancion: SinSancion = False):
    """[FIA] Decisiones oficiales de los comisarios sobre un piloto, en una carrera o en toda la
    temporada (puede haber más de una): sesión, hecho, infracción, artículos citados, decisión,
    motivo, fecha y URL del documento oficial."""
    return [_compacto(r) for r in consultas.sanciones_piloto(año, carrera, numero_auto, nombre_piloto,
                                                            incluir_sin_sancion)]


@mcp.tool()
@seguro
def fia_decisiones_de_carrera(año: Año, carrera: Carrera, incluir_sin_sancion: SinSancion = False):
    """[FIA] Decisiones oficiales de los comisarios sobre todos los pilotos y equipos en una carrera.
    Excluye las vueltas borradas por límites de pista."""
    return [_compacto(r) for r in consultas.sanciones_carrera(año, carrera,
                                                             incluir_sin_sancion=incluir_sin_sancion)]


# ---------------------------------------------------------------- consultas conjuntas

def _compactar_conjunta(res: dict) -> dict:
    if "decisiones_fia" in res:
        res["decisiones_fia"] = [_compacto(r) for r in res["decisiones_fia"]]
    return res


@mcp.tool()
@seguro
def sanciones_de_piloto_completo(nombre_piloto: Annotated[str, Field(description='Nombre, apellido o abreviatura del piloto, ej. "Bearman".')],
                                 año: Año, carrera: Carrera, incluir_sin_sancion: SinSancion = False):
    """[OpenF1 + FIA] Todo sobre las sanciones de un piloto en una carrera, en una sola llamada:
    identifica al piloto (OpenF1), trae las decisiones oficiales ("decisiones_fia"), las sanciones
    anunciadas en pista ("sanciones_en_pista", con vuelta y si se cumplieron), las que no tienen
    documento de la FIA ("solo_en_race_control"), las banderas blanco y negro y la secuencia de
    Race Control. Es la primera opción cuando se conoce el piloto y la carrera."""
    return _compactar_conjunta(sanciones.sanciones_completas(nombre_piloto, año, carrera, incluir_sin_sancion))


@mcp.tool()
@seguro
def sanciones_de_carrera_completo(año: Año, carrera: Carrera, incluir_sin_sancion: SinSancion = False):
    """[OpenF1 + FIA] Todas las sanciones de una carrera, de las dos fuentes: decisiones oficiales
    ("decisiones_fia"), sanciones anunciadas en pista ("sanciones_en_pista", cada una con su
    "documento_fia" si lo tiene), las que no tienen documento ("solo_en_race_control") y las
    banderas blanco y negro. Es la primera opción para preguntas sobre una carrera entera."""
    return _compactar_conjunta(sanciones.sanciones_de_carrera_completas(año, carrera, incluir_sin_sancion))


@mcp.tool()
@seguro
def ultimas_sanciones_de_piloto_completo(nombre_piloto: Annotated[str, Field(description='Nombre, apellido o abreviatura del piloto, ej. "Hamilton".')]):
    """[OpenF1 + FIA] Todas las sanciones de un piloto en la última carrera en la que lo
    sancionaron, de las dos fuentes y con el mismo formato que sanciones_de_piloto_completo.
    Es la primera opción para "la última sanción de X"."""
    return _compactar_conjunta(sanciones.ultimas_sanciones_completas(nombre_piloto))
