"""Datos del informe.

El modelo escribe solo los textos en lenguaje simple. Todo lo oficial (decisión,
artículo, fecha, link, texto del reglamento, colores de equipo) sale de las fuentes,
así el informe no depende de que el modelo copie bien un dato.
"""
import re
from datetime import datetime

from ..fuentes import openf1
from ..fuentes.fia import consultas
from ..rag import store

SESIONES = {
    "free practice 1": "Práctica 1", "free practice 2": "Práctica 2", "free practice 3": "Práctica 3",
    "qualifying": "Clasificación", "sprint qualifying": "Clasificación sprint",
    "sprint shootout": "Clasificación sprint", "sprint": "Sprint", "race": "Carrera",
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
        (r"(\d+)[- ]second", lambda m: f"+{m.group(1)} s", "de tiempo", False),
        (r"drive[- ]through", lambda m: "Drive-through", "de tiempo", False),
        (r"stop[- ]and[- ]go", lambda m: "Stop & Go", "de tiempo", False),
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
    exactos = [r for r in store.buscar(cita, año=año, cita=cita, k=1, min_similitud=1.1)
               if r.get("coincidencia") == "exacta"]
    return exactos[0] if exactos else None


def armar(año: int, carrera: str, fichas_agente: list[dict], glosario: list[dict] | None = None,
          titulo: str | None = None) -> tuple[dict, list[str]]:
    """Datos para la plantilla y lista de advertencias (documentos que no se encontraron)."""
    meeting = openf1.buscar_meeting(año, carrera)
    pilotos = _pilotos(meeting)
    fichas, advertencias, reglamento_general = [], [], None

    for f in fichas_agente:
        rec = consultas.decision(año, carrera, f["documento"])
        if not rec:
            advertencias.append(f"No se encontró el documento {f['documento']} de {carrera} {año}.")
            continue
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
        })

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
        },
        "generado": datetime.now().strftime("%d/%m/%Y"),
        "sanciones": fichas,
        "fichas": fichas,
        "resumen": [(SINGULAR.get(t, t) if n == 1 else t, n)
                    for t, n in sorted(conteo.items(), key=lambda kv: -kv[1])[:4]],
        "glosario": [(g["termino"], g["definicion"]) for g in glosario or []],
    }
    return datos, advertencias
