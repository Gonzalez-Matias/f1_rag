"""UI "Pit Wall Agent" en Streamlit (mismo estilo que el informe PDF).

- Barra lateral: logo, nueva conversación, conversaciones guardadas e informes generados.
- Arriba a la derecha: el modelo. El usuario elige proveedor y modelo y puede traer su
  propia clave: se guarda solo en la sesión del navegador, nunca en disco.
- Centro: el chat. Cada respuesta tiene un bloque desplegable "Razonamiento" con todo
  el proceso en orden (razonamiento del modelo y cada tool, con su fuente, argumentos y
  resultado en JSON). Afuera del bloque queda solo la respuesta final.
- Informe: si la respuesta explicó sanciones, debajo aparece el botón "Generar informe".
  Un informe generado se ve en la misma página (vista previa) y se descarga en PDF o HTML.
- Mientras el agente responde no se puede enviar otro mensaje: hay un botón "Detener".

Las conversaciones se guardan en data/conversaciones.sqlite (checkpointer de LangGraph):
sobreviven a reinicios y la memoria del agente sale de ahí mismo.

Ejecutar:  streamlit run app.py
"""
import hashlib
import html
import re
import uuid
from datetime import datetime
from pathlib import Path

import streamlit as st
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from agente_f1 import config, conversaciones
from agente_f1.agent import build_agent
from agente_f1.informe import render as informe_render
from agente_f1.llm import PROVEEDORES, get_provider
from agente_f1.util import parse_json

st.set_page_config(page_title="Pit Wall Agent", layout="wide")

