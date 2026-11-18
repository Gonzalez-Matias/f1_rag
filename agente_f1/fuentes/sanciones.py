"""Consultas conjuntas de sanciones: unen las dos fuentes, que son complementarias.

  - OpenF1: quién es el piloto, y qué anunció Race Control durante la sesión: sanciones (con
    vuelta y si se cumplieron), banderas blanco y negro y la secuencia de la investigación.
  - FIA: la decisión oficial de los comisarios (hecho, artículos, sanción y motivo).

Cada fuente queda en su propio bloque, para que se vea de dónde sale cada dato. Cada sanción de
Race Control se cruza con su decisión de la FIA: las que no tienen documento (por ejemplo, porque
la FIA todavía no lo publicó) quedan en "solo_en_race_control". Si una fuente falla, se devuelve
la otra con un aviso.
"""
import re
from datetime import date, datetime

from . import calendario, openf1
from .fia import consultas


def clave_sancion(texto: str | None) -> str | None:
    """Tipo de sanción, comparable entre fuentes: '5 SECOND TIME PENALTY' -> '5s'."""
    t = (texto or "").upper()
    if re.search(r"STOP\s*(?:/|&|-|AND)?\s*GO", t):
        return "stop-go"
    if re.search(r"DRIVE[\s-]*THROUGH", t):
        return "drive-through"
    segundos = re.search(r"(\d+)[\s-]*SECOND", t)
    if segundos:
        return f"{segundos.group(1)}s"
    for clave in ("DISQUALIF", "REPRIMAND", "WARNING"):
        if clave in t:
            return clave.lower()
    return None


def _autos_de(decision: dict) -> set[int]:
    autos = {decision.get("numero_auto")}
    autos |= {int(a["Car"]) for a in decision.get("autos") or [] if str(a.get("Car", "")).strip().isdigit()}
    return autos


def cruzar(en_pista: list[dict], decisiones: list[dict]) -> list[str]:
    """Agrega a cada sanción de Race Control su documento de la FIA (`documento_fia`).

    Una decisión se usa una sola vez. Devuelve las referencias que quedaron sin documento.
    """
    libres = [d for d in reversed(decisiones) if not d.get("sin_sancion")]   # la FIA lista de nueva a vieja
    sin_documento = []
    for s in en_pista:
        par = next((d for d in libres if s["numero_auto"] in _autos_de(d)
                    and clave_sancion(d.get("decision")) == clave_sancion(s["sancion"])), None)
        s["documento_fia"] = par.get("documento") if par else None
        if par:
            libres.remove(par)
        else:
            sin_documento.append(s["referencia"])
    return sin_documento


