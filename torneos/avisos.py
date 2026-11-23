"""Mails al jugador: pago, partidos, horarios, desafíos, resultados y recordatorios.

Todos llevan su enlace personal. Si el mail no está configurado (en la compu
local) no se manda nada y queda anotado en el registro.
"""
from datetime import date, datetime, timedelta

from flask import url_for

from models import db
from . import util
from .models import Partido, PAR_AGENDADO

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _jugadores(insc):
    return [j for j in (insc.jugador1, insc.jugador2) if j] if insc else []


def _mandar(insc, asunto, lineas, comp):
    """Manda el mail a los jugadores de la inscripción. Devuelve cuántos salieron."""
    enviados = 0
    for j in _jugadores(insc):
        enlace = url_for("torneos.jugador", enlace=j.enlace, _external=True)
        cuerpo = "\n".join([f"Hola {j.nombre}!", "", *lineas, "", "Seguí todo desde tu enlace personal:", enlace,
                            "", f"{comp.organizador.nombre} · SOPI Torneos"])
        if util.enviar_mail(j.email, asunto, cuerpo):
            enviados += 1
    return enviados


def cuando(p):
    if not p.fecha_hora:
        return ""
    texto = f"el {DIAS[p.fecha_hora.weekday()]} {p.fecha_hora.strftime('%d/%m a las %H:%M')}"
    return texto + (f", cancha {p.cancha}" if p.cancha else "")


def _rival(p, insc):
    return p.lado_b if p.lado_a_id == insc.id else p.lado_a


def _nombre(insc):
    if not insc:
        return "a definir"
    return insc.jugador1.nombre_completo + (f" y {insc.jugador2.nombre_completo}" if insc.jugador2 else "")


def _ronda(p):
    from . import cuadro as cdr
    comp = p.lado_a.categoria.competencia
    if comp.tipo == "liga":
        return f"Fecha {p.semana}"
    if comp.tipo == "escalera":
        return "Desafío"
    return cdr.nombre_ronda(p.lado_a.categoria, p.cuadro, p.ronda, p)


# ---------------------------------------------------------------- pagos
def pago(insc):
    comp = insc.categoria.competencia
    if insc.estado_pago == "confirmado":
        return _mandar(insc, f"Estás dado de alta en {comp.nombre}", [
            f"{comp.organizador.nombre} confirmó tu pago: ya estás dado de alta en {comp.nombre} ({insc.categoria.nombre}).",
            "Cuando se armen los partidos te avisamos.",
        ], comp)
    if insc.estado_pago == "rechazado":
        return _mandar(insc, f"Revisá tu pago de {comp.nombre}", [
            f"{comp.organizador.nombre} no pudo confirmar tu pago de {comp.nombre}.",
            "Entrá a tu enlace para volver a subir el comprobante o escribile al organizador.",
        ], comp)
    return 0


def monto(insc):
    from .cobros import cargo_jugador
    comp = insc.categoria.competencia
    if not comp.precio:
        return 0
    return comp.precio + cargo_jugador(comp) * (2 if insc.jugador2_id else 1)


def recordar_pago(insc):
    comp = insc.categoria.competencia
    lineas = [f"Te recordamos que falta confirmar el pago de tu inscripción en {comp.nombre} ({insc.categoria.nombre})."]
    if monto(insc):
        lineas.append(f"Monto: {util.pesos(monto(insc))}.")
    if comp.organizador.datos_bancarios:
        lineas += ["", "Datos para transferir:", comp.organizador.datos_bancarios]
    lineas += ["", "Cuando transfieras, subí el comprobante desde tu enlace."]
    return _mandar(insc, f"Falta tu pago de {comp.nombre}", lineas, comp)


# ------------------------------------------------------------- partidos
def partido_nuevo(p):
    """Se armó un partido (cuadro, zona o fecha de liga): avisa a los dos lados."""
    if p.estado != PAR_AGENDADO or not p.lado_a or not p.lado_b:
        return 0
    from . import cuadro as cdr
    comp = p.lado_a.categoria.competencia
    plazo = cdr.plazo_de(comp, p) if comp.tipo == "cuadro" else None
    enviados = 0
    for insc in (p.lado_a, p.lado_b):
        lineas = [f"Ya tenés partido en {comp.nombre}: {_ronda(p)} contra {_nombre(_rival(p, insc))}."]
        if p.fecha_hora:
            lineas.append(f"Se juega {cuando(p)}.")
        elif plazo and plazo.get("hasta"):
            lineas.append(f"Coordiná con tu rival y juguen antes del {plazo['hasta'].strftime('%d/%m')}.")
        else:
            lineas.append("El organizador te va a avisar el día y la hora.")
        enviados += _mandar(insc, f"Tu partido en {comp.nombre}", lineas, comp)
    return enviados


def partidos_nuevos(partidos):
    return sum(partido_nuevo(p) for p in partidos)


def horario(p):
    if not p.lado_a or not p.lado_b or not p.fecha_hora:
        return 0
    comp = p.lado_a.categoria.competencia
    return sum(_mandar(insc, f"Horario de tu partido en {comp.nombre}", [
        f"Tu partido de {comp.nombre} ({_ronda(p)}) contra {_nombre(_rival(p, insc))} se juega {cuando(p)}.",
    ], comp) for insc in (p.lado_a, p.lado_b))


def desafio(p):
    comp = p.lado_a.categoria.competencia
    vence = p.vence_en.strftime("%d/%m a las %H:%M") if p.vence_en else ""
    return _mandar(p.lado_b, f"Te desafiaron en {comp.nombre}", [
        f"{_nombre(p.lado_a)} te desafió en {comp.nombre}.",
        f"Aceptalo o rechazalo desde tu enlace{' antes del ' + vence if vence else ''}.",
    ], comp)


def resultado_para_confirmar(p, quien_cargo):
    comp = p.lado_a.categoria.competencia
    otro = _rival(p, quien_cargo)
    return _mandar(otro, f"Confirmá el resultado en {comp.nombre}", [
        f"{_nombre(quien_cargo)} cargó el resultado de su partido con vos en {comp.nombre}.",
        "Entrá a tu enlace para confirmarlo o avisar si no coincide.",
    ], comp)


# -------------------------------------------------------- recordatorios
def recordatorios(hoy=None):
    """Mail a los que juegan mañana (día, hora, cancha y rival). Una sola vez por partido.
    Lo corre una tarea programada todos los días: flask --app app torneos-recordatorios"""
    hoy = hoy or date.today()
    desde = datetime.combine(hoy + timedelta(days=1), datetime.min.time())
    hasta = desde + timedelta(days=1)
    partidos = Partido.query.filter(Partido.estado == PAR_AGENDADO, Partido.fecha_hora >= desde,
                                    Partido.fecha_hora < hasta, Partido.recordado.is_(False)).all()
    enviados = 0
    for p in partidos:
        if not p.lado_a or not p.lado_b:
            continue
        comp = p.lado_a.categoria.competencia
        for insc in (p.lado_a, p.lado_b):
            enviados += _mandar(insc, f"Mañana jugás en {comp.nombre}", [
                f"Te recordamos tu partido de {comp.nombre} ({_ronda(p)}):",
                f"Contra {_nombre(_rival(p, insc))}, {cuando(p)}.",
                *([f"Sede: {comp.sede}."] if comp.sede else []),
                "Si no podés ir, avisale cuanto antes al organizador.",
            ], comp)
        p.recordado = True
    db.session.commit()
    return len(partidos), enviados
