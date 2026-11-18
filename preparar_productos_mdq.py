"""Arma un CSV de productos (no paletas) del importador Pádel Mdq Shop para /admin/precios.

Toma el datos.json que se exporta del catálogo del importador, con:
    codigo, marca, nombre (ya con el nombre final para la tienda), costo, estado
y la carpeta de fotos (<codigo>.webp/.png/.jpeg/.gif).

Precio = lo calcula el admin con el margen (40%), porque la columna precio va vacía.
Solo se cargan los que tienen stock y foto.

Uso: python preparar_productos_mdq.py datos.json carpeta_fotos CATEGORIA salida.csv "Descripción con {nombre}"
"""
import csv
import json
import os
import sys

from preparar_paletas_mdq import STOCK, convertir_foto, slug


def main():
    datos, carpeta, categoria, salida, plantilla = sys.argv[1:6]
    base = os.path.dirname(os.path.abspath(__file__))
    filas, sin_foto = [], []
    for d in json.load(open(datos, encoding="utf-8")):
        if d["estado"] not in STOCK or not d["costo"]:
            continue
        origen = next((os.path.join(carpeta, f"{d['codigo']}.{e}")
                       for e in ("webp", "png", "jpeg", "jpg", "gif")
                       if os.path.exists(os.path.join(carpeta, f"{d['codigo']}.{e}"))), None)
        if not origen:
            sin_foto.append(d["nombre"])
            continue
        imagen = f"{slug(d['nombre'])}.jpg"
        destino = os.path.join(base, "static", "img", imagen)
        if not os.path.exists(destino):  # no pisar una foto que ya está en la tienda
            convertir_foto(origen, destino)
        filas.append([d["nombre"], d["marca"], "Pádel", categoria, d["costo"], "",
                      STOCK[d["estado"]], imagen, plantilla.format(nombre=d["nombre"])])

    with open(os.path.join(base, salida), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["nombre", "marca", "deporte", "categoria", "costo", "precio", "stock", "imagen", "descripcion"])
        w.writerows(filas)
    print(f"{len(filas)} productos -> {salida}")
    print(f"Sin foto ({len(sin_foto)}): " + ", ".join(sin_foto))


if __name__ == "__main__":
    main()
