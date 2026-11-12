"""Filtro por título de los documentos FIA (decide qué PDFs hace falta bajar)."""
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
