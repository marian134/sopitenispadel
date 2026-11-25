"""Motor del cuadro de eliminación directa.

- El cuadro tiene el tamaño justo (2, 4, 8, 16, 32, 64...) y los lugares que
  sobran son pases libres (byes), que van contra los mejores cabezas de serie.
- Los cabezas de serie se ubican como en cualquier torneo: el 1 arriba, el 2
  abajo, el 3 y el 4 en los otros cuartos, etc. El resto se sortea.
- Se crean de entrada todos los partidos de todas las rondas; al cargar un
  resultado, el ganador pasa solo al partido siguiente.
- Consuelo (opcional): para los que pierden su primer partido.
- Tercer puesto (opcional): entre los que pierden las semifinales.
"""
import math
import random

from models import db
from .models import (
    Categoria, Competencia, Inscripcion, Partido, PAGO_CONFIRMADO,
    EST_FINALIZADA, PAR_AGENDADO, PAR_BYE, PAR_JUGADO, PAR_PENDIENTE, PAR_WO,
)

PRINCIPAL, CONSUELO, TERCER, ZONA = "principal", "consuelo", "tercer", "zona"
PLATA = "plata"   # segundo cuadro con los que no clasificaron en las zonas (ej. "Copa de Plata")
NOMBRES_RONDA = {
    2: "Final", 4: "Semifinal", 8: "Cuartos de final", 16: "Octavos de final",
    32: "16avos de final", 64: "32avos de final", 128: "64avos de final",
}
TERMINADOS = (PAR_JUGADO, PAR_WO, PAR_BYE)

# Etapas con plazo (desde / hasta) que puede cargar el organizador.
# La clave de las rondas es la cantidad de jugadores que la juegan.
ETAPAS = [
    ("zonas", "Fase de zonas"), ("64", "32avos de final"), ("32", "16avos de final"),
    ("16", "Octavos de final"), ("8", "Cuartos de final"), ("4", "Semifinales"), ("2", "Final"),
]


def etapa_de(p):
    """Clave de etapa de un partido para buscar su plazo."""
    if p.cuadro == ZONA:
        return "zonas"
    if p.cuadro == TERCER:   # el tercer puesto se juega en los días de la final
        return "2"
    if p.cuadro not in (PRINCIPAL, PLATA):   # la Copa de Plata usa los mismos días por ronda que la de Oro
        return None
    total = max((int(x.ronda) for x in Partido.query.filter_by(categoria_id=p.categoria_id, cuadro=p.cuadro)),
                default=0)
    return str(2 ** (total - int(p.ronda) + 1)) if total else None


def plazo_de(comp, p):
    """{"desde", "hasta"} (date) del partido, o None."""
    from datetime import date
    clave = etapa_de(p)
    datos = (comp.reglas.get("plazos") or {}).get(clave) if clave else None
    if not datos:
        return None
    convertir = lambda v: date.fromisoformat(v) if v else None   # noqa: E731
    return {"desde": convertir(datos.get("desde")), "hasta": convertir(datos.get("hasta")),
            "nombre": dict(ETAPAS).get(clave)}


def plazos_vencidos(comp, hoy=None):
    """[(nombre de etapa, hasta, cantidad de partidos sin resultado)]."""
    from datetime import date
    hoy = hoy or date.today()
    pendientes = {}
    for p in Partido.query.filter_by(competencia_id=comp.id).all():
        if p.estado not in (PAR_AGENDADO,):
            continue
        plazo = plazo_de(comp, p)
        if plazo and plazo["hasta"] and plazo["hasta"] < hoy:
            clave = (plazo["nombre"], plazo["hasta"])
            pendientes[clave] = pendientes.get(clave, 0) + 1
    return [(n, h, c) for (n, h), c in sorted(pendientes.items(), key=lambda x: x[0][1])]


def tamano(n):
    t = 2
    while t < n:
        t *= 2
    return t


def orden_lineas(t):
    """Qué número de lugar va en cada línea del cuadro, para que el 1 y el 2
    solo se crucen en la final. Ej. 8 -> [1, 8, 4, 5, 2, 7, 3, 6]."""
    orden = [1, 2]
    while len(orden) < t:
        m = len(orden) * 2
        orden = [y for x in orden for y in (x, m + 1 - x)]
    return orden