st.markdown("""
<style>
  .block-container {padding-top: 1.4rem; max-width: 980px;}

  /* ---------- barra lateral ---------- */
  .pw-logo {font: italic 800 1.55rem/1 'Barlow Condensed', sans-serif; color: #fff;
            border-left: 6px solid #e8433a; padding: .15rem 0 .15rem .6rem; margin-bottom: .35rem;}
  .pw-sobre {font: 600 .68rem 'Barlow', sans-serif; letter-spacing: .16em; text-transform: uppercase;
             color: #a3a5b0;}
  .pw-seccion {font: 600 .66rem 'Barlow', sans-serif; letter-spacing: .18em; text-transform: uppercase;
               color: #6f7180; margin: .9rem 0 0; padding-bottom: .4rem; border-bottom: 1px solid #23242e;}
  section[data-testid="stSidebar"] button > div {justify-content: flex-start;}
  section[data-testid="stSidebar"] button p {text-align: left; width: 100%; white-space: nowrap;
                                              overflow: hidden; text-overflow: ellipsis;}
  /* conversaciones e informes: lista plana; la activa lleva la marca roja, como una posición en la torre */
  section[data-testid="stSidebar"] button[kind="secondary"],
  section[data-testid="stSidebar"] button[kind="tertiary"] {
      border: 0; border-left: 3px solid transparent; border-radius: 0 .35rem .35rem 0; background: transparent;
      min-height: 2rem; padding: .3rem .6rem; color: #b9bbc6;}
  section[data-testid="stSidebar"] button[kind="secondary"]:hover:not(:disabled) {background: #1a1b23; color: #fff;}
  section[data-testid="stSidebar"] button[kind="tertiary"] {border-left-color: #e8433a; background: #1a1b23;}
  section[data-testid="stSidebar"] button[kind="tertiary"] p {color: #fff; font-weight: 600;}
  section[data-testid="stSidebar"] button:disabled {opacity: 1;}
  section[data-testid="stSidebar"] button[kind="secondary"]:disabled p {color: #6f7180;}

  /* ---------- encabezado ---------- */
  h1, h2, h3 {font-style: italic !important;}
  h2, h3 {text-transform: uppercase; letter-spacing: .02em;}
  .pw-conv {font: italic 700 1.35rem/1.1 'Barlow Condensed', sans-serif; margin: .2rem 0 0;}
  .pw-meta {color: #8b8d98; font: 500 .74rem 'JetBrains Mono', monospace;}

  /* ---------- portada ---------- */
  .pw-portada {position: relative; overflow: hidden; background: #1f2029; color: #fff; border-radius: .6rem;
               padding: 1.7rem 1.9rem 0; margin: .5rem 0 1.4rem;}
  .pw-portada::before {content: ""; position: absolute; inset: 0 auto 0 0; width: 6px; background: #e8433a;}
  .pw-portada h1 {font: italic 800 2.7rem/1 'Barlow Condensed', sans-serif; color: #fff; margin: .45rem 0 .6rem; padding: 0;}
  .pw-portada p {color: #c9cad3; margin: 0; max-width: 40rem;}
  .pw-pasos {display: grid; grid-template-columns: repeat(3, 1fr); margin: 1.5rem -1.9rem 0; border-top: 1px solid #2f303c;}
  .pw-paso {padding: .9rem 1.2rem .95rem 1.9rem; border-right: 1px solid #2f303c;}
  .pw-paso:last-child {border-right: 0;}
  .pw-paso b {display: block; font: 700 .7rem 'JetBrains Mono', monospace; color: #ff6b61; letter-spacing: .08em;}
  .pw-paso span {display: block; font: 600 .98rem 'Barlow', sans-serif; color: #fff; margin: .15rem 0 .1rem;}
  .pw-paso small {color: #9c9eaa; font-size: .8rem;}
  .pw-ejemplo {font: 600 .64rem 'Barlow', sans-serif; letter-spacing: .16em; text-transform: uppercase;
               color: #ff6b61; margin: 0 0 .3rem .1rem;}
  .stMainBlockContainer div[data-testid="stButton"] button p {white-space: normal; text-align: left;}
  @media (max-width: 720px) {
      .pw-pasos {grid-template-columns: 1fr;}
      .pw-paso {border-right: 0; border-bottom: 1px solid #2f303c;}
      .pw-portada h1 {font-size: 2.1rem;}
  }

  /* ---------- mensajes: sin avatares; la pregunta va a la derecha, como una burbuja ---------- */
  div[data-testid="stChatMessage"] {padding: .2rem 0; gap: 0; background: transparent;}
  div[data-testid="stChatMessage"] > div:first-child:not([data-testid="stChatMessageContent"]) {display: none;}
  div[data-testid="stChatMessageAvatarUser"], div[data-testid="stChatMessageAvatarAssistant"] {display: none;}
  div[data-testid="stChatMessage"]:has(.pw-pregunta) {
      background: #1f2029; border-radius: .7rem .7rem .15rem .7rem; padding: .65rem 1rem; margin: 1rem 0 .6rem auto;
      width: fit-content; max-width: 78%;}
  .pw-pregunta {margin: 0; color: #fff;}
  .pw-interrumpida {color: #8b8d98; font-style: italic; border-left: 3px solid #3a3b47; padding-left: .7rem;}
  code {font-weight: 700;}

  /* ---------- bloque "Razonamiento" ---------- */
  div[data-testid="stExpander"] summary p, div[data-testid="stStatusWidget"] summary p {
      font: 700 .72rem 'Barlow', sans-serif !important; letter-spacing: .14em; text-transform: uppercase; color: #a3a5b0;}
  .pw-razon {color: #a3a5b0; font-style: italic;}
  .pw-tool {display: flex; flex-wrap: wrap; align-items: baseline; gap: .5rem; margin: .8rem 0 .25rem;}
  .pw-tool b {font: 700 .85rem 'JetBrains Mono', monospace; color: #fff;}
  .pw-tool span {font: 500 .78rem 'JetBrains Mono', monospace; color: #8b8d98;}
  .pw-fuente {font: 700 .6rem 'Barlow', sans-serif; letter-spacing: .12em; text-transform: uppercase;
              border-radius: .2rem; padding: .12rem .4rem; color: #14151c; background: #a3a5b0;}
  .pw-fuente.fia {background: #e8433a; color: #fff;}
  .pw-fuente.openf1 {background: #e6e6ea;}
  .pw-fuente.mixta {background: linear-gradient(90deg, #e6e6ea 50%, #e8433a 50%); color: #14151c;}
  .pw-fuente.local {background: transparent; color: #a3a5b0; box-shadow: inset 0 0 0 1px #4a4b58;}

  /* ---------- informe ---------- */
  .pw-informe {display: flex; align-items: baseline; gap: .7rem; margin: .2rem 0 .1rem;}
  .pw-informe b {font: italic 700 1.15rem/1.1 'Barlow Condensed', sans-serif; color: #fff;}
  .st-key-pw-acciones {margin-top: .4rem;}
  .st-key-pw-detener button {border-color: #e8433a; color: #ff6b61;}
  iframe {border-radius: .4rem;}
</style>
""", unsafe_allow_html=True)