def _decisiones(avisos: list, consulta, *args, **kwargs) -> list[dict]:
    try:
        return consulta(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - Race Control alcanza para saber qué se sancionó
        avisos.append(f"No se pudieron leer las decisiones de la FIA: {exc}")
        return []


def _race_control(avisos: list, año: int, entrada: dict | None, numero_auto: int | None = None) -> dict:
    """Mensajes, sanciones y banderas de Race Control de una carrera."""
    vacio = {"mensajes": [], "sanciones": [], "banderas": []}
    meeting_key = (entrada or {}).get("meeting_key")
    if meeting_key is None:
        avisos.append("OpenF1 no tiene esta carrera: no hay datos de Race Control.")
        return vacio
    try:
        crudos = openf1.get("race_control", meeting_key=meeting_key)
        return {"mensajes": openf1.mensajes_comisarios(meeting_key, numero_auto, crudos),
                **openf1.sanciones_en_pista(año, meeting_key, numero_auto, crudos)}
    except Exception as exc:  # noqa: BLE001 - la decisión oficial alcanza para explicar la sanción
        avisos.append(f"No se pudieron leer los mensajes de Race Control (OpenF1): {exc}")
        return vacio


def _problema_con_piloto(pilotos: list[dict], nombre: str) -> dict | None:
    if not pilotos:
        return {"error": f"No se encontró a '{nombre}' en OpenF1."}
    if len(pilotos) > 1:
        return {"error": f"'{nombre}' coincide con más de un piloto: indicá cuál.", "opciones": pilotos}
    return None


def sanciones_completas(nombre_piloto: str, año: int, carrera: str | int,
                        incluir_sin_sancion: bool = False) -> dict:
    """Un piloto en una carrera: decisiones de la FIA + todo lo de Race Control."""
    avisos = []
    entrada = calendario.resolver(año, carrera)
    meeting_key = (entrada or {}).get("meeting_key")

    pilotos = openf1.buscar_piloto(nombre_piloto, año, meeting_key)
    if not pilotos and meeting_key is not None:  # no corrió esa carrera: buscar en la temporada
        pilotos = openf1.buscar_piloto(nombre_piloto, año)
        if pilotos:
            avisos.append(f"{pilotos[0]['nombre']} no figura entre los pilotos de esa carrera en OpenF1.")
    problema = _problema_con_piloto(pilotos, nombre_piloto)
    if problema:
        return problema
    piloto = pilotos[0]

    decisiones = _decisiones(avisos, consultas.sanciones_piloto, año, entrada["carrera"] if entrada else carrera,
                             piloto["numero_auto"], piloto["nombre"], incluir_sin_sancion)
    rc = _race_control(avisos, año, entrada, piloto["numero_auto"])
    solo_rc = cruzar(rc["sanciones"], decisiones)
    return {
        "piloto": {**piloto, "fuente": "OpenF1"},
        "carrera": {"año": año, "nombre": decisiones[0]["carrera"] if decisiones else (entrada or {}).get("carrera", carrera),
                    "ronda": (entrada or {}).get("ronda")},
        "decisiones_fia": decisiones,
        "sanciones_en_pista": rc["sanciones"],
        "solo_en_race_control": solo_rc,
        "banderas_blanco_y_negro": rc["banderas"],
        "race_control_openf1": rc["mensajes"],
        "avisos": avisos,
    }


def sanciones_de_carrera_completas(año: int, carrera: str | int, incluir_sin_sancion: bool = False) -> dict:
    """Todas las sanciones de una carrera: decisiones de la FIA + anuncios de Race Control."""
    avisos = []
    entrada = calendario.resolver(año, carrera)
    decisiones = _decisiones(avisos, consultas.sanciones_carrera, año, entrada["carrera"] if entrada else carrera,
                             incluir_sin_sancion=incluir_sin_sancion)
    rc = _race_control(avisos, año, entrada)
    if not entrada and not decisiones:
        return {"error": f"No se encontró la carrera '{carrera}' en {año}.", "avisos": avisos}
    solo_rc = cruzar(rc["sanciones"], decisiones)
    return {
        "carrera": {"año": año, "nombre": (entrada or {}).get("carrera") or decisiones[0]["carrera"],
                    "ronda": (entrada or {}).get("ronda")},
        "decisiones_fia": decisiones,
        "sanciones_en_pista": rc["sanciones"],
        "solo_en_race_control": solo_rc,
        "banderas_blanco_y_negro": rc["banderas"],
        "avisos": avisos,
    }


def _dia_fia(fecha: str | None) -> date | None:
    try:
        return datetime.strptime((fecha or "").strip(), "%d %B %Y").date()
    except ValueError:
        return None


def ultimas_sanciones_completas(nombre_piloto: str, hoy: date | None = None) -> dict:
    """Todas las sanciones de un piloto en la última carrera en la que lo sancionaron.

    Busca la sanción más reciente en las dos fuentes (la FIA publica antes y después de las
    sesiones; Race Control anuncia durante) y devuelve la consulta completa de esa carrera.
    """
    año = (hoy or date.today()).year
    pilotos = []
    for temporada in (año, año - 1):
        pilotos = openf1.buscar_piloto(nombre_piloto, temporada)
        if pilotos:
            break
    problema = _problema_con_piloto(pilotos, nombre_piloto)
    if problema:
        return problema
    piloto, avisos = pilotos[0], []

    try:
        fia = consultas.ultima_sancion(piloto["numero_auto"], piloto["nombre"])
    except Exception as exc:  # noqa: BLE001
        fia = None
        avisos.append(f"No se pudieron leer las decisiones de la FIA: {exc}")

    en_pista, año_rc = None, None
    try:
        for y in (año, año - 1):
            propias = [s for s in openf1.sanciones_en_pista(y, numero_auto=piloto["numero_auto"])["sanciones"]
                       if s.get("piloto") in (None, piloto.get("abreviatura"))]  # los números cambian entre años
            if propias:
                en_pista, año_rc = propias[-1], y
                break
    except Exception as exc:  # noqa: BLE001
        avisos.append(f"No se pudieron leer los mensajes de Race Control (OpenF1): {exc}")

    dia_fia = _dia_fia((fia or {}).get("fecha"))
    dia_rc = date.fromisoformat(en_pista["fecha"][:10]) if en_pista and en_pista.get("fecha") else None
    if fia and (not en_pista or not dia_rc or (dia_fia and dia_fia >= dia_rc)):
        año_carrera, carrera, fuente = fia.get("año"), fia.get("carrera"), "FIA"
    elif en_pista:
        año_carrera, carrera, fuente = año_rc, en_pista.get("carrera"), "Race Control"
    else:
        return {"piloto": {**piloto, "fuente": "OpenF1"}, "resultado": "No se encontraron sanciones para ese piloto.",
                "avisos": avisos}

    res = sanciones_completas(piloto["nombre"], año_carrera, carrera)
    if "error" not in res:
        res["sancion_mas_reciente_en"] = fuente
        res["avisos"] = avisos + res["avisos"]
    return res
