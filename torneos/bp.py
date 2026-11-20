"""El Blueprint de torneos y el contexto compartido de las páginas."""
from flask import Blueprint

bp = Blueprint("torneos", __name__, url_prefix="/torneos")

# Lo completa init_app con obtener_contexto_base de app.py
_estado = {"contexto_base": None}

WHATSAPP_SOPI = "5491128321531"


def contexto(**extra):
    """Contexto de la tienda (menú, carrito) + lo propio de cada página."""
    import os
    from .cobros import cargo_jugador, precio_jugador
    from .util import organizador_actual, pesos

    base = _estado["contexto_base"]
    datos = base() if base else {}
    datos.update(
        organizador=organizador_actual(), pesos=pesos,
        precio_jugador=precio_jugador, cargo_jugador=cargo_jugador,
        cupon_sopi=os.environ.get("TORNEOS_CUPON", "").strip(),   # cupón de la tienda para el plan gratis
    )
    datos.update(extra)
    return datos