EJEMPLOS = [
    ("Un piloto en una carrera", "¿Por qué sancionaron a Bearman en São Paulo 2026?"),
    ("Última sanción", "¿Cuál fue la última sanción de Hamilton?"),
    ("Carrera completa", "¿Quiénes fueron sancionados en la quinta carrera de 2025?"),
]
PEDIR_INFORME = "Armame el informe en PDF de las sanciones que acabás de explicar."
INFORMES_EN_BARRA = 6

# Fuente de cada tool, para la etiqueta del bloque "Razonamiento": (texto, clase CSS)
FUENTE_LOCAL = {"buscar_en_reglamento": "Reglamento", "generar_informe": "Informe"}


def fuente_de(tool: str) -> tuple[str, str]:
    if tool.startswith("fia_"):
        return "FIA", "fia"
    if tool.startswith("openf1_"):
        return "OpenF1", "openf1"
    if tool.startswith("sanciones_"):
        return "OpenF1 + FIA", "mixta"
    return FUENTE_LOCAL.get(tool, "Tool"), "local"


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


def enviar():
    preguntar(st.session_state.entrada)


def detener():
    """No hace falta más: el clic ya corta la ejecución en curso y el próximo rerun cierra el turno."""
    st.session_state.detenida = True


if "thread_id" not in st.session_state:
    nueva_conversacion()
if "modelo" not in st.session_state:
    # {"proveedor", "modelo", "base_url"}; las claves van aparte, por proveedor, solo en la sesión
    st.session_state.modelo = {"proveedor": config.LLM_PROVIDER, "modelo": "", "base_url": ""}
    st.session_state.claves = {}
st.session_state.setdefault("pendiente", None)   # pregunta a enviar en esta ejecución
st.session_state.setdefault("generando", None)   # thread_id del turno en curso (None si no hay)
st.session_state.setdefault("detenida", False)

# Hay una pregunta por responder en esta ejecución: se bloquea todo lo que cambiaría de contexto.
ocupado = st.session_state.pendiente is not None
actual = conversaciones.obtener(st.session_state.thread_id)
cfg = st.session_state.modelo


def provider_actual():
    return get_provider(cfg["proveedor"], modelo=cfg["modelo"] or None,
                        api_key=st.session_state.claves.get(cfg["proveedor"]) or None,
                        base_url=cfg["base_url"] or None)


def agente_de_la_sesion(provider):
    """El agente se arma por sesión: puede llevar la clave del usuario, que no se comparte
    con otras sesiones ni se guarda. Todas comparten el checkpointer (las conversaciones)."""
    # La fecha entra en la huella: el prompt dice qué día es, así que el agente se rearma cada día.
    huella = hashlib.sha256(f"{provider.nombre}|{provider.modelo}|{provider.base_url}|{provider.api_key}|"
                            f"{datetime.now():%Y-%m-%d}".encode()).hexdigest()
    agentes = st.session_state.setdefault("_agentes", {})
    if huella not in agentes:
        agentes.clear()
        agentes[huella] = build_agent(provider, checkpointer=conversaciones.get_checkpointer())
    return agentes[huella]


