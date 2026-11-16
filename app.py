"""UI "Pit Wall Agent" en Streamlit (mismo estilo que el informe PDF).

- Barra lateral: logo, nueva conversación y la lista de conversaciones guardadas.
- Arriba a la derecha: el modelo. El usuario elige proveedor y modelo y puede traer su
  propia clave: se guarda solo en la sesión del navegador, nunca en disco.
- Centro: el chat. Cada respuesta tiene un bloque desplegable "Razonamiento" con todo
  el proceso en orden (razonamiento del modelo y cada tool con argumentos y resultado
  en JSON). Afuera del bloque queda solo la respuesta final.

Las conversaciones se guardan en data/conversaciones.sqlite (checkpointer de LangGraph):
sobreviven a reinicios y la memoria del agente sale de ahí mismo.

Ejecutar:  streamlit run app.py
"""
import hashlib
import uuid
from datetime import datetime

import streamlit as st
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from agente_f1 import config, conversaciones
from agente_f1.agent import build_agent
from agente_f1.llm import PROVEEDORES, get_provider, listar_modelos_proveedor
from agente_f1.util import parse_json

st.set_page_config(page_title="Pit Wall Agent", layout="wide")

st.markdown("""
<style>
  .block-container {padding-top: 1.4rem; max-width: 980px;}

  /* logo, como la portada del informe */
  .pw-logo {font: italic 800 1.55rem/1 'Barlow Condensed', sans-serif; color: #fff;
            border-left: 6px solid #e8433a; padding: .15rem 0 .15rem .6rem; margin-bottom: .35rem;}
  .pw-sobre {font: 600 .68rem 'Barlow', sans-serif; letter-spacing: .16em; text-transform: uppercase;
             color: #a3a5b0;}
  section[data-testid="stSidebar"] button > div {justify-content: flex-start;}
  section[data-testid="stSidebar"] button p {text-align: left; width: 100%;}
  /* los ejemplos de la portada se leen completos (sin "...") */
  .stMainBlockContainer div[data-testid="stButton"] button p {white-space: normal; text-align: left;}

  /* títulos en condensada itálica, como el informe */
  h1, h2, h3 {font-style: italic !important;}
  h2, h3 {text-transform: uppercase; letter-spacing: .02em;}
  .pw-conv {font: italic 700 1.35rem/1.1 'Barlow Condensed', sans-serif; margin: .2rem 0 0;}
  .pw-meta {color: #8b8d98; font-size: .85rem;}

  /* portada vacía */
  .pw-portada {background: #1f2029; color: #fff; border-radius: .6rem; padding: 1.6rem 1.8rem 1.4rem; margin: .5rem 0 1rem;}
  .pw-portada h1 {font: italic 800 2.3rem/1.05 'Barlow Condensed', sans-serif; color: #fff; margin: .4rem 0 .5rem; padding: 0;}
  .pw-portada p {color: #c9cad3; margin: 0;}

  /* mensajes */
  div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) {
      background: #1f2029; border-radius: .6rem;}
  code {font-weight: 700;}

  /* bloque "Razonamiento": etiqueta como los subtítulos de las fichas */
  div[data-testid="stExpander"] summary p, div[data-testid="stStatusWidget"] summary p {
      font: 700 .72rem 'Barlow', sans-serif !important; letter-spacing: .14em; text-transform: uppercase; color: #a3a5b0;}
  .pw-razon {color: #a3a5b0; font-style: italic;}
  .pw-tool {font: 700 .85rem 'JetBrains Mono', monospace; margin: .7rem 0 .2rem 0;}
  .pw-tool::before {content: "● "; color: #ff5a4f;}
</style>
""", unsafe_allow_html=True)

EJEMPLOS = [
    "¿Por qué sancionaron a Bearman en São Paulo 2026?",
    "¿Cuál fue la última sanción de Hamilton?",
    "¿Quiénes fueron sancionados en el GP de Baréin 2025?",
]


# ---------------------------------------------------------------- estado

def nueva_conversacion():
    st.session_state.thread_id = str(uuid.uuid4())


