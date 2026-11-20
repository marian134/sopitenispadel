"""Reglas por defecto de cada formato.

Se copian en la competencia al crearla (campo reglas_json) y el organizador
las puede cambiar. Los valores de la escalera son un formato habitual de
escalera de club.
"""
import copy

ESCALERA = {
    "semanas": 12,
    "orden": "puntos",                     # puntos | posicion
    "niveles_iniciales": [1, 3, 5, 7, 9, 11, 13],
    "puntos": {
        "gana_2_sets": 1.5,
        "gana_super_tiebreak": 1.0,
        "gana_wo": 1.0,
        "pierde_super_tiebreak": 0.0,
        "pierde_2_sets": -0.5,
        "pierde_wo": -1.0,
        "cancela_sin_aviso": -1.0,
        "inactividad_semanal": -1.0,
    },
    "piso_bajo_inicial": 3,                # no baja más de 3 puntos del nivel inicial
    "desafio_max_puestos_arriba": 5,
    "plazo_respuesta_dias": 2,
    "rechazos_seguidos_max": 1,
    "minimo_partidos_semana": 1,
    "semanas_libres": 2,
    "divisiones": [
        {"nombre": "Oro", "niveles": [13, 11]},
        {"nombre": "Plata", "niveles": [9, 7]},
        {"nombre": "Bronce", "niveles": [5, 3, 1]},
    ],
    "ascensos_cada_semanas": 4,
    # Un elemento por cada límite entre divisiones, de arriba hacia abajo:
    # Oro/Plata (Oro no tiene descensos) y Plata/Bronce.
    "cambios_division": [
        {"suben": 3, "bajan": 0},
        {"suben": 6, "bajan": 3},
    ],
    # Semanas con modo especial: "doble" duplica los puntos de los partidos;
    # el resto se muestra como aviso (ej. quién paga la cancha).
    "semanas_especiales": {
        "3": "doble", "7": "doble", "9": "paga_perdedor", "12": "1vs1",
    },
    "selfie_obligatoria": True,
    "formato_partido": "mejor de 3 sets con súper tie-break",
    "dobles_ranking_individual": True,
}

CUADRO = {
    "formato_partido": "mejor de 3 sets con tie-break",
    "consuelo": False,
    "tercer_puesto": False,
    "cabezas_de_serie": "ranking",         # ranking | manual
}


# Liga por fechas: se juega una fecha por semana (no hace falta jugarlas
# todas) y cada partido suma por games, como en un formato habitual de
# liga de club.
LIGA = {
    "formato_partido": "mejor de 3 sets; si quedan 1-1, súper tie-break a 10",
    "puntos": {
        "por_game": 1,          # cada game ganado en los sets 1 y 2
        "gana_partido": 3,
        "gana_super_tiebreak": 1,
    },
    "wo_como": "6-0 6-0",       # si no se presenta, cuenta como perder 6-0 6-0
    "desempate": "menos_partidos",
    "fechas": [],               # ["2026-11-01", "2026-11-08", ...]
    "precio_por_partido": "",   # texto, ej. "$12.000 por partido, incluye cancha y pelotas"
    "premio": "",
    "disponibles": {},          # {"3": [ids de inscripción que se anotaron para la fecha 3]}
}


def por_defecto(tipo):
    return copy.deepcopy({"escalera": ESCALERA, "liga": LIGA}.get(tipo, CUADRO))
