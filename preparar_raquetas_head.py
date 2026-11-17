"""
Arma raquetas_head.csv con las raquetas de tenis Head del mayorista Grupo Vieytes
(categoria "RAQUETAS TENIS" del portal) y baja las fotos.

Lee raquetas_head.json: [{id, nombre, costo, sugerido, imagen, stock: {"3/8": 15, ...}}]
(sacado de la API del portal estando logueado; ver talles_vieytes.py para el metodo).

- Precio de venta = precio sugerido de Head, redondeado a $100.
- Las variantes del portal son el grip: "1/4" -> 4 1/4, "3/8" -> 4 3/8 (las que
  vienen como "U 3/8" o "S 1/4" se suman al mismo grip). Van en la columna "talles".
- Las que ya estaban en la tienda (YA_EN_TIENDA) solo actualizan grip y stock:
  no se les toca el costo, el precio ni la foto.

Uso (desde la raiz del proyecto):
    py preparar_raquetas_head.py              # CSV + fotos en static/img/
    py preparar_raquetas_head.py --sin-fotos  # solo el CSV
Despues se carga raquetas_head.csv en /admin/precios y las fotos se suben con git.
"""
import csv
import json
import re
import sys
from pathlib import Path

from preparar_vieytes import bajar_foto, slug

ENTRADA = "raquetas_head.json"
SALIDA = "raquetas_head.csv"
DESTINO = Path("static/img")
MARCA, DEPORTE, CATEGORIA = "Head", "Tenis", "Raquetas"

# id del portal -> nombre en la tienda
NOMBRES = {
    "1002082": "Head Arthur Ashe Competition 2025",
    "1053583": "Head Boom MP Neon 2025",
    "1094220": "Head Extreme Team 2024",
    "1090746": "Head IG Challenge MP Rojo",
    "1051875": "Head IG Challenge Team L Stealth",
    "722005": "Head Instinct MP 2022",
    "722021": "Head MX Spark Suprm Rojo",
    "1040616": "Head Paw 21 Junior Blanco",
    "1002083": "Head Prestige MP 2023",
    "722010": "Head Prestige MP L 2023",
    "722009": "Head Prestige Pro 2023",
    "1002074": "Head Speed Junior 21",
    "1094221": "Head Speed MP L 2026",
    "1053584": "Head Speed Pro 2026",
    "1053588": "Head Squared",
}
# Ya cargadas en la tienda con ese mismo nombre: solo se actualizan grip y stock
YA_EN_TIENDA = {"1002082", "1053583", "1090746", "722021", "1002083", "1053584"}
# Se saltean: 722023 es la misma IG Challenge Team L que 1051875; 1090201 no tiene foto
SALTEAR = {"722023": "duplicada de 1051875", "1090201": "sin foto en el portal"}


def grips(stock):
    """{'U 3/8': 41, 'U 1/4': 0} -> {'4 3/8': 41, '4 1/4': 0}. Sin grip -> {}."""
    resultado = {}
    for variante, cantidad in stock.items():
        m = re.search(r"(1/4|3/8|1/2|5/8)", variante)
        if not m:
            return {}
        grip = f"4 {m.group(1)}"
        resultado[grip] = resultado.get(grip, 0) + int(cantidad or 0)
    return dict(sorted(resultado.items()))


def main(con_fotos):
    raquetas = json.load(open(ENTRADA, encoding="utf-8"))
    filas, salteadas, fallidas = [], [], []
    DESTINO.mkdir(parents=True, exist_ok=True)

    for r in raquetas:
        if r["id"] in SALTEAR:
            salteadas.append(f"{r['nombre'].strip()} ({SALTEAR[r['id']]})")
            continue
        nombre = NOMBRES[r["id"]]
        g = grips(r["stock"])
        talles = " ".join(f"{k}:{v}" for k, v in g.items())
        stock = sum(int(v or 0) for v in r["stock"].values())
        costo = int(round(r["costo"]))

        if r["id"] in YA_EN_TIENDA:
            # sin costo, precio ni imagen: el CSV deja los que ya tienen
            # (con costo y sin precio, /admin/precios recalcularia el precio con el margen)
            filas.append([nombre, MARCA, DEPORTE, CATEGORIA, "", "", stock, "", talles])
            continue

        precio = int(round(r["sugerido"] / 100.0)) * 100
        imagen = slug(nombre) + ".jpg"
        if con_fotos:
            try:
                bajar_foto(r["imagen"], DESTINO / imagen)
            except Exception as e:
                fallidas.append((nombre, str(e)[:60]))
        filas.append([nombre, MARCA, DEPORTE, CATEGORIA, costo, precio, stock, imagen, talles])

    with open(SALIDA, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(["nombre", "marca", "deporte", "categoria", "costo", "precio", "stock", "imagen", "talles"])
        w.writerows(filas)

    nuevas = len(filas) - len(YA_EN_TIENDA)
    print(f"CSV: {SALIDA} | raquetas nuevas: {nuevas} | ya en la tienda (solo grip/stock): {len(YA_EN_TIENDA)}")
    for s in salteadas:
        print(f"  Salteada: {s}")
    for n, e in fallidas:
        print(f"  Sin foto: {n} -> {e}")


if __name__ == "__main__":
    main("--sin-fotos" not in sys.argv)
