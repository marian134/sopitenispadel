"""Reglas por defecto de cada formato.

Se copian en la competencia al crearla (campo reglas_json) y el organizador
las puede cambiar. Los valores de la escalera copian los Desafíos Nivel Prado
(4ª edición, 2026).
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


def por_defecto(tipo):
    return copy.deepcopy(ESCALERA if tipo == "escalera" else CUADRO)
