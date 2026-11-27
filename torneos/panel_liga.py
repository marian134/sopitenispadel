"""Panel del organizador para la liga por fechas: opciones, fechas y partidos."""
from datetime import date, timedelta

from flask import abort, redirect, render_template, request, url_for

from models import db
from . import avisos
from . import liga
from .bp import bp, contexto
from .models import Partido, TIPO_LIGA, PAR_AGENDADO
from .panel import _mi_competencia
from .util import link_whatsapp, organizador_requerido


def _mi_liga(comp_id):
    comp = _mi_competencia(comp_id)
    if comp.tipo != TIPO_LIGA:
        abort(404)
    return comp


def _volver(comp, ancla="liga", error=None):
    args = {"comp_id": comp.id}
    if error:
        args["error"] = error
    return redirect(url_for("torneos.competencia_panel", **args) + f"#{ancla}")


def _numero(texto, defecto=0.0):
    try:
        return float((texto or "").replace(",", ".").strip() or defecto)
    except ValueError:
        raise ValueError("Revisá los números de la escala de puntos.")


@bp.route("/panel/<int:comp_id>/liga/opciones", methods=["GET", "POST"])
@organizador_requerido
def opciones_liga(comp_id):
    comp = _mi_liga(comp_id)
    reglas = comp.reglas
    error, guardado = None, False
    if request.method == "POST":
        f = request.form
        try:
            reglas["puntos"] = {
                "por_game": _numero(f.get("por_game"), 1),
                "gana_partido": _numero(f.get("gana_partido"), 3),
                "gana_super_tiebreak": _numero(f.get("gana_super_tiebreak"), 1),
            }
            fechas = []
            if f.get("generar") and f.get("primera"):
                primera = date.fromisoformat(f["primera"])
                cantidad = max(1, min(52, int(f.get("cantidad") or 1)))
                cada = max(1, int(f.get("cada") or 7))
                fechas = [(primera + timedelta(days=cada * k)).isoformat() for k in range(cantidad)]
            else:
                for linea in (f.get("fechas") or "").split():
                    fechas.append(date.fromisoformat(linea.strip()).isoformat())
            reglas["fechas"] = sorted(set(fechas))
            reglas["formato_partido"] = (f.get("formato_partido") or "").strip()[:120]
            reglas["wo_como"] = (f.get("wo_como") or "6-0 6-0").strip()[:20]
            liga.puntos_partido(comp, reglas["wo_como"])   # valida que sea un resultado posible
            reglas["precio_por_partido"] = (f.get("precio_por_partido") or "").strip()[:150]
            reglas["premio"] = (f.get("premio") or "").strip()[:300]
        except ValueError as e:
            error = str(e) if "puntos" in str(e) or "set" in str(e).lower() else \
                "Revisá las fechas (formato AAAA-MM-DD) y los números."
        else:
            comp.reglas = reglas
            if comp.fecha_inicio is None and reglas["fechas"]:
                comp.fecha_inicio = date.fromisoformat(reglas["fechas"][0])
                comp.fecha_fin = date.fromisoformat(reglas["fechas"][-1])
            db.session.commit()
            guardado = True
    return render_template(
        "torneos/opciones_liga.html",
        **contexto(comp=comp, reglas=reglas, error=error, guardado=guardado,
                   ejemplo=liga.ejemplo(comp) if not error else ""),
    )


@bp.route("/panel/<int:comp_id>/liga/fecha/<int:numero>/proponer", methods=["POST"])
@organizador_requerido
def liga_proponer(comp_id, numero):
    comp = _mi_liga(comp_id)
    if not liga.fecha_numero(comp, numero):
        abort(404)
    if comp.estado in ("finalizada", "cancelada"):
        return _volver(comp, f"fecha-{numero}", "La liga ya terminó: no se pueden armar partidos nuevos.")
    parejas, _sin = liga.proponer(comp, numero)
    nuevos = [liga.crear_partido(comp, numero, a.id, b.id) for a, b in parejas]
    db.session.commit()
    avisos.partidos_nuevos(nuevos)
    return _volver(comp, f"fecha-{numero}")


@bp.route("/panel/<int:comp_id>/liga/fecha/<int:numero>/partido", methods=["POST"])
@organizador_requerido
def liga_partido_nuevo(comp_id, numero):
    comp = _mi_liga(comp_id)
    if not liga.fecha_numero(comp, numero):
        abort(404)
    if comp.estado in ("finalizada", "cancelada"):
        return _volver(comp, f"fecha-{numero}", "La liga ya terminó: no se pueden armar partidos nuevos.")
    a, b = request.form.get("a", type=int), request.form.get("b", type=int)
    validos = {i.id for i in liga.participantes(comp)}
    if not a or not b or a == b or a not in validos or b not in validos:
        return _volver(comp, f"fecha-{numero}", "Elegí dos jugadores distintos.")
    nuevo = liga.crear_partido(comp, numero, a, b)
    db.session.commit()
    avisos.partido_nuevo(nuevo)
    return _volver(comp, f"fecha-{numero}")


@bp.route("/panel/partido/<int:partido_id>/borrar", methods=["POST"])
@organizador_requerido
def liga_partido_borrar(partido_id):
    p = db.session.get(Partido, partido_id)
    if not p:
        abort(404)
    comp = _mi_liga(p.competencia_id)
    if p.estado == PAR_AGENDADO and not p.resultados:
        db.session.delete(p)
        db.session.commit()
    return _volver(comp, f"fecha-{p.semana}")


def datos_liga(comp):
    tabla = liga.tabla(comp)
    puntos = {f["insc"].id: f["puntos"] for f in tabla}
    fechas = liga.estado_fechas(comp)
    partidos = {}
    for p in Partido.query.filter_by(competencia_id=comp.id).order_by(Partido.id).all():
        partidos.setdefault(p.semana, []).append(p)
    bloques = []
    for f in fechas:
        lista = []
        for p in partidos.get(f["numero"], []):
            wa = []
            if p.estado == PAR_AGENDADO:
                cuando = f["fecha"].strftime("%d/%m") + (p.fecha_hora.strftime(" a las %H:%M") if p.fecha_hora else "")
                for yo, rival in ((p.lado_a, p.lado_b), (p.lado_b, p.lado_a)):
                    texto = (f"Hola {yo.jugador1.nombre}! En la fecha {f['numero']} de {comp.nombre} ({cuando}"
                             f"{', cancha ' + p.cancha if p.cancha else ''}) jugás con {rival.jugador1.nombre_completo}.")
                    wa.append((yo.jugador1.nombre, link_whatsapp(yo.jugador1.celular, texto)))
            lista.append({"p": p, "puntos": liga.puntos_de(p), "wa": wa})
        anotados = liga.disponibles(comp, f["numero"])
        ocupados = {i for p in partidos.get(f["numero"], []) for i in (p.lado_a_id, p.lado_b_id)}
        bloques.append({**f, "partidos": lista, "anotados": anotados,
                        "sin_partido": [i for i in anotados if i.id not in ocupados]})
    return {
        "tabla": tabla, "puntos": puntos, "fechas": bloques, "proxima": liga.proxima_fecha(comp),
        "participantes": sorted(liga.participantes(comp), key=lambda i: i.jugador1.apellido),
        "ejemplo": liga.ejemplo(comp),
    }
