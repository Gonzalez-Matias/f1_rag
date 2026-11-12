"""Extrae los datos de un PDF de decisión de los comisarios FIA (solo lectura; la
descarga la hace scraper.py).

Probar con un PDF local:
    python -m agente_f1.fuentes.fia.parser decision.pdf

Requiere `pdftotext` (paquete poppler-utils).
"""
import json
import re
import subprocess
import sys

# Campos de la tabla central del documento, en el orden en que aparecen.
# "Offence" se usaba hasta ~2019; después pasó a "Infringement".
FIELDS = {
    "No / Driver": "driver",
    "Competitor": "competitor",
    "Time": "time",
    "Session": "session",
    "Fact": "fact",
    "Infringement": "infringement",
    "Offence": "infringement",
    "Decision": "decision",
    "Reason": "reason",
}
# Las etiquetas van en la columna 0 o 1 según el documento.
FIELD_RE = re.compile(r"^ ?(" + "|".join(re.escape(k) for k in FIELDS) + r")\s+(.*)$")
TABLE_HEADER_RE = re.compile(r"^ ?No\.?\s{2,}")
BOILERPLATE_RE = re.compile(
    r"^\s*(Note\s+)?(Competitors are reminded|Decisions of the Stewards are taken)")
# Ejemplos: "B1.6.3b", "12.1.1.i", "33.4", "Appendix L Chapter IV Article 2d"
ARTICLE_RE = re.compile(
    r"((?:Appendix\s+\w+\s+)?(?:Chapter\s+[IVX]+\s+)?)"  # prefijo opcional
    r"Articles?\s+([A-Z]?\d+(?:\.\d+)*(?:\.?[a-z]{1,4}\b|\s?[a-z]\))?)")
# Reglamento al que pertenece: "... of the FIA F1 Regulations", "... of the International Sporting Code"
REG_RE = re.compile(r"^\s+of\s+the\s+((?:FIA\s+)?[\w ]+?(?:Regulations|Code))")


def extract_articles(text: str):
    """Devuelve [{"article": "B1.6.3b", "regulation": "FIA F1 Regulations"}, ...]."""
    found = []
    matches = list(ARTICLE_RE.finditer(text))
    for n, m in enumerate(matches):
        # El reglamento puede aparecer después del artículo siguiente
        # ("Article X and Article Y of the ..."): se busca hacia adelante.
        reg = None
        for later in matches[n:]:
            r = REG_RE.match(text[later.end():])
            if r:
                reg = r.group(1)
                break
        prefix = m.group(1).strip()
        article = f"{prefix} Article {m.group(2)}" if prefix else m.group(2)
        found.append({"article": article, "regulation": reg})
    return found


def pdf_to_text(path: str) -> str:
    return subprocess.run(
        ["pdftotext", "-layout", path, "-"],
        check=True, capture_output=True, text=True,
    ).stdout


def collapse(lines):
    """Une las líneas de un campo en un solo texto, conservando párrafos."""
    text = "\n".join(l.strip() for l in lines).strip()
    text = re.sub(r"\n{2,}", "\n\n", text)
    return re.sub(r"(?<!\n)\n(?!\n)", " ", text)


def drop_cover_pages(text: str) -> str:
    """Algunos documentos traen una portada (Title / Description / Enclosed)."""
    pages = text.split("\f")
    body = [p for p in pages if not re.search(r"^Enclosed\s", p, re.M)]
    return "\f".join(body or pages)