def abrir(thread_id: str):
    st.session_state.thread_id = thread_id
    conv = conversaciones.obtener(thread_id)
    if conv and conv["proveedor"] in PROVEEDORES:
        st.session_state.modelo["proveedor"] = conv["proveedor"]  # cada conversación sigue con su proveedor


def preguntar(texto: str):
    st.session_state.pendiente = texto


if "thread_id" not in st.session_state:
    nueva_conversacion()
if "modelo" not in st.session_state:
    # {"proveedor", "modelo", "base_url"}; las claves van aparte, por proveedor, solo en la sesión
    st.session_state.modelo = {"proveedor": config.LLM_PROVIDER, "modelo": "", "base_url": ""}
    st.session_state.claves = {}
st.session_state.setdefault("pendiente", None)

actual = conversaciones.obtener(st.session_state.thread_id)
cfg = st.session_state.modelo


def provider_actual():
    return get_provider(cfg["proveedor"], modelo=cfg["modelo"] or None,
                        api_key=st.session_state.claves.get(cfg["proveedor"]) or None,
                        base_url=cfg["base_url"] or None)


@st.cache_data(show_spinner=False, ttl=120)
def _descubrir_modelos(proveedor: str, api_key: str, base_url: str) -> dict:
    return listar_modelos_proveedor(proveedor, api_key=api_key or None, base_url=base_url or None)


def agente_de_la_sesion(provider):
    """El agente se arma por sesión: puede llevar la clave del usuario, que no se comparte
    con otras sesiones ni se guarda. Todas comparten el checkpointer (las conversaciones)."""
    huella = hashlib.sha256(f"{provider.nombre}|{provider.modelo}|{provider.base_url}|{provider.api_key}".encode()).hexdigest()
    agentes = st.session_state.setdefault("_agentes", {})
    if huella not in agentes:
        agentes.clear()
        agentes[huella] = build_agent(provider, checkpointer=conversaciones.get_checkpointer())
    return agentes[huella]


# ---------------------------------------------------------------- barra lateral: conversaciones

with st.sidebar:
    st.markdown('<div class="pw-logo">Pit Wall Agent</div>'
                '<div class="pw-sobre">Sanciones de F1 con el reglamento en la mano</div>',
                unsafe_allow_html=True)
    st.write("")
    st.button("Nueva conversación", use_container_width=True, type="primary", on_click=nueva_conversacion)
    st.write("")
    lista = conversaciones.listar()
    if lista:
        st.caption("CONVERSACIONES")
    for conv in lista:
        activa = conv["thread_id"] == st.session_state.thread_id
        st.button(conv["titulo"], key=f"conv-{conv['thread_id']}", use_container_width=True,
                  type="secondary" if not activa else "tertiary", disabled=activa,
                  help=f"{conv['proveedor']} · {datetime.fromtimestamp(conv['actualizada']):%d/%m %H:%M}",
                  on_click=abrir, args=(conv["thread_id"],))
    if actual:
        st.divider()
        if st.button("Borrar esta conversación", use_container_width=True):
            conversaciones.borrar(st.session_state.thread_id)
            nueva_conversacion()
            st.rerun()


# ---------------------------------------------------------------- encabezado: conversación y modelo

provider = provider_actual()
h1, h2 = st.columns([5, 2.2], vertical_alignment="center")
with h1:
    if actual:
        st.markdown(f'<p class="pw-conv">{actual["titulo"]}</p>', unsafe_allow_html=True)
