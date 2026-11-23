"""Panel del organizador para torneos con cuadro: armar la llave, consuelo,
horarios y opciones."""
from datetime import datetime

from flask import abort, redirect, render_template, request, url_for

from models import db
from . import avisos
from . import cuadro as cdr
from . import zonas as zns
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
    if zns.activas(comp):
        return _volver(comp, "Este torneo empieza con zonas: armá las zonas primero.", f"cuadro-{cat.id}")
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
    avisos.partidos_nuevos(cdr.partidos(cat))
    return _volver(comp, ancla=f"cuadro-{cat.id}")


@bp.route("/panel/<int:comp_id>/zonas/<int:cat_id>/armar", methods=["POST"])
@organizador_requerido
def zonas_armar(comp_id, cat_id):
    comp, cat = _mi_categoria(comp_id, cat_id)
    if zns.hay_resultados(cat) or cdr.hay_resultados(cat):
        return _volver(comp, "Las zonas ya tienen resultados: no se pueden volver a sortear.", f"cuadro-{cat.id}")
    try:
        zns.armar(cat)
    except ValueError as e:
        db.session.rollback()
        return _volver(comp, str(e), f"cuadro-{cat.id}")
    db.session.commit()
    avisos.partidos_nuevos(zns.partidos(cat))
    return _volver(comp, ancla=f"cuadro-{cat.id}")


@bp.route("/panel/<int:comp_id>/zonas/<int:cat_id>/pasar", methods=["POST"])
@organizador_requerido
def zonas_pasar(comp_id, cat_id):
    """Pasa los clasificados de las zonas al cuadro principal."""
    comp, cat = _mi_categoria(comp_id, cat_id)
    if cdr.hay_resultados(cat):
        return _volver(comp, "El cuadro ya tiene resultados: no se puede volver a armar.", f"cuadro-{cat.id}")
    try:
        zns.pasar_al_cuadro(cat)
    except ValueError as e:
        db.session.rollback()
        return _volver(comp, str(e), f"cuadro-{cat.id}")
    db.session.commit()
    avisos.partidos_nuevos(cdr.partidos(cat))
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
    avisos.partidos_nuevos(cdr.partidos(cat, cdr.CONSUELO))
    return _volver(comp, ancla=f"cuadro-{cat.id}")


def _error_horario(comp, p, error):
    return redirect(url_for("torneos.competencia_panel", comp_id=comp.id, error_horario=error,
                            partido_error=p.id) + f"#partido-{p.id}")


@bp.route("/panel/partido/<int:partido_id>/horario", methods=["POST"])
@organizador_requerido
def partido_horario(partido_id):
    p = db.session.get(Partido, partido_id)
    if not p:
        abort(404)
    comp = _mi_competencia(p.competencia_id)
    f = request.form
    dia, hora, cancha = (f.get("dia") or "").strip(), (f.get("hora") or "").strip(), (f.get("cancha") or "").strip()[:40]
    if f.get("fecha_hora") and not dia:   # formato anterior (un solo campo)
        dia, _, hora = f.get("fecha_hora").partition("T")
    faltan = [n for n, v in (("el día", dia), ("la hora", hora), ("la cancha", cancha)) if not v]
    if faltan:
        return _error_horario(comp, p, f"Para guardar el horario falta {', '.join(faltan)}.")
    try:
        nuevo = datetime.strptime(f"{dia}T{hora[:5]}", "%Y-%m-%dT%H:%M")
    except ValueError:
        return _error_horario(comp, p, "El día o la hora no son válidos.")
    cambio = (p.fecha_hora, p.cancha)
    if p.fecha_hora != nuevo:
        p.recordado = False   # si cambió el día, vuelve a salir el recordatorio
    p.fecha_hora, p.cancha = nuevo, cancha
    db.session.commit()
    if cambio != (p.fecha_hora, p.cancha):
        avisos.horario(p)
    return redirect(url_for("torneos.competencia_panel", comp_id=comp.id, guardado=p.id) + f"#partido-{p.id}")