def parse_table(lines):
    """Parsea una tabla alineada por columnas (ej. lista de autos).

    Las columnas del encabezado se separan por 2+ espacios. Si un grupo del
    encabezado tiene varias palabras ("Turn Car") y las filas tienen la misma
    cantidad de valores en esa zona, se separa en varias columnas.
    """
    header, rows = lines[0], [l for l in lines[1:] if l.strip()]
    groups = [(m.start(), m.group()) for m in re.finditer(r"\S+(?: \S+)*", header)]
    bounds = [g[0] for g in groups[1:]] + [None]
    columns = []  # (inicio, fin, [nombres])
    for (start, name), end in zip(groups, bounds):
        words = name.split(" ")
        cells = [re.split(r"\s{2,}", r[start:end].strip()) for r in rows]
        if len(words) > 1 and cells and all(len(c) == len(words) for c in cells):
            columns.append((start, end, words))
        else:
            columns.append((start, end, [name]))
    table = []
    for r in rows:
        row = {}
        for start, end, names in columns:
            raw = r[start:end].strip()
            vals = re.split(r"\s{2,}", raw) if len(names) > 1 else [raw]
            row.update(zip(names, vals))
        table.append(row)
    return table


def parse(text: str) -> dict:
    lines = drop_cover_pages(text).replace("\f", "\n").splitlines()
    out = {"event": None, "event_dates": None, "from": None, "to": None,
           "document": None, "date": None, "published_time": None}

    # Encabezado: nombre del evento y fechas (primeras líneas no vacías).
    head = [l.strip() for l in lines if l.strip()][:2]
    if head:
        out["event"] = head[0]
    if len(head) > 1:
        out["event_dates"] = head[1]

    # Bloque From/To con la columna derecha Document/Date/Time.
    i = 0
    to_lines = []
    while i < len(lines) and not lines[i].startswith("The Stewards,"):
        line = lines[i]
        right = re.search(r"\s{2,}(Document|Date|Time)\s+(.+?)\s*$", line)
        if right:
            key = {"Document": "document", "Date": "date", "Time": "published_time"}[right.group(1)]
            out[key] = right.group(2)
            line = line[: right.start()]
        m = re.match(r"^ ?(From|To)\s+(.*)$", line)
        if m:
            if m.group(1) == "From":
                out["from"] = m.group(2).strip()
            else:
                to_lines.append(m.group(2))
        elif to_lines and line.strip():
            to_lines.append(line)
        i += 1
    out["to"] = collapse(to_lines) or None

    # Intro ("The Stewards, having received a report from ...").
    intro = []
    while i < len(lines) and not FIELD_RE.match(lines[i]):
        intro.append(lines[i])
        i += 1
    out["intro"] = collapse(intro) or None

    # Tabla central: cada etiqueta arranca en la columna 0; las líneas
    # siguientes que empiezan con espacios son continuación del valor.
    fields, current, rest, table = {}, None, [], []
    while i < len(lines):
        line = lines[i]
        if BOILERPLATE_RE.match(line):
            rest = lines[i:]
            break
        if TABLE_HEADER_RE.match(line):
            # La tabla termina en la próxima etiqueta de campo.
            j = i + 1
            while j < len(lines) and not FIELD_RE.match(lines[j]):
                j += 1
            table = parse_table(lines[i:j])
            i = j
            continue
        m = FIELD_RE.match(line)
        # "Time" también aparece dentro del texto: solo es etiqueta si aún no se usó.
        if m and FIELDS[m.group(1)] not in fields:
            current = FIELDS[m.group(1)]
            fields[current] = [m.group(2)]
        elif current:
            fields[current].append(line)
        i += 1
    for key, val in fields.items():
        out[key] = collapse(val)

    # Firmas: nombres entre el texto estándar y "The Stewards" final.
    stewards = []
    for line in rest:
        if BOILERPLATE_RE.match(line) or line.startswith(" "):
            continue
        if line.strip() == "The Stewards":
            break
        stewards += [n.strip() for n in re.split(r"\s{2,}", line) if n.strip()]
    out["stewards"] = stewards
    out["cars"] = table  # solo en documentos que afectan a varios autos

    # Derivados útiles.
    drv = re.match(r"^(\d+)\s*-\s*(.+)$", out.get("driver") or "")
    out["car_number"] = int(drv.group(1)) if drv else None
    out["driver_name"] = drv.group(2).strip() if drv else None
    out["articles"] = extract_articles(out.get("infringement") or "")
    return out


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(json.dumps(parse(pdf_to_text(sys.argv[1])), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
