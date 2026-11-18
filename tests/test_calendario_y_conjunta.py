"""Calendario (rondas y alias de carrera) y consulta conjunta OpenF1 + FIA. Sin red."""
from datetime import date

import pytest

from agente_f1.fuentes import calendario, openf1, sanciones
from agente_f1.fuentes.fia import consultas

MEETINGS = [
    {"meeting_key": 1, "meeting_name": "Pre-Season Testing", "location": "Sakhir", "country_name": "Bahrain",
     "circuit_short_name": "Sakhir", "date_start": "2025-02-26T07:00:00", "date_end": "2025-02-28T16:00:00"},
    {"meeting_key": 2, "meeting_name": "Australian Grand Prix", "location": "Melbourne", "country_name": "Australia",
     "circuit_short_name": "Melbourne", "date_start": "2025-03-14T01:30:00", "date_end": "2025-03-16T06:00:00"},
    {"meeting_key": 4, "meeting_name": "Italian Grand Prix", "location": "Monza", "country_name": "Italy",
     "circuit_short_name": "Monza", "date_start": "2025-09-05T11:30:00", "date_end": "2025-09-07T15:00:00"},
    {"meeting_key": 3, "meeting_name": "Emilia Romagna Grand Prix", "location": "Imola", "country_name": "Italy",
     "circuit_short_name": "Imola", "date_start": "2025-05-16T11:30:00", "date_end": "2025-05-18T15:00:00"},
    {"meeting_key": 5, "meeting_name": "Bahrain Grand Prix", "location": "Sakhir", "country_name": "Bahrain",
     "circuit_short_name": "Sakhir", "date_start": "2025-04-11T11:30:00", "date_end": "2025-04-13T17:00:00",
     "is_cancelled": True},
    {"meeting_key": 6, "meeting_name": "São Paulo Grand Prix", "location": "São Paulo", "country_name": "Brazil",
     "circuit_short_name": "Interlagos", "date_start": "2025-11-07T14:30:00", "date_end": "2025-11-09T19:00:00"},
]
# El índice de la FIA va de la carrera más nueva a la más vieja, e incluye los tests.
FIA = [{"event_id": n, "year": 2025, "name": nombre, "position": n} for n, nombre in enumerate(
    ["São Paulo Grand Prix", "Italian Grand Prix", "Emilia Romagna Grand Prix", "Australian Grand Prix",
     "Bahrain Tests Season 2025"])]


@pytest.fixture
def fuentes(monkeypatch):
    monkeypatch.setattr(openf1, "get", lambda endpoint, *a, **k: MEETINGS if endpoint == "meetings" else [])
    monkeypatch.setattr(consultas.scraper, "carreras", lambda con, año, **k: FIA)


def test_calendario_numera_solo_las_carreras(fuentes):
    cal = calendario.calendario(2025)
    # en orden por fecha, sin el test de pretemporada ni la carrera cancelada
    assert [(e["ronda"], e["carrera"]) for e in cal] == [
        (1, "Australian Grand Prix"), (2, "Emilia Romagna Grand Prix"),
        (3, "Italian Grand Prix"), (4, "São Paulo Grand Prix")]
    assert cal[0]["fecha_inicio"] == "2025-03-14" and cal[0]["fuente"] == "OpenF1"


@pytest.mark.parametrize("texto, ronda", [("5", 5), (5, 5), ("ronda 5", 5), ("Round 12", 12),
                                          ("Monza", None), ("70th Anniversary", None)])
def test_ronda_de(texto, ronda):
    assert calendario.ronda_de(texto) == ronda


@pytest.mark.parametrize("texto, esperada", [
    (3, "Italian Grand Prix"),                 # número de ronda
    ("Monza", "Italian Grand Prix"),           # lugar
    ("Brazil", "São Paulo Grand Prix"),        # país
    ("interlagos", "São Paulo Grand Prix"),    # circuito
    ("Sao Paulo", "São Paulo Grand Prix"),     # parte del nombre, sin acentos
])
def test_carrera_fia_por_ronda_o_alias(fuentes, texto, esperada):
    assert consultas._buscar_carrera(None, 2025, texto)["name"] == esperada


