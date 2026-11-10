#!/usr/bin/env python3
"""
Convierte el catálogo del mayorista (texto copiado de su web) en un CSV
listo para subir en /admin/precios de la tienda SOPI.

Uso (Git Bash, parado en la carpeta donde están los archivos):

    python convertir_catalogo.py catalogo.txt
    python convertir_catalogo.py catalogo.txt --precio premium --stock 3

Podés pegar varias páginas y varias categorías en el mismo catalogo.txt:
los productos repetidos se descartan solos.
"""
import argparse
import csv
import re
import sys

# --- Ajustes que podés cambiar ------------------------------------------------

# Deporte con el que se cargan todos los productos de este mayorista
DEPORTE = "Pádel"

# Si querés renombrar categorías del mayorista a las de tu tienda
CATEGORIAS = {
    "Mochilas": "Bolsos",
}

ESTADOS = ("Disponible", "Encargar", "No Disponible")

# ------------------------------------------------------------------------------


def leer(path):
    datos = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return datos.decode(enc)
        except UnicodeDecodeError:
            pass
    sys.exit("No pude leer el archivo: guardalo como UTF-8 desde el Bloc de notas.")


def a_precio(texto):
    """'$ 14.490' -> 14490"""
    digitos = re.sub(r"\D", "", texto or "")
    return int(digitos) if digitos else 0


def nombre_completo(marca, nombre):
    """Sin marca, 'Evo Roja' no dice nada en tu tienda: se antepone."""
    if nombre.lower().startswith(marca.lower()):
        return nombre
    return f"{marca} {nombre}"


def parsear(texto):
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    productos = []

    for i, linea in enumerate(lineas):
        # Cada tarjeta tiene: nombre, marca, nombre, categoría, Silver, $, Premium, $, estado
        if linea != "Silver" or i < 4 or i + 4 >= len(lineas):
            continue
        if not lineas[i + 1].startswith("$") or lineas[i + 2] != "Premium":
            continue

        nombre1, marca, nombre2, categoria = lineas[i - 4: i]
        if nombre1 != nombre2:
            continue  # no es una tarjeta de producto

        estado = lineas[i + 4]
        productos.append({
            "nombre": nombre1,
            "marca": marca,
            "categoria": categoria,
            "silver": a_precio(lineas[i + 1]),
            "premium": a_precio(lineas[i + 3]),
            "estado": estado if estado in ESTADOS else "Disponible",
        })
    return productos


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entrada", help="archivo de texto con el catálogo copiado")
    ap.add_argument("-o", "--salida", default="productos.csv")
    ap.add_argument("--precio", choices=("silver", "premium"), default="silver",
                    help="qué precio del mayorista se usa como costo (por defecto: silver)")
    ap.add_argument("--stock", type=int, default=5,
                    help="stock inicial de los productos disponibles (por defecto: 5)")
    ap.add_argument("--con-agotados", action="store_true",
                    help="incluir también los 'No Disponible' (con stock 0)")
    args = ap.parse_args()

    productos = parsear(leer(args.entrada))
    if not productos:
        sys.exit("No encontré productos. ¿Copiaste la página completa con Ctrl + A?")

    filas, vistos = [], set()
    omitidos = {"repetidos": [], "sin precio": [], "no disponible": []}

    for p in productos:
        nombre = nombre_completo(p["marca"], p["nombre"])
        clave = nombre.lower()

        if clave in vistos:
            omitidos["repetidos"].append(nombre)
            continue
        vistos.add(clave)

        costo = p[args.precio]
        if costo <= 0:
            omitidos["sin precio"].append(nombre)
            continue

        if p["estado"] == "No Disponible" and not args.con_agotados:
            omitidos["no disponible"].append(nombre)
            continue

        stock = args.stock if p["estado"] == "Disponible" else 0
        filas.append({
            "nombre": nombre,
            "marca": p["marca"],
            "deporte": DEPORTE,
            "categoria": CATEGORIAS.get(p["categoria"], p["categoria"]),
            "costo": costo,
            "stock": stock,
            "imagen": "",
            "descripcion": "",
        })

    campos = ["nombre", "marca", "deporte", "categoria", "costo", "stock", "imagen", "descripcion"]
    with open(args.salida, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        w.writeheader()
        w.writerows(filas)

    print(f"Leí {len(productos)} productos del catálogo.")
    print(f"Guardé {len(filas)} en {args.salida} (costo = precio {args.precio}, stock {args.stock}).")
    for motivo, nombres in omitidos.items():
        if nombres:
            print(f"\nOmitidos por {motivo} ({len(nombres)}):")
            for n in nombres:
                print(f"  - {n}")


if __name__ == "__main__":
    main()
