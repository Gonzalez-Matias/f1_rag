"""Calendario (rondas y alias de carrera) y consulta conjunta OpenF1 + FIA. Sin red."""
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
                        lambda meeting_key, auto=None: [{"fecha": "x", "mensaje": f"CAR {auto} (BEA) - meeting {meeting_key}"}])
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