def test_carrera_ambigua_o_inexistente(fuentes):
    with pytest.raises(ValueError, match="más de una carrera"):
        consultas._buscar_carrera(None, 2025, "Italy")       # Imola y Monza
    with pytest.raises(ValueError, match="no existe la ronda 9"):
        consultas._buscar_carrera(None, 2025, "9")
    with pytest.raises(ValueError, match="Opciones"):
        consultas._buscar_carrera(None, 2025, "Marte")


def test_sin_openf1_el_calendario_sale_del_indice_fia(monkeypatch, fuentes):
    monkeypatch.setattr(openf1, "get", lambda *a, **k: [])   # temporada anterior a 2023
    monkeypatch.setattr("agente_f1.fuentes.fia.cache.conectar", lambda: None)
    cal = calendario.calendario(2025)
    assert [e["carrera"] for e in cal][0] == "Australian Grand Prix" and cal[0]["fuente"] == "FIA"
    assert all("Tests" not in e["carrera"] for e in cal)


# ---------------------------------------------------------------- consulta conjunta

BEARMAN = {"numero_auto": 87, "nombre": "Oliver BEARMAN", "abreviatura": "BEA", "equipo": "Haas F1 Team"}


@pytest.fixture
def conjunta(monkeypatch, fuentes):
    llamadas = {}

    def sanciones_piloto(año, carrera, numero_auto, nombre_piloto=None, incluir_sin_sancion=False):
        llamadas["fia"] = (año, carrera, numero_auto, nombre_piloto, incluir_sin_sancion)
        return [{"carrera": "São Paulo Grand Prix", "documento": "41", "decision": "Reprimand"}]

    monkeypatch.setattr(openf1, "buscar_piloto", lambda nombre, año, meeting_key=None: [BEARMAN])
    monkeypatch.setattr(openf1, "mensajes_comisarios",
                        lambda meeting_key, auto=None, mensajes=None: [{"fecha": "x", "mensaje": f"CAR {auto} (BEA) - meeting {meeting_key}"}])
    monkeypatch.setattr(consultas, "sanciones_piloto", sanciones_piloto)
    return llamadas


def test_conjunta_une_las_dos_fuentes(conjunta):
    res = sanciones.sanciones_completas("Bearman", 2025, "Brazil", incluir_sin_sancion=True)
    # la FIA recibe el nombre oficial y el número de auto que resolvió OpenF1
    assert conjunta["fia"] == (2025, "São Paulo Grand Prix", 87, "Oliver BEARMAN", True)
    assert res["piloto"]["numero_auto"] == 87 and res["piloto"]["fuente"] == "OpenF1"
    assert res["carrera"] == {"año": 2025, "nombre": "São Paulo Grand Prix", "ronda": 4}
    assert res["decisiones_fia"][0]["documento"] == "41"
    assert "meeting 6" in res["race_control_openf1"][0]["mensaje"]
    assert res["avisos"] == []


def test_conjunta_piloto_ambiguo_o_inexistente(conjunta, monkeypatch):
    monkeypatch.setattr(openf1, "buscar_piloto", lambda *a, **k: [BEARMAN, {**BEARMAN, "numero_auto": 5}])
    res = sanciones.sanciones_completas("o", 2025, "Brazil")
    assert "más de un piloto" in res["error"] and len(res["opciones"]) == 2
    monkeypatch.setattr(openf1, "buscar_piloto", lambda *a, **k: [])
    assert "No se encontró" in sanciones.sanciones_completas("Nadie", 2025, "Brazil")["error"]
    assert "fia" not in conjunta   # sin piloto no se consulta la FIA


def test_conjunta_sin_race_control_devuelve_igual_la_decision(conjunta, monkeypatch):
    def falla(*a, **k):
        raise TimeoutError("OpenF1 no responde")
    monkeypatch.setattr(openf1, "mensajes_comisarios", falla)
    res = sanciones.sanciones_completas("Bearman", 2025, "Interlagos")
    assert res["decisiones_fia"] and res["race_control_openf1"] == []
    assert "Race Control" in res["avisos"][0]


