"""Panel del organizador: sus competencias, categorías e inscriptos."""
import os
from datetime import datetime

from flask import abort, redirect, render_template, request, send_from_directory, url_for

from models import db
from . import reglas as reglas_mod
from .bp import bp, contexto
from .models import (
    Categoria, Competencia, Inscripcion,
    EST_BORRADOR, EST_CANCELADA, EST_EN_CURSO, EST_INSCRIPCION,
    PAGO_CONFIRMADO, PAGO_PENDIENTE, PAGO_RECHAZADO, PLAN_GRATIS,
    TIPO_CUADRO, TIPO_ESCALERA,
)
from .util import (
    CARPETA_ARCHIVOS, link_whatsapp, organizador_actual, organizador_requerido, slug_unico,
)

FILAS_CATEGORIA_NUEVAS = 3


def _mi_competencia(comp_id):
    org = organizador_actual()
    comp = db.session.get(Competencia, comp_id)
    if not comp or comp.organizador_id != org.id:
        abort(404)
    return comp


def _puede_crear(org):
    """El plan gratis permite una sola competencia (sin contar canceladas)."""
    if org.plan != PLAN_GRATIS:
        return True
    usadas = Competencia.query.filter(
        Competencia.organizador_id == org.id, Competencia.estado != EST_CANCELADA
    ).count()
    return usadas == 0


def _fecha(valor):
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date() if valor else None
    except ValueError:
        return None


def _fecha_hora(valor):
    try:
        return datetime.strptime(valor, "%Y-%m-%dT%H:%M") if valor else None
    except ValueError:
        return None


@bp.route("/panel")
@organizador_requerido
def panel():
    org = organizador_actual()
    competencias = (
        Competencia.query.filter_by(organizador_id=org.id)
        .order_by(Competencia.creado_en.desc()).all()
    )
    return render_template(
        "torneos/panel.html",
        **contexto(
            org=org, competencias=competencias, puede_crear=_puede_crear(org),
            bienvenida=request.args.get("bienvenida"),
        ),
    )


def _guardar_competencia(comp, form):
    """Pasa el formulario a la competencia. Devuelve un error o None."""
    nombre = (form.get("nombre") or "").strip()[:150]
    if not nombre:
        return "Poné un nombre."
    if comp.id is None:
        tipo = form.get("tipo")
        if tipo not in (TIPO_CUADRO, TIPO_ESCALERA):
            return "Elegí si es un torneo con cuadro o una escalera."
        comp.tipo = tipo
        comp.reglas = reglas_mod.por_defecto(tipo)
    try:
        precio = int((form.get("precio") or "0").replace(".", "").replace("$", "").strip() or 0)
    except ValueError:
        return "El precio tiene que ser un número, sin centavos."
    inicio, fin = _fecha(form.get("fecha_inicio")), _fecha(form.get("fecha_fin"))
    if inicio and fin and fin < inicio:
        return "La fecha de fin es anterior a la de inicio."

    # Categorías: filas existentes (cat_id_N) y nuevas
    filas = []
    for clave in form:
        if not clave.startswith("cat_nombre_"):
            continue
        n = clave[len("cat_nombre_"):]
        cat_nombre = (form.get(clave) or "").strip()[:80]
        cupo_txt = (form.get(f"cat_cupo_{n}") or "").strip()
        if cupo_txt and not cupo_txt.isdigit():
            return f"El cupo de \"{cat_nombre or 'una categoría'}\" tiene que ser un número."
        filas.append({
            "id": form.get(f"cat_id_{n}") or None,
            "nombre": cat_nombre,
            "modalidad": "dobles" if form.get(f"cat_modalidad_{n}") == "dobles" else "singles",
            "cupo": int(cupo_txt) if cupo_txt else None,
            "orden": int(n) if n.isdigit() else 99,
        })
    if not any(f["nombre"] for f in filas):
        return "Agregá al menos una categoría."

    comp.nombre = nombre
    comp.deporte = "Tenis"
    comp.sede = (form.get("sede") or "").strip()[:150]
    comp.localidad = (form.get("localidad") or "").strip()[:100]
    comp.descripcion = (form.get("descripcion") or "").strip()[:3000]
    comp.fecha_inicio, comp.fecha_fin = inicio, fin
    comp.cierre_inscripcion = _fecha_hora(form.get("cierre_inscripcion"))
    comp.precio = max(0, precio)
    comp.incluye = (form.get("incluye") or "").strip()[:150]
    if comp.id is None:
        comp.slug = slug_unico(Competencia, nombre)
        db.session.add(comp)
        db.session.flush()

    existentes = {str(c.id): c for c in comp.categorias}
    for f in sorted(filas, key=lambda x: x["orden"]):
        cat = existentes.get(f["id"]) if f["id"] else None
        if cat and not f["nombre"]:
            # borrar solo si no tiene inscriptos
            if not cat.inscripciones:
                db.session.delete(cat)
            continue
        if not f["nombre"]:
            continue
        if not cat:
            cat = Categoria(competencia_id=comp.id)
            db.session.add(cat)
        cat.nombre, cat.modalidad, cat.cupo, cat.orden = f["nombre"], f["modalidad"], f["cupo"], f["orden"]
    return None


