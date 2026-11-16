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


# La plantilla está pensada para imprimir (los márgenes los pone @page). Para verla en la app
# se le agrega una de estas dos hojas de estilo, sin tocar el archivo guardado:
#   "hoja": una página blanca simulada, como se va a ver el PDF (lista de informes);
#   "chat": el informe como parte de la conversación, con los colores de la app y sin
#           aspecto de documento (misma estructura y los mismos datos).
_ESTILOS_VISTA = {
    "hoja": "html{background:#2a2b36} body{background:#fff; max-width:210mm; margin:0 auto; "
            "padding:0 14mm 12mm; min-height:100vh}",
    "chat": """
      :root { --tinta: #e6e6ea; --gris: #a3a5b0; --linea: #2a2b36; --suave: #1f2029; --rojo: #ff5a4f; }
      html, body { background: #14151c; }
      body { zoom: 1.14; padding: 0 1px 1px; overflow: hidden; }
      .portada { background: #1f2029; margin: 0; padding: 5mm 6mm; border-radius: 2.5mm; border-left: 1.6mm solid #e8433a; }
      h1 { font-size: 22pt; margin: 1.5mm 0 1mm; }
      .meta { font-size: 9pt; }
      .cuadros { margin-top: 4mm; }
      .cuadro { background: #14151c; padding: 2.2mm 3.5mm; }
      .cuadro b { font-size: 17pt; }
      h2 { color: #fff; margin: 6mm 0 2mm; }
      .torre td { border-bottom-color: #23242e; }
      .num { color: #fff; }
      .quien b, dt, .torre b { color: #fff; }
      .insignia { background: #e8433a; }
      .insignia.leve { background: #3a3b47; }
      .regla { background: #2a1d1f; }
      .ficha-pie a { color: #ff6b61; }
      dd { color: #c9cad3; }
      @media (max-width: 640px) { dl.glosario { columns: 1; } .cuadros { flex-wrap: wrap; } }
    """,
}


def vista_previa(contenido: str, modo: str = "hoja", url_fuentes: str = "/app/static/fuentes/") -> str:
    """HTML del informe listo para mostrar dentro de la app (tipografías servidas por Streamlit).

    Los links se abren en otra pestaña: adentro del marco del chat no tendría sentido navegar.
    """
    extra = f'<base target="_blank"><style>{_ESTILOS_VISTA[modo]}</style>'
    return contenido.replace("url(fuentes/", f"url({url_fuentes}").replace("</head>", extra + "</head>", 1)


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
