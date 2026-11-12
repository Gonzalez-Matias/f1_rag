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
