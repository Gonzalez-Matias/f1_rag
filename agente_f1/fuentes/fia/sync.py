"""Mantener el índice al día.

- indexar(): una vez, guarda título y URL de todos los documentos (sin PDFs).
- auto_actualizar(): antes de cada consulta, pregunta a OpenF1 si hubo sesiones
  desde la última sincronización y actualiza solo esas carreras (1 pedido cada una).
"""
from .. import openf1
from ...util import normalizar
from . import scraper
from .cache import ahora, conectar, meta

POST_SESION = 48 * 3600       # tras una sesión, la FIA publica decisiones durante horas o días
INTERVALO_CHEQUEO = 15 * 60   # mínimo entre chequeos con OpenF1
REINTENTO_TEMPORADA = 6 * 3600


def indexar(desde_año: int = 2019, hasta_año: int | None = None, log=print) -> None:
    """Guarda título y URL de todos los documentos, sin bajar PDFs (~35 min desde 2019).

    Se puede cortar y volver a correr: retoma donde quedó.
    """
    con = conectar()
    con.execute("DELETE FROM seasons")  # por si apareció una temporada nueva
    con.commit()
    seasons = scraper.temporadas(con)
    for año in sorted((y for y in seasons if desde_año <= y <= (hasta_año or max(seasons))), reverse=True):
        for carrera in scraper.carreras(con, año, ttl=0):
            pendiente = con.execute("SELECT docs_fetched_at IS NULL FROM events WHERE event_id=?",
                                    (carrera["event_id"],)).fetchone()[0]
            # Las 2 últimas carreras se vuelven a listar siempre: la anterior
            # puede haber recibido documentos después de la última pasada.
            docs = scraper.documentos(con, carrera, ttl=0, recientes=2)
            if pendiente:
                log(f"{año} {carrera['name']}: {len(docs)} documentos")
    meta(con, "last_sync", ahora())
    meta(con, "last_check", ahora())


def _actualizar_carrera(con, año: int, nombre: str) -> bool:
    """Actualiza solo los documentos de una carrera. Devuelve False si la FIA no la tiene."""
    if año not in scraper.temporadas(con):
        con.execute("DELETE FROM seasons")  # temporada nueva: volver a leer la lista
        con.commit()
        if año not in scraper.temporadas(con):
            return False
    q = normalizar(nombre)
    buscar = lambda carreras: next((c for c in carreras if normalizar(c["name"]) == q), None)
    carrera = buscar(scraper.carreras(con, año))
    if carrera is None:
        # Carrera nueva en el índice: releer la temporada (1 pedido), como mucho cada 6 h
        # por nombre (ej. "Pre-Season Testing" de OpenF1 no existe con ese nombre en la FIA).
        clave = f"season_retry:{año}:{q}"
        if ahora() - float(meta(con, clave) or 0) < REINTENTO_TEMPORADA:
            return False
        meta(con, clave, ahora())
        carrera = buscar(scraper.carreras(con, año, ttl=0))
        if carrera is None:
            return False
    scraper.documentos(con, carrera, forzar=True)  # 1 pedido; solo agrega documentos nuevos
    return True


def auto_actualizar(con) -> None:
    """Si hubo sesiones de F1 desde la última sincronización, actualiza esas carreras.

    Si OpenF1 no responde (por ejemplo durante una sesión en vivo), actualiza la
    carrera más reciente del índice, como mucho una vez por hora.
    """
    t = ahora()
    if t - float(meta(con, "last_check") or 0) < INTERVALO_CHEQUEO:
        return
    meta(con, "last_check", t)
    ultima = float(meta(con, "last_sync") or 0)
    try:
        activas = openf1.carreras_con_actividad(max(ultima - POST_SESION, t - 30 * 86400), t)
    except Exception:
        activas = None
    if activas is None:
        if t - ultima < 3600:
            return
        for carrera in scraper.carreras(con, scraper.año_actual(con))[:1]:
            scraper.documentos(con, carrera, forzar=True)
    else:
        for c in activas:
            _actualizar_carrera(con, c["año"], c["nombre"])
    meta(con, "last_sync", t)