# ---------------------------------------------------------------- informes

def render_informe(ruta_html: Path, ruta_pdf: Path | None, clave: str, alto: int = 620):
    """Vista previa del informe (HTML) y botones de descarga."""
    columnas = st.columns([1.3, 1.3, 3])
    if ruta_pdf and ruta_pdf.exists():
        columnas[0].download_button("Descargar PDF", ruta_pdf.read_bytes(), file_name=ruta_pdf.name,
                                    mime="application/pdf", key=f"dl-{clave}-pdf", type="primary",
                                    use_container_width=True)
    contenido = ruta_html.read_text(encoding="utf-8")
    columnas[1].download_button("Descargar HTML", contenido, file_name=ruta_html.name, mime="text/html",
                                key=f"dl-{clave}-html", use_container_width=True)
    # El HTML sale de nuestra plantilla (Jinja con autoescape): los textos del modelo van escapados.
    st.iframe(informe_render.vista_previa(contenido), height=alto)


@st.dialog("Informe de sanciones", width="large")
def abrir_informe(informe: dict):
    st.markdown(f'<div class="pw-informe"><b>{html.escape(informe["titulo"])}</b>'
                f'<span class="pw-meta">{informe["generado"]:%d/%m/%Y %H:%M}</span></div>', unsafe_allow_html=True)
    render_informe(informe["html"], informe["pdf"], clave=f"dlg-{informe['html'].stem}")


def informes_del_turno(eventos: list[dict]) -> list[tuple[Path, Path | None]]:
    """Archivos de los informes generados en un turno: [(html, pdf o None)]."""
    out = []
    for ev in eventos:
        resultado = ev.get("resultado")
        archivos = resultado.get("archivos") if ev.get("tool") == "generar_informe" and isinstance(resultado, dict) else None
        ruta_html = config.ROOT / archivos["html"] if archivos and archivos.get("html") else None
        if ruta_html and ruta_html.exists():
            ruta_pdf = config.ROOT / archivos["pdf"] if archivos.get("pdf") else None
            out.append((ruta_html, ruta_pdf))
    return out


def hay_decisiones(eventos: list[dict]) -> bool:
    """El turno trajo decisiones de la FIA (hay material para un informe)."""
    for ev in eventos:
        tool, resultado = ev.get("tool", ""), ev.get("resultado")
        if tool.startswith("sanciones_") and isinstance(resultado, dict) and resultado.get("decisiones_fia"):
            return True
        if tool.startswith("fia_") and resultado and not (isinstance(resultado, dict) and
                                                         ("error" in resultado or "resultado" in resultado)):
            return True
    return False


# ---------------------------------------------------------------- barra lateral

