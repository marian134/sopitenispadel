"""Acciones del jugador en la escalera, desde su enlace personal:
desafiar, responder, cargar y confirmar resultados, pedir semana libre."""
import os
from datetime import datetime, timedelta

from flask import abort, redirect, request, send_from_directory, url_for

from models import db
from . import avisos
from . import escalera as esc
from .bp import bp
from .models import (
    Inscripcion, Jugador, Partido, Resultado,
    PAR_AGENDADO, PAR_DESAFIO, PAR_EN_DISPUTA, PAR_RECHAZADO,
)
from .util import CARPETA_ARCHIVOS, guardar_archivo, organizador_actual

def _msj_confirmado(comp):
    return {"cuadro": "confirmado_cuadro", "liga": "confirmado_liga"}.get(comp.tipo, "confirmado")


def esperando_horario(comp, p):
    """En el cuadro, el resultado se carga recién cuando el organizador fijó el horario
    (salvo que la ronda tenga plazo y los jugadores lo arreglen solos)."""
    if comp.tipo != "cuadro" or p.fecha_hora:
        return False
    from . import cuadro as cdr
    plazo = cdr.plazo_de(comp, p)
    return not (plazo and plazo.get("hasta"))


MENSAJES = {
    "comprobante": "Listo, mandaste el comprobante. El organizador lo revisa y te confirma.",
    "desafio": "Desafío enviado. Avisale a tu rival por WhatsApp para que lo responda.",
    "aceptado": "Aceptaste el desafío. Coordinen día y cancha, y después carguen el resultado.",
    "rechazado": "Rechazaste el desafío.",
    "no_rechazo": "No podés rechazar dos desafíos seguidos: tenés que aceptar este.",
    "resultado": "Resultado cargado. Falta que tu rival lo confirme.",
    "confirmado": "¡Resultado confirmado! Los puntos se suman al ranking del lunes.",
    "confirmado_cuadro": "¡Resultado confirmado! Ya quedó cargado en el cuadro.",
    "confirmado_liga": "¡Resultado confirmado! Ya suma en la tabla.",
    "disputa": "Los resultados no coinciden: lo va a definir el organizador.",
    "wo": "Avisamos al organizador que tu rival no se presentó. Él lo define.",
    "libre": "Listo, tenés la semana que viene libre: no vas a perder puntos por inactividad.",
    "no_libre": "No te quedan semanas libres.",
    "invalido": "Ese desafío ya no es válido (cambió el ranking o ya hay un partido entre ustedes).",
    "selfie": "Falta la selfie del partido.",
    "no_juego": "La escalera no está en juego en este momento.",
    "anotado": "¡Listo! Estás anotado para la fecha. El organizador arma los partidos y te avisa.",
    "desanotado": "Te bajaste de la fecha.",
    "con_partido": "Ya tenés partido armado en esa fecha: si no podés, avisale al organizador.",
}


@bp.route("/jugador/<enlace>/liga-fecha", methods=["POST"])
def liga_anotarse(enlace):
    """El jugador se anota (o se baja) para una fecha de la liga."""
    from . import liga
    j = _jugador(enlace)
    insc = _mi_inscripcion(j, request.form.get("insc", type=int))
    comp = insc.categoria.competencia
    numero = request.form.get("fecha", type=int)
    dia = liga.fecha_numero(comp, numero) if comp.tipo == "liga" else None
    from datetime import date
    if not dia or dia < date.today() or not liga.participa(insc):
        return _volver(enlace, error="invalido", ancla=f"insc-{insc.id}")
    si = request.form.get("accion") == "anotarme"
    if not si and any(insc.id in (p.lado_a_id, p.lado_b_id)
                      for p in Partido.query.filter_by(competencia_id=comp.id, semana=numero).all()):
        return _volver(enlace, error="con_partido", ancla=f"insc-{insc.id}")
    liga.marcar_disponible(comp, insc, numero, si)
    db.session.commit()
    return _volver(enlace, msj="anotado" if si else "desanotado", ancla=f"insc-{insc.id}")


def _jugador(enlace):
    return Jugador.query.filter_by(enlace=enlace).first_or_404()


def _mi_inscripcion(j, insc_id):
    insc = db.session.get(Inscripcion, insc_id or 0)
    if not insc or j.id not in (insc.jugador1_id, insc.jugador2_id):
        abort(404)
    return insc


def _mi_partido(j, partido_id):
    p = db.session.get(Partido, partido_id or 0)
    if not p:
        abort(404)
    for insc in (p.lado_a, p.lado_b):
        if insc and j.id in (insc.jugador1_id, insc.jugador2_id):
            return p, insc
    abort(404)


def _volver(enlace, msj=None, error=None, ancla=""):
    args = {"enlace": enlace}
    if msj:
        args["msj"] = msj
    if error:
        args["error"] = error
    return redirect(url_for("torneos.jugador", **args) + (f"#{ancla}" if ancla else ""))


