"""Ingesta del corpus: documentos -> texto -> párrafos -> embeddings -> Chroma (coseno).

Párrafo = un inciso de un artículo ("B1.6.3b"), con sus sub-incisos (i., ii.) adentro.
Es la misma granularidad con la que citan los comisarios ("Breach of Article B1.6.3b"),
así la tool puede traer el párrafo exacto. El texto de un artículo sin incisos se
corta en las líneas vacías.

A cada párrafo se le antepone la cita y el título antes de calcular el embedding: un
inciso suelto ("At no time may an F1 Car be reversed...") tiene poco contexto.

Formatos soportados (se detectan por el contenido):
  - Reglamento de F1 (2025: "48.1 ... a)"; 2026: "B1.6.3 ... a.")
  - Código Deportivo Internacional (bilingüe: se toma la columna en inglés; "12.2.1.a")
  - Apéndice L del Código, Capítulo IV: código de conducción en pista ("Art. 2 d)")
  - Glosario propio en markdown ("## Término"), válido para todas las temporadas (año 0)

Convención de nombres en data/reglamento/:  <año>_<nombre>.pdf  ·  glosario.md
"""
import re
import subprocess
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from langchain_core.documents import Document

from .. import config

MAX_SANGRIA_INCISO = 16  # más sangría = sub-inciso o texto de una tabla, sigue en el mismo párrafo
MIN_CHARS = 25           # párrafos más cortos (ej. "Deleted.") no aportan
LOTE = 50                # párrafos por pedido de embeddings
NOMBRE_GLOSARIO = "Glosario Pit Wall Agent"


@dataclass(frozen=True)
class Formato:
    nombre: str
    articulo: re.Pattern       # grupos: (número, inciso en la misma línea o None, texto)
    inciso: re.Pattern | None  # grupos: (sangría, letra, texto)
    capitulo: re.Pattern       # títulos que cierran el párrafo en curso
    prefijo: str = ""          # se antepone al número de artículo (ej. "L-IV-")
    columna_derecha: bool = False  # PDFs bilingües francés | inglés
    desde: str | None = None   # recortar el texto a partir de la última aparición de esto
    hasta: str | None = None
    cita: str = "{art}{inc}"   # cómo se escribe la cita en este documento
    titulo_en_encabezado: bool = True  # False: los artículos no tienen título; se usa el del capítulo

    def citar(self, articulo: str, inciso: str) -> str:
        art = articulo.removeprefix(self.prefijo)
        if self is F1 and inciso and art[0].isdigit():  # reglamento hasta 2025: "48.1 a)"
            return f"{art} {inciso})"
        if not inciso:
            return self.cita.split("{inc}")[0].replace("{art}", art).rstrip(" .")
        return self.cita.format(art=art, inc=inciso)


F1 = Formato(
    "reglamento_f1",
    # "B1.6.3     Driving in the Pit..."  /  "48.1   Any driver who..."
    articulo=re.compile(r"^\s{0,3}((?:[A-F]\d+|\d+)(?:\.\d+)+)()\)?\s{2,}(\S.*?)\s*$"),
    inciso=re.compile(r"^(\s+)([a-z])[.)]\s+(\S.*)$"),
    # "ARTICLE B5: TOTAL TIME...", "APPENDIX B4: ...", "32)    CHANGES OF DRIVER", "SECTION B: ..."
    capitulo=re.compile(r"^\s*(?:(?:ARTICLE|APPENDIX)\s+[A-F]?\d+\s*:|\d+\)\s{2,}[A-Z])"),
)
ISC = Formato(
    "codigo_deportivo",
    # "12.2.1 Any of the following offences..."  /  "12.2.1.a All bribery..."
    articulo=re.compile(r"^\s{0,3}(\d+(?:\.\d+)+)(?:\.([a-z]))?\s+(\S.*?)\s*$"),
    inciso=None,
    capitulo=re.compile(r"^\s*(?:ARTICLE\s+\d+(?:\.\d+)?\s+[A-Z]|SECTION\s+\d+)"),
    columna_derecha=True,
    cita="{art}.{inc}",
    titulo_en_encabezado=False,
    # Solo los artículos que citan las decisiones de F1: oficiales y comisarios (11),
    # infracciones y penalizaciones (12), protestas (13), derecho de revisión (14) y apelaciones (15).
    desde="ARTICLE 11 OFFICIALS",
    hasta="ARTICLE 16 RULES",
)
APENDICE_L = Formato(
    "apendice_l_iv",
    # "2.    Overtaking, car control and track limits"
    articulo=re.compile(r"^\s{0,3}(\d+)\.()\s{2,}(\S.*?)\s*$"),
    inciso=re.compile(r"^(\s+)([a-z])\)\s*(\S.*)$"),
    capitulo=re.compile(r"^\s*CHAPTER\s+[IVX]+"),
    prefijo="L-IV-",
    columna_derecha=True,
    desde="CHAPTER IV - CODE OF DRIVING CONDUCT",
    hasta="CHAPTER V - CODE OF DRIVING CONDUCT",
    cita="Ap. L, cap. IV, art. {art} {inc})",
)
# Encabezado de sección que se repite en las páginas ("SECTION B: SPORTING REGULATIONS", "B"):
# se descarta sin cortar el artículo en curso (puede quedar en medio de un artículo).
SECCION_RE = re.compile(r"^\s*(SECTION [A-F]:.*|[A-F])\s*$")


