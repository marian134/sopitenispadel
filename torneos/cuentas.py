"""Alta, ingreso y perfil de los organizadores."""
import os
import re

from flask import abort, current_app, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from models import db
from .bp import bp, contexto, WHATSAPP_SOPI
from .models import Organizador, PLAN_PAGO, PRECIO_POR_INSCRIPTO
from .util import (
    CARPETA_ARCHIVOS, enviar_mail, guardar_archivo, organizador_actual, organizador_requerido, slug_unico,
)

EMAIL_OK = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
COLOR_OK = re.compile(r"^#[0-9a-fA-F]{6}$")


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


# ---------------------------------------------------------
# OLVIDÉ MI CONTRASEÑA (link por mail, vale 2 horas y una sola vez:
# deja de servir apenas cambia la contraseña)
# ---------------------------------------------------------
def _serializador():
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(current_app.secret_key, salt="torneos-clave")


def _token_clave(org):
    return _serializador().dumps({"id": org.id, "h": org.clave_hash[-12:]})


def _org_del_token(token):
    from itsdangerous import BadSignature, SignatureExpired
    try:
        datos = _serializador().loads(token, max_age=2 * 3600)
    except (BadSignature, SignatureExpired):
        return None
    org = db.session.get(Organizador, datos.get("id"))
    if not org or not org.activo or org.clave_hash[-12:] != datos.get("h"):
        return None
    return org


@bp.route("/olvide-mi-clave", methods=["GET", "POST"])
def olvide_clave():
    enviado = False
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        org = Organizador.query.filter_by(email=email).first()
        if org and org.activo:
            link = url_for("torneos.nueva_clave", token=_token_clave(org), _external=True)
            ok = enviar_mail(org.email, "Cambiar tu contraseña de SOPI Torneos",
                             f"Hola {org.nombre}!\n\nPara elegir una contraseña nueva entrá a este link "
                             f"(vale 2 horas):\n{link}\n\nSi no lo pediste, ignorá este mail.")
            if not ok:
                current_app.logger.info("Link para cambiar la clave de %s: %s", org.email, link)
        enviado = True   # siempre lo mismo, para no revelar qué mails tienen cuenta
    return render_template("torneos/olvide_clave.html", **contexto(enviado=enviado))


@bp.route("/nueva-clave/<token>", methods=["GET", "POST"])
def nueva_clave(token):
    org = _org_del_token(token)
    if not org:
        return render_template("torneos/nueva_clave.html", **contexto(invalido=True))
    error = None
    if request.method == "POST":
        clave = request.form.get("clave") or ""
        if len(clave) < 8:
            error = "La contraseña tiene que tener al menos 8 caracteres."
        elif clave != request.form.get("clave2"):
            error = "Las dos contraseñas no coinciden."
        else:
            org.clave_hash = generate_password_hash(clave)
            db.session.commit()
            session["torneo_org_id"] = org.id
            return redirect(url_for("torneos.panel"))
    return render_template("torneos/nueva_clave.html", **contexto(invalido=False, error=error))


@bp.route("/terminos")
def terminos():
    return render_template("torneos/terminos.html", **contexto())


@bp.route("/panel/perfil", methods=["GET", "POST"])
@organizador_requerido
def perfil():
    org = organizador_actual()
    guardado, error = False, None
    if request.method == "POST":
        org.nombre = (request.form.get("nombre") or org.nombre).strip()[:120]
        org.whatsapp = (request.form.get("whatsapp") or "").strip()[:40]
        org.datos_bancarios = (request.form.get("datos_bancarios") or "").strip()[:500]
        if org.plan == PLAN_PAGO:
            # Plan pago: las páginas de sus torneos llevan su logo y su color
            color = (request.form.get("color") or "").strip()
            org.color = color if COLOR_OK.match(color) else None
            archivo = request.files.get("logo")
            if archivo and archivo.filename:
                try:
                    if os.path.splitext(archivo.filename)[1].lower() == ".pdf":
                        raise ValueError("El logo tiene que ser una imagen (JPG, PNG o WEBP).")
                    org.logo = guardar_archivo(archivo)
                except ValueError as e:
                    error = f"Logo: {e}"
            if request.form.get("quitar_logo"):
                org.logo = None
        db.session.commit()
        guardado = not error
    return render_template("torneos/perfil.html", **contexto(org=org, guardado=guardado, error=error))


@bp.route("/logo/<int:org_id>")
def logo(org_id):
    """Logo público del organizador (solo plan pago)."""
    org = db.session.get(Organizador, org_id)
    if not org or not org.logo or org.plan != PLAN_PAGO:
        abort(404)
    from .archivos import servir
    return servir(org.logo)
