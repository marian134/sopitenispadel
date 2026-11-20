"""Motor de la escalera de desafíos.

Cómo funciona (con las reglas por defecto de El Prado):
- La etapa arranca el día de inicio de la competencia y se divide en semanas
  de 7 días. La semana 1 empieza ese día.
- Cada partido suma o resta puntos (tabla torneo_movimiento) en la semana en
  que se desafió. El nivel oficial de un jugador es su nivel inicial más los
  puntos de las semanas YA CERRADAS: por eso el ranking "se actualiza el lunes".
- Al cerrar una semana se resta la inactividad, se guarda la foto del ranking
  y, cada N semanas, se proponen ascensos y descensos para que el organizador
  los apruebe.
- Nada corre solo: procesar() se llama cada vez que alguien abre una página de
  la escalera y pone al día lo que haya quedado pendiente.
"""
from datetime import date, datetime, timedelta

from models import db
from .models import (
    Movimiento, Partido, RankingSemana,
    EST_EN_CURSO, EST_FINALIZADA, EST_INSCRIPCION, PAGO_CONFIRMADO,
    PAR_AGENDADO, PAR_DESAFIO, PAR_EN_DISPUTA, PAR_JUGADO, PAR_VENCIDO, PAR_WO,
    PARTIDOS_ABIERTOS, TIPO_ESCALERA,
)

SIN_DIVISION = "Sin división"
NOMBRES_ESPECIALES = {
    "doble": "Puntaje doble",
    "paga_perdedor": "Paga solo el perdedor",
    "1vs1": "Desafíos 1 vs 1",
}


# ---------------------------------------------------------
# SEMANAS
# ---------------------------------------------------------
def semana_de(comp, momento):
    """Número de semana de la etapa para una fecha (0 = todavía no empezó)."""
    if not comp.fecha_inicio:
        return None
    dia = momento.date() if isinstance(momento, datetime) else momento
    dias = (dia - comp.fecha_inicio).days
    return 0 if dias < 0 else dias // 7 + 1


def semana_actual(comp, hoy=None):
    return semana_de(comp, hoy or date.today())


def inicio_semana(comp, semana):
    return datetime.combine(comp.fecha_inicio + timedelta(days=7 * (semana - 1)), datetime.min.time())


def total_semanas(comp):
    return int(comp.reglas.get("semanas") or 12)


def especial(comp, semana):
    clave = (comp.reglas.get("semanas_especiales") or {}).get(str(semana))
    return clave, NOMBRES_ESPECIALES.get(clave, clave) if clave else None


def en_juego(comp, hoy=None):
    """True si hoy se puede desafiar: escalera abierta y dentro de las semanas."""
    if comp.tipo != TIPO_ESCALERA or comp.estado not in (EST_INSCRIPCION, EST_EN_CURSO):
        return False
    s = semana_actual(comp, hoy)
    return bool(s) and 1 <= s <= total_semanas(comp)


# ---------------------------------------------------------
# PARTICIPANTES Y DIVISIONES
# ---------------------------------------------------------
def participa(insc):
    comp = insc.categoria.competencia
    pago_ok = insc.estado_pago == PAGO_CONFIRMADO or not comp.precio
    return not insc.baja and pago_ok and insc.nivel_inicial is not None


def participantes(cat):
    return [i for i in cat.inscripciones if participa(i)]


def nombres_divisiones(comp):
    return [d["nombre"] for d in comp.reglas.get("divisiones") or []]


def division_por_nivel(comp, nivel):
    for d in comp.reglas.get("divisiones") or []:
        if nivel is not None and float(nivel) in [float(n) for n in d.get("niveles", [])]:
            return d["nombre"]
    return None


# ---------------------------------------------------------
# PUNTOS Y RANKING
# ---------------------------------------------------------
def puntos_oficiales(insc, hasta_semana):
    """Nivel inicial + movimientos de las semanas anteriores a hasta_semana,
    con el piso que marcan las reglas."""
    comp = insc.categoria.competencia
    suma = sum(
        m.puntos for m in Movimiento.query.filter_by(inscripcion_id=insc.id)
        if m.semana is not None and m.semana < hasta_semana
    )
    nivel = (insc.nivel_inicial or 0) + suma
    piso = comp.reglas.get("piso_bajo_inicial")
    if piso is not None:
        nivel = max(nivel, (insc.nivel_inicial or 0) - float(piso))
    return round(nivel, 2)


