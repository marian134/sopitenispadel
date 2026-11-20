"""Administración de torneos para Sopi, en /admin/torneos.

Usa la misma clave de admin de la tienda (session["admin"]).
Los datos para que el organizador le pague a Sopi salen de la variable de
entorno TORNEOS_DATOS_PAGO (ej. "Alias: sopi.torneos · Titular: ...").
"""
import os
from datetime import datetime
from functools import wraps

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from models import db
from .bp import contexto
from .cobros import impagos
from .models import Cobro, Competencia, Organizador, PLAN_GRATIS, PLAN_PAGO
from .util import link_whatsapp, pesos

admin_bp = Blueprint("torneos_admin", __name__, url_prefix="/admin/torneos")


def admin_requerido(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return vista(*args, **kwargs)
    return envoltura


def _texto_cobro(cobro):
    org = cobro.organizador if hasattr(cobro, "organizador") else db.session.get(Organizador, cobro.organizador_id)
    comp = db.session.get(Competencia, cobro.competencia_id)
    datos = os.environ.get("TORNEOS_DATOS_PAGO", "").strip()
    return (
        f"Hola {org.nombre}! Te paso el resumen de SOPI Torneos por {comp.nombre}: "
        f"{cobro.inscriptos} jugadores x {pesos(cobro.precio_unitario)} = {pesos(cobro.monto)}. "
        + (f"Datos para transferir: {datos}. " if datos else "Te paso los datos para transferir. ")
        + "¡Gracias!"
    )


@admin_bp.route("/")
@admin_requerido
def inicio():
    organizadores = Organizador.query.order_by(Organizador.creado_en.desc()).all()
    filas = []
    for org in organizadores:
        deuda = impagos(org)
        filas.append({
            "org": org, "competencias": len(org.competencias),
            "deuda": sum(c.monto for c in deuda), "cobros_impagos": len(deuda),
        })
    pendientes = Cobro.query.filter_by(pagado=False).order_by(Cobro.creado_en).all()
    pagados = Cobro.query.filter_by(pagado=True).order_by(Cobro.pagado_en.desc()).limit(30).all()
    nombres = {o.id: o for o in organizadores}
    comps = {c.id: c for c in Competencia.query.filter(
        Competencia.id.in_([c.competencia_id for c in pendientes + pagados] or [0])).all()}
    cobros_pend = [{
        "c": c, "org": nombres.get(c.organizador_id), "comp": comps.get(c.competencia_id),
        "wa": link_whatsapp(nombres[c.organizador_id].whatsapp, _texto_cobro(c)) if nombres.get(c.organizador_id) else None,
    } for c in pendientes]
    return render_template(
        "torneos/admin_torneos.html",
        **contexto(
            filas=filas, cobros_pend=cobros_pend,
            pagados=[{"c": c, "org": nombres.get(c.organizador_id), "comp": comps.get(c.competencia_id)} for c in pagados],
            total_pendiente=sum(c.monto for c in pendientes),
            total_cobrado=sum(c.monto for c in Cobro.query.filter_by(pagado=True).all()),
        ),
    )


@admin_bp.route("/organizador/<int:org_id>", methods=["POST"])
@admin_requerido
def organizador(org_id):
    org = db.session.get(Organizador, org_id)
    if not org:
        abort(404)
    accion = request.form.get("accion")
    if accion == "plan" and request.form.get("plan") in (PLAN_GRATIS, PLAN_PAGO):
        org.plan = request.form["plan"]
    elif accion == "precio":
        valor = (request.form.get("precio") or "").replace(".", "").replace("$", "").strip()
        if valor.isdigit():
            org.precio_por_inscripto = int(valor)
    elif accion == "activo":
        org.activo = not org.activo
    db.session.commit()
    return redirect(url_for("torneos_admin.inicio") + f"#org-{org.id}")


@admin_bp.route("/cobro/<int:cobro_id>", methods=["POST"])
@admin_requerido
def cobro(cobro_id):
    c = db.session.get(Cobro, cobro_id)
    if not c:
        abort(404)
    if request.form.get("accion") == "pagado":
        c.pagado, c.pagado_en = True, datetime.now()
    elif request.form.get("accion") == "impago":
        c.pagado, c.pagado_en = False, None
    db.session.commit()
    return redirect(url_for("torneos_admin.inicio") + "#cobros")
