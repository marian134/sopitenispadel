"""Administración de torneos para Sopi, en /admin/torneos.

Usa la misma clave de admin de la tienda (session["admin"]).
Los datos para que el organizador le pague a Sopi salen de la variable de
entorno TORNEOS_DATOS_PAGO (ej. "Alias: sopi.torneos · Titular: ...").
"""
import os
from datetime import datetime
from functools import wraps

import csv
import io

from flask import Blueprint, Response, abort, redirect, render_template, request, session, url_for

from models import db
from .bp import contexto
from . import control
from .cobros import impagos
from .models import Categoria, Cobro, Competencia, Inscripcion, Organizador, PLAN_GRATIS, PLAN_PAGO, EST_BORRADOR, EST_INSCRIPCION
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
            "parecidos": control.parecidos(org, organizadores),
            "pide": [c for c in org.competencias if c.pide_publicar and c.estado == EST_BORRADOR],
            "wa": link_whatsapp(org.whatsapp, f"Hola {org.nombre}! Te escribo de SOPI Torneos."),
            "torneos": sorted(org.competencias, key=lambda c: c.creado_en, reverse=True),
        })
    por_aprobar = [f for f in filas if not f["org"].aprobado and f["org"].activo]
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
            filas=filas, cobros_pend=cobros_pend, por_aprobar=por_aprobar,
            aprobado_ok=request.args.get("aprobado"),
            hecho=request.args.get("hecho"), hecho_org=request.args.get("org", type=int),
            hecho_error=request.args.get("error"), hecho_cobro=request.args.get("hecho_cobro"),
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
    hecho, error = None, False
    if accion == "cobro":
        # plan y precio juntos, desde la ficha del organizador
        plan = request.form.get("plan")
        valor = (request.form.get("precio") or "0").replace(".", "").replace("$", "").strip() or "0"
        if plan not in (PLAN_GRATIS, PLAN_PAGO):
            hecho, error = "Elegí gratis o pago.", True
        elif plan == PLAN_PAGO and not valor.isdigit():
            hecho, error = "El precio tiene que ser un número (por ejemplo 2000), sin letras.", True
        else:
            org.plan = plan
            if plan == PLAN_PAGO:
                org.precio_por_inscripto = int(valor)
                hecho = ("Guardado: plan pago, sin tope de jugadores, "
                         + (f"le cobrás {pesos(org.precio_por_inscripto)} por jugador inscripto."
                            if org.precio_por_inscripto else "y no le cobrás nada."))
            else:
                hecho = f"Guardado: plan gratis (1 torneo de hasta {control.TOPE_GRATIS} jugadores, no le cobrás)."
    elif accion == "plan" and request.form.get("plan") in (PLAN_GRATIS, PLAN_PAGO):
        org.plan = request.form["plan"]
        hecho = ("Listo: plan pago, sin tope de jugadores." if org.plan == PLAN_PAGO
                 else f"Listo: plan gratis (1 torneo de hasta {control.TOPE_GRATIS} jugadores).")
    elif accion == "precio":
        valor = (request.form.get("precio") or "").replace(".", "").replace("$", "").strip()
        if valor.isdigit():
            org.precio_por_inscripto = int(valor)
            hecho = (f"Listo: precio por inscripto {pesos(org.precio_por_inscripto)}."
                     if org.precio_por_inscripto else "Listo: precio por inscripto $0 (no se le cobra).")
        else:
            hecho, error = "El precio tiene que ser un número, sin letras.", True
    elif accion == "activo":
        org.activo = not org.activo
        hecho = "Listo: cuenta activa." if org.activo else "Listo: cuenta desactivada (ya no puede ingresar)."
    elif accion == "aprobar":
        org.aprobado = True
        publicados = []
        for comp in org.competencias:
            if comp.pide_publicar and comp.estado == EST_BORRADOR and comp.categorias:
                comp.estado, comp.pide_publicar = EST_INSCRIPCION, False
                publicados.append(comp)
        db.session.commit()
        control.avisar_aprobado(org, publicados)
        hecho = "Listo: cuenta aprobada" + (f" y publicado {', '.join(c.nombre for c in publicados)}" if publicados else "") + ". Le avisamos por mail."
        return redirect(url_for("torneos_admin.inicio", aprobado=org.nombre, hecho=hecho, org=org.id) + f"#org-{org.id}")
    elif accion == "desaprobar":
        org.aprobado = False
        hecho = "Listo: le quitaste la aprobación. Sus torneos nuevos van a esperar que los apruebes."
    db.session.commit()
    return redirect(url_for("torneos_admin.inicio", hecho=hecho, org=org.id, error=1 if error else None)
                    + f"#org-{org.id}")


