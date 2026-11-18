"""Datos del informe.

El modelo escribe solo los textos en lenguaje simple. Todo lo oficial (decisión,
artículo, fecha, link, texto del reglamento, colores de equipo) sale de las fuentes,
así el informe no depende de que el modelo copie bien un dato.
"""
import re
from datetime import datetime

from ..fuentes import openf1, sanciones
from ..fuentes.fia import consultas
from ..rag import store

SESIONES = {
    "free practice 1": "Práctica 1", "free practice 2": "Práctica 2", "free practice 3": "Práctica 3",
    "qualifying": "Clasificación", "sprint qualifying": "Clasificación sprint",
    "sprint shootout": "Clasificación sprint", "sprint": "Sprint", "race": "Carrera",
    "reconnaissance laps": "Vueltas de reconocimiento",
}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
GRIS = "8B8D98"
SINGULAR = {"reprimendas": "reprimenda", "advertencias": "advertencia", "multas": "multa",
            "descalificaciones": "descalificación", "vueltas borradas": "vuelta borrada", "otras": "otra"}


def sesion_es(sesion: str | None) -> str:
    return SESIONES.get((sesion or "").strip().lower(), sesion or "")


def etiqueta_sancion(decision: str | None) -> tuple[str, str, bool]:
    """Resumen corto de la sanción: (etiqueta, tipo para el resumen, es_leve).

    "Drop of 10 grid positions..." -> ("−10 grilla", "de grilla", False)
    """
    d = (decision or "").lower()
    reglas = [
        (r"stop\s*(?:/|&|-|and)?\s*go", lambda m: "Stop & Go", "de tiempo", False),
        (r"(\d+)[- ]second", lambda m: f"+{m.group(1)} s", "de tiempo", False),
        (r"drive[- ]through", lambda m: "Drive-through", "de tiempo", False),
        (r"(\d+) grid (?:position|place)", lambda m: f"−{m.group(1)} grilla", "de grilla", False),
        (r"start(?:s)? (?:the race )?from the pit lane|pit lane start", lambda m: "Largada en pits", "de grilla", False),
        (r"disqualif", lambda m: "Descalificado", "descalificaciones", False),
        (r"reprimand", lambda m: "Reprimenda", "reprimendas", True),
        (r"warning", lambda m: "Advertencia", "advertencias", True),
        (r"€\s?(\d(?:[\d.,]*\d)?)", lambda m: f"€{m.group(1)}", "multas", True),
        (r"deletion of the lap time", lambda m: "Vuelta borrada", "vueltas borradas", True),
        (r"no further action", lambda m: "Sin sanción", "sin sanción", True),
    ]
    for patron, fmt, tipo, leve in reglas:
        m = re.search(patron, d)
        if m:
            return fmt(m), tipo, leve
    return "Sanción", "otras", False


def fecha_es(fecha: str | None) -> str:
    """'07 November 2026' (formato de la FIA) -> '07/11/2026'."""
    try:
        return datetime.strptime((fecha or "").strip(), "%d %B %Y").strftime("%d/%m/%Y")
    except ValueError:
        return fecha or ""


def recortar(texto: str | None, maximo: int = 280) -> str | None:
    """Primeras oraciones del texto, hasta ~maximo caracteres."""
    if not texto or len(texto) <= maximo:
        return texto
    corte = texto[:maximo]
    # Fin de oración real: punto después de una palabra (no "i." ni "a." de un sub-inciso).
    fines = [m.end() for m in re.finditer(r"(?<=\w{3})[.;](?=\s)", corte)]
    fin = fines[-1] if fines and fines[-1] > maximo // 2 else None
    return (corte[:fin] if fin else corte.rsplit(" ", 1)[0]) + " […]"


def _fechas(meeting: dict | None) -> str:
    """'6 al 8 de noviembre de 2026' a partir del meeting de OpenF1."""
    try:
        fin = datetime.fromisoformat(meeting["date_end"])
        inicio = datetime.fromisoformat(meeting["date_start"])
        return f"{inicio.day} al {fin.day} de {MESES[fin.month - 1]} de {fin.year}"
    except (TypeError, KeyError, ValueError):
        return ""


def _pilotos(meeting: dict | None) -> dict[int, dict]:
    """Número de auto -> {abreviatura, color de equipo} para esa carrera (OpenF1)."""
    if not meeting:
        return {}
    try:
        return {d["driver_number"]: d for d in openf1.get("drivers", meeting_key=meeting["meeting_key"])}
    except Exception:  # sin OpenF1 el informe sale igual, con colores neutros
        return {}


def _texto_reglamento(año: int, cita: str | None) -> dict | None:
    """Párrafo exacto del reglamento para la cita (None si el RAG no está disponible)."""
    if not cita or store.motivo_no_disponible():
        return None
    try:
        return store.parrafo_exacto(cita, año)
    except Exception:  # noqa: BLE001 - sin el texto del artículo el informe sale igual, con la decisión
        return None


def _es_race_control(ficha: dict) -> bool:
    return str(ficha["documento"]).strip().upper().startswith("RC-")


def _sanciones_race_control(año: int, meeting: dict | None) -> dict[str, dict]:
    """Referencia ("RC-3") -> sanción anunciada por Race Control en esa carrera."""
    if not meeting:
        return {}
    try:
        return {s["referencia"]: s for s in openf1.sanciones_en_pista(año, meeting["meeting_key"])["sanciones"]}
    except Exception:  # noqa: BLE001 - las fichas con documento de la FIA salen igual
        return {}