@bp.route("/panel/<int:comp_id>/opciones", methods=["GET", "POST"])
@organizador_requerido
def opciones_cuadro(comp_id):
    comp = _mi_competencia(comp_id)
    if comp.tipo != TIPO_CUADRO:
        abort(404)
    reglas = comp.reglas
    guardado, error = False, None
    if request.method == "POST":
        f = request.form
        reglas["consuelo"] = bool(f.get("consuelo"))
        reglas["tercer_puesto"] = bool(f.get("tercer_puesto"))
        reglas["formato_partido"] = (f.get("formato_partido") or "").strip()[:100]
        reglas["selfie_obligatoria"] = bool(f.get("selfie_obligatoria"))
        try:
            zonas_cfg = {
                "activo": bool(f.get("zonas_activo")),
                "tamano": min(6, max(3, int(f.get("zonas_tamano") or 3))),
                "clasifican": min(4, max(1, int(f.get("zonas_clasifican") or 2))),
                "puntos": {k: float((f.get(f"zp_{k}") or "0").replace(",", "."))
                           for k in ("gana", "pierde", "bonus_set", "gana_wo", "pierde_wo")},
                "desempate": [c for c in (f.get(f"desempate_{n}") for n in range(1, 6))
                              if c in zns.CRITERIOS],
            }
            plazos = {}
            for clave, _nombre in cdr.ETAPAS:
                desde, hasta = f.get(f"plazo_desde_{clave}") or "", f.get(f"plazo_hasta_{clave}") or ""
                if desde or hasta:
                    for v in (desde, hasta):
                        if v:
                            datetime.strptime(v, "%Y-%m-%d")
                    plazos[clave] = {"desde": desde, "hasta": hasta}
        except ValueError:
            error = "Revisá los números y las fechas."
        else:
            reglas["zonas"] = zonas_cfg
            reglas["plazos"] = plazos
            comp.reglas = reglas
            db.session.commit()
            guardado = True
    return render_template(
        "torneos/opciones_cuadro.html",
        **contexto(comp=comp, reglas=reglas, guardado=guardado, error=error, zonas=zns.reglas(comp),
                   criterios=zns.CRITERIOS, etapas=cdr.ETAPAS, plazos=reglas.get("plazos") or {}),
    )


def datos_cuadro(comp):
    """Lo que el panel necesita de cada categoría con cuadro."""
    avisos = cdr.avisos_horarios(comp)
    categorias = []
    for cat in sorted(comp.categorias, key=lambda c: c.orden):
        participantes = cdr.participantes(cat)
        t = cdr.tamano(len(participantes)) if len(participantes) >= 2 else 0
        entrantes, pendientes = cdr.entrantes_consuelo(cat) if cdr.partidos(cat) else ([], 0)
        zonas = zns.estructura(cat) if zns.activas(comp) else []
        categorias.append({
            "cat": cat,
            "zonas": zonas,
            "zonas_armadas": bool(zonas),
            "zonas_pendientes": sum(z["pendientes"] for z in zonas),
            "zonas_con_resultados": zns.hay_resultados(cat) if zonas else False,
            "participantes": len(participantes),
            "tamano": t, "byes": t - len(participantes) if t else 0, "max_cabezas": cdr.max_cabezas(t),
            "principal": cdr.estructura(cat),
            "consuelo": cdr.estructura(cat, cdr.CONSUELO),
            "tercer": cdr.partidos(cat, cdr.TERCER),
            "campeon": cdr.campeon(cat), "podio": cdr.podio(cat),
            "campeon_consuelo": cdr.campeon(cat, cdr.CONSUELO),
            "con_resultados": cdr.hay_resultados(cat),
            "consuelo_listo": not pendientes and len(entrantes) >= 2,
            "consuelo_entrantes": len(entrantes), "consuelo_pendientes": pendientes,
        })
    por_jugar = (
        Partido.query.filter(Partido.competencia_id == comp.id, Partido.estado.in_((PAR_AGENDADO, PAR_PENDIENTE)))
        .all()
    )
    por_jugar = [p for p in por_jugar if (p.lado_a_id or p.lado_b_id) and p.cuadro != cdr.ZONA]
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
    return {
        "categorias": categorias, "por_jugar": filas, "zonas_activas": zns.activas(comp),
        "reglas_zonas": zns.reglas(comp), "vencidos": cdr.plazos_vencidos(comp),
        "plazos": [(nombre, (comp.reglas.get("plazos") or {}).get(clave)) for clave, nombre in cdr.ETAPAS
                   if (comp.reglas.get("plazos") or {}).get(clave)],
    }
