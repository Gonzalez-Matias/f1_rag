"""Conversaciones persistentes (una por sesión de chat).

- La memoria del agente es el checkpointer de LangGraph en SQLite: cada conversación
  es un thread_id y sus mensajes sobreviven a reinicios de la app.
- La tabla `conversaciones` guarda lo que la UI necesita para listarlas
  (título, proveedor, fechas).
- El historial que muestra la UI se reconstruye desde los mensajes del checkpointer,
  así hay una sola fuente de verdad.
"""
import sqlite3
import threading
import time
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver

from . import config
from .llm import LLMProvider
from .util import parse_json

INTERRUMPIDA = "Respuesta interrumpida."

_lock = threading.Lock()
_conn = None
_saver = None


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.CONVERSACIONES_DB.parent.mkdir(parents=True, exist_ok=True)
        # Streamlit ejecuta cada rerun en otro hilo: la conexión se comparte con un lock.
        _conn = sqlite3.connect(config.CONVERSACIONES_DB, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("""CREATE TABLE IF NOT EXISTS conversaciones (
            thread_id TEXT PRIMARY KEY, titulo TEXT NOT NULL, proveedor TEXT NOT NULL,
            creada REAL NOT NULL, actualizada REAL NOT NULL)""")
        _conn.commit()
    return _conn


def get_checkpointer() -> SqliteSaver:
    global _saver
    if _saver is None:
        _saver = SqliteSaver(_db())
        _saver.setup()
    return _saver


def listar() -> list[dict]:
    with _lock:
        rows = _db().execute("SELECT * FROM conversaciones ORDER BY actualizada DESC").fetchall()
    return [dict(r) for r in rows]


def obtener(thread_id: str) -> dict | None:
    with _lock:
        row = _db().execute("SELECT * FROM conversaciones WHERE thread_id=?", (thread_id,)).fetchone()
    return dict(row) if row else None


def registrar(thread_id: str, primera_pregunta: str, proveedor: str) -> None:
    """Crea la conversación (si no existe) o actualiza su fecha."""
    titulo = " ".join(primera_pregunta.split())
    titulo = titulo if len(titulo) <= 48 else titulo[:47] + "…"
    ahora = time.time()
    with _lock:
        _db().execute(
            "INSERT INTO conversaciones VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(thread_id) DO UPDATE SET actualizada=excluded.actualizada",
            (thread_id, titulo, proveedor, ahora, ahora))
        _db().commit()


def borrar(thread_id: str) -> None:
    with _lock:
        get_checkpointer().delete_thread(thread_id)
        _db().execute("DELETE FROM conversaciones WHERE thread_id=?", (thread_id,))
        _db().commit()


def rutas_de_informes(thread_id: str, checkpointer=None) -> list[Path]:
    """HTML de los informes generados en una conversación, en orden y si siguen en disco.

    Sale de los resultados de `generar_informe` guardados en el checkpointer: no hace falta
    el agente, así que la barra lateral lo puede usar aunque el modelo no esté disponible.
    """
    guardado = (checkpointer or get_checkpointer()).get_tuple({"configurable": {"thread_id": thread_id}})
    mensajes = guardado.checkpoint["channel_values"].get("messages", []) if guardado else []
    rutas = []
    for m in mensajes:
        if not isinstance(m, ToolMessage) or m.name != "generar_informe":
            continue
        resultado = parse_json(m.content)
        relativa = ((resultado.get("archivos") or {}).get("html") if isinstance(resultado, dict) else None)
        ruta = config.ROOT / relativa if relativa else None
        if ruta and ruta.exists() and ruta not in rutas:
            rutas.append(ruta)
    return rutas


def turnos(agent, thread_id: str, provider: LLMProvider) -> list[dict]:
    """Reconstruye el historial para la UI a partir de los mensajes guardados.

    turno = {"pregunta", "respuesta", "proceso": [eventos]}
    evento = {"tipo": "razonamiento", "texto"} | {"tipo": "tool", "tool", "argumentos", "resultado"}
    """
    estado = agent.get_state({"configurable": {"thread_id": thread_id}})
    out, pendientes = [], {}
    for m in estado.values.get("messages", []):
        if isinstance(m, HumanMessage):
            out.append({"pregunta": m.text, "respuesta": "", "proceso": []})
        elif not out:
            continue
        elif isinstance(m, AIMessage):
            frag = provider.extraer(m)
            if frag.razonamiento:
                out[-1]["proceso"].append({"tipo": "razonamiento", "texto": frag.razonamiento})
            if m.tool_calls:
                for tc in m.tool_calls:
                    ev = {"tipo": "tool", "tool": tc["name"], "argumentos": tc["args"]}
                    out[-1]["proceso"].append(ev)
                    pendientes[tc["id"]] = ev
            else:
                out[-1]["respuesta"] = frag.texto or m.text
        elif isinstance(m, ToolMessage) and m.tool_call_id in pendientes:
            pendientes.pop(m.tool_call_id)["resultado"] = parse_json(m.content)
    return out


def cerrar_turno_interrumpido(agent, thread_id: str) -> bool:
    """Deja consistente una conversación cuyo último turno se cortó (botón Detener, recarga).

    Un corte puede dejar guardada una llamada a una tool sin su resultado, y con eso los
    modelos rechazan el mensaje siguiente. Se completa cada llamada pendiente con un
    resultado "interrumpido" y se cierra el turno con una respuesta corta, así la
    conversación se puede seguir. Devuelve True si hubo algo que cerrar.
    """
    cfg = {"configurable": {"thread_id": thread_id}}
    mensajes = agent.get_state(cfg).values.get("messages", [])
    if not mensajes:
        return False
    ultimo = mensajes[-1]
    if isinstance(ultimo, AIMessage) and not ultimo.tool_calls:
        return False  # el turno terminó bien
    resueltas = {m.tool_call_id for m in mensajes if isinstance(m, ToolMessage)}
    nuevos = [ToolMessage(content='{"error": "Interrumpido por el usuario."}', tool_call_id=tc["id"], name=tc["name"])
              for m in mensajes if isinstance(m, AIMessage) for tc in m.tool_calls if tc["id"] not in resueltas]
    nuevos.append(AIMessage(content=INTERRUMPIDA))
    # Se reenvían también los mensajes ya visibles: el paso que se cortó puede no haber llegado
    # a guardarse (queda como escritura pendiente) y update_state lo descartaría. Con el mismo
    # id, los que ya estaban guardados se reemplazan por sí mismos y no se duplican.
    agent.update_state(cfg, {"messages": [*mensajes, *nuevos]}, as_node="model")
    return True