def test_sanciones_de_piloto_en_toda_la_temporada(monkeypatch, fuentes):
    monkeypatch.setattr(consultas, "conectar", lambda: None)
    monkeypatch.setattr(consultas, "auto_actualizar", lambda con: None)
    monkeypatch.setattr(consultas, "_sanciones_del_piloto",
                        lambda con, carrera, auto, nombre, sin: [] if "Tests" in carrera["name"] or "Emilia" in carrera["name"]
                        else [{"carrera": carrera["name"], "documento": "9"}, {"carrera": carrera["name"], "documento": "3"}])
    res = consultas.sanciones_piloto(2025, None, 87)
    # orden cronológico: primera carrera primero y, dentro de cada una, el documento más viejo primero
    assert [(r["carrera"], r["documento"]) for r in res] == [
        ("Australian Grand Prix", "3"), ("Australian Grand Prix", "9"),
        ("Italian Grand Prix", "3"), ("Italian Grand Prix", "9"),
        ("São Paulo Grand Prix", "3"), ("São Paulo Grand Prix", "9")]
    assert len(consultas.sanciones_piloto(2025, "Monza", 87)) == 2


# ---------------------------------------------------------------- sanciones de Race Control

def _rc(mensaje, fecha, vuelta=None, sesion=100, meeting=6):
    return {"message": mensaje, "date": fecha, "lap_number": vuelta, "session_key": sesion, "meeting_key": meeting}


MENSAJES_RC = [
    _rc("FIA STEWARDS: REPRIMAND (DRIVING) FOR CAR 87 (BEA) - REVERSING IN THE PIT LANE (14:59:59)", "2025-11-08T18:17:00", sesion=99),
    _rc("FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 23 (ALB) - REJOINING UNSAFELY (14:50:05)", "2025-11-09T18:00:00", 42),
    _rc("FIA STEWARDS: INCIDENT INVOLVING CAR 23 (ALB) UNDER INVESTIGATION - UNSAFE (14:50:05)", "2025-11-09T17:58:00", 40),
    _rc("FIA STEWARDS: PENALTY SERVED - 5 SECOND TIME PENALTY FOR CAR 23 (ALB) (14:50:05)", "2025-11-09T18:04:00", 46),
    _rc("FIA STEWARDS: 10 SECOND STOP/GO PENALTY FOR CAR 81 (PIA) - CAUSING A COLLISION", "2025-11-09T18:10:00", 50),
    _rc("BLACK AND WHITE FLAG FOR CAR 51 (CAM) - TRACK LIMITS", "2025-11-09T18:19:00", 58),
    _rc("CAR 4 (NOR) TIME 1:12.345 DELETED - TRACK LIMITS AT TURN 4", "2025-11-09T18:20:00", 59),
]


@pytest.fixture
def race_control(monkeypatch, fuentes):
    def get(endpoint, filtros="", _timeout=20, **params):
        return {"meetings": MEETINGS, "race_control": MENSAJES_RC,
                "sessions": [{"session_key": 99, "session_name": "Qualifying"}, {"session_key": 100, "session_name": "Race"}]}.get(endpoint, [])
    monkeypatch.setattr(openf1, "get", get)


def test_lee_las_sanciones_de_race_control(race_control):
    res = openf1.sanciones_en_pista(2025, 6)
    assert [(s["referencia"], s["numero_auto"], s["sancion"], s["sesion"]) for s in res["sanciones"]] == [
        ("RC-1", 87, "REPRIMAND (DRIVING)", "Qualifying"),
        ("RC-2", 23, "5 SECOND TIME PENALTY", "Race"),
        ("RC-3", 81, "10 SECOND STOP/GO PENALTY", "Race")]
    alb = res["sanciones"][1]
    assert alb["motivo"] == "REJOINING UNSAFELY" and alb["vuelta"] == 42 and alb["cumplida"] and alb["vuelta_cumplida"] == 46
    assert not res["sanciones"][2]["cumplida"]
    assert [(b["numero_auto"], b["motivo"]) for b in res["banderas"]] == [(51, "TRACK LIMITS")]
    # la referencia no cambia al filtrar por auto
    assert [s["referencia"] for s in openf1.sanciones_en_pista(2025, 6, 81)["sanciones"]] == ["RC-3"]


@pytest.mark.parametrize("texto, clave", [
    ("5 SECOND TIME PENALTY", "5s"), ("Driver: 5 second time penalty", "5s"), ("10 SECOND STOP/GO PENALTY", "stop-go"),
    ("10 second stop and go penalty", "stop-go"), ("DRIVE THROUGH PENALTY", "drive-through"),
    ("Drive-through penalty", "drive-through"), ("Reprimand (Driving)", "reprimand"), ("€5000 fine", None)])
