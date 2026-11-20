"""Motor de la liga por fechas (una fecha por semana, puntos por games).

- El organizador carga las fechas (ej. todos los domingos). No hace falta
  jugarlas todas: cada partido suma.
- Cada fecha el organizador arma los partidos (a mano, o le pide al sistema
  una propuesta según la tabla, sin repetir rivales).
- Puntos por partido: cada game ganado en los sets 1 y 2 + un bonus por ganar
  + otro por ganar el súper tie-break. Un 6-2 6-3 da 15 al ganador y 5 al rival.
- W.O.: cuenta como perder 6-0 6-0.
- Tabla: suma de puntos; a igual puntaje, arriba quien jugó menos partidos.
"""
from datetime import date, datetime

from models import db
from .models import Movimiento, Partido, PAGO_CONFIRMADO, PAR_AGENDADO, PAR_JUGADO, PAR_WO

JUGADOS = (PAR_JUGADO, PAR_WO)


# ---------------------------------------------------------
# FECHAS
# ---------------------------------------------------------
def fechas(comp):
    """[(número, date)] ordenadas."""
    salida = []
    for i, texto in enumerate(comp.reglas.get("fechas") or [], start=1):
        try:
            salida.append((i, date.fromisoformat(texto)))
        except ValueError:
            continue
    return salida


def fecha_numero(comp, numero):
    return dict(fechas(comp)).get(numero)


def proxima_fecha(comp, hoy=None):
    """Número de la próxima fecha (hoy incluido), o None si ya pasaron todas."""
    hoy = hoy or date.today()
    for n, d in fechas(comp):
        if d >= hoy:
            return n
    return None


def estado_fechas(comp, hoy=None):
    """Para la tira de fechas: [{numero, fecha, estado}] con estado
    jugada | proxima | futura | sin_partidos."""
    hoy = hoy or date.today()
    prox = proxima_fecha(comp, hoy)
    con_partidos = {p.semana for p in Partido.query.filter_by(competencia_id=comp.id).all()
                    if p.estado in JUGADOS}
    salida = []
    for n, d in fechas(comp):
        if n == prox:
            estado = "proxima"
        elif d < hoy:
            estado = "jugada" if n in con_partidos else "sin_partidos"
        else:
            estado = "futura"
        salida.append({"numero": n, "fecha": d, "estado": estado})
    return salida


# ---------------------------------------------------------
# PARTICIPANTES Y DISPONIBILIDAD
# ---------------------------------------------------------
def participa(insc):
    comp = insc.categoria.competencia
    return not insc.baja and (insc.estado_pago == PAGO_CONFIRMADO or not comp.precio)


def participantes(comp):
    return [i for cat in comp.categorias for i in cat.inscripciones if participa(i)]


def disponibles(comp, numero):
    ids = set((comp.reglas.get("disponibles") or {}).get(str(numero), []))
    return [i for i in participantes(comp) if i.id in ids]


def marcar_disponible(comp, insc, numero, si=True):
    reglas = comp.reglas
    disp = reglas.get("disponibles") or {}
    lista = set(disp.get(str(numero), []))
    if si:
        lista.add(insc.id)
    else:
        lista.discard(insc.id)
    disp[str(numero)] = sorted(lista)
    reglas["disponibles"] = disp
    comp.reglas = reglas


def esta_disponible(comp, insc, numero):
    return insc.id in (comp.reglas.get("disponibles") or {}).get(str(numero), [])


# ---------------------------------------------------------
# PUNTOS
# ---------------------------------------------------------
def puntos_partido(comp, sets_lado_a):
    """(puntos lado A, puntos lado B) para un resultado desde el lado A."""
    from .escalera import leer_sets
    sets = leer_sets(sets_lado_a)
    pts = comp.reglas.get("puntos") or {}
    por_game = float(pts.get("por_game", 1))
    gana = float(pts.get("gana_partido", 3))
    gana_stb = float(pts.get("gana_super_tiebreak", 1))
    games_a = sum(a for a, b in sets[:2])
    games_b = sum(b for a, b in sets[:2])
    gana_a = sum(1 for a, b in sets if a > b) == 2
    tres = len(sets) == 3
    pa = games_a * por_game + (gana + (gana_stb if tres else 0) if gana_a else 0)
    pb = games_b * por_game + (gana + (gana_stb if tres else 0) if not gana_a else 0)
    return pa, pb


def ejemplo(comp, sets="6-2 6-3"):
    """Texto de ejemplo para explicar la escala en la página."""
    pa, pb = puntos_partido(comp, sets)
    return f"Un {sets} le da {_num(pa)} al ganador y {_num(pb)} al rival."


def _num(x):
    return str(int(x)) if float(x).is_integer() else str(x)


def _mov(comp, insc, partido, puntos, motivo):
    db.session.add(Movimiento(
        competencia_id=comp.id, jugador_id=insc.jugador1_id, inscripcion_id=insc.id,
        partido_id=partido.id, semana=partido.semana, puntos=puntos, motivo=motivo,
    ))


def aplicar_resultado(partido, sets_lado_a):
    comp = partido.lado_a.categoria.competencia
    from .escalera import leer_sets
    sets = leer_sets(sets_lado_a)
    pa, pb = puntos_partido(comp, sets_lado_a)
    gana_a = sum(1 for a, b in sets if a > b) == 2
    partido.estado = PAR_JUGADO
    partido.ganador_id = partido.lado_a_id if gana_a else partido.lado_b_id
    for r in partido.resultados:
        r.confirmado = True
    _mov(comp, partido.lado_a, partido, pa, "liga")
    _mov(comp, partido.lado_b, partido, pb, "liga")


