"""UI "Pit Wall Agent" en Streamlit (estilos en static/app.css).

- Barra lateral: logo, nueva conversación y conversaciones guardadas. Cada una tiene un menú
  (tres puntos) para eliminarla, y la abierta muestra sus informes como subsección.
- Arriba a la derecha: el modelo. El usuario elige proveedor y modelo y puede traer su
  propia clave: se guarda solo en la sesión del navegador, nunca en disco.
- Centro: el chat. Cada respuesta tiene un bloque desplegable "Razonamiento" con todo
  el proceso en orden (razonamiento del modelo y cada tool, con su fuente, argumentos y
  resultado en JSON). Afuera del bloque queda solo la respuesta final.
- Informe: cuando el agente explica sanciones de una carrera, el informe (una ficha por
  sanción) es la respuesta: se ve en el chat, sin texto antes, y se descarga en PDF o HTML. Los informes quedan en la barra lateral,
  debajo de su conversación.
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
from agente_f1.llm import PROVEEDORES, get_provider, listar_modelos_proveedor
from agente_f1.util import parse_json

st.set_page_config(page_title="Pit Wall Agent", layout="wide")

st.markdown(f"<style>\n{(config.ROOT / 'static' / 'app.css').read_text(encoding='utf-8')}\n</style>",
            unsafe_allow_html=True)

EJEMPLOS = [
    ("Un piloto en una carrera", "¿Por qué sancionaron a Bearman en São Paulo 2026?"),
    ("Última sanción", "¿Cuál fue la última sanción de Hamilton?"),
    ("Carrera completa", "¿Quiénes fueron sancionados en la quinta carrera de 2025?"),
]
PEDIR_INFORME = "Armame el informe en PDF de las sanciones que acabás de explicar."

# Fuente de cada tool, para la etiqueta del bloque "Razonamiento": (texto, clase CSS)
TOOLS_CONJUNTAS = {"sanciones_de_piloto_completo", "sanciones_de_carrera_completo", "ultimas_sanciones_de_piloto_completo"}
FUENTE_LOCAL = {"buscar_en_reglamento": "Reglamento", "generar_informe": "Informe"}


def fuente_de(tool: str) -> tuple[str, str]:
    if tool.startswith("fia_"):
        return "FIA", "fia"
    if tool.startswith("openf1_"):
        return "OpenF1", "openf1"
    if tool in TOOLS_CONJUNTAS:
        return "OpenF1 + FIA", "mixta"
    return FUENTE_LOCAL.get(tool, "Tool"), "local"


# ---------------------------------------------------------------- estado

def nueva_conversacion():
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.recien_respondida = None


def abrir(thread_id: str):
    st.session_state.thread_id = thread_id
    st.session_state.recien_respondida = None
    conv = conversaciones.obtener(thread_id)
    if conv and conv["proveedor"] in PROVEEDORES:
        st.session_state.modelo["proveedor"] = conv["proveedor"]  # cada conversación sigue con su proveedor


def eliminar(thread_id: str):
    conversaciones.borrar(thread_id)
    if thread_id == st.session_state.thread_id:
        nueva_conversacion()


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
# Conversación cuya última respuesta se acaba de generar en esta sesión: su bloque
# "Razonamiento" queda abierto al terminar, como estaba durante la respuesta.
st.session_state.setdefault("recien_respondida", None)

# Hay una pregunta por responder en esta ejecución: se bloquea todo lo que cambiaría de contexto.
ocupado = st.session_state.pendiente is not None
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
    # La fecha entra en la huella: el prompt dice qué día es, así que el agente se rearma cada día.
    huella = hashlib.sha256(f"{provider.nombre}|{provider.modelo}|{provider.base_url}|{provider.api_key}|"
                            f"{datetime.now():%Y-%m-%d}".encode()).hexdigest()
    agentes = st.session_state.setdefault("_agentes", {})
    if huella not in agentes:
        agentes.clear()
        agentes[huella] = build_agent(provider, checkpointer=conversaciones.get_checkpointer())
    return agentes[huella]


# ---------------------------------------------------------------- informes

def render_informe(ruta_html: Path, ruta_pdf: Path | None, clave: str):
    """El informe en pantalla y, debajo, sus descargas (los archivos se leen recién al descargar).

    El HTML sale de nuestra plantilla (Jinja con autoescape): los textos del modelo van escapados.
    """
    st.iframe(informe_render.vista_previa(ruta_html.read_text(encoding="utf-8")), height="content")
    columnas = st.columns([1.3, 1.3, 3])
    if ruta_pdf and ruta_pdf.exists():
        columnas[0].download_button("Descargar PDF", ruta_pdf.read_bytes, file_name=ruta_pdf.name,
                                    mime="application/pdf", key=f"dl-{clave}-pdf", type="primary", width="stretch")
    else:
        columnas[0].caption("PDF no disponible en este servidor")
    columnas[1].download_button("Descargar HTML", ruta_html.read_bytes, file_name=ruta_html.name,
                                mime="text/html", key=f"dl-{clave}-html", width="stretch")


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
        if tool in TOOLS_CONJUNTAS and isinstance(resultado, dict) and any(
                resultado.get(k) for k in ("decisiones_fia", "sanciones_en_pista")):
            return True
        if tool.startswith("fia_") and resultado and not (isinstance(resultado, dict) and
                                                         ("error" in resultado or "resultado" in resultado)):
            return True
    return False


# ---------------------------------------------------------------- barra lateral

with st.sidebar:
    st.markdown('<img class="pw-logo" src="app/static/logo.png" alt="Pit Wall Agent">'
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
            thread_id = conv["thread_id"]
            activa = thread_id == st.session_state.thread_id
            # La fila es la caja de la conversación: título y, adentro, el menú de los tres puntos.
            with st.container(key=f"fila-{'on-' if activa else ''}{thread_id}", horizontal=True, gap=None,
                              vertical_alignment="center"):
                st.button(conv["titulo"], key=f"conv-{thread_id}", width="stretch",
                          type="tertiary" if activa else "secondary", disabled=activa or ocupado,
                          help=f"{conv['proveedor']} · {datetime.fromtimestamp(conv['actualizada']):%d/%m %H:%M}",
                          on_click=abrir, args=(thread_id,))
                with st.popover(":material/more_vert:", key=f"menu-{thread_id}", help="Opciones", disabled=ocupado):
                    st.button("Eliminar conversación", key=f"borrar-{thread_id}", icon=":material/delete:",
                              type="tertiary", on_click=eliminar, args=(thread_id,))
            # Los informes son una subsección de su conversación: se ven debajo de la abierta.
            informes = [informe_render.leer(r) for r in conversaciones.rutas_de_informes(thread_id)] if activa else []
            if informes:
                with st.container(key="informes-conv", gap=None):
                    st.markdown('<div class="pw-subseccion">Informes</div>', unsafe_allow_html=True)
                    for inf in informes:
                        # "Gran Premio de São Paulo 2026 - ..." -> "São Paulo 2026 - ..."
                        corto = re.sub(r"^Gran Premio (?:de la |del |de )", "", inf["titulo"])
                        if st.button(corto, key=f"inf-{inf['html'].stem}", width="stretch", disabled=ocupado,
                                     icon=":material/description:",
                                     help=f"{inf['titulo']} · generado el {inf['generado']:%d/%m/%Y a las %H:%M}"):
                            abrir_informe(inf)


# ---------------------------------------------------------------- encabezado: conversación y modelo

provider = provider_actual()
h1, h2 = st.container(key="pw-encabezado").columns([5, 2.2], vertical_alignment="center")
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
            return (f"{len(resultado['decisiones_fia'])} decisiones FIA · "
                    f"{len(resultado.get('sanciones_en_pista') or [])} en Race Control · "
                    f"{len(resultado.get('solo_en_race_control') or [])} sin documento")
        if "sanciones" in resultado:
            return f"{len(resultado['sanciones'])} sanciones · {len(resultado.get('banderas') or [])} banderas"
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
        '<div class="pw-portada"><div class="pw-sobre">Sanciones de Fórmula 1</div>'
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
            recien = t == len(historial) - 1 and st.session_state.recien_respondida == st.session_state.thread_id
            with st.expander("Razonamiento", expanded=recien):
                render_proceso(turno["proceso"])
        generados = informes_del_turno(turno["proceso"])
        if turno["respuesta"] == conversaciones.INTERRUMPIDA:
            st.markdown(f'<p class="pw-interrumpida">{conversaciones.INTERRUMPIDA}</p>', unsafe_allow_html=True)
        elif not generados:
            st.markdown(turno["respuesta"])
        # Si hay informe, el informe es la respuesta: va solo, con la descarga, y no se muestra
        # el texto del modelo (que en ese caso es apenas un "Informe listo.").
        for n, (ruta_html, ruta_pdf) in enumerate(generados):
            render_informe(ruta_html, ruta_pdf, clave=f"{st.session_state.thread_id}-{t}-{n}")
        # Si el modelo explicó sanciones sin armar el informe (ej. varias carreras), se puede
        # pedir desde acá: solo en la última respuesta.
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
        # Todo el proceso, en orden. Arranca abierto y durante la respuesta no se le hace
        # ningún update(): cada update vuelve a plegar el bloque, aunque el usuario lo haya abierto.
        proceso_box = st.status("Razonamiento", expanded=True)
        actividad = st.empty()                                 # qué está haciendo ahora
        respuesta_box = st.empty()                             # solo la respuesta final
        # Un clic acá corta esta ejecución (Streamlit la interrumpe en el próximo paso del
        # stream) y arranca otra, que cierra el turno. Si hay una tool en curso, corta al terminar.
        with st.container(key="pw-detener"):
            st.button("Detener", on_click=detener, icon=":material/stop:",
                      help="Corta la respuesta para poder preguntar otra cosa.")

    respuesta, texto_razon = "", ""
    informe_listo = False  # ya se generó el informe: lo que escriba el modelo después no se muestra
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
                if frag.texto and not informe_listo:
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
                            actividad.markdown(f'<p class="pw-actividad">Consultando {fuente_de(tc["name"])[0]}…</p>',
                                               unsafe_allow_html=True)
                    elif isinstance(m, ToolMessage) and m.tool_call_id in pendientes:
                        ev, slot = pendientes.pop(m.tool_call_id)
                        ev["resultado"] = parse_json(m.content)
                        with slot.container():
                            render_tool(ev)
                        slot_razon = None
                        informe_listo = informe_listo or bool(informes_del_turno([ev]))
                        actividad.markdown(f'<p class="pw-actividad">{"Mostrando el informe…" if informe_listo else "Razonando…"}</p>',
                                           unsafe_allow_html=True)
    except Exception as exc:  # ej. 429 agotados los reintentos, clave inválida, servidor local apagado
        # El error puede haber dejado una tool sin resultado: se cierra el turno para poder seguir.
        conversaciones.cerrar_turno_interrumpido(agent, st.session_state.thread_id)
        st.session_state.generando = None
        proceso_box.update(label="Error", state="error", expanded=False)
        actividad.empty()
        respuesta_box.markdown(f"Ocurrió un error con el modelo: `{exc}`")
        st.stop()

    st.session_state.generando = None
    st.session_state.recien_respondida = st.session_state.thread_id
    actividad.empty()
    respuesta_box.markdown(respuesta)
    st.rerun()  # redibuja desde el checkpointer (informe, botones, conversación en la lista)