def _ficha_race_control(f: dict, s: dict, pilotos: dict[int, dict], año: int) -> dict:
    """Ficha de una sanción anunciada en pista que no tiene documento de la FIA."""
    piloto = pilotos.get(s["numero_auto"]) or {}
    etiqueta, tipo, leve = etiqueta_sancion(s["sancion"])
    cita = f.get("cita")
    parrafo = _texto_reglamento(año, cita)
    try:
        fecha = datetime.fromisoformat(s["fecha"]).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        fecha = ""
    return {
        "auto": s["numero_auto"], "codigo": s.get("piloto") or piloto.get("name_acronym") or "",
        "color": piloto.get("team_colour") or GRIS,
        "piloto": (piloto.get("full_name") or s.get("piloto") or "").title(),
        "equipo": piloto.get("team_name") or "", "sesion": sesion_es(s.get("sesion")),
        "etiqueta": etiqueta, "tipo": tipo, "leve": leve,
        "motivo_corto": f.get("motivo_corto", ""), "que_paso": f.get("que_paso", ""),
        "regla_simple": f.get("regla_simple", ""), "por_que": f.get("por_que", ""),
        "cita": cita, "reglamento": parrafo["reglamento"] if parrafo else None,
        "regla_original": recortar(parrafo["texto"]) if parrafo else None,
        "doc": None, "fecha": fecha, "url": None, "vuelta": s.get("vuelta"),
    }


def armar(año: int, carrera: str, fichas_agente: list[dict], glosario: list[dict] | None = None,
          titulo: str | None = None) -> tuple[dict, list[str]]:
    """Datos para la plantilla y lista de advertencias (documentos que no se encontraron)."""
    meeting = openf1.buscar_meeting(año, carrera)
    pilotos = _pilotos(meeting)
    fichas, advertencias, reglamento_general, usadas = [], [], None, []
    numeros = [f["documento"] for f in fichas_agente if not _es_race_control(f)]
    oficiales = consultas.decisiones(año, carrera, numeros) if numeros else {}
    en_pista = None  # sanciones de Race Control, se piden solo si alguna ficha las usa

    for f in fichas_agente:
        if _es_race_control(f):
            if en_pista is None:
                en_pista = _sanciones_race_control(año, meeting)
            s = en_pista.get(str(f["documento"]).strip().upper())
            if not s:
                advertencias.append(f"No se encontró la sanción {f['documento']} en Race Control ({carrera} {año}).")
                continue
            fichas.append(_ficha_race_control(f, s, pilotos, año))
            continue
        rec = oficiales.get(str(f["documento"]))
        if not rec:
            advertencias.append(f"No se encontró el documento {f['documento']} de {carrera} {año}.")
            continue
        usadas.append(rec)
        articulos = [a["article"] for a in rec.get("articulos") or []]
        cita = f.get("cita") or (articulos[0] if articulos else None)
        parrafo = _texto_reglamento(año, cita)
        etiqueta, tipo, leve = etiqueta_sancion(rec.get("decision"))
        piloto = pilotos.get(rec.get("numero_auto")) or {}
        nombre = rec.get("piloto") or rec.get("equipo") or ""
        reglamento = parrafo["reglamento"] if parrafo else next(
            (a.get("regulation") for a in rec.get("articulos") or [] if a.get("regulation")), None)
        reglamento_general = reglamento_general or (parrafo or {}).get("reglamento")
        fichas.append({
            "auto": rec.get("numero_auto") or "–",
            "codigo": piloto.get("name_acronym") or (nombre.split()[-1][:3].upper() if nombre else ""),
            "color": piloto.get("team_colour") or GRIS,
            "piloto": nombre,
            "equipo": piloto.get("team_name") or rec.get("equipo") or "",
            "sesion": sesion_es(rec.get("sesion")),
            "etiqueta": etiqueta, "tipo": tipo, "leve": leve,
            "motivo_corto": f.get("motivo_corto", ""),
            "que_paso": f.get("que_paso", ""),
            "regla_simple": f.get("regla_simple", ""),
            "por_que": f.get("por_que", ""),
            "cita": cita,
            "reglamento": reglamento,
            "regla_original": recortar(parrafo["texto"]) if parrafo else None,
            "doc": rec.get("documento"),
            "fecha": fecha_es(rec.get("fecha")),
            "url": rec.get("url"),
            "vuelta": None,
        })

    # Las decisiones de la FIA que Race Control anunció en pista muestran en qué vuelta fue
    if usadas:
        anuncios = [dict(s) for s in (en_pista if en_pista is not None else _sanciones_race_control(año, meeting)).values()]
        sanciones.cruzar(anuncios, usadas)
        vueltas = {s["documento_fia"]: s.get("vuelta") for s in anuncios if s["documento_fia"]}
        for ficha in fichas:
            if ficha["doc"] in vueltas:
                ficha["vuelta"] = vueltas[ficha["doc"]]

    conteo: dict[str, int] = {}
    for f in fichas:
        conteo[f["tipo"]] = conteo.get(f["tipo"], 0) + 1
    datos = {
        "gp": {
            "nombre": titulo or f"{(meeting or {}).get('meeting_name') or carrera} {año}",
            "año": año,
            "circuito": (meeting or {}).get("location", ""),
            "fechas": _fechas(meeting),
            "reglamento": reglamento_general,
            "usa_race_control": any(not f["url"] for f in fichas),
        },
        "generado": datetime.now().strftime("%d/%m/%Y"),
        "fichas": fichas,
        "resumen": [(SINGULAR.get(t, t) if n == 1 else t, n)
                    for t, n in sorted(conteo.items(), key=lambda kv: -kv[1])[:4]],
        "glosario": [(g["termino"], g["definicion"]) for g in glosario or []],
    }
    return datos, advertencias