with st.sidebar:
    st.markdown('<div class="pw-logo">Pit Wall Agent</div>'
                '<div class="pw-sobre">Sanciones de F1 con el reglamento en la mano</div>',
                unsafe_allow_html=True)
    st.write("")
    st.button("Nueva conversación", use_container_width=True, type="primary", on_click=nueva_conversacion,
              disabled=ocupado)
    lista = conversaciones.listar()
    if lista:
        st.markdown('<div class="pw-seccion">Conversaciones</div>', unsafe_allow_html=True)
    with st.container(gap=None):
        for conv in lista:
            activa = conv["thread_id"] == st.session_state.thread_id
            st.button(conv["titulo"], key=f"conv-{conv['thread_id']}", use_container_width=True,
                      type="tertiary" if activa else "secondary", disabled=activa or ocupado,
                      help=f"{conv['proveedor']} · {datetime.fromtimestamp(conv['actualizada']):%d/%m %H:%M}",
                      on_click=abrir, args=(conv["thread_id"],))

    informes = informe_render.listar(maximo=INFORMES_EN_BARRA)
    if informes:
        st.markdown('<div class="pw-seccion">Informes</div>', unsafe_allow_html=True)
    with st.container(gap=None):
        for inf in informes:
            # "Gran Premio de São Paulo 2026 - ..." -> "São Paulo 2026 - ...": lo que distingue un informe de otro
            corto = re.sub(r"^Gran Premio (?:de la |del |de )", "", inf["titulo"])
            if st.button(f"{inf['generado']:%d/%m} · {corto}", key=f"inf-{inf['html'].stem}",
                         use_container_width=True, disabled=ocupado,
                         help=f"{inf['titulo']} · generado el {inf['generado']:%d/%m/%Y a las %H:%M}"):
                abrir_informe(inf)

    if actual:
        st.markdown('<div class="pw-seccion">Esta conversación</div>', unsafe_allow_html=True)
        if st.button("Borrar conversación", use_container_width=True, disabled=ocupado):
            conversaciones.borrar(st.session_state.thread_id)
            nueva_conversacion()
            st.rerun()


# ---------------------------------------------------------------- encabezado: conversación y modelo

provider = provider_actual()
h1, h2 = st.columns([5, 2.2], vertical_alignment="center")
with h1:
    if actual:
        st.markdown(f'<p class="pw-conv">{html.escape(actual["titulo"])}</p>', unsafe_allow_html=True)
with h2:
    with st.popover(f"Modelo · {provider.etiqueta}", use_container_width=True, disabled=ocupado):
        nombres = list(PROVEEDORES)
        elegido = st.selectbox(
            "Proveedor", nombres, index=nombres.index(cfg["proveedor"]) if cfg["proveedor"] in nombres else 0,
            format_func=lambda n: PROVEEDORES[n].etiqueta, disabled=actual is not None,
            help="Una conversación guardada sigue con su proveedor; para cambiarlo, empezá una nueva.")
        clase = PROVEEDORES[elegido]
        modelo = st.text_input("Modelo", value=cfg["modelo"] if elegido == cfg["proveedor"] else "",
                               placeholder=clase.modelo_default, help="Vacío = el modelo por defecto.")
        clave, base_url = "", ""
        if clase.env_api_key:
            en_env = bool(get_provider(elegido).api_key)
            clave = st.text_input(
                "Tu clave de API", type="password", value=st.session_state.claves.get(elegido, ""),
                placeholder="usando la del .env" if en_env else "pegá tu clave",
                help="Se usa solo en esta sesión del navegador: no se guarda en disco ni se comparte.")
        else:
            base_url = st.text_input("URL del servidor local", value=cfg["base_url"] if elegido == cfg["proveedor"] else "",
                                     placeholder=clase.base_url_default)
            st.caption("El modelo tiene que soportar tool calling (ej. qwen3, llama3.1).")
        if st.button("Usar este modelo", type="primary", use_container_width=True):
            st.session_state.modelo = {"proveedor": elegido, "modelo": modelo.strip(), "base_url": base_url.strip()}
            if clave.strip():
                st.session_state.claves[elegido] = clave.strip()
            st.rerun()
    st.markdown(f'<p class="pw-meta" style="text-align:right;margin:.15rem 0 0">{provider.modelo}</p>',
                unsafe_allow_html=True)

if not provider.disponible():
    st.session_state.pendiente = None
    st.info(f"Para usar **{provider.etiqueta}** cargá tu clave de API en **Modelo** (arriba a la derecha). "
            "Se usa solo en esta sesión y no se guarda.")
    st.stop()
agent = agente_de_la_sesion(provider)

# Si la ejecución anterior se cortó a mitad de una respuesta (botón Detener, o se recargó la
# página), el turno quedó abierto: se cierra antes de mostrar el historial o seguir preguntando.
if st.session_state.generando:
    conversaciones.cerrar_turno_interrumpido(agent, st.session_state.generando)
    st.session_state.generando = None