@bp.route("/jugador/<enlace>/desafiar", methods=["POST"])
def desafiar(enlace):
    j = _jugador(enlace)
    insc = _mi_inscripcion(j, request.form.get("insc", type=int))
    comp = insc.categoria.competencia
    esc.procesar(comp)
    if not esc.en_juego(comp):
        return _volver(enlace, error="no_juego")
    semana = esc.semana_actual(comp)
    grupos = esc.ranking(insc.categoria, semana)
    rival_id = request.form.get("rival", type=int)
    validos = {f["insc"].id: f["insc"] for f in esc.desafiables(insc, grupos, semana)}
    if rival_id not in validos:
        return _volver(enlace, error="invalido", ancla=f"insc-{insc.id}")
    dias = int(comp.reglas.get("plazo_respuesta_dias") or 2)
    nuevo = Partido(
        competencia_id=comp.id, categoria_id=insc.categoria_id, semana=semana,
        lado_a_id=insc.id, lado_b_id=rival_id, desafiante_id=insc.id,
        estado=PAR_DESAFIO, vence_en=datetime.now() + timedelta(days=dias),
    )
    db.session.add(nuevo)
    db.session.commit()
    avisos.desafio(nuevo)
    return _volver(enlace, msj="desafio", ancla=f"insc-{insc.id}")


@bp.route("/jugador/<enlace>/responder", methods=["POST"])
def responder(enlace):
    j = _jugador(enlace)
    p, mia = _mi_partido(j, request.form.get("partido", type=int))
    comp = p.lado_a.categoria.competencia
    esc.procesar(comp)
    if p.estado != PAR_DESAFIO or p.lado_b_id != mia.id:
        return _volver(enlace, error="invalido")
    if request.form.get("accion") == "aceptar":
        p.estado = PAR_AGENDADO
        mia.rechazos_seguidos = 0
        msj = "aceptado"
    else:
        maximo = int(comp.reglas.get("rechazos_seguidos_max") or 1)
        if (mia.rechazos_seguidos or 0) >= maximo:
            return _volver(enlace, error="no_rechazo", ancla=f"insc-{mia.id}")
        p.estado = PAR_RECHAZADO
        mia.rechazos_seguidos = (mia.rechazos_seguidos or 0) + 1
        msj = "rechazado"
    db.session.commit()
    return _volver(enlace, msj=msj, ancla=f"insc-{mia.id}")


def _sets_del_form(form, un_set=False):
    """Lee los sets que cargó el jugador (desde su lado) y devuelve el texto."""
    partes = []
    for n in (1, 2, 3):
        mio, suyo = (form.get(f"s{n}a") or "").strip(), (form.get(f"s{n}b") or "").strip()
        if mio == "" and suyo == "":
            continue
        if not (mio.isdigit() and suyo.isdigit()):
            raise ValueError("Completá los games de cada set con números.")
        partes.append(f"{int(mio)}-{int(suyo)}")
    return esc.sets_texto(esc.leer_sets(" ".join(partes), un_set=un_set))


@bp.route("/jugador/<enlace>/resultado", methods=["POST"])
def cargar_resultado(enlace):
    j = _jugador(enlace)
    p, mia = _mi_partido(j, request.form.get("partido", type=int))
    comp = p.lado_a.categoria.competencia
    if p.estado != PAR_AGENDADO or esc.resultado_de_jugador(p, mia):
        return _volver(enlace, error="invalido")
    if esperando_horario(comp, p):
        return redirect(url_for("torneos.jugador", enlace=enlace,
                                error_texto="Vas a poder cargar el resultado cuando el organizador fije día, hora y cancha.")
                        + f"#partido-{p.id}")
    try:
        desde_mi_lado = _sets_del_form(request.form, un_set=comp.tipo == "cuadro")
    except ValueError as e:
        return redirect(url_for("torneos.jugador", enlace=enlace, error_texto=str(e)) + f"#partido-{p.id}")
    selfie = None
    if request.files.get("selfie") and request.files["selfie"].filename:
        try:
            selfie = guardar_archivo(request.files["selfie"])
        except ValueError as e:
            return redirect(url_for("torneos.jugador", enlace=enlace, error_texto=str(e)) + f"#partido-{p.id}")
    elif comp.reglas.get("selfie_obligatoria", comp.tipo == "escalera"):
        return _volver(enlace, error="selfie", ancla=f"partido-{p.id}")

    lado_a = desde_mi_lado if mia.id == p.lado_a_id else esc.invertir(desde_mi_lado)
    otro = next((r for r in p.resultados if r.cargado_por == "jugador" and r.cargado_por_id != mia.id), None)
    db.session.add(Resultado(partido_id=p.id, cargado_por="jugador", cargado_por_id=mia.id,
                             sets=lado_a, selfie=selfie))
    db.session.flush()
    if otro:
        if otro.sets == lado_a:
            esc.aplicar_resultado(p, lado_a)
            msj = _msj_confirmado(comp)
        else:
            p.estado = PAR_EN_DISPUTA
            msj = "disputa"
    else:
        msj = "resultado"
    db.session.commit()
    if msj == "resultado":
        avisos.resultado_para_confirmar(p, mia)
    return _volver(enlace, msj=msj, ancla=f"insc-{mia.id}")


