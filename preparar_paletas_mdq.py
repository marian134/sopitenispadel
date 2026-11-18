"""Arma el CSV de paletas del importador Pádel Mdq Shop para cargar en /admin/precios.

Costo = el menor entre precio Silver y Premium del importador (si está en dólares,
se pasa a pesos con la cotización de esa marca).
Precio = lo calcula el admin con el margen (40%), porque la columna precio va vacía.
Uso: python preparar_paletas_mdq.py MARCA [carpeta_fotos_webp]
"""
import csv
import os
import re
import sys
import unicodedata

STOCK = {"Disponible": 3, "Pocas Unidades": 1}

# (código importador, modelo, silver, premium, estado)
BULLPADEL = [
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

# Precios en dólares
NOX = [
    ("2605", "AT10 Genius 18k Alum Bs.As 2026", 310, 300, "Disponible"),
    ("2606", "AT10 Genius 18k Alum 2026", 300, 290, "Disponible"),
    ("2607", "AT10 Genius 12k Alum 2026", 285, 275, "Disponible"),
    ("2608", "AT10 Genius 12k Alum Lite 2026", 280, 270, "Disponible"),
    ("2609", "AT Attack 18k Alum 2026", 285, 275, "Disponible"),
    ("2610", "AT Attack 12k Alum 2026", 275, 265, "Disponible"),
    ("2611", "EA10 Ventus Hybrid 12k 2026", 255, 245, "Disponible"),
    ("2612", "EA10 Ventus Attack 12k 2026", 255, 245, "Disponible"),
    ("2613", "ML10 Ventus Control 3k 2026", 280, 270, "Disponible"),
    ("2614", "VK10 Ventus Control 12k 2026", 265, 255, "Disponible"),
    ("2615", "Ventus Hybrid 12k Lite 2026", 270, 260, "Disponible"),
    ("2616", "AT10 Pro Cup Hard 2026", 230, 215, "Disponible"),
    ("2617", "AT10 Pro Cup Soft 2026", 230, 215, "Disponible"),
    ("2618", "AT10 Genius Junior 2026", 175, 165, "Disponible"),
    ("2619", "X-Hero 2026", 0, 0, "No Disponible"),
    ("2620", "AT10 Genius 18k 2025", 255, 245, "Disponible"),
    ("2621", "AT10 Genius 12k 2025", 250, 240, "Disponible"),
    ("2622", "ML10 Quantum 3k 2025", 250, 240, "Disponible"),
    ("2623", "Future Attack 12k 2025", 255, 245, "Pocas Unidades"),
    ("2624", "Future Hybrid 12k 2025", 255, 245, "Pocas Unidades"),
    ("2625", "AT10 Genius 18k 2024", 235, 225, "Disponible"),
    ("2626", "AT10 Genius 12k 2024", 235, 225, "Disponible"),
    ("2627", "AT10 Genius 18k 2023", 235, 225, "Disponible"),
]

# Adidas: precios en pesos. "Metalbone Ctrl 2.2" del importador se corrige a 3.2.
ADIDAS = [
    ("2000", "Metalbone Pro EDT 3.5", 561480, 585900, "Pocas Unidades"),
    ("2001", "Metalbone Reserve EDT 3.5", 525840, 548700, "Disponible"),
    ("2002", "Metalbone HRD 3.5", 496800, 518400, "Disponible"),
    ("2003", "Metalbone 3.5", 496800, 518400, "Disponible"),
    ("2004", "Metalbone Ctrl 3.5", 529000, 552000, "Disponible"),
    ("2005", "Metalbone Carbon 3.5", 348915, 364088, "Disponible"),
    ("2006", "Metalbone Carbon Ctrl 3.5", 384400, 400500, "Disponible"),
    ("2007", "Metalbone Team 3.5", 315500, 329250, "Pocas Unidades"),
    ("2008", "Metalbone Team Light 3.5", 361850, 377550, "Disponible"),
    ("2009", "Metalbone Superlight 3.5", 320850, 334800, "Disponible"),
    ("2010", "Arrow Hit Pro EDT 3.5", 578150, 604500, "Disponible"),
    ("2011", "Arrow Hit 3.5", 467195, 487500, "Disponible"),
    ("2012", "Arrow Hit Ctrl 3.5", 467195, 487500, "Disponible"),
    ("2013", "Arrow Hit Hexagon 3.5", 295690, 308550, "Disponible"),
    ("2014", "Arrow Hit Light 3.5 Ari Sanchez", 454530, 474300, "Disponible"),
    ("2015", "Arrow Hit Carbon 3.5", 331175, 345575, "Disponible"),
    ("2016", "Arrow Hit Carbon Ctrl 3.5", 331750, 345575, "Disponible"),
    ("2017", "Arrow Hit Junior Blue/Pink 3.5", 0, 0, "No Disponible"),
    ("2018", "Cross It Pro EDT 3.5", 508000, 530100, "Disponible"),
    ("2020", "Cross It Ctrl 3.5", 449450, 468990, "Disponible"),
    ("2021", "Cross It Light 3.5", 445600, 465000, "Disponible"),
    ("2022", "Cross It Carbon 3.5", 354830, 370260, "Disponible"),
    ("2023", "Cross It Carbon Ctrl 3.5", 354830, 370260, "Disponible"),
    ("2024", "Cross It Team Ctrl 3.5", 233420, 243570, "Disponible"),
    ("2025", "Cross It Team Light 3.5", 347500, 362700, "Disponible"),
    ("2026", "ARG WC 3.5", 235370, 245605, "Disponible"),
    ("2027", "Drive Blue 3.5", 159670, 166615, "Disponible"),
    ("2028", "Match Black/Orange 3.5", 147845, 154275, "Disponible"),
    ("2029", "Match Black/Green 3.5", 147845, 154275, "Disponible"),
    ("2030", "Metalbone 09", 235370, 245605, "Disponible"),
    ("2031", "Adipower 10 Aniversary", 567700, 592400, "Disponible"),
    ("2032", "Lasaigues Metalbone Series White", 285255, 297660, "Disponible"),
    ("2033", "Lasaigues Metalbone Series Red", 285255, 297660, "No Disponible"),
    ("2034", "Lasaigues Metalbone Series Blue", 285255, 297660, "Pocas Unidades"),
    ("2035", "Metalbone Pro EDT 3.4", 545460, 569150, "Disponible"),
    ("2036", "Metalbone HRD 3.4", 433100, 451930, "Disponible"),
    ("2037", "Metalbone 3.4", 433100, 451930, "Disponible"),
    ("2038", "Metalbone Ctrl 3.4", 472360, 492900, "Disponible"),
    ("2039", "Metalbone Carbon 3.4", 383200, 399900, "Disponible"),
    ("2040", "Metalbone Carbon Ctrl 3.4", 365400, 381300, "Disponible"),
    ("2041", "Metalbone Team 3.4", 0, 0, "No Disponible"),
    ("2042", "Adipower Ctrl Mtw Pro EDT 3.4", 477280, 498600, "Disponible"),
    ("2043", "Adipower Multiweight Ctrl 3.4", 439700, 458800, "Pocas Unidades"),
    ("2044", "Adipower Carbon Ctrl 3.4", 318300, 332250, "Pocas Unidades"),
    ("2045", "Cross It Pro EDT 3.4", 379850, 396350, "Disponible"),
    ("2046", "Cross It 3.4", 365260, 381150, "Disponible"),
    ("2047", "Cross It Ctrl 3.4", 375000, 391200, "Disponible"),
    ("2048", "Cross It Light 3.4", 401000, 418500, "Disponible"),
    ("2049", "Cross It Carbon (Maxi Arce) 3.4", 374300, 390600, "No Disponible"),
    ("2050", "Cross It Carbon Ctrl 3.4", 311695, 325240, "Disponible"),
    ("2051", "Match Blue 3.4", 116890, 121970, "Disponible"),
    ("2052", "Match Black 3.4", 116890, 121970, "Disponible"),
    ("2053", "Adipower Ctrl Series Green", 140890, 147000, "Disponible"),
    ("2054", "Adipower Ctrl Series Red", 140890, 147000, "Disponible"),
    ("2055", "Adipower Ctrl Series Blue", 140890, 147000, "Disponible"),
    ("2056", "Zukur Ctrl Green", 145100, 151370, "Disponible"),
    ("2057", "Zukur Ctrl Orange", 145100, 151370, "Disponible"),
    ("2058", "Zukur Ctrl Blue", 145100, 151370, "Disponible"),
    ("2059", "Zukur Ctrl Red", 145100, 151370, "Disponible"),
    ("2060", "Zukur Ctrl 2.0 LTD Orange", 140890, 147000, "Disponible"),
    ("2061", "Zukur Ctrl 2.0 LTD Green", 140890, 147000, "Disponible"),
    ("2062", "X-Treme Lime", 172550, 180100, "Disponible"),
    ("2063", "X-Treme Orange", 172550, 180100, "Disponible"),
    ("2064", "X-Treme Silver/Gold", 172550, 180100, "Disponible"),
    ("2065", "Training Ctrl Tubular Reforzado", 122450, 127800, "Disponible"),
    ("2066", "Precision Pro Tubular Reforzado", 122450, 127800, "Disponible"),
    ("2067", "Elevation Tour Green", 114900, 120000, "Disponible"),
    ("2068", "Elevation Tour Gold", 114900, 120000, "Disponible"),
    ("2069", "Elevation Tour Orange", 114900, 120000, "Disponible"),
    ("2070", "Faster Green", 114900, 120000, "Pocas Unidades"),
    ("2071", "Adipower Multiweight 3.3", 349600, 364800, "Pocas Unidades"),
    ("2072", "Adipower Multiweight Ctrl 3.3", 349600, 364800, "Pocas Unidades"),
    ("2073", "Adipower Ctrl 3.3", 339200, 353270, "Pocas Unidades"),
    ("2074", "Cross It 3.3", 349600, 364800, "Pocas Unidades"),
    ("2075", "Cross It Ctrl 3.3", 349600, 364800, "Disponible"),
    ("2076", "Metalbone HRD 3.2", 374300, 390600, "Disponible"),
    ("2077", "Metalbone 3.2", 383200, 399900, "Disponible"),
    ("2078", "Metalbone Ctrl 3.2", 365400, 381300, "Disponible"),
    ("2079", "Multiweight Master LTD 3.2", 288500, 301070, "Disponible"),
    ("2080", "Adipower Multiweight 3.2", 270440, 282200, "Disponible"),
    ("2081", "Adipower Multiweight Ctrl 3.2", 270440, 282200, "Pocas Unidades"),
    ("2082", "Adipower 3.2", 270440, 282200, "Pocas Unidades"),
    ("2083", "Adipower Ctrl 3.2", 270440, 282200, "Disponible"),
    ("2084", "Cross It Light 3.2", 401050, 418500, "Disponible"),
]

# dolar: cotización si los precios vienen en dólares.
# ya_cargadas: modelos que ya están en la tienda con precio propio (no se tocan).
MARCAS = {
    "Bullpadel": {"paletas": BULLPADEL, "dolar": None,
                  "ya_cargadas": {"Hack 04 2026", "Ionic Power 2026", "Vertex 05 Woman 2026"}},
    "Nox": {"paletas": NOX, "dolar": 1450,
            "ya_cargadas": {"AT10 Genius 18k Alum Bs.As 2026", "AT Attack 18k Alum 2026", "AT10 Pro Cup Soft 2026"}},
    "Adidas": {"paletas": ADIDAS, "dolar": None,
               "ya_cargadas": {"Cross It Light 3.5"}},
}


def slug(texto):
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", texto).strip("-")


def descripcion(marca, modelo):
    partes = [f"Paleta de pádel {marca} {modelo}."]
    if "Junior" in modelo:
        partes.append("Pensada para chicos.")
    if "Woman" in modelo:
        partes.append("Línea femenina, más liviana y manejable.")
    if "Comfort" in modelo or "Light" in modelo or "Lite" in modelo:
        partes.append("Pensada para mayor confort y salida de bola.")
    if "Ctrl" in modelo:
        partes.append("Versión control: más manejable y precisa.")
    if "Team" in modelo or "Match" in modelo or "Drive" in modelo or "Training" in modelo:
        partes.append("Ideal para jugadores en progresión.")
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
    marca = sys.argv[1]
    datos = MARCAS[marca]
    carpeta_fotos = sys.argv[2] if len(sys.argv) > 2 else None
    base = os.path.dirname(os.path.abspath(__file__))
    filas, sin_foto = [], []
    for codigo, modelo, silver, premium, estado in datos["paletas"]:
        if modelo in datos["ya_cargadas"] or estado not in STOCK:
            continue
        costo = min(silver, premium) * (datos["dolar"] or 1)
        nombre = f"{marca} {modelo}"
        imagen = ""
        origen = None
        if carpeta_fotos:  # la foto puede venir como .webp, .png, .jpeg o .gif
            for ext in ("webp", "png", "jpeg", "jpg", "gif"):
                ruta = os.path.join(carpeta_fotos, f"{codigo}.{ext}")
                if os.path.exists(ruta):
                    origen = ruta
                    break
        if origen:
            imagen = f"{slug(nombre)}.jpg"
            destino = os.path.join(base, "static", "img", imagen)
            if not os.path.exists(destino):  # no pisar una foto que ya está en la tienda
                convertir_foto(origen, destino)
        else:
            sin_foto.append(nombre)
            continue  # sin foto no se muestra en la tienda, no tiene sentido cargarla
        filas.append([nombre, marca, "Pádel", "Paletas", costo, "", STOCK[estado],
                      imagen, descripcion(marca, modelo)])

    salida = os.path.join(base, f"paletas_{slug(marca)}.csv")
    with open(salida, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["nombre", "marca", "deporte", "categoria", "costo", "precio", "stock", "imagen", "descripcion"])
        w.writerows(filas)
    print(f"{len(filas)} paletas -> {salida}")
    print(f"Sin foto ({len(sin_foto)}): " + ", ".join(sin_foto))


if __name__ == "__main__":
    main()