with h2:
    with st.popover(f"Modelo · {provider.etiqueta}", use_container_width=True):
        nombres = list(PROVEEDORES)
        elegido = st.selectbox(
            "Proveedor", nombres, index=nombres.index(cfg["proveedor"]) if cfg["proveedor"] in nombres else 0,
            format_func=lambda n: PROVEEDORES[n].etiqueta, disabled=actual is not None,
            help="Una conversación guardada sigue con su proveedor; para cambiarlo, empezá una nueva.")
        clase = PROVEEDORES[elegido]
        clave, base_url = "", ""
        if clase.env_api_key:
            en_env = bool(get_provider(elegido).api_key)
            clave = st.text_input(
                "Tu clave de API", type="password", value=st.session_state.claves.get(elegido, ""),
                placeholder="usando la del .env" if en_env else "pegá tu clave",
                help="Se usa solo en esta sesión del navegador: no se guarda en disco ni se comparte.")
        else:
            base_url = st.text_input(
                "URL del servidor local",
                value=cfg["base_url"] if (elegido == cfg["proveedor"] and cfg["base_url"]) else (clase.base_url_default or ""),
                placeholder=clase.base_url_default,
            )
            st.caption("El modelo tiene que soportar tool calling (ej. qwen3, llama3.1).")

        clave_efectiva = clave.strip() or (get_provider(elegido).api_key if clase.env_api_key else "")
        catalogo = _descubrir_modelos(elegido, clave_efectiva, base_url.strip())
        modelos_disponibles = catalogo.get("modelos") or [clase.modelo_default]

        modelo_actual = cfg["modelo"] if (elegido == cfg["proveedor"] and cfg["modelo"]) else clase.modelo_default
        idx_modelo = (
            modelos_disponibles.index(modelo_actual)
            if modelo_actual in modelos_disponibles
            else 0
        )
        modelo_sel = st.selectbox("Modelo", modelos_disponibles, index=idx_modelo)
        if catalogo.get("fuente") == "api_en_vivo":
            st.caption(f"{len(modelos_disponibles)} modelos activos detectados en la API.")
        else:
            st.caption("Catálogo base · Ingresá tu clave de API para listar los modelos de tu cuenta.")

        modelo_custom = st.text_input(
            "Otro modelo (personalizado)",
            value="" if modelo_actual in modelos_disponibles else modelo_actual,
            placeholder="Opcional: ej. modelo específico o custom",
            help="Permite ingresar cualquier identificador de modelo que no figure en la lista.",
        )
        modelo_final = modelo_custom.strip() if modelo_custom.strip() else modelo_sel

        if st.button("Usar este modelo", type="primary", use_container_width=True):
            st.session_state.modelo = {"proveedor": elegido, "modelo": modelo_final, "base_url": base_url.strip()}
            if clave.strip():
                st.session_state.claves[elegido] = clave.strip()
            st.rerun()
    st.markdown(f'<p class="pw-meta" style="text-align:right;margin:.15rem 0 0">{provider.modelo}</p>',
                unsafe_allow_html=True)

if not provider.disponible():
    st.info(f"Para usar **{provider.etiqueta}** cargá tu clave de API en **Modelo** (arriba a la derecha). "
            "Se usa solo en esta sesión y no se guarda.")
    st.stop()
agent = agente_de_la_sesion(provider)


# ---------------------------------------------------------------- render del proceso

def render_razonamiento(texto: str):
    st.markdown(f'<div class="pw-razon">\n\n{texto}\n\n</div>', unsafe_allow_html=True)


def render_tool(ev: dict):
    st.markdown(f'<p class="pw-tool">{ev["tool"]}</p>', unsafe_allow_html=True)
    datos = {"tool": ev["tool"], "argumentos": ev["argumentos"]}
    if "resultado" in ev:
        datos["resultado"] = ev["resultado"]
    st.json(datos, expanded=2)


def render_proceso(eventos: list[dict]):
    for ev in eventos:
        if ev["tipo"] == "razonamiento":
            render_razonamiento(ev["texto"])
        else:
            render_tool(ev)


def render_descargas(eventos: list[dict], clave: str):
    """Botones para descargar los informes generados en ese turno (PDF y HTML)."""
    for n, ev in enumerate(e for e in eventos if e.get("tool") == "generar_informe"):
        archivos = (ev.get("resultado") or {}).get("archivos") if isinstance(ev.get("resultado"), dict) else None
        if not archivos:
            continue
        columnas = st.columns(4)
        for col, (tipo, mime) in zip(columnas, [("pdf", "application/pdf"), ("html", "text/html")]):
            ruta = config.ROOT / archivos[tipo] if archivos.get(tipo) else None
            if ruta and ruta.exists():
                col.download_button(f"Descargar informe {tipo.upper()}", ruta.read_bytes(), file_name=ruta.name,
                                    mime=mime, key=f"dl-{clave}-{n}-{tipo}", type="primary" if tipo == "pdf" else "secondary",
                                    use_container_width=True)


# ---------------------------------------------------------------- historial (desde el checkpointer)

