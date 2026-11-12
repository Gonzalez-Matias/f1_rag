"""Parser de decisiones FIA, con el texto de PDFs reales (tests/fixtures)."""
from pathlib import Path

from agente_f1.fuentes.fia.parser import parse

FIXTURES = Path(__file__).parent / "fixtures"


def leer(nombre: str) -> dict:
    return parse((FIXTURES / nombre).read_text(encoding="utf-8"))


def test_decision_2026_reprimenda():
    d = leer("decision_2026_bearman.txt")
    assert d["document"] == "41"
    assert d["date"] == "07 November 2026"
    assert d["car_number"] == 87
    assert d["driver_name"] == "Oliver Bearman"
    assert d["competitor"] == "TGR Haas F1 Team"
    assert d["session"] == "Qualifying"
    assert d["decision"].startswith("Driver: Reprimand (Driving).")
    assert d["articles"] == [{"article": "B1.6.3b", "regulation": "FIA F1 Regulations"}]
    assert len(d["stewards"]) == 4


def test_decision_2019_usa_offence_en_vez_de_infringement():
    d = leer("decision_2019_ferrari.txt")
    assert d["infringement"].startswith("Breach of Article 12.1.1.i")
    assert d["articles"] == [{"article": "12.1.1.i", "regulation": "FIA International Sporting Code"}]
    assert "€50,000" in d["decision"]


def test_vueltas_borradas_portada_y_tabla_de_autos():
    d = leer("decision_2026_vueltas_borradas.txt")
    assert d["to"] == "All Officials, All Teams"  # se salteó la portada
    assert d["car_number"] is None
    assert len(d["cars"]) == 8
    assert d["cars"][0] == {"No.": "1", "Turn": "4", "Car": "51", "Driver": "Rafael Camara",
                            "Competitor": "TGR Haas F1 Team", "Time of Day": "16:29:11", "Lap Time": "PIT"}
    assert [a["article"] for a in d["articles"]] == ["Appendix L Chapter IV Article 2 c)", "B1.8.6"]
