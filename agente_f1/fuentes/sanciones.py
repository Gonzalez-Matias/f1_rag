"""Consulta conjunta de sanciones: une las dos fuentes, que son complementarias.

  - OpenF1: quién es el piloto (nombre -> número de auto) y qué se anunció en vivo por
    Race Control (incidente anotado, investigado, sanción).
  - FIA: la decisión oficial de los comisarios (hecho, artículos, sanción y motivo).

Cada fuente queda en su propio bloque del resultado, para que se vea de dónde sale cada dato.
"""
from . import calendario, openf1
from .fia import consultas


def sanciones_completas(nombre_piloto: str, año: int, carrera: str | int,
                        incluir_sin_sancion: bool = False) -> dict:
    """Piloto (OpenF1) + decisiones oficiales (FIA) + mensajes de Race Control (OpenF1).

    Si OpenF1 no tiene la carrera, igual devuelve las decisiones de la FIA, con un aviso.
    """
    avisos = []
    entrada = calendario.resolver(año, carrera)
    meeting_key = (entrada or {}).get("meeting_key")

    pilotos = openf1.buscar_piloto(nombre_piloto, año, meeting_key)
    if not pilotos and meeting_key is not None:  # no corrió esa carrera: buscar en la temporada
        pilotos = openf1.buscar_piloto(nombre_piloto, año)
        if pilotos:
            avisos.append(f"{pilotos[0]['nombre']} no figura entre los pilotos de esa carrera en OpenF1.")
    if not pilotos:
        return {"error": f"No se encontró a '{nombre_piloto}' en la temporada {año} (OpenF1)."}
    if len(pilotos) > 1:
        return {"error": f"'{nombre_piloto}' coincide con más de un piloto: indicá cuál.", "opciones": pilotos}
    piloto = pilotos[0]

    decisiones = consultas.sanciones_piloto(año, entrada["carrera"] if entrada else carrera,
                                            piloto["numero_auto"], piloto["nombre"], incluir_sin_sancion)

    mensajes = []
    if meeting_key is None:
        avisos.append("OpenF1 no tiene esta carrera: no hay mensajes de Race Control.")
    else:
        try:
            mensajes = openf1.mensajes_comisarios(meeting_key, piloto["numero_auto"])
        except Exception as exc:  # noqa: BLE001 - la decisión oficial alcanza para explicar la sanción
            avisos.append(f"No se pudieron leer los mensajes de Race Control (OpenF1): {exc}")

    return {
        "piloto": {**piloto, "fuente": "OpenF1"},
        "carrera": {"año": año, "nombre": decisiones[0]["carrera"] if decisiones else (entrada or {}).get("carrera", carrera),
                    "ronda": (entrada or {}).get("ronda")},
        "decisiones_fia": decisiones,
        "race_control_openf1": mensajes,
        "avisos": avisos,
    }