# ---------------------------------------------------------------- texto

def pdf_a_texto(path: Path, columna_derecha: bool = False) -> str:
    cmd = ["pdftotext", "-layout"]
    if columna_derecha:  # A4: 595 pt de ancho; el inglés va en la mitad derecha
        cmd += ["-x", "297", "-y", "0", "-W", "300", "-H", "842"]
    return subprocess.run(cmd + [str(path), "-"], check=True, capture_output=True, text=True).stdout


def detectar_formato(texto: str) -> Formato:
    inicio = texto[:20000]
    # El orden importa: el reglamento de F1 menciona al Código y a sus apéndices.
    if re.search(r"FORMULA (?:1|ONE)\s+(?:SPORTING\s+)?REGULATIONS", inicio, re.I):
        return F1
    if re.search(r"APPENDIX L|ANNEXE L", inicio):
        return APENDICE_L
    if re.search(r"INTERNATIONAL SPORTING CODE|CODE SPORTIF INTERNATIONAL", inicio, re.I):
        return ISC
    return F1


def _recortar(texto: str, formato: Formato) -> str:
    if formato.desde and formato.desde in texto:
        texto = texto[texto.rindex(formato.desde):]  # la última aparición: la primera es el índice
    if formato.hasta and formato.hasta in texto:
        texto = texto[:texto.rindex(formato.hasta)]
    return texto


def _clave(linea: str) -> str:
    # Se comparan sin números ni espacios extra: el pie trae el número de página y su
    # alineación cambia de una página a otra.
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", linea)).strip()


def _encabezados(texto: str) -> dict[str, str]:
    """Líneas que se repiten arriba/abajo en muchas páginas: {clave: un ejemplo original}."""
    paginas = [p.splitlines() for p in texto.split("\f")]
    conteo, ejemplo = Counter(), {}
    for lineas in paginas:
        utiles = [l for l in lineas if l.strip()]
        for l in utiles[:3] + utiles[-3:]:
            ejemplo.setdefault(_clave(l), l)
        conteo.update({_clave(l) for l in utiles[:3] + utiles[-3:]})
    return {k: ejemplo[k] for k, n in conteo.items() if len(paginas) >= 3 and n >= 0.3 * len(paginas)}


def quitar_encabezados(texto: str) -> list[str]:
    """Saca encabezados y pies de página."""
    repetidas = _encabezados(texto)
    return [l for l in texto.replace("\f", "\n").splitlines() if _clave(l) not in repetidas]


def nombre_reglamento(texto: str, archivo: Path, formato: Formato = F1) -> str:
    """Nombre oficial para citar, con la fecha de la versión entre paréntesis.

    Reglamento F1: sale del pie de página ("2026 Formula 1 Regulations - Section B [Sporting]
    ... 01 October 2026" + "Issue 09"). Código y Apéndice L: del encabezado "Application from
    26th June 2026".
    """
    año = re.match(r"(\d{4})", archivo.name)
    año = año.group(1) if año else ""
    pies = list(_encabezados(texto).values())
    if formato is not F1:
        m = re.search(r"Application from (\d{1,2})(?:st|nd|rd|th)? (\w+ \d{4})", texto)
        fecha = f" ({int(m.group(1)):02d} {m.group(2)})" if m else ""
        nombre = f"FIA International Sporting Code {año}"
        return nombre + (", Appendix L, Chapter IV" if formato is APENDICE_L else "") + fecha
    titulo = next((l for l in pies if re.search(r"Regulations", l)), None)
    if not titulo:
        return archivo.stem.replace("_", " ")
    partes = [p.strip() for p in re.split(r"\s{2,}", titulo.strip()) if p.strip()]
    nombre, fecha = partes[0], next((p for p in partes[1:] if re.search(r"\d{4}", p)), None)
    issue = next((m.group(0) for l in pies if (m := re.search(r"Issue\s+\d+", l))), None)
    return nombre + (f", {issue}" if issue else "") + (f" ({fecha})" if fecha else "")


