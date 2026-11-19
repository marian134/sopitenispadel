"""Alta, ingreso y perfil de los organizadores."""
import re

from flask import redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from models import db
from .bp import bp, contexto, WHATSAPP_SOPI
from .models import Organizador, PRECIO_POR_INSCRIPTO
from .util import organizador_actual, organizador_requerido, slug_unico

EMAIL_OK = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _siguiente_seguro(valor):
    """Solo deja volver a páginas de torneos (evita redirigir afuera)."""
    if valor and valor.startswith("/torneos/") and not valor.startswith("//"):
        return valor
    return url_for("torneos.panel")


@bp.route("/organizar", methods=["GET", "POST"])
def organizar():
    """Página de venta + alta de organizador."""
    if organizador_actual() and request.method == "GET":
        return redirect(url_for("torneos.panel"))

    error, datos = None, {}
    if request.method == "POST":
        datos = {
            "nombre": (request.form.get("nombre") or "").strip()[:120],
            "email": (request.form.get("email") or "").strip().lower()[:120],
            "whatsapp": (request.form.get("whatsapp") or "").strip()[:40],
        }
        clave = request.form.get("clave") or ""
        if not datos["nombre"] or not datos["email"] or not datos["whatsapp"]:
            error = "Completá el nombre, el mail y el WhatsApp."
        elif not EMAIL_OK.match(datos["email"]):
            error = "El mail no parece válido."
        elif len(clave) < 8:
            error = "La contraseña tiene que tener al menos 8 caracteres."
        elif clave != request.form.get("clave2"):
            error = "Las dos contraseñas no coinciden."
        elif Organizador.query.filter_by(email=datos["email"]).first():
            error = "Ya hay una cuenta con ese mail. Ingresá con tu contraseña."
        else:
            org = Organizador(
                nombre=datos["nombre"],
                slug=slug_unico(Organizador, datos["nombre"]),
                email=datos["email"],
                whatsapp=datos["whatsapp"],
                clave_hash=generate_password_hash(clave),
            )
            db.session.add(org)
            db.session.commit()
            # no se borra el resto de la sesión (carrito de la tienda)
            session["torneo_org_id"] = org.id
            return redirect(url_for("torneos.panel", bienvenida=1))

    return render_template(
        "torneos/organizar.html",
        **contexto(error=error, datos=datos, precio=PRECIO_POR_INSCRIPTO, whatsapp_sopi=WHATSAPP_SOPI),
    )


@bp.route("/ingresar", methods=["GET", "POST"])
def ingresar():
    error = None
    siguiente = request.values.get("siguiente", "")
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        clave = request.form.get("clave") or ""
        org = Organizador.query.filter_by(email=email).first()
        if org and org.activo and check_password_hash(org.clave_hash, clave):
            # no se borra el resto de la sesión (carrito de la tienda)
            session["torneo_org_id"] = org.id
            return redirect(_siguiente_seguro(siguiente))
        error = "Mail o contraseña incorrectos."
    return render_template("torneos/ingresar.html", **contexto(error=error, siguiente=siguiente))


@bp.route("/salir", methods=["POST"])
def salir():
    session.pop("torneo_org_id", None)
    return redirect(url_for("torneos.calendario"))


@bp.route("/panel/perfil", methods=["GET", "POST"])
@organizador_requerido
def perfil():
    org = organizador_actual()
    guardado = False
    if request.method == "POST":
        org.nombre = (request.form.get("nombre") or org.nombre).strip()[:120]
        org.whatsapp = (request.form.get("whatsapp") or "").strip()[:40]
        org.datos_bancarios = (request.form.get("datos_bancarios") or "").strip()[:500]
        db.session.commit()
        guardado = True
    return render_template("torneos/perfil.html", **contexto(org=org, guardado=guardado))
