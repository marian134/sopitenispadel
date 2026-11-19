"""Panel del organizador para torneos con cuadro: armar la llave, consuelo,
horarios y opciones."""
from datetime import datetime

from flask import abort, redirect, render_template, request, url_for

from models import db
from . import cuadro as cdr
from .bp import bp, contexto
from .models import Categoria, Partido, TIPO_CUADRO, PAR_AGENDADO, PAR_PENDIENTE
from .panel import _mi_competencia
from .util import link_whatsapp, organizador_requerido


def _mi_categoria(comp_id, cat_id):
    comp = _mi_competencia(comp_id)
    cat = db.session.get(Categoria, cat_id)
    if not cat or cat.competencia_id != comp.id or comp.tipo != TIPO_CUADRO:
        abort(404)
    return comp, cat


def _volver(comp, error=None, ancla=""):
    args = {"comp_id": comp.id}
    if error:
        args["error"] = error
    return redirect(url_for("torneos.competencia_panel", **args) + (f"#{ancla}" if ancla else ""))


@bp.route("/panel/<int:comp_id>/cuadro/<int:cat_id>/armar", methods=["POST"])
@organizador_requerido
def cuadro_armar(comp_id, cat_id):
    comp, cat = _mi_categoria(comp_id, cat_id)
    if cdr.hay_resultados(cat):
        return _volver(comp, "El cuadro ya tiene resultados: no se puede volver a armar.", f"cuadro-{cat.id}")
    try:
        cdr.armar(cat, cdr.participantes(cat))
        cdr._borrar(cat, cdr.CONSUELO)
        cdr._borrar(cat, cdr.TERCER)
    except ValueError as e:
        db.session.rollback()
        return _volver(comp, str(e), f"cuadro-{cat.id}")
    db.session.commit()
    return _volver(comp, ancla=f"cuadro-{cat.id}")


@bp.route("/panel/<int:comp_id>/cuadro/<int:cat_id>/consuelo", methods=["POST"])
@organizador_requerido
def cuadro_consuelo(comp_id, cat_id):
    comp, cat = _mi_categoria(comp_id, cat_id)
    if cdr.hay_resultados(cat, cdr.CONSUELO):
        return _volver(comp, "El consuelo ya tiene resultados.", f"cuadro-{cat.id}")
    try:
        cdr.armar_consuelo(cat)
    except ValueError as e:
        db.session.rollback()
        return _volver(comp, f"Consuelo: {e}", f"cuadro-{cat.id}")
    db.session.commit()
    return _volver(comp, ancla=f"cuadro-{cat.id}")


@bp.route("/panel/partido/<int:partido_id>/horario", methods=["POST"])
@organizador_requerido
def partido_horario(partido_id):
    p = db.session.get(Partido, partido_id)
    if not p:
        abort(404)
    comp = _mi_competencia(p.competencia_id)
    valor = request.form.get("fecha_hora") or ""
    try:
        p.fecha_hora = datetime.strptime(valor, "%Y-%m-%dT%H:%M") if valor else None
    except ValueError:
        return _volver(comp, "La fecha y hora no es válida.", "horarios")
    p.cancha = (request.form.get("cancha") or "").strip()[:40] or None
    db.session.commit()
    return _volver(comp, ancla=f"partido-{p.id}")


@bp.route("/panel/<int:comp_id>/opciones", methods=["GET", "POST"])
@organizador_requerido
def opciones_cuadro(comp_id):
    comp = _mi_competencia(comp_id)
    if comp.tipo != TIPO_CUADRO:
        abort(404)
    reglas = comp.reglas
    guardado = False
    if request.method == "POST":
        reglas["consuelo"] = bool(request.form.get("consuelo"))
        reglas["tercer_puesto"] = bool(request.form.get("tercer_puesto"))
        reglas["formato_partido"] = (request.form.get("formato_partido") or "").strip()[:100]
        reglas["selfie_obligatoria"] = bool(request.form.get("selfie_obligatoria"))
        comp.reglas = reglas
        db.session.commit()
        guardado = True
    return render_template("torneos/opciones_cuadro.html", **contexto(comp=comp, reglas=reglas, guardado=guardado))


def datos_cuadro(comp):
    """Lo que el panel necesita de cada categoría con cuadro."""
    avisos = cdr.avisos_horarios(comp)
    categorias = []
    for cat in sorted(comp.categorias, key=lambda c: c.orden):
        participantes = cdr.participantes(cat)
        t = cdr.tamano(len(participantes)) if len(participantes) >= 2 else 0
        entrantes, pendientes = cdr.entrantes_consuelo(cat) if cdr.partidos(cat) else ([], 0)
        categorias.append({
            "cat": cat,
            "participantes": len(participantes),
            "tamano": t, "byes": t - len(participantes) if t else 0, "max_cabezas": cdr.max_cabezas(t),
            "principal": cdr.estructura(cat),
            "consuelo": cdr.estructura(cat, cdr.CONSUELO),
            "tercer": cdr.partidos(cat, cdr.TERCER),
            "campeon": cdr.campeon(cat),
            "campeon_consuelo": cdr.campeon(cat, cdr.CONSUELO),
            "con_resultados": cdr.hay_resultados(cat),
            "consuelo_listo": not pendientes and len(entrantes) >= 2,
            "consuelo_entrantes": len(entrantes), "consuelo_pendientes": pendientes,
        })
    por_jugar = (
        Partido.query.filter(Partido.competencia_id == comp.id, Partido.estado.in_((PAR_AGENDADO, PAR_PENDIENTE)))
        .all()
    )
    por_jugar = [p for p in por_jugar if p.lado_a_id or p.lado_b_id]
    por_jugar.sort(key=lambda p: (p.fecha_hora is None, p.fecha_hora or datetime.max,
                                  p.categoria_id, p.cuadro or "", int(p.ronda or 0), p.posicion or 0))
    filas = []
    for p in por_jugar:
        cat = p.lado_a.categoria if p.lado_a else p.lado_b.categoria
        avisos_wa = []
        if p.estado == PAR_AGENDADO and p.fecha_hora:
            cuando = p.fecha_hora.strftime("%d/%m a las %H:%M")
            for yo, rival in ((p.lado_a, p.lado_b), (p.lado_b, p.lado_a)):
                texto = (f"Hola {yo.jugador1.nombre}! Tu partido de {comp.nombre} ({cat.nombre}, "
                         f"{cdr.nombre_ronda(cat, p.cuadro, p.ronda)}) es el {cuando}"
                         f"{' en la cancha ' + p.cancha if p.cancha else ''} contra {rival.jugador1.nombre_completo}.")
                avisos_wa.append((yo.jugador1.nombre, link_whatsapp(yo.jugador1.celular, texto)))
        filas.append({
            "p": p, "cat": cat, "ronda": cdr.nombre_ronda(cat, p.cuadro, p.ronda),
            "avisos": avisos.get(p.id, []), "wa": avisos_wa,
        })
    return {"categorias": categorias, "por_jugar": filas}
