"""Helpers compartidos por varios módulos."""
import json
import re
import unicodedata
from functools import wraps


def normalizar(texto: str | None) -> str:
    """Minúsculas, sin acentos y con espacios simples: 'São  Paulo' -> 'sao paulo'."""
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).lower().strip()


def parse_json(texto):
    """JSON -> objeto; si no es JSON válido devuelve el texto tal cual."""
    try:
        return json.loads(texto)
    except (TypeError, ValueError):
        return texto


def a_json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1)


def seguro(fn):
    """Envuelve una tool para que:

    - siempre devuelva JSON como texto (lo que mejor entiende el modelo, y la UI
      puede parsearlo para mostrar el proceso);
    - convierta cualquier excepción en {"error": ...}: el modelo recibe el error
      como resultado de la tool y decide qué hacer, sin cortar el flujo del agente.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return a_json(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001 - a propósito: ningún error corta el flujo
            return a_json({"error": f"{type(exc).__name__}: {exc}"})
    return wrapper
