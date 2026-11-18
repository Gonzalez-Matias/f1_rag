"""Informe: etiquetas de sanción, recortes y que la plantilla genere HTML y PDF (sin red)."""
import shutil
import subprocess

import pytest

from agente_f1.informe import render
from agente_f1.informe.datos import etiqueta_sancion, fecha_es, recortar, sesion_es


@pytest.mark.parametrize("decision, etiqueta, leve", [
    ("Drop of 10 grid positions for the next Race", "−10 grilla", False),
    ("5 second time penalty", "+5 s", False),
    ("Drive-through penalty", "Drive-through", False),
    ("Driver: Reprimand (Driving).", "Reprimenda", True),
    ("Competitor: Formal warning.", "Advertencia", True),
    ("The competitor (BWT Alpine F1 Team) is fined €100.", "€100", True),
    ("Disqualification from the Qualifying session", "Descalificado", False),
])
def test_etiqueta_sancion(decision, etiqueta, leve):
    e, _tipo, l = etiqueta_sancion(decision)
    assert (e, l) == (etiqueta, leve)


def test_textos_en_castellano():
    assert fecha_es("07 November 2026") == "07/11/2026"
    assert sesion_es("Free Practice 1") == "Práctica 1"
    assert sesion_es("Qualifying") == "Clasificación"


def test_recorta_en_fin_de_oracion_y_no_en_un_subinciso():
    texto = ("A speed limit of 80km/h will be imposed in the Pit Lane during the whole Competition. "
             "However, this limit may be amended by the Race Director. i. Any Competitor whose driver "
             "exceeds the limit during any free practice session will be fined for each km/h above it.")
    assert recortar(texto, 160).endswith("Race Director. […]")


def datos_de_ejemplo():
    ficha = {"auto": 87, "codigo": "BEA", "color": "9C9FA2", "piloto": "Oliver Bearman", "equipo": "Haas",
             "sesion": "Clasificación", "etiqueta": "Reprimenda", "tipo": "reprimendas", "leve": True,
             "motivo_corto": "retrocedió en el pit lane", "que_paso": "Puso marcha atrás en boxes.",
             "regla_simple": "No se puede retroceder con el motor.", "por_que": "Sin peligro: reprimenda.",
             "cita": "B1.6.3b", "reglamento": "2026 Formula 1 Regulations - Section B",
             "regla_original": "At no time may an F1 Car be reversed in the Pit Lane under its own power.",
             "doc": "41", "fecha": "07/11/2026", "url": "https://www.fia.com/x.pdf"}
    return {"gp": {"nombre": "Gran Premio de São Paulo 2026", "año": 2026, "circuito": "São Paulo",
                   "fechas": "6 al 8 de noviembre de 2026", "reglamento": "2026 Formula 1 Regulations - Section B"},
            "generado": "07/11/2026", "fichas": [ficha],
            "resumen": [("reprimendas", 1)], "glosario": [("Reprimenda", "Advertencia formal.")]}


def test_plantilla_html():
    html = render.html(datos_de_ejemplo())
    assert "Gran Premio de São Paulo 2026" in html and "Art. B1.6.3b" in html and "Oliver Bearman" in html
    assert '<style media="screen">' in html   # la vista de pantalla viaja en el mismo archivo


def test_genera_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(render.config, "ROOT", tmp_path)
    archivos = render.guardar(datos_de_ejemplo(), destino=tmp_path)
    assert "pdf" in archivos, archivos.get("aviso")
    pdf = tmp_path / archivos["pdf"]
    assert pdf.read_bytes().startswith(b"%PDF")
    # Usa las tipografías incluidas y no las de reemplazo (pdffonts viene con poppler,
    # el mismo paquete que pdftotext).
    if shutil.which("pdffonts"):
        fuentes = subprocess.run(["pdffonts", str(pdf)], capture_output=True, text=True).stdout
        assert "Barlow" in fuentes and "JetBrains" in fuentes


def test_el_informe_sale_aunque_falle_el_reglamento(monkeypatch):
    """Si la base del reglamento falla, la ficha se arma igual, sin el texto original del artículo."""
    from agente_f1.informe import datos

    def falla(*a, **k):
        raise RuntimeError("Error executing plan: Internal error: Error finding id")
    monkeypatch.setattr(datos.store, "motivo_no_disponible", lambda: None)
    monkeypatch.setattr(datos.store, "parrafo_exacto", falla)
    assert datos._texto_reglamento(2026, "B1.6.3b") is None


def test_ficha_de_una_sancion_sin_documento_fia(monkeypatch):
    from agente_f1.informe import datos, render

    sancion = {"referencia": "RC-3", "numero_auto": 81, "piloto": "PIA", "sancion": "10 SECOND STOP/GO PENALTY",
               "sesion": "Race", "vuelta": 16, "fecha": "2025-11-09T18:10:00+00:00"}
    monkeypatch.setattr(datos.openf1, "buscar_meeting", lambda año, carrera: {"meeting_key": 6, "meeting_name": "São Paulo Grand Prix"})
    monkeypatch.setattr(datos.openf1, "get", lambda *a, **k: [{"driver_number": 81, "name_acronym": "PIA", "full_name": "OSCAR PIASTRI"}])
    monkeypatch.setattr(datos.openf1, "sanciones_en_pista", lambda año, mk: {"sanciones": [sancion], "banderas": []})
    armado, avisos = datos.armar(2025, "São Paulo", [{"documento": "rc-3", "que_paso": "Chocó."}, {"documento": "RC-9"}])
    assert len(armado["fichas"]) == 1 and "RC-9" in avisos[0]
    ficha = armado["fichas"][0]
    assert (ficha["auto"], ficha["piloto"], ficha["etiqueta"], ficha["sesion"], ficha["fecha"]) == (
        81, "Oscar Piastri", "Stop & Go", "Carrera", "09/11/2025")
    html = render.html(armado)
    assert "Regla relacionada" not in html   # sin cita no se muestra
    assert "Sin documento de la FIA" in html and "vuelta 16" in html and "Race Control (OpenF1)" in html
