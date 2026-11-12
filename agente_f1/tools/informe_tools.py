"""Tool que genera el resultado tangible: el informe de sanciones en PDF y HTML."""
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ..informe import datos as informe_datos
from ..informe import render
from ._util import seguro


class Ficha(BaseModel):
    """Textos en lenguaje simple de una sanción. Los datos oficiales los completa la tool."""
    documento: str = Field(description='Número de documento de la decisión de la FIA, ej. "41".')
    motivo_corto: str = Field(description='Qué pasó en 3 a 6 palabras, ej. "retrocedió en el pit lane".')
    que_paso: str = Field(description="Qué pasó, en una o dos oraciones simples.")
    regla_simple: str = Field(description="Qué dice la regla aplicada, explicada con tus palabras.")
    por_que: str = Field(description="Por qué correspondía esta sanción y no otra.")
    cita: str | None = Field(default=None, description='Artículo a mostrar, ej. "B1.6.3b". Por defecto, el primero que cita la decisión.')


class Termino(BaseModel):
    termino: str = Field(description='Término técnico usado en el informe, ej. "Reprimenda".')
    definicion: str = Field(description="Definición en una oración, para alguien que empieza a seguir la F1.")


@tool(parse_docstring=True)
@seguro
def generar_informe(año: int, carrera: str, fichas: list[Ficha], glosario: list[Termino] | None = None,
                    titulo: str | None = None) -> dict:
    """Genera el informe de sanciones (PDF y HTML) con una ficha por sanción.

    Usala cuando el usuario pida un informe, después de tener las decisiones y los
    artículos del reglamento. Vos escribís solo los textos en simple de cada ficha;
    la decisión, el artículo, la fecha, el link y el texto del reglamento los completa
    la tool desde las fuentes oficiales.

    Args:
        año: temporada.
        carrera: nombre de la carrera, ej. "São Paulo Grand Prix".
        fichas: una por sanción, en el orden en que deben aparecer.
        glosario: términos técnicos que aparecen en las fichas, con su definición simple.
        titulo: título del informe en castellano, ej. "Gran Premio de São Paulo 2026".

    Returns:
        Rutas de los archivos generados y advertencias si algún documento no se encontró.
    """
    datos, advertencias = informe_datos.armar(
        año, carrera, [f.model_dump() if isinstance(f, BaseModel) else f for f in fichas],
        [g.model_dump() if isinstance(g, BaseModel) else g for g in glosario or []], titulo)
    if not datos["fichas"]:
        return {"error": "No se pudo armar ninguna ficha. " + " ".join(advertencias)}
    archivos = render.guardar(datos)
    return {"archivos": archivos, "fichas": len(datos["fichas"]), "advertencias": advertencias}