historial = conversaciones.turnos(agent, st.session_state.thread_id, provider) if actual else []
if not historial:
    st.markdown('<div class="pw-portada"><div class="pw-sobre">Pit Wall Agent · Sanciones de F1</div>'
                '<h1>Preguntá por cualquier sanción</h1>'
                '<p>Busco la decisión oficial de los comisarios, el artículo del reglamento que se aplicó '
                'y te lo explico en simple. Si querés, te armo un informe en PDF.</p></div>',
                unsafe_allow_html=True)
    for col, ejemplo in zip(st.columns(len(EJEMPLOS)), EJEMPLOS):
        col.button(ejemplo, use_container_width=True, on_click=preguntar, args=(ejemplo,))

for t, turno in enumerate(historial):
    with st.chat_message("user"):
        st.markdown(turno["pregunta"])
    with st.chat_message("assistant"):
        if turno["proceso"]:
            with st.expander("Razonamiento", expanded=False):
                render_proceso(turno["proceso"])
        st.markdown(turno["respuesta"])
        render_descargas(turno["proceso"], clave=f"{st.session_state.thread_id}-{t}")

pregunta = st.chat_input("Preguntá sobre cualquier sanción de F1…") or st.session_state.pendiente
st.session_state.pendiente = None


# ---------------------------------------------------------------- turno en streaming

if pregunta:
    conversaciones.registrar(st.session_state.thread_id, pregunta, provider.nombre)
    with st.chat_message("user"):
        st.markdown(pregunta)
    with st.chat_message("assistant"):
        proceso_box = st.status("Razonando…", expanded=True)  # todo el proceso, en orden
        respuesta_box = st.empty()                             # solo la respuesta final

    respuesta, texto_razon = "", ""
    slot_razon = None    # placeholder del segmento de razonamiento en curso
    pendientes = {}      # tool_call_id -> (evento, placeholder)

    config_run = {"configurable": {"thread_id": st.session_state.thread_id}}
    try:
        # "messages": tokens del modelo (razonamiento y texto) a medida que llegan.
        # "updates":  cada paso del grafo (llamadas a tools y resultados), en orden.
        for modo, chunk in agent.stream({"messages": [{"role": "user", "content": pregunta}]},
                                        config_run, stream_mode=["messages", "updates"]):
            if modo == "messages":
                token, _meta = chunk
                if not isinstance(token, AIMessageChunk):
                    continue
                frag = provider.extraer(token)  # el adaptador sabe dónde viene el razonamiento
                if frag.razonamiento:
                    if slot_razon is None:  # segmento nuevo (al inicio o después de una tool)
                        slot_razon, texto_razon = proceso_box.empty(), ""
                    texto_razon += frag.razonamiento
                    with slot_razon.container():
                        render_razonamiento(texto_razon)
                if frag.texto:
                    respuesta += frag.texto
                    respuesta_box.markdown(respuesta + "▌")
                continue

            for _nodo, update in (chunk or {}).items():
                for m in (update or {}).get("messages", []):
                    if isinstance(m, AIMessage) and m.tool_calls:
                        respuesta = ""  # el texto previo a una tool call no es la respuesta final
                        respuesta_box.empty()
                        slot_razon = None
                        for tc in m.tool_calls:
                            ev = {"tipo": "tool", "tool": tc["name"], "argumentos": tc["args"]}
                            slot = proceso_box.empty()
                            with slot.container():
                                render_tool(ev)
                            pendientes[tc["id"]] = (ev, slot)
                    elif isinstance(m, ToolMessage) and m.tool_call_id in pendientes:
                        ev, slot = pendientes.pop(m.tool_call_id)
                        ev["resultado"] = parse_json(m.content)
                        with slot.container():
                            render_tool(ev)
                        slot_razon = None
    except Exception as exc:  # ej. 429 agotados los reintentos, clave inválida, servidor local apagado
        proceso_box.update(label="Error", state="error", expanded=False)
        respuesta_box.markdown(f"Ocurrió un error con el modelo: `{exc}`")
        st.stop()

    proceso_box.update(label="Razonamiento", state="complete", expanded=False)
    respuesta_box.markdown(respuesta)
    st.rerun()  # redibuja desde el checkpointer (proceso plegado, conversación en la lista)
