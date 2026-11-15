"""Plantilla -> HTML y PDF."""
import re
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import config
from ..util import normalizar

AQUI = Path(__file__).parent
ESTATICO = config.ROOT / "static"  # tipografías (compartidas con la UI)
_env = Environment(loader=FileSystemLoader(AQUI), autoescape=select_autoescape(["html"]))


def html(datos: dict) -> str:
    return _env.get_template("plantilla.html").render(**datos)


def guardar(datos: dict, destino: Path = config.INFORMES_DIR) -> dict:
    """Escribe el informe en HTML y en PDF. Devuelve las rutas relativas a la raíz del proyecto.

    Si WeasyPrint no está disponible (en Windows necesita librerías del sistema),
    se genera solo el HTML, que se puede imprimir a PDF desde el navegador.
    """
    destino.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", normalizar(datos["gp"]["nombre"])).strip("-")[:60] or "informe"
    base = destino / f"{datetime.now():%Y%m%d-%H%M%S}-{slug}"
    contenido = html(datos)
    base.with_suffix(".html").write_text(contenido, encoding="utf-8")
    out = {"html": str(base.with_suffix(".html").relative_to(config.ROOT))}
    try:
        from weasyprint import HTML
        # base_url: las tipografías están en static/fuentes (las comparte con la UI)
        # La "/" final importa: sin ella, "fuentes/..." se resuelve contra la carpeta de arriba.
        HTML(string=contenido, base_url=ESTATICO.as_uri() + "/").write_pdf(base.with_suffix(".pdf"))
        out["pdf"] = str(base.with_suffix(".pdf").relative_to(config.ROOT))
    except (ImportError, OSError) as exc:  # OSError: faltan las librerías del sistema (Pango)
        out["aviso"] = f"No se pudo generar el PDF ({exc}); quedó solo el HTML."
    return out


# Hoja simulada para ver el informe en pantalla: la plantilla está pensada para imprimir
# (los márgenes los pone @page), así que acá se agregan como relleno del body.
_ESTILO_VISTA = ("<style>html{background:#2a2b36} body{background:#fff; max-width:210mm; margin:0 auto; "
                 "padding:0 14mm 12mm; min-height:100vh}</style>")


def vista_previa(contenido: str, url_fuentes: str = "/app/static/fuentes/") -> str:
    """HTML del informe listo para mostrar dentro de la app (tipografías servidas por Streamlit)."""
    return contenido.replace("url(fuentes/", f"url({url_fuentes}").replace("</head>", _ESTILO_VISTA + "</head>", 1)


def listar(destino: Path = config.INFORMES_DIR, maximo: int | None = None) -> list[dict]:
    """Informes generados, del más nuevo al más viejo: {"titulo", "generado", "html", "pdf"}."""
    out = []
    for ruta in sorted(destino.glob("*.html"), reverse=True)[:maximo]:
        cabecera = ruta.read_text(encoding="utf-8", errors="replace")[:600]
        titulo = re.search(r"<title>(?:Informe de sanciones · )?(.*?)</title>", cabecera, re.S)
        try:
            generado = datetime.strptime(ruta.name[:15], "%Y%m%d-%H%M%S")
        except ValueError:
            generado = datetime.fromtimestamp(ruta.stat().st_mtime)
        pdf = ruta.with_suffix(".pdf")
        out.append({"titulo": titulo.group(1).strip() if titulo else ruta.stem, "generado": generado,
                    "html": ruta, "pdf": pdf if pdf.exists() else None})
    return out