if st.session_state.detenida:
    st.session_state.detenida = False
    st.toast("Respuesta detenida. Ya podés preguntar otra cosa.")


# ---------------------------------------------------------------- render del proceso

def render_razonamiento(texto: str):
    st.markdown(f'<div class="pw-razon">\n\n{texto}\n\n</div>', unsafe_allow_html=True)


def _resumen_argumentos(argumentos: dict) -> str:
    """Los argumentos en una línea, para leer la llamada sin abrir el JSON."""
    partes = []
    for k, v in (argumentos or {}).items():
        if isinstance(v, (list, dict)):
            v = f"[{len(v)}]"
        texto = str(v)
        partes.append(f"{k}={texto if len(texto) <= 40 else texto[:39] + '…'}")
    return ", ".join(partes)


def _resumen_resultado(resultado) -> str:
    if isinstance(resultado, dict):
        if "error" in resultado:
            return "error"
        if "decisiones_fia" in resultado:
            return (f"{len(resultado['decisiones_fia'])} decisiones · "
                    f"{len(resultado.get('race_control_openf1') or [])} mensajes de Race Control")
        if "mensajes" in resultado:
            return f"{len(resultado['mensajes'])} mensajes"
        if "archivos" in resultado:
            return f"{resultado.get('fichas', 0)} fichas"
        return "1 resultado"
    if isinstance(resultado, list):
        return f"{len(resultado)} resultados"
    return ""


def render_tool(ev: dict):
    etiqueta, clase = fuente_de(ev["tool"])
    resumen = _resumen_argumentos(ev["argumentos"])
    if "resultado" in ev:
        resumen += f"  →  {_resumen_resultado(ev['resultado'])}"
    st.markdown(f'<div class="pw-tool"><span class="pw-fuente {clase}">{etiqueta}</span><b>{html.escape(ev["tool"])}</b>'
                f'<span>{html.escape(resumen)}</span></div>', unsafe_allow_html=True)
    datos = {"argumentos": ev["argumentos"]}
    if "resultado" in ev:
        datos["resultado"] = ev["resultado"]
    st.json(datos, expanded=1)


def render_proceso(eventos: list[dict]):
    for ev in eventos:
        if ev["tipo"] == "razonamiento":
            render_razonamiento(ev["texto"])
        else:
            render_tool(ev)


