"""Fase de zonas (grupos todos contra todos) antes del cuadro.

- El organizador elige el tamaño de las zonas (3, 4 o 5) y cuántos pasan al
  cuadro por zona. Si los jugadores no alcanzan, algunas zonas quedan con uno
  menos (en las planillas de los clubes figura como "Libre").
- Los cabezas de serie se reparten uno por zona; el resto se sortea.
- Cada zona juega todos contra todos, ordenado en fechas (#1, #2, #3...).
- Tabla por zona: PJ, PG, PP, sets, games y puntos con la escala del torneo
  (por defecto 3 por ganar, 0 por perder, +1 de bonus al que pierde por cada
  set que ganó). Desempate configurable.
- Al terminar, los clasificados pasan al cuadro: los 1ros como cabezas de
  serie, y el resto ubicado para no cruzarse en primera ronda con alguien de
  su misma zona. Donde faltan jugadores van pases libres.

Partidos de zona: cuadro="zona", posicion = número de zona, semana = fecha.
"""
import math
import random

from models import db
from . import cuadro as cdr
from .models import Partido, PAR_AGENDADO, PAR_ANULADO, PAR_JUGADO, PAR_WO

ZONA = cdr.ZONA
JUGADOS = (PAR_JUGADO, PAR_WO)

POR_DEFECTO = {
    "activo": False,
    "tamano": 3,
    "clasifican": 2,
    "puntos": {"gana": 3, "pierde": 0, "bonus_set": 1, "gana_wo": 3, "pierde_wo": 0},
    "desempate": ["puntos", "ganados", "dif_sets", "dif_games", "directo"],
    "plata": False,                 # los que no clasifican juegan un segundo cuadro
    "nombre_oro": "Copa de Oro",
    "nombre_plata": "Copa de Plata",
}
CRITERIOS = {
    "puntos": "Puntos",
    "ganados": "Partidos ganados",
    "dif_sets": "Diferencia de sets",
    "dif_games": "Diferencia de games",
    "directo": "Resultado entre ellos",
    "menos_jugados": "Menos partidos jugados",
}


def reglas(comp):
    datos = dict(POR_DEFECTO)
    datos.update(comp.reglas.get("zonas") or {})
    datos["puntos"] = {**POR_DEFECTO["puntos"], **(datos.get("puntos") or {})}
    return datos


def activas(comp):
    return comp.tipo == "cuadro" and bool(reglas(comp).get("activo"))


