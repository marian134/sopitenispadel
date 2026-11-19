"""Módulo de torneos de tenis (escaleras de desafíos y cuadros).

Vive aparte de la tienda: carpeta torneos/, tablas "torneo_*" y plantillas
en templates/torneos/. Se publica en /torneos.

Se conecta desde app.py con:
    import torneos                                   (junto a los otros imports,
                                                      antes de db.create_all)
    torneos.init_app(app, obtener_contexto_base)     (después de definir obtener_contexto_base)

La pestaña "Torneos" del menú queda oculta hasta el lanzamiento. Para
mostrarla, poner la variable de entorno TORNEOS_VISIBLE=1.
"""
import os

from flask import Blueprint, current_app, render_template
from werkzeug.exceptions import HTTPException

from . import models  # noqa: F401  (registra las tablas antes de db.create_all)
from .models import (
    Competencia, ESTADOS_PUBLICOS, EST_INSCRIPCION, EST_EN_CURSO, EST_FINALIZADA,
)

bp = Blueprint("torneos", __name__, url_prefix="/torneos")

_contexto_base = None

WHATSAPP_ORGANIZAR = (
    "https://wa.me/5491128321531?text="
    "Hola%20SOPI!%20Quiero%20organizar%20un%20torneo%20de%20tenis"
)


def torneos_visible():
    return os.environ.get("TORNEOS_VISIBLE", "") == "1"


def init_app(app, contexto_base):
    """Registra las rutas. contexto_base es obtener_contexto_base de app.py."""
    global _contexto_base
    _contexto_base = contexto_base
    app.register_blueprint(bp)

    @app.context_processor
    def _torneos():
        return {"torneos_visible": torneos_visible()}


def _contexto(**extra):
    contexto = _contexto_base() if _contexto_base else {}
    contexto.update(extra)
    return contexto


# ---------------------------------------------------------
# ERRORES: un problema en torneos muestra su propia página
# y no arrastra a la tienda.
# ---------------------------------------------------------
@bp.errorhandler(Exception)
def _error_torneos(error):
    if isinstance(error, HTTPException):
        return error
    current_app.logger.exception("Error en torneos")
    try:
        return render_template("torneos/error.html", **_contexto()), 500
    except Exception:
        return "Tuvimos un problema con los torneos. Probá de nuevo en un momento.", 500


# ---------------------------------------------------------
# PÁGINAS
# ---------------------------------------------------------
@bp.route("/")
def calendario():
    competencias = (
        Competencia.query
        .filter(Competencia.estado.in_(ESTADOS_PUBLICOS))
        .order_by(Competencia.fecha_inicio.desc().nullslast(), Competencia.id.desc())
        .all()
    )
    grupos = [
        ("Inscripción abierta", [c for c in competencias if c.estado == EST_INSCRIPCION]),
        ("En juego", [c for c in competencias if c.estado == EST_EN_CURSO]),
        ("Finalizados", [c for c in competencias if c.estado == EST_FINALIZADA]),
    ]
    return render_template(
        "torneos/calendario.html",
        **_contexto(
            grupos=[g for g in grupos if g[1]],
            whatsapp_organizar=WHATSAPP_ORGANIZAR,
        ),
    )
