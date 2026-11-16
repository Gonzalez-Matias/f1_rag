"""Detener una respuesta a mitad de camino, y listado / vista previa de informes. Sin red."""
from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from agente_f1 import conversaciones
from agente_f1.informe import render
from agente_f1.llm import get_provider


@tool
def consulta(x: int) -> str:
    """Tool de prueba."""
    return "resultado"


class ModeloFalso(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _agente():
    respuestas = [AIMessage(content="", tool_calls=[{"name": "consulta", "args": {"x": 1}, "id": "c1"}]),
                  AIMessage(content="respuesta final")]
    # mismos middlewares que el agente real: cambian los nodos del grafo
    return create_agent(model=ModeloFalso(responses=respuestas), tools=[consulta], system_prompt="x",
                        checkpointer=InMemorySaver(),
                        middleware=[ToolCallLimitMiddleware(tool_name="consulta", run_limit=6),
                                    ToolCallLimitMiddleware(run_limit=20)])


def _cortar_en(agente, cfg, nodo):
    """Corre el turno y lo abandona apenas termina `nodo`, como hace Streamlit al tocar Detener."""
    for modo, chunk in agente.stream({"messages": [{"role": "user", "content": "hola"}]}, cfg,
                                     stream_mode=["messages", "updates"]):
        if modo == "updates" and nodo in chunk:
            break


def _tipos(agente, cfg):
    return [type(m).__name__ for m in agente.get_state(cfg).values["messages"]]


def test_corte_con_una_tool_sin_resultado():
    agente, cfg = _agente(), {"configurable": {"thread_id": "a"}}
    _cortar_en(agente, cfg, "model")   # el modelo pidió la tool y no llegó a ejecutarse
    assert conversaciones.cerrar_turno_interrumpido(agente, "a")
    mensajes = agente.get_state(cfg).values["messages"]
    # la llamada pendiente queda con su resultado y el turno, cerrado: el modelo acepta lo que sigue
    assert _tipos(agente, cfg) == ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage"]
    assert mensajes[2].tool_call_id == "c1" and "Interrumpido" in mensajes[2].content
    assert mensajes[3].content == conversaciones.INTERRUMPIDA
    assert not conversaciones.cerrar_turno_interrumpido(agente, "a")   # no cierra dos veces

    salida = agente.invoke({"messages": [{"role": "user", "content": "otra pregunta"}]}, cfg)
    assert isinstance(salida["messages"][-1], AIMessage) and salida["messages"][-2].content == "otra pregunta"


def test_corte_despues_de_la_tool_conserva_su_resultado():
    agente, cfg = _agente(), {"configurable": {"thread_id": "b"}}
    _cortar_en(agente, cfg, "tools")
    assert conversaciones.cerrar_turno_interrumpido(agente, "b")
    mensajes = agente.get_state(cfg).values["messages"]
    assert _tipos(agente, cfg) == ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage"]
    assert mensajes[2].content == "resultado"


def test_turno_completo_no_se_toca():
    agente, cfg = _agente(), {"configurable": {"thread_id": "c"}}
    agente.invoke({"messages": [{"role": "user", "content": "hola"}]}, cfg)
    assert not conversaciones.cerrar_turno_interrumpido(agente, "c")
    assert not conversaciones.cerrar_turno_interrumpido(agente, "conversacion-que-no-existe")


def test_el_historial_muestra_el_turno_interrumpido():
    agente, cfg = _agente(), {"configurable": {"thread_id": "d"}}
    _cortar_en(agente, cfg, "model")
    conversaciones.cerrar_turno_interrumpido(agente, "d")
    turno = conversaciones.turnos(agente, "d", get_provider("openai", api_key="x"))[0]
    assert turno["pregunta"] == "hola" and turno["respuesta"] == conversaciones.INTERRUMPIDA
    assert turno["proceso"][0]["tool"] == "consulta"


# ---------------------------------------------------------------- informes

def test_listar_informes(tmp_path):
    (tmp_path / "20261107-220154-sao-paulo.html").write_text(
        "<html><head><title>Informe de sanciones · Gran Premio de São Paulo 2026</title></head></html>", encoding="utf-8")
    (tmp_path / "20261107-220154-sao-paulo.pdf").write_bytes(b"%PDF")
    (tmp_path / "20261108-101500-mexico.html").write_text("<title>Informe de sanciones · México 2026</title>", encoding="utf-8")
    informes = render.listar(tmp_path)
    assert [i["titulo"] for i in informes] == ["México 2026", "Gran Premio de São Paulo 2026"]   # el más nuevo primero
    assert informes[0]["pdf"] is None and informes[1]["pdf"].name.endswith(".pdf")
    assert f"{informes[1]['generado']:%d/%m/%Y %H:%M}" == "07/11/2026 22:01"
    assert len(render.listar(tmp_path, maximo=1)) == 1
    assert render.listar(tmp_path / "no-existe") == []


def test_vista_previa_usa_las_tipografias_de_la_app():
    original = "<html><head><style>@font-face { src: url(fuentes/Barlow-Regular.ttf); }</style></head><body>x</body></html>"
    vista = render.vista_previa(original)
    chat = render.vista_previa(original, modo="chat")
    assert "--tinta: #e6e6ea" in chat and "max-width:210mm" not in chat and 'target="_blank"' in chat
    assert "url(/app/static/fuentes/Barlow-Regular.ttf)" in vista and "url(fuentes/" not in vista
    assert vista.index("max-width:210mm") < vista.index("</head>")   # la hoja simulada va en el <head>