def aplicar_wo(partido, ausente_id):
    """El ausente pierde como si fuera 6-0 6-0 (o lo que diga la regla)."""
    comp = partido.lado_a.categoria.competencia
    presente_es_a = partido.lado_b_id == ausente_id
    base = comp.reglas.get("wo_como") or "6-0 6-0"
    sets = base if presente_es_a else " ".join(f"{b}-{a}" for a, b in
                                               (tuple(int(x) for x in s.split("-")) for s in base.split()))
    pa, pb = puntos_partido(comp, sets)
    partido.estado = PAR_WO
    partido.ganador_id = partido.lado_a_id if presente_es_a else partido.lado_b_id
    _mov(comp, partido.lado_a, partido, pa, "liga_wo")
    _mov(comp, partido.lado_b, partido, pb, "liga_wo")


# ---------------------------------------------------------
# TABLA
# ---------------------------------------------------------
def tabla(comp):
    """Filas ordenadas: inscripción, puntos, partidos jugados, fechas jugadas."""
    lista = Partido.query.filter_by(competencia_id=comp.id).all()
    jugados = [p for p in lista if p.estado in JUGADOS]
    filas = []
    for insc in participantes(comp):
        mios = [p for p in jugados if insc.id in (p.lado_a_id, p.lado_b_id)]
        puntos = sum(m.puntos for m in Movimiento.query.filter_by(inscripcion_id=insc.id).all())
        filas.append({
            "insc": insc, "puntos": round(puntos, 2), "pj": len(mios),
            "ganados": sum(1 for p in mios if p.ganador_id == insc.id),
            "fechas_jugadas": {p.semana for p in mios},
        })
    filas.sort(key=lambda f: (-f["puntos"], f["pj"], f["insc"].jugador1.apellido))
    for pos, f in enumerate(filas, start=1):
        f["posicion"] = pos
    return filas


def puntos_de(partido):
    """{inscripcion_id: puntos} que sumó cada uno en el partido."""
    return {m.inscripcion_id: m.puntos for m in Movimiento.query.filter_by(partido_id=partido.id).all()}


def partidos_por_fecha(comp, solo_jugados=True):
    """[(número, date, [partidos])] de la más reciente a la más vieja."""
    dias = dict(fechas(comp))
    grupos = {}
    for p in Partido.query.filter_by(competencia_id=comp.id).all():
        if solo_jugados and p.estado not in JUGADOS:
            continue
        grupos.setdefault(p.semana, []).append(p)
    return [(n, dias.get(n), grupos[n]) for n in sorted(grupos, reverse=True)]


def resultados(comp):
    """Partidos jugados para mostrar: [(número, date, [fila])], la fecha más
    reciente primero. Cada fila tiene ganador a la izquierda y el resultado
    leído desde su lado."""
    from .escalera import invertir
    salida = []
    for numero, dia, partidos in partidos_por_fecha(comp):
        filas = []
        for p in partidos:
            gana_a = p.ganador_id == p.lado_a_id
            ganador, perdedor = (p.lado_a, p.lado_b) if gana_a else (p.lado_b, p.lado_a)
            res = [r for r in p.resultados if not r.ausente_id and r.confirmado]
            if p.estado == PAR_WO:
                sets = "W.O."
            elif res:
                sets = res[-1].sets if gana_a else invertir(res[-1].sets)
            else:
                sets = ""
            pts = puntos_de(p)
            filas.append({"p": p, "ganador": ganador, "perdedor": perdedor, "sets": sets,
                          "pts_ganador": pts.get(ganador.id, 0), "pts_perdedor": pts.get(perdedor.id, 0)})
        salida.append((numero, dia, filas))
    return salida


# ---------------------------------------------------------
# ARMAR PARTIDOS DE UNA FECHA
# ---------------------------------------------------------
def rivales_previos(comp):
    previos = set()
    for p in Partido.query.filter_by(competencia_id=comp.id).all():
        if p.lado_a_id and p.lado_b_id and p.estado != "anulado":
            previos.add(frozenset((p.lado_a_id, p.lado_b_id)))
    return previos


def proponer(comp, numero):
    """Propone parejas para la fecha con los que se anotaron (o con todos si
    nadie se anotó): ordena por la tabla y junta vecinos sin repetir rivales.
    Devuelve (parejas, sin_rival)."""
    ya = {i for p in Partido.query.filter_by(competencia_id=comp.id, semana=numero).all()
          for i in (p.lado_a_id, p.lado_b_id)}
    jugadores = disponibles(comp, numero) or participantes(comp)
    jugadores = [i for i in jugadores if i.id not in ya]
    orden = {f["insc"].id: f["posicion"] for f in tabla(comp)}
    jugadores.sort(key=lambda i: orden.get(i.id, 999))
    previos = rivales_previos(comp)
    parejas, libres = [], list(jugadores)
    while len(libres) >= 2:
        a = libres.pop(0)
        rival = next((b for b in libres if frozenset((a.id, b.id)) not in previos), libres[0])
        libres.remove(rival)
        parejas.append((a, rival))
    return parejas, libres


def crear_partido(comp, numero, a_id, b_id, cuando=None, cancha=None):
    cat_id = next((i.categoria_id for i in participantes(comp) if i.id == a_id), None)
    p = Partido(competencia_id=comp.id, categoria_id=cat_id, semana=numero, lado_a_id=a_id, lado_b_id=b_id,
                estado=PAR_AGENDADO, fecha_hora=cuando, cancha=cancha)
    db.session.add(p)
    return p
