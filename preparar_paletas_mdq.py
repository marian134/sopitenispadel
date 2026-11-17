"""Arma el CSV de paletas del importador Pádel Mdq Shop para cargar en /admin/precios.

Costo = el menor entre precio Silver y Premium del importador.
Precio = lo calcula el admin con el margen (40%), porque la columna precio va vacía.
Uso: python preparar_paletas_mdq.py [carpeta_fotos_webp]
"""
import csv
import os
import re
import sys
import unicodedata

MARCA = "Bullpadel"
STOCK = {"Disponible": 3, "Pocas Unidades": 1}

# (código importador, modelo, silver, premium, estado)
PALETAS = [
    ("2171", "Vertex 05 2027", 513350, 535680, "Pocas Unidades"),
    ("2172", "Vertex 05 Hybrid 2027", 493750, 515200, "Pocas Unidades"),
    ("2173", "Vertex 05 Geo 2027", 493750, 515200, "Pocas Unidades"),
    ("2174", "Vertex 05 Woman 2027", 475900, 496620, "Pocas Unidades"),
    ("2175", "Hack 05 2027", 493750, 515200, "Pocas Unidades"),
    ("2176", "Hack 05 Hybrid 2027", 504450, 526380, "Pocas Unidades"),
    ("2177", "Hack 05 Comfort 2027", 426000, 444550, "Pocas Unidades"),
    ("2178", "Xplo Pro 2027", 474150, 494750, "Pocas Unidades"),
    ("2179", "Xplo Comfort 2027", 408190, 425900, "Pocas Unidades"),
    ("2180", "Neuron 02 2027", 493750, 515200, "Pocas Unidades"),
    ("2181", "Neuron 02 Edge 2027", 525835, 548700, "Pocas Unidades"),
    ("2182", "Neuron 02 Comfort 2027", 408190, 425900, "Pocas Unidades"),
    ("2183", "Pearl Woman 2027", 434930, 453840, "Pocas Unidades"),
    ("2184", "Elite Woman 02 2027", 445600, 465000, "Pocas Unidades"),
    ("2185", "Flow Legend Woman 2027", 408190, 425900, "Pocas Unidades"),
    ("2186", "Wonder Woman 2027", 426000, 444500, "Pocas Unidades"),
    ("2187", "Vertex 05 2026", 401050, 418500, "Disponible"),
    ("2188", "Vertex 05 Hybrid 2026", 418850, 437100, "Disponible"),
    ("2189", "Vertex 05 Geo 2026", 401050, 418500, "Disponible"),
    ("2190", "Vertex 05 Woman 2026", 365400, 381300, "Disponible"),
    ("2191", "Hack 04 2026", 418850, 437100, "Disponible"),
    ("2192", "Hack 04 Hybrid 2026", 409990, 427800, "Disponible"),
    ("2193", "Xplo Pro 2026", 392150, 409200, "Disponible"),
    ("2194", "Xplo Comfort 2026", 356500, 372000, "Disponible"),
    ("2195", "Neuron 02 2026", 401050, 418500, "Disponible"),
    ("2196", "Neuron 02 Edge 2026", 401050, 418500, "Disponible"),
    ("2197", "Pearl Woman 2026", 392150, 409200, "Disponible"),
    ("2198", "Elite Woman 2026", 383230, 399900, "Disponible"),
    ("2199", "Flow Legend Woman 2026", 365400, 381300, "Disponible"),
    ("2200", "Wonder Woman 2026", 409950, 427800, "Disponible"),
    ("2201", "Ionic Power 2026", 356500, 372000, "Disponible"),
    ("2202", "Ionic Control 2026", 356500, 372000, "Disponible"),
    ("2203", "Ionic Light 2026", 311930, 325500, "Disponible"),
    ("2204", "Vertex Advanced 2026", 285200, 297600, "Disponible"),
    ("2205", "Hack Advanced 2026", 276280, 288300, "Disponible"),
    ("2206", "Indiga Power 2026", 231700, 241800, "Disponible"),  # el importador dice "20026"
    ("2207", "Indiga Woman 2026", 231700, 241800, "Disponible"),
    ("2208", "Hack 04 2025", 365400, 381300, "Disponible"),
    ("2209", "Vertex 04 2025", 365400, 381300, "Disponible"),
    ("2210", "Vertex 04 Woman 2025", 347500, 362700, "Disponible"),
    ("2211", "Xplo Pro 2025", 365400, 381300, "Disponible"),
    ("2212", "Neuron 2025", 335110, 349680, "Disponible"),
    ("2213", "Elite Woman 2025", 365400, 381300, "Disponible"),
    ("2214", "Hack 03 2024", 347500, 362700, "Disponible"),
    ("2215", "Vertex 04 2024", 365400, 381300, "Disponible"),
]

# Ya están en la tienda con precio propio: no se tocan.
YA_CARGADAS = {"Hack 04 2026", "Ionic Power 2026", "Vertex 05 Woman 2026"}


def slug(texto):
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", texto).strip("-")


def descripcion(modelo):
    partes = [f"Paleta de pádel {MARCA} {modelo}."]
    if "Woman" in modelo:
        partes.append("Línea femenina, más liviana y manejable.")
    if "Comfort" in modelo or "Light" in modelo:
        partes.append("Pensada para mayor confort y salida de bola.")
    if "Advanced" in modelo or "Indiga" in modelo:
        partes.append("Ideal para jugadores en progresión.")
    return " ".join(partes)


def convertir_foto(origen, destino):
    from PIL import Image

    img = Image.open(origen).convert("RGBA")
    img.thumbnail((500, 500), Image.LANCZOS)
    fondo = Image.new("RGB", (500, 500), "white")
    fondo.paste(img, ((500 - img.width) // 2, (500 - img.height) // 2), img)
    fondo.save(destino, "JPEG", quality=88)


def main():
    carpeta_fotos = sys.argv[1] if len(sys.argv) > 1 else None
    base = os.path.dirname(os.path.abspath(__file__))
    filas, sin_foto = [], []
    for codigo, modelo, silver, premium, estado in PALETAS:
        if modelo in YA_CARGADAS or estado not in STOCK:
            continue
        nombre = f"{MARCA} {modelo}"
        imagen = ""
        origen = carpeta_fotos and os.path.join(carpeta_fotos, f"{codigo}.webp")
        if origen and os.path.exists(origen):
            imagen = f"{slug(nombre)}.jpg"
            convertir_foto(origen, os.path.join(base, "static", "img", imagen))
        else:
            sin_foto.append(nombre)
        filas.append([nombre, MARCA, "Pádel", "Paletas", min(silver, premium), "", STOCK[estado],
                      imagen, descripcion(modelo)])

    salida = os.path.join(base, f"paletas_{slug(MARCA)}.csv")
    with open(salida, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["nombre", "marca", "deporte", "categoria", "costo", "precio", "stock", "imagen", "descripcion"])
        w.writerows(filas)
    print(f"{len(filas)} paletas -> {salida}")
    print(f"Sin foto ({len(sin_foto)}): " + ", ".join(sin_foto))


if __name__ == "__main__":
    main()