def max_cabezas(t):
    """Cantidad de cabezas de serie que se suele usar (sugerencia, no límite)."""
    return 0 if t < 4 else max(2, t // 4)


def participantes(cat):
    comp = cat.competencia
    return [
        i for i in cat.inscripciones
        if not i.baja and (i.estado_pago == PAGO_CONFIRMADO or not comp.precio)
    ]


def partidos(cat, cuadro=PRINCIPAL):
    return (
        Partido.query.filter_by(categoria_id=cat.id, cuadro=cuadro)
        .order_by(Partido.ronda, Partido.posicion).all()
    )


def hay_resultados(cat, cuadro=PRINCIPAL):
    return any(p.estado in (PAR_JUGADO, PAR_WO) for p in partidos(cat, cuadro))


def _borrar(cat, cuadro):
    for p in partidos(cat, cuadro):
        db.session.delete(p)
    db.session.flush()


def armar(cat, jugadores, cuadro=PRINCIPAL, usar_siembra=True, rng=None, lugares=None):
    """Arma el cuadro con esos jugadores (inscripciones). Devuelve los partidos.
    lugares: {número de lugar: inscripción} ya decidido (ej. clasificados de
    las zonas); si no viene, se ubican cabezas de serie y se sortea el resto."""
    rng = rng or random.Random()
    n = len(jugadores)
    if n < 2:
        raise ValueError("Hacen falta al menos 2 jugadores para armar el cuadro.")
    _borrar(cat, cuadro)
    t = tamano(n)
    if lugares:
        lugar = dict(lugares)
    else:
        cabezas = []
        if usar_siembra:
            # se respetan todos los números que puso el organizador (si numera a
            # los 8 de un cuadro de 8: 1 contra 8, 4 contra 5, 2 contra 7, 3 contra 6)
            cabezas = sorted([i for i in jugadores if i.siembra], key=lambda i: (i.siembra, i.id))[:t]
        resto = [i for i in jugadores if i not in cabezas]
        rng.shuffle(resto)
        lugar = {k + 1: insc for k, insc in enumerate(cabezas + resto)}   # n+1..t quedan vacíos (byes)
    lineas = [lugar.get(numero) for numero in orden_lineas(t)]

    rondas = int(math.log2(t))
    creados = {}
    for r in range(1, rondas + 1):
        for k in range(t // 2 ** r):
            p = Partido(competencia_id=cat.competencia_id, categoria_id=cat.id, cuadro=cuadro,
                        ronda=str(r), posicion=k, estado=PAR_PENDIENTE)
            if r == 1:
                a, b = lineas[2 * k], lineas[2 * k + 1]
                p.lado_a_id = a.id if a else None
                p.lado_b_id = b.id if b else None
            db.session.add(p)
            creados[(r, k)] = p
    db.session.flush()
    for k in range(t // 2):
        p = creados[(1, k)]
        if p.lado_a_id and p.lado_b_id:
            p.estado = PAR_AGENDADO
        else:
            p.estado = PAR_BYE
            p.ganador_id = p.lado_a_id or p.lado_b_id
            avanzar(p)
    db.session.flush()
    return list(creados.values())


def rondas_de(cat, cuadro=PRINCIPAL):
    lista = partidos(cat, cuadro)
    return max((int(p.ronda) for p in lista), default=0)


def nombres_cuadros(comp):
    """Nombres para mostrar: {"principal": ..., "plata": ...}."""
    z = (comp.reglas.get("zonas") or {})
    plata = bool(z.get("activo") and z.get("plata"))
    return {
        PRINCIPAL: (z.get("nombre_oro") or "Copa de Oro") if plata else "Cuadro",
        PLATA: z.get("nombre_plata") or "Copa de Plata",
    }


def nombre_ronda(cat, cuadro, ronda, partido=None):
    if cuadro == TERCER:
        return "Tercer puesto"
    if cuadro == PLATA:
        total = rondas_de(cat, cuadro)
        jugadores = 2 ** (total - int(ronda) + 1)
        return f"{nombres_cuadros(cat.competencia)[PLATA]} · {NOMBRES_RONDA.get(jugadores, f'Ronda {ronda}')}"
    if cuadro == ZONA:
        if partido is not None:
            return f"Zona {partido.posicion} · Fecha {partido.semana}"
        return "Fase de zonas"
    total = rondas_de(cat, cuadro)
    jugadores = 2 ** (total - int(ronda) + 1)
    nombre = NOMBRES_RONDA.get(jugadores, f"Ronda {ronda}")
    z = cat.competencia.reglas.get("zonas") or {}
    if cuadro == PRINCIPAL and z.get("activo") and z.get("plata"):   # con dos copas, que no se confundan
        return f"{nombres_cuadros(cat.competencia)[PRINCIPAL]} · {nombre}"
    return nombre


def _siguiente(p):
    return Partido.query.filter_by(
        categoria_id=p.categoria_id, cuadro=p.cuadro, ronda=str(int(p.ronda) + 1), posicion=p.posicion // 2,
    ).first()


def perdedor_id(p):
    if p.estado not in (PAR_JUGADO, PAR_WO) or not p.ganador_id:
        return None
    return p.lado_b_id if p.ganador_id == p.lado_a_id else p.lado_a_id


def avanzar(p):
    """Pasa el ganador de p al partido siguiente (y arma el tercer puesto)."""
    if p.cuadro == ZONA:          # en las zonas no se avanza: cuenta para la tabla
        return
    if p.cuadro == TERCER:
        _revisar_final_torneo(p)
        return
    sig = _siguiente(p)
    if sig is None:      # era la final
        _revisar_final_torneo(p)
        return
    if p.posicion % 2 == 0:
        sig.lado_a_id = p.ganador_id
    else:
        sig.lado_b_id = p.ganador_id
    if sig.lado_a_id and sig.lado_b_id and sig.estado == PAR_PENDIENTE:
        sig.estado = PAR_AGENDADO
    # Semifinales terminadas -> tercer puesto (si está activado)
    comp = db.session.get(Competencia, p.competencia_id)
    cat = db.session.get(Categoria, p.categoria_id)
    if comp.reglas.get("tercer_puesto") and p.cuadro == PRINCIPAL and int(p.ronda) == rondas_de(cat) - 1:
        _armar_tercer_puesto(cat)


def _armar_tercer_puesto(cat):
    total = rondas_de(cat)
    semis = Partido.query.filter_by(categoria_id=cat.id, cuadro=PRINCIPAL, ronda=str(total - 1)).all()
    perdedores = [perdedor_id(s) for s in sorted(semis, key=lambda s: s.posicion)]
    if len(perdedores) != 2 or not all(perdedores):
        return
    if Partido.query.filter_by(categoria_id=cat.id, cuadro=TERCER).first():
        return
    db.session.add(Partido(competencia_id=cat.competencia_id, categoria_id=cat.id, cuadro=TERCER,
                           ronda="1", posicion=0, lado_a_id=perdedores[0], lado_b_id=perdedores[1],
                           estado=PAR_AGENDADO))


def campeon(cat, cuadro=PRINCIPAL):
    total = rondas_de(cat, cuadro)
    if not total:
        return None
    final = Partido.query.filter_by(categoria_id=cat.id, cuadro=cuadro, ronda=str(total)).first()
    if final and final.estado in TERMINADOS and final.ganador_id:
        return db.session.get(Inscripcion, final.ganador_id)
    return None


def podio(cat):
    """Al terminar la final: {"campeon", "subcampeon", "terceros": [...]}; si no, None.
    Con partido por el tercer puesto, el tercero es el ganador (cuando se juega);
    sin ese partido, los dos que perdieron las semifinales."""
    total = rondas_de(cat)
    if not total:
        return None
    final = Partido.query.filter_by(categoria_id=cat.id, cuadro=PRINCIPAL, ronda=str(total)).first()
    if not final or final.estado not in TERMINADOS or not final.ganador_id:
        return None
    sub = perdedor_id(final)
    terceros = []
    tercer = Partido.query.filter_by(categoria_id=cat.id, cuadro=TERCER).first()
    if tercer:
        if tercer.estado in TERMINADOS and tercer.ganador_id:
            terceros = [tercer.ganador_id]
    elif total >= 2:
        semis = Partido.query.filter_by(categoria_id=cat.id, cuadro=PRINCIPAL, ronda=str(total - 1)).all()
        terceros = [x for x in (perdedor_id(s) for s in semis) if x]
    return {
        "campeon": db.session.get(Inscripcion, final.ganador_id),
        "subcampeon": db.session.get(Inscripcion, sub) if sub else None,
        "terceros": [db.session.get(Inscripcion, x) for x in terceros],
        "tercer_pendiente": bool(tercer) and not terceros,
    }


def _revisar_final_torneo(p):
    """Si se jugaron todas las finales (y tercer puesto), el torneo queda finalizado."""
    db.session.flush()
    comp = db.session.get(Competencia, p.competencia_id)
    for cat in comp.categorias:
        lista = Partido.query.filter_by(categoria_id=cat.id).all()
        if not lista or any(x.estado not in TERMINADOS + ("anulado",) for x in lista):
            return
    comp.estado = EST_FINALIZADA


# ---------------------------------------------------------
# CONSUELO
# ---------------------------------------------------------
def entrantes_consuelo(cat):
    """(entrantes, pendientes): los que perdieron su primer partido jugado, y
    cuántos jugadores todavía no jugaron el suyo."""
    entrantes, pendientes = [], 0
    lista = partidos(cat)
    for insc in participantes(cat):
        mios = [p for p in lista if insc.id in (p.lado_a_id, p.lado_b_id) and p.estado != PAR_BYE]
        if not mios:
            continue
        primero = min(mios, key=lambda p: int(p.ronda))
        if primero.estado not in (PAR_JUGADO, PAR_WO):
            pendientes += 1
        elif primero.ganador_id != insc.id:
            entrantes.append(insc)
    return entrantes, pendientes


def armar_consuelo(cat, rng=None):
    entrantes, pendientes = entrantes_consuelo(cat)
    if pendientes:
        raise ValueError(f"Faltan {pendientes} jugadores por jugar su primer partido.")
    return armar(cat, entrantes, cuadro=CONSUELO, usar_siembra=False, rng=rng)


# ---------------------------------------------------------
# PARA MOSTRAR
# ---------------------------------------------------------
def estructura(cat, cuadro=PRINCIPAL):
    """[{"nombre": "Cuartos de final", "partidos": [...]}, ...] en orden."""
    lista = partidos(cat, cuadro)
    rondas = {}
    for p in lista:
        rondas.setdefault(int(p.ronda), []).append(p)
    return [
        {"numero": r, "nombre": nombre_ronda(cat, cuadro, r), "partidos": sorted(ps, key=lambda p: p.posicion)}
        for r, ps in sorted(rondas.items())
    ]


def avisos_horarios(comp, margen_minutos=90):
    """Partidos con el mismo jugador muy pegados o dos partidos en la misma
    cancha a la misma hora: {partido_id: [avisos]}."""
    programados = [
        p for p in Partido.query.filter_by(competencia_id=comp.id).all()
        if p.fecha_hora and p.estado not in TERMINADOS
    ]
    avisos = {}
    for i, p in enumerate(programados):
        for q in programados[i + 1:]:
            minutos = abs((p.fecha_hora - q.fecha_hora).total_seconds()) / 60
            comunes = {p.lado_a_id, p.lado_b_id} & {q.lado_a_id, q.lado_b_id} - {None}
            if comunes and minutos < margen_minutos:
                for x in (p, q):
                    avisos.setdefault(x.id, []).append("Un jugador tiene otro partido muy cerca de este horario")
            if p.cancha and q.cancha and p.cancha.strip().lower() == q.cancha.strip().lower() and minutos < margen_minutos:
                for x in (p, q):
                    avisos.setdefault(x.id, []).append(f"La cancha {p.cancha} ya tiene otro partido a esa hora")
    return avisos