def puntos_semana(insc, semana):
    return round(sum(
        m.puntos for m in Movimiento.query.filter_by(inscripcion_id=insc.id, semana=semana)
    ), 2)


def partidos_de(insc, estados=None, semana=None):
    q = Partido.query.filter(
        (Partido.lado_a_id == insc.id) | (Partido.lado_b_id == insc.id)
    )
    if estados:
        q = q.filter(Partido.estado.in_(estados))
    if semana is not None:
        q = q.filter(Partido.semana == semana)
    return q.order_by(Partido.creado_en.desc()).all()


def ranking(cat, semana_ref):
    """Ranking oficial por división: [(división, [filas])]. Cada fila tiene
    inscripción, puntos, posición (dentro de la división) y partidos jugados."""
    comp = cat.competencia
    filas = []
    for insc in participantes(cat):
        jugados = len(partidos_de(insc, estados=(PAR_JUGADO, PAR_WO)))
        filas.append({
            "insc": insc, "puntos": puntos_oficiales(insc, semana_ref), "jugados": jugados,
            "division": insc.division or SIN_DIVISION,
        })
    orden = nombres_divisiones(comp) + [SIN_DIVISION]
    grupos = []
    for nombre in orden:
        grupo = [f for f in filas if f["division"] == nombre]
        if not grupo:
            continue
        grupo.sort(key=lambda f: (-f["puntos"], -(f["insc"].nivel_inicial or 0),
                                  f["insc"].jugador1.apellido))
        for pos, f in enumerate(grupo, start=1):
            f["posicion"] = pos
        grupos.append((nombre, grupo))
    return grupos


def fila_de(grupos, insc):
    for nombre, grupo in grupos:
        for f in grupo:
            if f["insc"].id == insc.id:
                return nombre, grupo, f
    return None, [], None


def desafiables(insc, grupos, semana):
    """Rivales que insc puede desafiar esta semana: de su división, hasta N
    puestos más arriba, sin otro partido abierto entre los dos."""
    comp = insc.categoria.competencia
    _, grupo, mia = fila_de(grupos, insc)
    if not mia:
        return []
    maximo = int(comp.reglas.get("desafio_max_puestos_arriba") or 5)
    abiertos = set()
    for p in partidos_de(insc, estados=PARTIDOS_ABIERTOS, semana=semana):
        abiertos.add(p.lado_a_id if p.lado_b_id == insc.id else p.lado_b_id)
    return [
        f for f in grupo
        if mia["posicion"] - maximo <= f["posicion"] < mia["posicion"] and f["insc"].id not in abiertos
    ]


# ---------------------------------------------------------
# RESULTADOS
# ---------------------------------------------------------
def _partir_sets(texto):
    sets = []
    for parte in (texto or "").replace(",", " ").split():
        try:
            a, b = (int(x) for x in parte.split("-"))
        except ValueError:
            raise ValueError("Escribí cada set como 6-4, separados por espacios.")
        if a == b or a < 0 or b < 0:
            raise ValueError("Ningún set puede terminar empatado.")
        sets.append((a, b))
    return sets


def leer_sets(texto, un_set=False):
    """'6-4 3-6 10-8' -> [(6, 4), (3, 6), (10, 8)] desde el lado A. Lanza
    ValueError si no es un resultado válido de 2 o 3 sets (o de 1 set, como
    un pro set a 8, si un_set=True)."""
    sets = _partir_sets(texto)
    if un_set and len(sets) == 1:
        return sets
    if len(sets) not in (2, 3):
        raise ValueError("El resultado tiene que tener 2 o 3 sets.")
    ganados_a = sum(1 for a, b in sets if a > b)
    ganados_b = len(sets) - ganados_a
    if max(ganados_a, ganados_b) != 2 or (len(sets) == 2 and ganados_a == 1):
        raise ValueError("Alguien tiene que ganar 2 sets.")
    if len(sets) == 3 and (sets[0][0] > sets[0][1]) == (sets[1][0] > sets[1][1]):
        raise ValueError("Si alguien ganó los dos primeros sets, no hay tercer set.")
    return sets


def sets_texto(sets):
    return " ".join(f"{a}-{b}" for a, b in sets)


def invertir(texto):
    """Resultado visto desde el otro lado: '6-4 3-6' -> '4-6 6-3'."""
    return sets_texto([(b, a) for a, b in _partir_sets(texto)])