def _partir(texto: str, maximo: int) -> list[str]:
    """Parte un párrafo largo en pedazos de hasta `maximo` caracteres, por oraciones."""
    if len(texto) <= maximo:
        return [texto]
    partes, actual = [], ""
    for oracion in re.split(r"(?<=[.;:])\s+", texto):
        if actual and len(actual) + len(oracion) + 1 > maximo:
            partes.append(actual)
            actual = ""
        actual = f"{actual} {oracion}".strip()
    return partes + [actual] if actual else partes


def _titulo_util(texto: str, capitulo: str) -> str:
    """El encabezado del artículo si es un título; si es la primera oración, el del capítulo."""
    if capitulo and (len(texto) > 90 or texto.rstrip().endswith((".", ",", ";"))):
        return capitulo
    return texto


# ---------------------------------------------------------------- párrafos

def parrafos(texto: str, base_meta: dict, maximo: int = config.RAG_MAX_CHARS_PARRAFO,
             formato: Formato = F1) -> list[Document]:
    out, articulo, titulo, inciso, buffer, capitulo = [], None, "", "", [], ""
    vistos = set()

    def cerrar():
        cuerpo = re.sub(r"\s+", " ", " ".join(buffer)).strip()
        if not articulo or len(cuerpo) < MIN_CHARS:
            return
        cita = formato.citar(articulo, inciso)
        for n, parte in enumerate(_partir(cuerpo, maximo)):
            if (cita, n, parte[:60]) in vistos:  # el índice del PDF repite títulos
                continue
            vistos.add((cita, n, parte[:60]))
            out.append(Document(
                page_content=f"{cita} · {titulo}\n{parte}",
                metadata={**base_meta, "articulo": articulo, "inciso": inciso, "cita": cita,
                          "titulo": titulo, "parte": n},
            ))

    for linea in quitar_encabezados(_recortar(texto, formato)):
        if SECCION_RE.match(linea):
            continue
        if formato.capitulo.match(linea):
            cerrar()
            articulo, inciso, buffer = None, "", []
            capitulo = re.sub(r"\s+", " ", re.sub(r"^\s*(?:ARTICLE\s+\S+|\d+\))\s*:?\s*", "", linea)).strip().capitalize()
            continue
        m = formato.articulo.match(linea)
        if m:
            cerrar()
            articulo = formato.prefijo + m.group(1)
            inciso = m.group(2) or ""
            if inciso:  # ISC: "12.2.1.a All bribery..." -> el texto es el cuerpo del inciso
                buffer = [m.group(3)]
            else:
                titulo = _titulo_util(m.group(3), capitulo) if formato.titulo_en_encabezado else (capitulo or m.group(3))
                buffer = []
                if titulo != m.group(3):  # el encabezado era la primera oración: va al cuerpo
                    buffer = [m.group(3)]
            continue
        it = formato.inciso.match(linea) if formato.inciso else None
        if it and articulo and len(it.group(1)) < MAX_SANGRIA_INCISO:
            cerrar()
            inciso, buffer = it.group(2), [it.group(3)]
            continue
        if not linea.strip():
            if not inciso and buffer:  # texto del artículo sin incisos: corta en la línea vacía
                cerrar()
                buffer = []
            continue
        buffer.append(linea.strip())
    cerrar()
    return out


def parrafos_glosario(texto: str, fuente: str) -> list[Document]:
    """Glosario en markdown: cada "## Término" es un párrafo, válido para todos los años (año 0)."""
    out = []
    for bloque in re.split(r"^##\s+", texto, flags=re.M)[1:]:
        termino, _, definicion = bloque.partition("\n")
        definicion = re.sub(r"\s+", " ", definicion).strip()
        if termino.strip() and definicion:
            out.append(Document(
                page_content=f"Glosario · {termino.strip()}\n{definicion}",
                metadata={"fuente": fuente, "reglamento": NOMBRE_GLOSARIO, "año": 0,
                          "articulo": "glosario", "inciso": "", "cita": termino.strip(),
                          "titulo": termino.strip(), "parte": 0},
            ))
    return out


