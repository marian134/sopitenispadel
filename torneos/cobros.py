"""Lo que Sopi le cobra a los organizadores del plan pago.

- El cobro se crea al cerrar la inscripción de un torneo con cuadro, o al
  terminar la última semana de una escalera: jugadores inscriptos × precio
  por inscripto del organizador ($2.000 por defecto).
- Cuentan los jugadores con la inscripción activa (y el pago confirmado si la
  inscripción tiene precio). Una pareja de dobles son 2 jugadores.
- Un organizador que debe más de un cobro no puede crear torneos nuevos.
"""
from models import db
from .models import Cobro, PAGO_CONFIRMADO, PLAN_PAGO

MAXIMO_COBROS_IMPAGOS = 1


def jugadores_cobrables(comp):
    total = 0
    for cat in comp.categorias:
        for i in cat.inscripciones:
            if i.baja or (comp.precio and i.estado_pago != PAGO_CONFIRMADO):
                continue
            total += 2 if i.jugador2_id else 1
    return total


def crear_cobro(comp):
    """Crea el cobro de la competencia (una sola vez). Devuelve el cobro o None."""
    org = comp.organizador
    if org.plan != PLAN_PAGO:
        return None
    existente = Cobro.query.filter_by(competencia_id=comp.id).first()
    if existente:
        return existente
    jugadores = jugadores_cobrables(comp)
    if not jugadores:
        return None
    cobro = Cobro(organizador_id=org.id, competencia_id=comp.id, inscriptos=jugadores,
                  precio_unitario=org.precio_por_inscripto)
    db.session.add(cobro)
    return cobro


def impagos(org):
    return Cobro.query.filter_by(organizador_id=org.id, pagado=False).order_by(Cobro.creado_en).all()


def bloqueado_por_deuda(org):
    return len(impagos(org)) > MAXIMO_COBROS_IMPAGOS


def cargo_jugador(comp):
    """Lo que se suma al precio por jugador cuando el organizador elige
    pasarle el costo del sistema al jugador (solo plan pago)."""
    org = comp.organizador
    if org.plan == PLAN_PAGO and comp.reglas.get("cargo_al_jugador"):
        return org.precio_por_inscripto
    return 0


def precio_jugador(comp):
    return (comp.precio or 0) + cargo_jugador(comp)