@bp.route("/jugador/<enlace>/comprobante", methods=["POST"])
def subir_comprobante(enlace):
    """El jugador sube (o vuelve a subir) el comprobante de pago."""
    j = _jugador(enlace)
    insc = _mi_inscripcion(j, request.form.get("insc", type=int))
    if insc.baja or insc.estado_pago == "confirmado":
        return _volver(enlace, ancla=f"insc-{insc.id}")
    try:
        insc.comprobante = guardar_archivo(request.files.get("comprobante"))
    except ValueError as e:
        return redirect(url_for("torneos.jugador", enlace=enlace, error_texto=f"Comprobante: {e}") + f"#insc-{insc.id}")
    insc.estado_pago = "pendiente"
    db.session.commit()
    return _volver(enlace, msj="comprobante", ancla=f"insc-{insc.id}")


@bp.route("/jugador/<enlace>/confirmar", methods=["POST"])
def confirmar_resultado(enlace):
    """El rival confirma (o no) el resultado que cargó el otro."""
    j = _jugador(enlace)
    p, mia = _mi_partido(j, request.form.get("partido", type=int))
    otro = next((r for r in p.resultados if r.cargado_por == "jugador" and r.cargado_por_id != mia.id), None)
    if p.estado != PAR_AGENDADO or not otro or otro.ausente_id:
        return _volver(enlace, error="invalido")
    if request.form.get("accion") == "confirmar":
        esc.aplicar_resultado(p, otro.sets)
        msj = _msj_confirmado(p.lado_a.categoria.competencia)
    else:
        p.estado = PAR_EN_DISPUTA
        msj = "disputa"
    db.session.commit()
    return _volver(enlace, msj=msj, ancla=f"insc-{mia.id}")


@bp.route("/jugador/<enlace>/wo", methods=["POST"])
def reclamar_wo(enlace):
    """El jugador avisa que el rival no se presentó: lo define el organizador."""
    j = _jugador(enlace)
    p, mia = _mi_partido(j, request.form.get("partido", type=int))
    if p.estado != PAR_AGENDADO:
        return _volver(enlace, error="invalido")
    rival_id = p.lado_b_id if mia.id == p.lado_a_id else p.lado_a_id
    db.session.add(Resultado(partido_id=p.id, cargado_por="jugador", cargado_por_id=mia.id,
                             sets="W.O.", ausente_id=rival_id))
    p.estado = PAR_EN_DISPUTA
    db.session.commit()
    return _volver(enlace, msj="wo", ancla=f"insc-{mia.id}")


@bp.route("/jugador/<enlace>/semana-libre", methods=["POST"])
def semana_libre(enlace):
    """Pide la semana que viene libre (hay que avisar con una semana de anticipación)."""
    j = _jugador(enlace)
    insc = _mi_inscripcion(j, request.form.get("insc", type=int))
    comp = insc.categoria.competencia
    if not esc.en_juego(comp):
        return _volver(enlace, error="no_juego")
    proxima = esc.semana_actual(comp) + 1
    disponibles = int(comp.reglas.get("semanas_libres") or 0) - esc.semanas_libres_usadas(insc)
    if disponibles <= 0 or proxima > esc.total_semanas(comp):
        return _volver(enlace, error="no_libre", ancla=f"insc-{insc.id}")
    if not esc.tiene_semana_libre(insc, proxima):
        esc.pedir_semana_libre(insc, proxima)
        db.session.commit()
    return _volver(enlace, msj="libre", ancla=f"insc-{insc.id}")


@bp.route("/resultado/<int:res_id>/selfie")
def ver_selfie(res_id):
    """La selfie la ven los dos jugadores del partido y su organizador."""
    r = db.session.get(Resultado, res_id)
    if not r or not r.selfie:
        abort(404)
    p = r.partido
    org = organizador_actual()
    permitido = org and p.lado_a.categoria.competencia.organizador_id == org.id
    enlace = request.args.get("e")
    if not permitido and enlace:
        j = Jugador.query.filter_by(enlace=enlace).first()
        permitido = bool(j) and any(
            insc and j.id in (insc.jugador1_id, insc.jugador2_id) for insc in (p.lado_a, p.lado_b)
        )
    if not permitido:
        abort(404)
    from .archivos import servir
    return servir(r.selfie)