def documentos_de(path: Path) -> list[Document]:
    """Párrafos de un archivo del corpus (PDF de reglamento o glosario .md)."""
    if path.suffix == ".md":
        return parrafos_glosario(path.read_text(encoding="utf-8"), path.name)
    formato = detectar_formato(pdf_a_texto(path))
    texto = pdf_a_texto(path, columna_derecha=formato.columna_derecha)
    año = re.match(r"(\d{4})_", path.name)
    meta = {"fuente": path.name, "reglamento": nombre_reglamento(texto, path, formato),
            "año": int(año.group(1)) if año else 0}
    return parrafos(texto, meta, formato=formato)


# ---------------------------------------------------------------- carga

PAUSA_LOTE = 31  # s entre lotes de 50: el tier gratuito permite 100 embeddings por minuto
# El tier gratuito también tiene un tope de 1000 embeddings por día (compartido con las
# búsquedas del agente): la ingesta se detiene sin error y se retoma al otro día.


class LimiteDiario(Exception):
    pass


def _prioridad(path: Path) -> tuple:
    """Orden de carga: glosario, después lo más nuevo y lo más citado; lo más grande al final."""
    if path.suffix == ".md":
        return (0,)
    año = re.match(r"(\d{4})_", path.name)
    orden_formato = {"appendix_l": 0, "f1_": 1, "international_sporting_code": 2}
    tipo = next((v for k, v in orden_formato.items() if k in path.name), 3)
    return (1, -(int(año.group(1)) if año else 0), tipo, path.name)


def _agregar_con_reintentos(store, docs, ids, intentos: int = 6):
    """Si igual llega un 429, espera lo que pide Google ("retry in 30s") y reintenta."""
    for intento in range(intentos):
        try:
            return store.add_documents(docs, ids=ids)
        except Exception as exc:  # noqa: BLE001
            texto = str(exc)
            if "per day" in texto or "PerDay" in texto:
                raise LimiteDiario(texto) from exc
            if ("429" not in texto and "RESOURCE_EXHAUSTED" not in texto) or intento == intentos - 1:
                raise
            espera = re.search(r"retry in ([0-9.]+)s", texto)
            time.sleep(float(espera.group(1)) + 2 if espera else 35)


def ingestar(directorio: Path = config.REGLAMENTO_DIR, desde_cero: bool = False, maximo: int | None = None,
             log=print) -> int:
    """Carga en Chroma los párrafos del corpus que todavía no están.

    Es incremental y se puede cortar y retomar: los ids de los párrafos son fijos
    (archivo + cita + número), así que solo se calculan los embeddings que faltan.
    Con `desde_cero=True` se borra la colección y se carga todo. `maximo` limita cuántos
    párrafos se cargan en esta corrida (para dejar cupo diario a las búsquedas del agente).
    """
    from .store import get_vectorstore

    archivos = sorted([*directorio.glob("*.pdf"), *directorio.glob("*.md")], key=_prioridad)
    if not archivos:
        raise SystemExit(f"No hay documentos en {directorio}. Ver README › Corpus del reglamento.")
    store = get_vectorstore()
    if desde_cero:
        store.reset_collection()
    existentes = set(store.get(include=[])["ids"])
    total, ultimo_lote = 0, 0.0
    for path in archivos:
        docs = documentos_de(path)
        ids = [f"{d.metadata['fuente']}:{d.metadata['cita']}:{d.metadata['parte']}:{n}" for n, d in enumerate(docs)]
        faltan = [(d, i) for d, i in zip(docs, ids) if i not in existentes]
        if not faltan:
            log(f"{path.name}: completo ({len(docs)} párrafos)")
            continue
        for k in range(0, len(faltan), LOTE):
            if maximo is not None and total >= maximo:
                log(f"Se cargaron {total} párrafos (máximo de esta corrida). Volver a correr para seguir.")
                return total
            espera = ultimo_lote + PAUSA_LOTE - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            ultimo_lote = time.monotonic()
            lote = faltan[k:k + LOTE][:None if maximo is None else maximo - total]
            try:
                _agregar_con_reintentos(store, [d for d, _ in lote], [i for _, i in lote])
            except LimiteDiario:
                log(f"Se alcanzó el límite diario de embeddings del tier gratuito ({total} párrafos cargados "
                    "en esta corrida). Volver a correr mañana: retoma donde quedó.")
                return total
            total += len(lote)
            log(f"{path.name}: {len(docs) - len(faltan) + k + len(lote)}/{len(docs)} párrafos")
    return total
