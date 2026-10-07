"""Páginas legales, botón de arrepentimiento y feed para Google Merchant Center.

Se conecta desde app.py con:
    import legales                                   (junto a los otros imports)
    legales.init_app(app, obtener_contexto_base)     (después de definir obtener_contexto_base)
"""
import os
from datetime import datetime
from xml.sax.saxutils import escape

from flask import (
    Blueprint, render_template, request, session, redirect, url_for, Response,
)

from models import db, Producto

bp = Blueprint("legales", __name__)

URL_PUBLICA = os.environ.get("URL_BASE", "http://127.0.0.1:5000").rstrip("/")

# ---------------------------------------------------------
# DATOS DEL NEGOCIO: editá acá y se actualizan todas las páginas.
# Tienen que coincidir EXACTO con lo que cargues en Merchant Center.
# ---------------------------------------------------------
NEGOCIO = {
    "nombre": "SOPI Sports",
    "localidad": "Quilmes, Provincia de Buenos Aires",
    "email": "mariano.d.vallejos@gmail.com",
    "whatsapp_texto": "+54 9 11 2832-1531",
    "whatsapp_url": "https://wa.me/5491128321531",
    "instagram_url": "https://www.instagram.com/sopi.tenispadel/",
    "cuit": "",                       # si lo completás, se muestra en Contacto
    "envio_gratis_desde": 150000,
    "plazo_envio": "3 días hábiles",
    "dias_arrepentimiento": 10,       # mínimo legal: 10 días corridos (Ley 24.240, art. 34)
}

_contexto_base = None


def init_app(app, contexto_base):
    """Registra las rutas. contexto_base es obtener_contexto_base de app.py."""
    global _contexto_base
    _contexto_base = contexto_base
    app.register_blueprint(bp)


# ---------------------------------------------------------
# MODELO: solicitudes del botón de arrepentimiento
# (db.create_all() de app.py crea la tabla sola)
# ---------------------------------------------------------
class Revocacion(db.Model):
    __tablename__ = "revocaciones"

    id = db.Column(db.Integer, primary_key=True)
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    nombre = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    pedido = db.Column(db.String(60), nullable=False, default="")
    detalle = db.Column(db.Text, nullable=False, default="")

    @property
    def codigo(self):
        return f"ARR-{self.id:06d}"


def _render(pagina, titulo, descripcion, **extra):
    contexto = _contexto_base()
    return render_template(
        "legal.html",
        pagina=pagina, titulo=titulo, descripcion=descripcion, negocio=NEGOCIO,
        **contexto, **extra,
    )


# ---------------------------------------------------------
# PÁGINAS
# ---------------------------------------------------------
@bp.route("/envios")
def envios():
    return _render(
        "envios", "Envíos",
        "Enviamos a todo el país por Andreani. Envío gratis en compras desde $150.000.",
    )


@bp.route("/cambios-y-devoluciones")
def devoluciones():
    return _render(
        "devoluciones", "Cambios y devoluciones",
        "Podés arrepentirte de tu compra dentro de los 10 días corridos de recibida. Te explicamos cómo.",
    )


@bp.route("/contacto")
def contacto():
    return _render(
        "contacto", "Contacto",
        "Escribinos por WhatsApp, Instagram o mail. Despachamos desde Quilmes, Buenos Aires.",
    )


@bp.route("/terminos-y-condiciones")
def terminos():
    return _render(
        "terminos", "Términos y condiciones",
        "Condiciones de compra de SOPI Sports: precios, medios de pago, envíos y devoluciones.",
    )


@bp.route("/privacidad")
def privacidad():
    return _render(
        "privacidad", "Política de privacidad",
        "Qué datos recopilamos cuando comprás en SOPI Sports y cómo los usamos.",
    )


# ---------------------------------------------------------
# BOTÓN DE ARREPENTIMIENTO (Res. 424/2020)
# ---------------------------------------------------------
@bp.route("/arrepentimiento", methods=["GET", "POST"])
def arrepentimiento():
    error = None

    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()[:120]
        email = (request.form.get("email") or "").strip()[:120]
        pedido = (request.form.get("pedido") or "").strip()[:60]
        detalle = (request.form.get("detalle") or "").strip()[:2000]

        if not nombre or "@" not in email:
            error = "Completá tu nombre y un email válido."
        else:
            r = Revocacion(nombre=nombre, email=email, pedido=pedido, detalle=detalle)
            db.session.add(r)
            db.session.commit()
            return _render(
                "arrepentimiento_ok", "Solicitud recibida",
                "Recibimos tu solicitud de arrepentimiento.",
                revocacion=r,
            )

    return _render(
        "arrepentimiento", "Botón de arrepentimiento",
        "Solicitá la revocación de tu compra dentro de los 10 días corridos de recibida.",
        error=error, form=request.form,
    )


@bp.route("/admin/arrepentimientos")
def admin_arrepentimientos():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    revocaciones = Revocacion.query.order_by(Revocacion.creado_en.desc()).limit(200).all()
    return _render(
        "admin_arrepentimientos", "Solicitudes de arrepentimiento",
        "Solicitudes recibidas.",
        revocaciones=revocaciones,
    )


# ---------------------------------------------------------
# FEED PARA GOOGLE MERCHANT CENTER
# URL: /feed/google.xml
# ---------------------------------------------------------
@bp.route("/feed/google.xml")
def feed_google():
    items = []

    productos = (
        Producto.query
        .filter(Producto.slug != None)   # noqa: E711
        .order_by(Producto.id)
        .all()
    )

    for p in productos:
        if not p.imagen:
            continue   # Google exige imagen

        link = f"{URL_PUBLICA}{url_for('producto_detalle', slug=p.slug)}"
        imagen = f"{URL_PUBLICA}{url_for('static', filename='img/' + p.imagen)}"
        descripcion = (p.descripcion or "").strip() or f"{p.nombre} - {p.marca}"
        disponibilidad = "in_stock" if p.stock > 0 else "out_of_stock"

        items.append(
            "    <item>\n"
            f"      <g:id>{p.id}</g:id>\n"
            f"      <g:title>{escape(p.nombre[:150])}</g:title>\n"
            f"      <g:description>{escape(descripcion[:4900])}</g:description>\n"
            f"      <g:link>{escape(link)}</g:link>\n"
            f"      <g:image_link>{escape(imagen)}</g:image_link>\n"
            f"      <g:availability>{disponibilidad}</g:availability>\n"
            f"      <g:price>{p.precio:.2f} ARS</g:price>\n"
            f"      <g:brand>{escape(p.marca or NEGOCIO['nombre'])}</g:brand>\n"
            "      <g:condition>new</g:condition>\n"
            "      <g:identifier_exists>no</g:identifier_exists>\n"
            "    </item>"
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">\n'
        "  <channel>\n"
        f"    <title>{escape(NEGOCIO['nombre'])}</title>\n"
        f"    <link>{escape(URL_PUBLICA)}</link>\n"
        "    <description>Productos de pádel y tenis</description>\n"
        + "\n".join(items)
        + "\n  </channel>\n</rss>\n"
    )

    return Response(xml, mimetype="application/xml")
