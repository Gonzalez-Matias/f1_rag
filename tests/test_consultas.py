"""Filtro por título de los documentos FIA (decide qué PDFs hace falta bajar)."""
from agente_f1.fuentes.fia import consultas
from agente_f1.fuentes.fia.consultas import autos_del_titulo, es_sancion


def test_es_sancion():
    assert es_sancion("Doc 41 - Infringement - Car 87 - Reversing in the Pit Lane")
    assert es_sancion("Offence - Ferrari (Fuel declaration)")              # formato 2019
    assert es_sancion("Decision - Car 88 (incident with car 99 in turn 12)")
    assert not es_sancion("Doc 31 - Summons - Car 11 - Alleged driving in an unsafe condition")
    assert not es_sancion("Doc 45 - Provisional Qualifying Classification")


def test_autos_del_titulo():
    assert autos_del_titulo("Doc 41 - Infringement - Car 87 - Reversing in the Pit Lane") == [87]
    # el auto sancionado es el primero; el "car 99" del paréntesis es el otro involucrado
    assert autos_del_titulo("Decision - Car 88 (incident with car 99 in turn 12)") == [88]
    assert autos_del_titulo("Offence - Ferrari (Fuel declaration)") == []
    assert autos_del_titulo("Doc 44 - Infringement - Qualifying Deleted Lap Times") == []


def test_titulos_corregidos_tambien_son_sanciones():
    for titulo, autos in [("Doc 68 - Corrected Race - Infringement - Car 81 - Causing a collision with Car 12 in Turn 1", [81]),
                          ("Doc 65 - Corrected - Sprint Infringement - Car 30 - Causing a Collision (With Car 87 at T4)", [30]),
                          ("Doc 45 - Corrected Infringement - Car 14 - Change to PU elements", [14]),
                          ("Doc 19 - (Infringement - Car 41 - Changes to PU Element (Corrected)", [41]),
                          ("Infringement (Corrected) - Car 18 - Causing a Collision", [18]),
                          ("Replacement for Document 47 - Offence - Car 44 - 2nd Practice Start", [44]),
                          ("Doc 12 - Infringment - Car 5 - Pit Lane Speeding", [5])]:
        assert es_sancion(titulo) and autos_del_titulo(titulo) == autos, titulo
    assert not es_sancion("Doc 31 - Summons - Car 11 - Alleged yellow flag infringement")


def test_la_version_corregida_reemplaza_a_la_original(monkeypatch):
    docs = [{"title": t} for t in ["Offence - Car 10 - Collision with car 14 (corrected)", "Doc 9 - Summons - Car 10 - Collision",
                                   "Offence - Car 10 - collision with car 14", "Offence - Car 10 - Pit lane speeding"]]
    monkeypatch.setattr(consultas.scraper, "documentos", lambda con, carrera: docs)
    assert [d["title"] for d in consultas._documentos_de_sancion(None, {})] == [
        "Offence - Car 10 - Collision with car 14 (corrected)", "Offence - Car 10 - Pit lane speeding"]
