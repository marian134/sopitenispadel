"""Fichas técnicas de las paletas (forma, peso, balance, materiales, nivel...).

Los datos están en data/fichas_paletas.json: una lista de objetos con el
nombre EXACTO del producto en la tienda y sus datos. Se buscaron en las webs
oficiales de cada marca y en tiendas/reviews confiables. Si un dato no se
encontró queda en null y no se muestra.

Para agregar o corregir una paleta, editá ese archivo (no hace falta tocar
código). El nombre se compara sin mayúsculas, tildes ni espacios de más.
"""
import json
import os
import re
import unicodedata

ARCHIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fichas_paletas.json")

# (clave en el JSON, cómo se muestra) en el orden de la tabla
CAMPOS = [
    ("forma", "Forma"),
    ("balance", "Balance"),
    ("peso", "Peso"),
    ("cara", "Caras"),
    ("nucleo", "Núcleo"),
    ("marco", "Marco"),
    ("espesor", "Espesor"),
    ("nivel", "Nivel"),
    ("juego", "Tipo de juego"),
    ("jugador", "Jugador"),
]
# Los que van como etiquetas rápidas al lado del precio
RAPIDOS = ("forma", "balance", "peso", "nivel")


def _clave(nombre):
    t = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


def _cargar():
    try:
        with open(ARCHIVO, encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, ValueError):
        return {}
    fichas = {}
    for d in datos:
        if not isinstance(d, dict) or not d.get("nombre"):
            continue
        if str(d.get("confianza", "")).lower() == "no es paleta":
            continue
        limpio = {k: str(d[k]).strip() for k, _ in CAMPOS
                  if d.get(k) not in (None, "", "null") and str(d[k]).strip()}
        if limpio:
            fichas[_clave(d["nombre"])] = limpio
    return fichas


FICHAS = _cargar()


def datos_ficha(producto):
    """{'forma': 'Lágrima', ...} o {} si no hay ficha para ese producto."""
    if (producto.categoria or "").lower() not in ("paletas", "palas"):
        return {}
    return FICHAS.get(_clave(producto.nombre), {})


def ficha_tecnica(producto):
    """Lista de (etiqueta, valor) para la tabla de la página del producto."""
    d = datos_ficha(producto)
    return [(etiqueta, d[k]) for k, etiqueta in CAMPOS if k in d]


def ficha_rapida(producto):
    """Las 3 o 4 características principales, para mostrar junto al precio."""
    d = datos_ficha(producto)
    return [(etiqueta, d[k]) for k, etiqueta in CAMPOS if k in RAPIDOS and k in d]


def frase_ficha(producto):
    """Un párrafo con la ficha en palabras, para la descripción y para Google."""
    d = datos_ficha(producto)
    if not d:
        return None
    partes = []
    forma = d.get("forma")
    if forma:
        partes.append(f"Tiene forma {('de ' + forma.lower()) if forma.lower() in ('lágrima', 'diamante') else forma.lower()}")
    if d.get("balance"):
        partes.append(f"balance {d['balance'].lower()}")
    if d.get("peso"):
        partes.append(f"un peso de {d['peso']}")
    frase = ""
    if partes:
        frase = (", ".join(partes[:-1]) + " y " + partes[-1]) if len(partes) > 1 else partes[0]
        if not frase.startswith("Tiene"):
            frase = "Tiene " + frase
        frase += "."
    mat = []
    if d.get("cara"):
        mat.append(f"caras de {d['cara']}")
    if d.get("nucleo"):
        mat.append(f"núcleo {d['nucleo']}")
    if mat:
        frase += f" Está fabricada con {' y '.join(mat)}."
    uso = []
    if d.get("nivel"):
        uso.append(f"jugadores de nivel {d['nivel'].lower()}")
    if d.get("juego"):
        j = d["juego"].lower()
        uso.append("un juego polivalente" if j == "polivalente" else f"un juego de {j}")
    if uso:
        frase += f" Recomendada para {' que buscan '.join(uso)}."
    if d.get("jugador"):
        frase += f" Es la paleta de {d['jugador']}."
    return frase.strip() or None