def test_clave_de_sancion(texto, clave):
    assert sanciones.clave_sancion(texto) == clave


def test_cruza_cada_sancion_con_una_sola_decision():
    en_pista = [{"referencia": f"RC-{i}", "numero_auto": 30, "sancion": t}
                for i, t in enumerate(["5 SECOND TIME PENALTY", "10 SECOND TIME PENALTY", "5 SECOND TIME PENALTY"], 1)]
    decisiones = [{"documento": "9", "numero_auto": 30, "decision": "10 second time penalty"},
                  {"documento": "7", "numero_auto": 30, "decision": "5 second time penalty"},
                  {"documento": "8", "numero_auto": 12, "decision": "5 second time penalty"}]
    assert sanciones.cruzar(en_pista, decisiones) == ["RC-3"]
    assert [s["documento_fia"] for s in en_pista] == ["7", "9", None]


def test_carrera_completa_marca_lo_que_solo_esta_en_race_control(race_control, monkeypatch):
    monkeypatch.setattr(consultas, "sanciones_carrera", lambda año, carrera, incluir_sin_sancion=False: [
        {"carrera": carrera, "documento": "41", "numero_auto": 87, "decision": "Reprimand (Driving)"},
        {"carrera": carrera, "documento": "60", "numero_auto": 23, "decision": "5 second time penalty"}])
    res = sanciones.sanciones_de_carrera_completas(2025, "Brazil")
    assert res["solo_en_race_control"] == ["RC-3"] and res["avisos"] == []
    assert [s["documento_fia"] for s in res["sanciones_en_pista"]] == ["41", "60", None]


def test_carrera_sin_documentos_fia_devuelve_race_control(race_control, monkeypatch):
    def falla(*a, **k):
        raise ValueError("todavía no tiene documentos de la FIA")
    monkeypatch.setattr(consultas, "sanciones_carrera", falla)
    res = sanciones.sanciones_de_carrera_completas(2025, "Brazil")
    assert res["decisiones_fia"] == [] and res["solo_en_race_control"] == ["RC-1", "RC-2", "RC-3"]
    assert "FIA" in res["avisos"][0]


def _ultimas(monkeypatch, fia, en_pista):
    pedidas = []
    monkeypatch.setattr(openf1, "buscar_piloto", lambda nombre, año, meeting_key=None: [BEARMAN])
    monkeypatch.setattr(consultas, "ultima_sancion", lambda auto, nombre=None: fia)
    monkeypatch.setattr(openf1, "sanciones_en_pista", lambda año, meeting_key=None, numero_auto=None, mensajes=None:
                        {"sanciones": en_pista if año == 2026 else [], "banderas": []})

    def completas(nombre, año, carrera, incluir_sin_sancion=False):
        pedidas.append((año, carrera))
        return {"decisiones_fia": [], "avisos": []}
    monkeypatch.setattr(sanciones, "sanciones_completas", completas)
    return sanciones.ultimas_sanciones_completas("Bearman", date(2026, 11, 18)), pedidas


def test_ultimas_sanciones_traen_toda_la_ultima_carrera(monkeypatch):
    fia = {"fecha": "08 November 2026", "decision": "5 second time penalty", "año": 2026, "carrera": "São Paulo Grand Prix"}
    vieja = {"fecha": "2026-11-07T18:17:00", "sancion": "REPRIMAND (DRIVING)", "piloto": "BEA", "numero_auto": 87,
             "carrera": "São Paulo Grand Prix"}
    res, pedidas = _ultimas(monkeypatch, fia, [vieja])
    assert pedidas == [(2026, "São Paulo Grand Prix")] and res["sancion_mas_reciente_en"] == "FIA"

    # una sanción en pista posterior, todavía sin documento, define la última carrera
    nueva = {**vieja, "fecha": "2026-11-22T04:00:00", "sancion": "5 SECOND TIME PENALTY", "carrera": "Las Vegas Grand Prix"}
    res, pedidas = _ultimas(monkeypatch, fia, [vieja, nueva])
    assert pedidas == [(2026, "Las Vegas Grand Prix")] and res["sancion_mas_reciente_en"] == "Race Control"

    # el mismo número en manos de otro piloto no cuenta
    res, pedidas = _ultimas(monkeypatch, None, [{**nueva, "piloto": "XXX"}])
    assert pedidas == [] and "No se encontraron" in res["resultado"]