def render_pregunta(texto: str):
    with st.chat_message("user"):
        st.markdown(f'<div class="pw-pregunta">\n\n{html.escape(texto)}\n\n</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------- historial (desde el checkpointer)

historial = conversaciones.turnos(agent, st.session_state.thread_id, provider) if actual else []
if not historial and not ocupado:
    st.markdown(
        '<div class="pw-portada"><div class="pw-sobre">Pit Wall Agent · Sanciones de F1</div>'
        '<h1>Preguntá por cualquier sanción</h1>'
        '<p>Te explico en simple por qué sancionaron a un piloto, con la decisión oficial de los '
        'comisarios y el artículo del reglamento que se aplicó.</p>'
        '<div class="pw-pasos">'
        '<div class="pw-paso"><b>01 · FIA</b><span>La decisión oficial</span>'
        '<small>Hecho, sanción y motivo, del documento de los comisarios.</small></div>'
        '<div class="pw-paso"><b>02 · REGLAMENTO</b><span>La regla que se aplicó</span>'
        '<small>El texto del artículo citado, de la temporada que corresponde.</small></div>'
        '<div class="pw-paso"><b>03 · INFORME</b><span>Para guardar o compartir</span>'
        '<small>Una ficha por sanción, en PDF, con un clic.</small></div>'
        '</div></div>', unsafe_allow_html=True)
    for col, (tipo, ejemplo) in zip(st.columns(len(EJEMPLOS)), EJEMPLOS):
        col.markdown(f'<div class="pw-ejemplo">{tipo}</div>', unsafe_allow_html=True)
        col.button(ejemplo, use_container_width=True, on_click=preguntar, args=(ejemplo,))

for t, turno in enumerate(historial):
    render_pregunta(turno["pregunta"])
    with st.chat_message("assistant"):
        if turno["proceso"]:
            with st.expander("Razonamiento", expanded=False):
                render_proceso(turno["proceso"])
        if turno["respuesta"] == conversaciones.INTERRUMPIDA:
            st.markdown(f'<p class="pw-interrumpida">{conversaciones.INTERRUMPIDA}</p>', unsafe_allow_html=True)
        else:
            st.markdown(turno["respuesta"])
        generados = informes_del_turno(turno["proceso"])
        for n, (ruta_html, ruta_pdf) in enumerate(generados):
            with st.expander("Informe · vista previa y descarga", expanded=t == len(historial) - 1):
                render_informe(ruta_html, ruta_pdf, clave=f"{st.session_state.thread_id}-{t}-{n}")
        # El informe se ofrece desde la interfaz (no lo ofrece el modelo en cada respuesta):
        # solo en la última respuesta, si explicó sanciones y todavía no se generó.
        if t == len(historial) - 1 and not generados and not ocupado and hay_decisiones(turno["proceso"]):
            with st.container(key="pw-acciones"):
                st.button("Generar informe en PDF", on_click=preguntar, args=(PEDIR_INFORME,),
                          help="Una ficha por sanción, con la regla aplicada y un glosario.")

st.chat_input("Respondiendo… detené la respuesta para preguntar otra cosa" if ocupado
              else "Preguntá sobre cualquier sanción de F1…", key="entrada", on_submit=enviar, disabled=ocupado)
pregunta = st.session_state.pendiente
st.session_state.pendiente = None


# ---------------------------------------------------------------- turno en streaming

if pregunta:
    conversaciones.registrar(st.session_state.thread_id, pregunta, provider.nombre)
    st.session_state.generando = st.session_state.thread_id
    render_pregunta(pregunta)
    with st.chat_message("assistant"):
        proceso_box = st.status("Razonando…", expanded=True)  # todo el proceso, en orden
        respuesta_box = st.empty()                             # solo la respuesta final
        # Un clic acá corta esta ejecución (Streamlit la interrumpe en el próximo paso del
        # stream) y arranca otra, que cierra el turno. Si hay una tool en curso, corta al terminar.
        with st.container(key="pw-detener"):
            st.button("Detener", on_click=detener, icon=":material/stop:",
                      help="Corta la respuesta para poder preguntar otra cosa.")

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
                            proceso_box.update(label=f"Consultando {fuente_de(tc['name'])[0]}…")
                    elif isinstance(m, ToolMessage) and m.tool_call_id in pendientes:
                        ev, slot = pendientes.pop(m.tool_call_id)
                        ev["resultado"] = parse_json(m.content)
                        with slot.container():
                            render_tool(ev)
                        slot_razon = None
                        proceso_box.update(label="Razonando…")
    except Exception as exc:  # ej. 429 agotados los reintentos, clave inválida, servidor local apagado
        # El error puede haber dejado una tool sin resultado: se cierra el turno para poder seguir.
        conversaciones.cerrar_turno_interrumpido(agent, st.session_state.thread_id)
        st.session_state.generando = None
        proceso_box.update(label="Error", state="error", expanded=False)
        respuesta_box.markdown(f"Ocurrió un error con el modelo: `{exc}`")
        st.stop()

    st.session_state.generando = None
    proceso_box.update(label="Razonamiento", state="complete", expanded=False)
    respuesta_box.markdown(respuesta)
    st.rerun()  # redibuja desde el checkpointer (proceso plegado, conversación en la lista)