# ---------------------------------------------------------
# ARMADO
# ---------------------------------------------------------
def repartir(jugadores, tamano, rng=None):
    """Lista de zonas (listas de inscripciones). Cabezas de serie uno por zona."""
    rng = rng or random.Random()
    n = len(jugadores)
    if n < 2:
        raise ValueError("Hacen falta al menos 2 jugadores para armar las zonas.")
    cantidad = max(1, math.ceil(n / tamano))
    if n / cantidad < 2:               # que ninguna zona quede de un solo jugador
        cantidad = max(1, n // 2)
    cabezas = sorted([i for i in jugadores if i.siembra], key=lambda i: i.siembra)[:cantidad]
    resto = [i for i in jugadores if i not in cabezas]
    rng.shuffle(resto)
    zonas = [[] for _ in range(cantidad)]
    for k, insc in enumerate(cabezas):
        zonas[k].append(insc)
    # el resto, de a uno por zona empezando por las más chicas (quedan parejas)
    for insc in resto:
        min(zonas, key=len).append(insc)
    return zonas


def fixture(jugadores):
    """Todos contra todos en fechas (método del círculo). [(fecha, a, b)]."""
    lista = list(jugadores)
    if len(lista) % 2:
        lista.append(None)                # "Libre": ese jugador descansa en la fecha
    n = len(lista)
    salida = []
    for fecha in range(1, n):
        for k in range(n // 2):
            a, b = lista[k], lista[n - 1 - k]
            if a is not None and b is not None:
                salida.append((fecha, a, b))
        lista = [lista[0]] + [lista[-1]] + lista[1:-1]
    return salida


def partidos(cat):
    return (Partido.query.filter_by(categoria_id=cat.id, cuadro=ZONA)
            .order_by(Partido.posicion, Partido.semana, Partido.id).all())


def hay_resultados(cat):
    return any(p.estado in JUGADOS for p in partidos(cat))


def armar(cat, rng=None):
    """Arma las zonas de la categoría con los inscriptos confirmados."""
    comp = cat.competencia
    jugadores = cdr.participantes(cat)
    zonas = repartir(jugadores, int(reglas(comp)["tamano"]), rng)
    cdr._borrar(cat, ZONA)
    cdr._borrar(cat, cdr.PRINCIPAL)
    cdr._borrar(cat, cdr.CONSUELO)
    cdr._borrar(cat, cdr.TERCER)
    cdr._borrar(cat, cdr.PLATA)
    for numero, zona in enumerate(zonas, start=1):
        for insc in zona:
            insc.zona = numero
        for fecha, a, b in fixture(zona):
            db.session.add(Partido(competencia_id=comp.id, categoria_id=cat.id, cuadro=ZONA, ronda="0",
                                   posicion=numero, semana=fecha, lado_a_id=a.id, lado_b_id=b.id,
                                   estado=PAR_AGENDADO))
    for insc in cat.inscripciones:
        if insc not in jugadores:
            insc.zona = None
    db.session.flush()
    return zonas


# ---------------------------------------------------------
# TABLA
# ---------------------------------------------------------
def _sets_de(p):
    """[(games A, games B)] del resultado confirmado, o [] si no hay."""
    res = [r for r in p.resultados if r.confirmado and not r.ausente_id and r.sets and r.sets[0].isdigit()]
    if not res:
        return []
    from .escalera import _partir_sets
    try:
        # en un abandono cuentan solo los sets terminados (el último puede estar a medias)
        sets = _partir_sets(res[-1].sets, parcial=True)
    except ValueError:
        return []
    if "ret" in res[-1].sets:
        sets = [s for s in sets if max(s) >= 6 and abs(s[0] - s[1]) >= 2 or max(s) == 7]
    return sets


def tabla_zona(comp, lista_partidos, miembros):
    """Filas ordenadas de una zona."""
    r = reglas(comp)
    pts = r["puntos"]
    filas = {i.id: {"insc": i, "pj": 0, "pg": 0, "pp": 0, "sets_g": 0, "sets_p": 0, "games_g": 0,
                    "games_p": 0, "puntos": 0.0, "bonus": 0.0} for i in miembros}
    for p in lista_partidos:
        if p.estado not in JUGADOS or p.lado_a_id not in filas or p.lado_b_id not in filas:
            continue
        a, b = filas[p.lado_a_id], filas[p.lado_b_id]
        a["pj"] += 1
        b["pj"] += 1
        ganador, perdedor = (a, b) if p.ganador_id == p.lado_a_id else (b, a)
        ganador["pg"] += 1
        perdedor["pp"] += 1
        if p.estado == PAR_WO:
            ganador["puntos"] += float(pts["gana_wo"])
            perdedor["puntos"] += float(pts["pierde_wo"])
            continue
        ganador["puntos"] += float(pts["gana"])
        perdedor["puntos"] += float(pts["pierde"])
        for ga, gb in _sets_de(p):
            a["games_g"] += ga
            a["games_p"] += gb
            b["games_g"] += gb
            b["games_p"] += ga
            if ga > gb:
                a["sets_g"] += 1
                b["sets_p"] += 1
            else:
                b["sets_g"] += 1
                a["sets_p"] += 1
        # bonus: el que pierde suma por cada set que ganó
        sets_perdedor = perdedor["insc"].id
        ganados_perdedor = sum(1 for ga, gb in _sets_de(p)
                               if (ga > gb) == (sets_perdedor == p.lado_a_id))
        perdedor["bonus"] += ganados_perdedor * float(pts["bonus_set"])
    for f in filas.values():
        f["total"] = round(f["puntos"] + f["bonus"], 2)
        f["dif_sets"] = f["sets_g"] - f["sets_p"]
        f["dif_games"] = f["games_g"] - f["games_p"]

    orden = [c for c in r["desempate"] if c in CRITERIOS] or POR_DEFECTO["desempate"]

    def clave(f):
        valores = []
        for c in orden:
            if c == "puntos":
                valores.append(-f["total"])
            elif c == "ganados":
                valores.append(-f["pg"])
            elif c == "dif_sets":
                valores.append(-f["dif_sets"])
            elif c == "dif_games":
                valores.append(-f["dif_games"])
            elif c == "menos_jugados":
                valores.append(f["pj"])
        return valores

    lista = sorted(filas.values(), key=lambda f: (clave(f), f["insc"].jugador1.apellido))
    if "directo" in orden:
        lista = _desempate_directo(lista, lista_partidos, clave)
    for pos, f in enumerate(lista, start=1):
        f["posicion"] = pos
    return lista


def _desempate_directo(lista, lista_partidos, clave):
    """Si dos quedan iguales en todo lo anterior, va arriba el que ganó el partido entre ellos."""
    salida = list(lista)
    cambio = True
    while cambio:
        cambio = False
        for k in range(len(salida) - 1):
            x, y = salida[k], salida[k + 1]
            if clave(x) != clave(y):
                continue
            entre = next((p for p in lista_partidos if p.estado in JUGADOS
                          and {p.lado_a_id, p.lado_b_id} == {x["insc"].id, y["insc"].id}), None)
            if entre and entre.ganador_id == y["insc"].id:
                salida[k], salida[k + 1] = y, x
                cambio = True
    return salida


def estructura(cat):
    """[{numero, tabla, partidos: [(fecha, [partidos])], completa}] por zona."""
    comp = cat.competencia
    todos = partidos(cat)
    por_zona = {}
    for p in todos:
        por_zona.setdefault(p.posicion, []).append(p)
    salida = []
    for numero in sorted(por_zona):
        lista = por_zona[numero]
        miembros = {i.id: i for p in lista for i in (p.lado_a, p.lado_b) if i}
        fechas = {}
        for p in lista:
            fechas.setdefault(p.semana, []).append(p)
        salida.append({
            "numero": numero, "tabla": tabla_zona(comp, lista, list(miembros.values())),
            "fechas": sorted(fechas.items()),
            "completa": all(p.estado in JUGADOS + (PAR_ANULADO,) for p in lista),
            "pendientes": sum(1 for p in lista if p.estado not in JUGADOS + (PAR_ANULADO,)),
        })
    return salida


# ---------------------------------------------------------
# CLASIFICADOS AL CUADRO
# ---------------------------------------------------------
def clasificados(cat, no_clasificados=False):
    """[[1ros...], [2dos...], ...] cada grupo ordenado por mejor campaña.
    no_clasificados=True: los puestos que no pasan al cuadro principal
    ([[3ros...], [4tos...]]), para la Copa de Plata."""
    comp = cat.competencia
    cuantos = int(reglas(comp)["clasifican"])
    zonas = estructura(cat)
    grupos = []
    puestos = range(cuantos, max((len(z["tabla"]) for z in zonas), default=0)) if no_clasificados else range(cuantos)
    for puesto in puestos:
        filas = [(z["numero"], z["tabla"][puesto]) for z in zonas if len(z["tabla"]) > puesto]
        filas.sort(key=lambda zf: (-zf[1]["total"], -zf[1]["pg"], -zf[1]["dif_sets"], -zf[1]["dif_games"]))
        grupos.append([(numero, f["insc"]) for numero, f in filas])
    return grupos


def lugares_cuadro(grupos, rng=None):
    """Asigna lugares del cuadro: 1ros como cabezas (lugares 1..k), el resto
    buscando que nadie cruce en primera ronda con alguien de su zona."""
    rng = rng or random.Random()
    total = sum(len(g) for g in grupos)
    t = cdr.tamano(total)
    lugar, zona_de = {}, {}
    siguiente = 1
    for numero, insc in grupos[0] if grupos else []:
        lugar[siguiente] = insc
        zona_de[siguiente] = numero
        siguiente += 1
    rival = {s: t + 1 - s for s in range(1, t + 1)}   # con orden_lineas, el lugar s juega contra t+1-s
    for grupo in grupos[1:]:
        libres = list(range(siguiente, siguiente + len(grupo)))
        mejor, mejor_choques = None, None
        for _ in range(300):
            orden = list(grupo)
            rng.shuffle(orden)
            choques = sum(1 for s, (numero, _i) in zip(libres, orden) if zona_de.get(rival[s]) == numero)
            if mejor is None or choques < mejor_choques:
                mejor, mejor_choques = orden, choques
            if choques == 0:
                break
        for s, (numero, insc) in zip(libres, mejor):
            lugar[s] = insc
            zona_de[s] = numero
        siguiente += len(grupo)
    return lugar


def pasar_al_cuadro(cat, rng=None):
    """Arma el cuadro principal con los clasificados de las zonas."""
    grupos = clasificados(cat)
    jugadores = [insc for g in grupos for _n, insc in g]
    if len(jugadores) < 2:
        raise ValueError("Hacen falta al menos 2 clasificados para armar el cuadro.")
    lugares = lugares_cuadro(grupos, rng)
    cdr._borrar(cat, cdr.CONSUELO)
    cdr._borrar(cat, cdr.TERCER)
    cdr._borrar(cat, cdr.PLATA)
    creados = cdr.armar(cat, jugadores, lugares=lugares, rng=rng)
    if reglas(cat.competencia).get("plata"):
        resto = clasificados(cat, no_clasificados=True)
        otros = [insc for g in resto for _n, insc in g]
        if len(otros) >= 2:
            creados += cdr.armar(cat, otros, cuadro=cdr.PLATA, lugares=lugares_cuadro(resto, rng), rng=rng)
    return creados
