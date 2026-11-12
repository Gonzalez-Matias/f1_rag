"""Corpus del RAG: cada formato de documento se parte bien en párrafos citables."""
from pathlib import Path

import pytest

from agente_f1.rag.ingest import APENDICE_L, F1, ISC, parrafos, parrafos_glosario
from agente_f1.rag.store import partir_cita

FIX = Path(__file__).parent / "fixtures"
GLOSARIO = Path(__file__).parent.parent / "data" / "reglamento" / "glosario.md"


def por_cita(docs):
    return {d.metadata["cita"]: d for d in docs}


def test_reglamento_2025_cita_como_el_documento():
    docs = por_cita(parrafos((FIX / "reglamento_2025_extracto.txt").read_text(), {"año": 2025}, formato=F1))
    assert "48.1 a)" in docs  # así lo citan las decisiones de 2025
    assert docs["48.1 a)"].metadata["articulo"] == "48.1" and docs["48.1 a)"].metadata["inciso"] == "a"
    assert docs["48.1 a)"].metadata["titulo"] == "False start"  # título del capítulo "48) FALSE START"


def test_codigo_deportivo_columna_en_ingles():
    docs = por_cita(parrafos((FIX / "codigo_deportivo_2026_extracto.txt").read_text(), {"año": 2026}, formato=ISC))
    i = docs["12.2.1.i"]
    assert i.metadata["articulo"] == "12.2.1" and i.metadata["inciso"] == "i"
    assert "Failure to follow the instructions of the relevant officials" in i.page_content
    assert not any("respect" in d.page_content and "infraction" in d.page_content for d in docs.values())  # sin francés


def test_apendice_l_capitulo_iv():
    docs = por_cita(parrafos((FIX / "apendice_l_2026_cap4.txt").read_text(), {"año": 2026}, formato=APENDICE_L))
    d = docs["Ap. L, cap. IV, art. 2 d)"]
    assert d.metadata["articulo"] == "L-IV-2" and d.metadata["inciso"] == "d"
    assert "Causing a collision" in d.page_content


@pytest.mark.parametrize("cita, esperado", [
    ("Appendix L Chapter IV Article 2 d)", ("L-IV-2", "d")),  # como lo extrae el parser de decisiones
    ("Ap. L, cap. IV, art. 2 d)", ("L-IV-2", "d")),            # como lo muestra el corpus
    ("48.1 a)", ("48.1", "a")),
    ("12.2.1.i", ("12.2.1", "i")),
])
def test_partir_cita_entiende_todos_los_formatos(cita, esperado):
    assert partir_cita(cita) == esperado


def test_glosario_propio():
    docs = parrafos_glosario(GLOSARIO.read_text(encoding="utf-8"), "glosario.md")
    terminos = {d.metadata["cita"] for d in docs}
    assert len(docs) >= 30
    assert "Reprimenda (Reprimand)" in terminos
    assert all(d.metadata["año"] == 0 for d in docs)  # vale para todas las temporadas