@bp.route("/panel/nueva", methods=["GET", "POST"])
@organizador_requerido
def competencia_nueva():
    org = organizador_actual()
    if not _puede_crear(org):
        return redirect(url_for("torneos.panel"))
    comp = Competencia(organizador_id=org.id, estado=EST_BORRADOR)
    error = None
    if request.method == "POST":
        error = _guardar_competencia(comp, request.form)
        if not error:
            db.session.commit()
            return redirect(url_for("torneos.competencia_panel", comp_id=comp.id))
        db.session.rollback()
        comp = Competencia(organizador_id=org.id, estado=EST_BORRADOR)
    return render_template(
        "torneos/competencia_form.html",
        **contexto(comp=comp, error=error, form=request.form, filas_nuevas=FILAS_CATEGORIA_NUEVAS + 2),
    )


@bp.route("/panel/<int:comp_id>/editar", methods=["GET", "POST"])
@organizador_requerido
def competencia_editar(comp_id):
    comp = _mi_competencia(comp_id)
    error = None
    if request.method == "POST":
        error = _guardar_competencia(comp, request.form)
        if not error:
            db.session.commit()
            return redirect(url_for("torneos.competencia_panel", comp_id=comp.id))
        db.session.rollback()
    return render_template(
        "torneos/competencia_form.html",
        **contexto(comp=comp, error=error, form=request.form if error else None,
                   filas_nuevas=FILAS_CATEGORIA_NUEVAS),
    )


@bp.route("/panel/<int:comp_id>/estado", methods=["POST"])
@organizador_requerido
def competencia_estado(comp_id):
    """Abrir inscripción, cerrarla (empieza el juego), volver a borrador o cancelar."""
    comp = _mi_competencia(comp_id)
    accion = request.form.get("accion")
    if accion == "abrir" and comp.estado == EST_BORRADOR and comp.categorias:
        comp.estado = EST_INSCRIPCION
    elif accion == "cerrar" and comp.estado == EST_INSCRIPCION:
        comp.estado = EST_EN_CURSO
    elif accion == "borrador" and comp.estado == EST_INSCRIPCION and not _hay_inscriptos(comp):
        comp.estado = EST_BORRADOR
    elif accion == "cancelar" and comp.estado in (EST_BORRADOR, EST_INSCRIPCION):
        comp.estado = EST_CANCELADA
    db.session.commit()
    return redirect(url_for("torneos.competencia_panel", comp_id=comp.id))


def _hay_inscriptos(comp):
    return any(not i.baja for c in comp.categorias for i in c.inscripciones)


@bp.route("/panel/<int:comp_id>")
@organizador_requerido
def competencia_panel(comp_id):
    comp = _mi_competencia(comp_id)
    url_publica = url_for("torneos.torneo", slug=comp.slug, _external=True)
    categorias = []
    for cat in sorted(comp.categorias, key=lambda c: c.orden):
        inscriptos = sorted(cat.inscripciones, key=lambda i: (i.baja, i.creado_en))
        filas = []
        for i in inscriptos:
            enlace = url_for("torneos.jugador", enlace=i.jugador1.enlace, _external=True)
            texto = (
                f"Hola {i.jugador1.nombre}! Confirmamos tu inscripción en {comp.nombre} "
                f"({cat.nombre}). Desde este enlace seguís todo: {enlace}"
            )
            filas.append({"i": i, "wa": link_whatsapp(i.jugador1.celular, texto)})
        activos = [i for i in inscriptos if not i.baja]
        categorias.append({
            "cat": cat, "filas": filas, "activos": len(activos),
            "confirmados": sum(1 for i in activos if i.estado_pago == PAGO_CONFIRMADO),
        })
    return render_template(
        "torneos/competencia_panel.html",
        **contexto(
            comp=comp, categorias=categorias, url_publica=url_publica,
            niveles=comp.reglas.get("niveles_iniciales", []),
        ),
    )


@bp.route("/panel/inscripcion/<int:insc_id>", methods=["POST"])
@organizador_requerido
def inscripcion_accion(insc_id):
    insc = db.session.get(Inscripcion, insc_id)
    if not insc:
        abort(404)
    comp = _mi_competencia(insc.categoria.competencia_id)
    accion = request.form.get("accion")
    if accion == "confirmar":
        insc.estado_pago = PAGO_CONFIRMADO
    elif accion == "rechazar":
        insc.estado_pago = PAGO_RECHAZADO
    elif accion == "pendiente":
        insc.estado_pago = PAGO_PENDIENTE
    elif accion == "baja":
        insc.baja = True
    elif accion == "alta":
        insc.baja = False
    elif accion == "nivel":
        valor = (request.form.get("nivel") or "").replace(",", ".").strip()
        try:
            insc.nivel_inicial = float(valor) if valor else None
        except ValueError:
            pass
    db.session.commit()
    return redirect(url_for("torneos.competencia_panel", comp_id=comp.id) + f"#cat-{insc.categoria_id}")


@bp.route("/panel/inscripcion/<int:insc_id>/comprobante")
@organizador_requerido
def comprobante(insc_id):
    """El comprobante solo lo ve el organizador de esa competencia."""
    insc = db.session.get(Inscripcion, insc_id)
    if not insc or not insc.comprobante:
        abort(404)
    _mi_competencia(insc.categoria.competencia_id)
    nombre = os.path.basename(insc.comprobante)
    return send_from_directory(CARPETA_ARCHIVOS, nombre)