@admin_bp.route("/cobro/<int:cobro_id>", methods=["POST"])
@admin_requerido
def cobro(cobro_id):
    c = db.session.get(Cobro, cobro_id)
    if not c:
        abort(404)
    hecho = None
    if request.form.get("accion") == "pagado":
        c.pagado, c.pagado_en = True, datetime.now()
        hecho = f"Listo: cobro de {pesos(c.monto)} marcado como pagado."
    elif request.form.get("accion") == "impago":
        c.pagado, c.pagado_en = False, None
        hecho = f"Listo: el cobro de {pesos(c.monto)} volvió a pendientes."
    db.session.commit()
    return redirect(url_for("torneos_admin.inicio", hecho_cobro=hecho) + "#cobros")


ESTADOS_PAGO = {"pendiente": "Pago a revisar", "confirmado": "Pago confirmado", "rechazado": "Pago rechazado"}


@admin_bp.route("/inscriptos")
@admin_requerido
def inscriptos():
    """Tablero con todos los inscriptos de todos los torneos, con filtros y totales."""
    comp_id = request.args.get("torneo", type=int)
    org_id = request.args.get("organizador", type=int)
    estado = request.args.get("pago") or ""
    texto = (request.args.get("q") or "").strip().lower()
    consulta = (Inscripcion.query.join(Categoria, Inscripcion.categoria_id == Categoria.id)
                .join(Competencia, Categoria.competencia_id == Competencia.id))
    if comp_id:
        consulta = consulta.filter(Competencia.id == comp_id)
    if org_id:
        consulta = consulta.filter(Competencia.organizador_id == org_id)
    if estado == "baja":
        consulta = consulta.filter(Inscripcion.baja.is_(True))
    elif estado in ESTADOS_PAGO:
        consulta = consulta.filter(Inscripcion.estado_pago == estado, Inscripcion.baja.is_(False))
    filas = consulta.order_by(Inscripcion.creado_en.desc()).all()
    if texto:
        def coincide(i):
            js = [x for x in (i.jugador1, i.jugador2) if x]
            return any(texto in " ".join(filter(None, [x.nombre_completo, x.dni, x.email or "", x.celular or ""])).lower() for x in js)
        filas = [i for i in filas if coincide(i)]
    if request.args.get("formato") == "csv":
        salida = io.StringIO()
        w = csv.writer(salida, delimiter=";")
        w.writerow(["Torneo", "Organizador", "Categoría", "Jugador", "DNI", "Celular", "Mail", "Compañero/a",
                    "Estado", "Fecha"])
        for i in filas:
            comp = i.categoria.competencia
            w.writerow([comp.nombre, comp.organizador.nombre, i.categoria.nombre, i.jugador1.nombre_completo,
                        i.jugador1.dni, i.jugador1.celular or "", i.jugador1.email or "",
                        i.jugador2.nombre_completo if i.jugador2 else "",
                        "De baja" if i.baja else ESTADOS_PAGO.get(i.estado_pago, i.estado_pago),
                        i.creado_en.strftime("%d/%m/%Y %H:%M")])
        return Response("﻿" + salida.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=inscriptos-torneos.csv"})
    activos = [i for i in filas if not i.baja]
    totales = {
        "inscripciones": len(activos),
        "jugadores": sum(2 if i.jugador2_id else 1 for i in activos),
        "confirmados": sum(1 for i in activos if i.estado_pago == "confirmado"),
        "a_revisar": sum(1 for i in activos if i.estado_pago == "pendiente"),
        "rechazados": sum(1 for i in activos if i.estado_pago == "rechazado"),
        "bajas": len(filas) - len(activos),
    }
    return render_template(
        "torneos/admin_inscriptos.html",
        **contexto(filas=filas, totales=totales, estados=ESTADOS_PAGO,
                   competencias=Competencia.query.order_by(Competencia.creado_en.desc()).all(),
                   organizadores=Organizador.query.order_by(Organizador.nombre).all(),
                   filtro={"torneo": comp_id, "organizador": org_id, "pago": estado, "q": request.args.get("q", "")}),
    )
