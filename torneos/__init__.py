"""Módulo de torneos de tenis (escaleras de desafíos y cuadros).

Vive aparte de la tienda: carpeta torneos/, tablas "torneo_*" y plantillas
en templates/torneos/. Se publica en /torneos.

Se conecta desde app.py con:
    import torneos                                   (junto a los otros imports,
                                                      antes de db.create_all)
    torneos.init_app(app, obtener_contexto_base)     (después de definir obtener_contexto_base)

La pestaña "Torneos" del menú queda oculta hasta el lanzamiento. Para
mostrarla, poner la variable de entorno TORNEOS_VISIBLE=1.

Partes:
    models.py    tablas
    util.py      ayudas (slugs, WhatsApp, archivos, mail, sesión del organizador)
    publico.py   calendario, página del torneo, inscripción, panel del jugador
    cuentas.py   alta e ingreso de organizadores, perfil
    panel.py     competencias e inscriptos del organizador
"""
import os

from flask import current_app, render_template
from werkzeug.exceptions import HTTPException

from . import models  # noqa: F401  (registra las tablas antes de db.create_all)
from .bp import bp, contexto, _estado
from . import publico, cuentas, panel  # noqa: F401  (registran sus rutas en bp)


def torneos_visible():
    return os.environ.get("TORNEOS_VISIBLE", "") == "1"


def init_app(app, contexto_base):
    """Registra las rutas. contexto_base es obtener_contexto_base de app.py."""
    _estado["contexto_base"] = contexto_base
    app.register_blueprint(bp)

    @app.context_processor
    def _torneos():
        return {"torneos_visible": torneos_visible()}


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
        from models import db
        db.session.rollback()
        return render_template("torneos/error.html", **contexto()), 500
    except Exception:
        return "Tuvimos un problema con los torneos. Probá de nuevo en un momento.", 500
