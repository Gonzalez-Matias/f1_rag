"""Tool de recuperación sobre el reglamento (RAG por párrafos, similitud del coseno)."""
from datetime import datetime

from langchain_core.tools import tool

from ..rag import store
from ._util import seguro


@tool(parse_docstring=True)
@seguro
def buscar_en_reglamento(consulta: str, año: int, articulo: str | None = None,
                         fecha_decision: str | None = None) -> list | dict:
    """Busca párrafos del reglamento de F1 vigente en una temporada.

    Usala siempre que expliques una sanción: para traer el texto del artículo que
    citan los comisarios y las reglas relacionadas. Para citar usá la "cita"
    (ej. B1.6.3b) y el nombre del "reglamento" de cada párrafo.

    Args:
        consulta: qué buscar, en inglés (el reglamento está en inglés), ej. "reversing in the pit lane".
        año: temporada de la sanción; el reglamento cambia de un año a otro.
        articulo: artículo citado en la decisión, ej. "B1.6.3b" o "12.1.1.i". Si se indica,
            ese párrafo viene primero (coincidencia "exacta"); si no está en el corpus, el
            resultado trae un aviso y no tiene sentido volver a buscarlo.
        fecha_decision: fecha de la decisión de la FIA, ej. "12 September 2026". Sirve para
            avisar si la versión cargada del reglamento es posterior y puede haber cambiado.

    Returns:
        Párrafos con cita, título del artículo, nombre del reglamento, año, tipo de coincidencia
        ("exacta" o "similitud", con su valor de coseno) y texto.
    """
    no_disponible = store.motivo_no_disponible()
    if no_disponible:
        # Error de configuración: reintentar no sirve, y cada intento gasta una llamada al modelo.
        return {"error": f"Reglamento no disponible: {no_disponible}",
                "no_reintentar": True,
                "sugerencia": "Explicá la sanción con la decisión de la FIA y avisá que falta el texto del artículo."}
    try:
        res = store.buscar(consulta, año=año, cita=articulo)
    except Exception as exc:
        if not store.es_limite_diario(exc):
            raise
        return {"error": "Se agotó el cupo diario de búsquedas del reglamento (tier gratuito de embeddings).",
                "no_reintentar": True,
                "sugerencia": "Explicá con la decisión de la FIA y avisá que hoy no se pudo consultar el reglamento."}
    if not res:
        return {"error": f"No se encontró nada en el reglamento {año} para '{consulta}'."}
    aviso = _aviso_version(res, fecha_decision)
    return [aviso] + res if aviso else res


def _aviso_version(resultados: list[dict], fecha_decision: str | None) -> dict | None:
    """Si la versión del reglamento es posterior a la decisión, la numeración o el texto pueden diferir."""
    try:
        decision = datetime.strptime((fecha_decision or "").strip(), "%d %B %Y").date().isoformat()
    except ValueError:
        return None
    posteriores = sorted({r["vigente_desde"] for r in resultados
                          if r.get("vigente_desde") and r["vigente_desde"] > decision})
    if not posteriores:
        return None
    return {"aviso": f"La versión cargada del reglamento es del {posteriores[0]} y la decisión es del "
                     f"{decision}: el texto o la numeración pueden no coincidir con los vigentes ese día."}
