"""RAG del reglamento: párrafos y búsqueda por similitud del coseno.

Usa embeddings falsos (deterministas) para no depender de la API de Google.
"""
from pathlib import Path

import pytest
from langchain_chroma import Chroma
from langchain_core.embeddings import DeterministicFakeEmbedding

from agente_f1.rag import store
from agente_f1.rag.ingest import parrafos

EXTRACTO = (Path(__file__).parent / "fixtures" / "reglamento_2026_b_extracto.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def docs():
    return parrafos(EXTRACTO, {"fuente": "2026_b.pdf", "año": 2026})


def test_un_parrafo_por_inciso(docs):
    b = next(d for d in docs if d.metadata["cita"] == "B1.6.3b")
    assert b.metadata["articulo"] == "B1.6.3" and b.metadata["inciso"] == "b"
    assert b.page_content == ("B1.6.3b · Driving in the Pit Entry Road, Pit Lane And Pit Exit Road\n"
                              "At no time may an F1 Car be reversed in the Pit Lane under its own power.")


def test_sin_encabezados_ni_pies_de_pagina(docs):
    assert not any("Fédération" in d.page_content or "SECTION B" in d.page_content for d in docs)


@pytest.mark.parametrize("cita, esperado", [
    ("B1.6.3b", ("B1.6.3", "b")),
    ("12.1.1.i", ("12.1.1", "i")),
    ("B1.6.3", ("B1.6.3", "")),
])
def test_partir_cita(cita, esperado):
    assert store.partir_cita(cita) == esperado


@pytest.fixture
def base(docs, tmp_path, monkeypatch):
    vs = Chroma(collection_name="prueba", embedding_function=DeterministicFakeEmbedding(size=256),
                persist_directory=str(tmp_path), collection_metadata={"hnsw:space": "cosine"})
    vs.add_documents(docs)
    monkeypatch.setattr(store, "_store", vs)
    return vs


def test_coleccion_en_espacio_coseno(base):
    assert base._collection.metadata["hnsw:space"] == "cosine"


def test_cita_exacta_primero_y_luego_similitud(base, docs):
    otro = next(d for d in docs if d.metadata["cita"] == "B1.6.3a")
    res = store.buscar(otro.page_content, año=2026, cita="B1.6.3b", min_similitud=0.5)
    assert (res[0]["cita"], res[0]["coincidencia"]) == ("B1.6.3b", "exacta")
    # el mismo texto que un párrafo guardado tiene similitud del coseno 1
    assert res[1]["cita"] == "B1.6.3a" and res[1]["similitud"] == pytest.approx(1.0, abs=1e-3)


def test_busqueda_por_metadatos(base):
    # inciso puntual
    res = store.buscar("x", año=2026, cita="B1.6.3b", min_similitud=1.1)  # umbral imposible: solo exactos
    assert [r["cita"] for r in res] == ["B1.6.3b"]
    # artículo completo: todos sus incisos, en orden
    res = store.buscar("x", año=2026, cita="B1.6.3", min_similitud=1.1)
    assert [r["cita"] for r in res] == ["B1.6.3a", "B1.6.3b", "B1.6.3c", "B1.6.3d", "B1.6.3e"]


def test_filtra_por_año(base):
    res = store.buscar("pit lane", año=1999, cita="B1.6.3b")
    assert len(res) == 1 and res[0]["no_esta_en_corpus"]  # ningún párrafo de otro año, solo el aviso


def test_nombre_del_reglamento_sale_del_pie_de_pagina():
    from agente_f1.rag.ingest import nombre_reglamento
    assert nombre_reglamento(EXTRACTO, Path("2026_b.pdf")) == \
        "2026 Formula 1 Regulations - Section B [Sporting], Issue 09 (01 October 2026)"


def test_avisa_si_el_articulo_no_esta_en_el_corpus(base, docs):
    for d in docs:  # la base de prueba no tiene nombre de reglamento: usar el de la fuente
        d.metadata.setdefault("reglamento", "2026 Formula 1 Regulations - Section B, Issue 09 (01 October 2026)")
    res = store.buscar("breach of the regulations", año=2026, cita="12.2.1.i", min_similitud=1.1)
    assert res[0]["no_esta_en_corpus"] is True
    assert "12.2.1.i" in res[0]["aviso"] and "No lo vuelvas a buscar" in res[0]["aviso"]


def test_vigente_desde():
    assert store.vigente_desde("2026 Formula 1 Regulations - Section B, Issue 09 (01 October 2026)") == "2026-10-01"
    assert store.vigente_desde("sin fecha") is None


def test_aviso_de_version_posterior_a_la_decision():
    from agente_f1.tools.reglamento_tools import _aviso_version
    res = [{"cita": "B1.8.6", "vigente_desde": "2026-10-01"}]
    assert "2026-09-12" in _aviso_version(res, "12 September 2026")["aviso"]
    assert _aviso_version(res, "07 November 2026") is None