def _mov(comp, insc, partido, puntos, motivo, semana=None):
    db.session.add(Movimiento(
        competencia_id=comp.id, jugador_id=insc.jugador1_id, inscripcion_id=insc.id,
        partido_id=partido.id if partido else None,
        semana=partido.semana if partido else semana,
        puntos=puntos, motivo=motivo,
    ))


def aplicar_resultado(partido, sets_lado_a):
    """Cierra el partido con un resultado (desde el lado A) y suma los puntos.
    En un cuadro no hay puntos: el ganador pasa a la ronda siguiente."""
    comp = partido.lado_a.categoria.competencia
    if comp.tipo != TIPO_ESCALERA:
        from . import cuadro
        sets = leer_sets(sets_lado_a, un_set=True)
        gana_a = sum(1 for a, b in sets if a > b) > len(sets) / 2
        partido.estado = PAR_JUGADO
        partido.ganador_id = partido.lado_a_id if gana_a else partido.lado_b_id
        for r in partido.resultados:
            r.confirmado = True
        cuadro.avanzar(partido)
        return
    sets = leer_sets(sets_lado_a)
    gana_a = sum(1 for a, b in sets if a > b) == 2
    ganador, perdedor = (partido.lado_a, partido.lado_b) if gana_a else (partido.lado_b, partido.lado_a)
    tres = len(sets) == 3
    pts = comp.reglas.get("puntos", {})
    mult = 2 if especial(comp, partido.semana)[0] == "doble" else 1
    _mov(comp, ganador, partido, mult * float(pts.get("gana_super_tiebreak" if tres else "gana_2_sets", 0)),
         "gana_super_tiebreak" if tres else "gana_2_sets")
    _mov(comp, perdedor, partido, mult * float(pts.get("pierde_super_tiebreak" if tres else "pierde_2_sets", 0)),
         "pierde_super_tiebreak" if tres else "pierde_2_sets")
    partido.estado = PAR_JUGADO
    partido.ganador_id = ganador.id
    for r in partido.resultados:
        r.confirmado = True


def aplicar_wo(partido, ausente_id):
    comp = partido.lado_a.categoria.competencia
    ausente = partido.lado_a if partido.lado_a_id == ausente_id else partido.lado_b
    presente = partido.lado_b if ausente is partido.lado_a else partido.lado_a
    if comp.tipo != TIPO_ESCALERA:
        from . import cuadro
        partido.estado = PAR_WO
        partido.ganador_id = presente.id
        cuadro.avanzar(partido)
        return
    pts = comp.reglas.get("puntos", {})
    _mov(comp, presente, partido, float(pts.get("gana_wo", 0)), "gana_wo")
    _mov(comp, ausente, partido, float(pts.get("pierde_wo", 0)), "pierde_wo")
    partido.estado = PAR_WO
    partido.ganador_id = presente.id


def resultado_de_jugador(partido, insc):
    for r in partido.resultados:
        if r.cargado_por == "jugador" and r.cargado_por_id == insc.id:
            return r
    return None


# ---------------------------------------------------------
# PONER AL DÍA (vencimientos, cierre de semanas)
# ---------------------------------------------------------
def _vencer_desafios(comp, ahora):
    vencidos = Partido.query.filter(
        Partido.competencia_id == comp.id, Partido.estado == PAR_DESAFIO,
        Partido.vence_en.isnot(None), Partido.vence_en < ahora,
    ).all()
    for p in vencidos:
        p.estado = PAR_VENCIDO
        p.lado_b.rechazos_seguidos = (p.lado_b.rechazos_seguidos or 0) + 1
    return bool(vencidos)


def _cerrar_semana(comp, semana):
    inicio = inicio_semana(comp, semana)
    pts = comp.reglas.get("puntos", {})
    minimo = int(comp.reglas.get("minimo_partidos_semana") or 0)
    for cat in comp.categorias:
        for insc in participantes(cat):
            if insc.creado_en >= inicio:      # se sumó durante esa semana: arranca la siguiente
                continue
            ya = Movimiento.query.filter_by(inscripcion_id=insc.id, semana=semana)
            if ya.filter(Movimiento.motivo.in_(("inactividad", "semana_libre"))).first():
                continue
            jugados = [p for p in partidos_de(insc, semana=semana)
                       if p.estado in (PAR_JUGADO, PAR_WO, PAR_AGENDADO, PAR_EN_DISPUTA)]
            if minimo and len(jugados) < minimo:
                _mov(comp, insc, None, float(pts.get("inactividad_semanal", 0)), "inactividad", semana)
        db.session.flush()
        for nombre, grupo in ranking(cat, semana + 1):
            for f in grupo:
                db.session.add(RankingSemana(
                    competencia_id=comp.id, semana=semana, jugador_id=f["insc"].jugador1_id,
                    inscripcion_id=f["insc"].id, puntos=f["puntos"], posicion=f["posicion"],
                    division=nombre,
                ))


