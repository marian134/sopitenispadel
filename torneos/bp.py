"""El Blueprint de torneos y el contexto compartido de las páginas."""
from flask import Blueprint

bp = Blueprint("torneos", __name__, url_prefix="/torneos")

# Lo completa init_app con obtener_contexto_base de app.py
_estado = {"contexto_base": None}

WHATSAPP_SOPI = "5491128321531"


def contexto(**extra):
    """Contexto de la tienda (menú, carrito) + lo propio de cada página."""
    from .util import organizador_actual, pesos

    base = _estado["contexto_base"]
    datos = base() if base else {}
    datos.update(organizador=organizador_actual(), pesos=pesos)
    datos.update(extra)
    return datos