def procesar(comp, ahora=None):
    """Pone la escalera al día. Se puede llamar todas las veces que haga falta."""
    if comp.tipo != TIPO_ESCALERA or not comp.fecha_inicio:
        return
    ahora = ahora or datetime.now()
    cambio = _vencer_desafios(comp, ahora)
    actual = semana_de(comp, ahora)
    reglas = comp.reglas
    cerrada = int(reglas.get("semana_cerrada") or 0)
    hasta = min((actual or 0) - 1, total_semanas(comp))
    for semana in range(cerrada + 1, hasta + 1):
        _cerrar_semana(comp, semana)
        reglas["semana_cerrada"] = semana
        cambio = True
        if semana == total_semanas(comp) and comp.estado in (EST_INSCRIPCION, EST_EN_CURSO):
            # Terminó la etapa: queda finalizada y, en el plan pago, se genera el cobro
            from .cobros import crear_cobro
            comp.estado = EST_FINALIZADA
            crear_cobro(comp)
    if cambio:
        comp.reglas = reglas
        db.session.commit()


# ---------------------------------------------------------
# ASCENSOS Y DESCENSOS
# ---------------------------------------------------------
def semana_cambio_pendiente(comp):
    """Última semana de cambio de división ya cerrada y sin aplicar, o None."""
    cada = int(comp.reglas.get("ascensos_cada_semanas") or 0)
    cerrada = int(comp.reglas.get("semana_cerrada") or 0)
    aplicadas = comp.reglas.get("divisiones_aplicadas") or []
    if not cada or len(nombres_divisiones(comp)) < 2:
        return None
    for semana in range(cerrada, 0, -1):
        if semana % cada == 0:
            return None if semana in aplicadas else semana
    return None


def propuesta_divisiones(cat, semana):
    """[(inscripción, de, a)] según el ranking al cerrar esa semana."""
    comp = cat.competencia
    nombres = nombres_divisiones(comp)
    grupos = dict(ranking(cat, semana + 1))
    cambios = comp.reglas.get("cambios_division") or []
    propuesta = []
    movidos = set()   # nadie sube y baja a la vez (pasa si una división tiene pocos jugadores)
    for i in range(len(nombres) - 1):
        arriba, abajo = nombres[i], nombres[i + 1]
        regla = cambios[i] if i < len(cambios) else {"suben": 0, "bajan": 0}
        de_arriba = grupos.get(arriba, [])
        de_abajo = grupos.get(abajo, [])
        bajan = int(regla.get("bajan") or 0)
        suben = int(regla.get("suben") or 0)
        for f in de_abajo[:suben]:
            if f["insc"].id not in movidos:
                propuesta.append((f["insc"], abajo, arriba))
                movidos.add(f["insc"].id)
        for f in (de_arriba[-bajan:] if bajan else []):
            if f["insc"].id not in movidos:
                propuesta.append((f["insc"], arriba, abajo))
                movidos.add(f["insc"].id)
    return propuesta


def aplicar_divisiones(comp, semana):
    for cat in comp.categorias:
        for insc, _de, a in propuesta_divisiones(cat, semana):
            insc.division = a
    reglas = comp.reglas
    reglas["divisiones_aplicadas"] = (reglas.get("divisiones_aplicadas") or []) + [semana]
    comp.reglas = reglas
    db.session.commit()


def semanas_libres_usadas(insc):
    return Movimiento.query.filter_by(inscripcion_id=insc.id, motivo="semana_libre").count()


def tiene_semana_libre(insc, semana):
    return bool(Movimiento.query.filter_by(inscripcion_id=insc.id, motivo="semana_libre", semana=semana).first())


def pedir_semana_libre(insc, semana):
    comp = insc.categoria.competencia
    db.session.add(Movimiento(
        competencia_id=comp.id, jugador_id=insc.jugador1_id, inscripcion_id=insc.id,
        semana=semana, puntos=0, motivo="semana_libre",
    ))
