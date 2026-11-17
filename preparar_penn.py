"""
Arma penn_niu_ama.csv y las fotos de los productos de Penn Argentina (marcas Penn, NIU y AMA).

Fuente: "propuesta Penn/LISTA A.pdf" y "LISTA B.pdf" (precios mayoristas por caja).
- Costo = LISTA B (compras de $100.000 a $1.000.000). Con LISTA A (desde $1.000.000) el margen es mayor.
- Tubo suelto: costo de la caja / 24, + 40%.
- Cajas x24 y bolsas x100 / x48 (para profes y clubes): costo + 15%.
- Paletas, bolsos y accesorios: costo + 40%.
- Precios redondeados a $100. Stock fijo (STOCK), a ajustar según lo que se compre.

Las fotos se sacan del PDF (LISTA A) con un script aparte que deja un PNG por foto,
nombrado por pagina y posicion (ej: p03_x-07_y218.png). Este script las pasa a fondo blanco,
las centra en un cuadrado y las guarda en static/img/ con el nombre del producto.

Uso (desde la raiz del proyecto):
    py preparar_penn.py CARPETA_CON_LOS_PNG     # CSV + fotos
    py preparar_penn.py --sin-fotos             # solo el CSV
Despues se carga penn_niu_ama.csv en /admin/precios y las fotos se suben con git.

Ya estaban en la tienda y NO se tocan: "Pelotas Penn Premiere - Tubo x3",
"Pack x3 tubos Penn Premiere (5% off)" y "Penn Padel x3".
Quedan afuera hasta confirmar si son de tenis o de padel: AMA Sport Pro, Master x2 y Master Rosa x2.
"""
import csv
import sys
from pathlib import Path

from preparar_vieytes import slug

SALIDA = "penn_niu_ama.csv"
DESTINO = Path("static/img")
STOCK = 10
LADO_FOTO = 500

MARGEN_PUBLICO = 0.40
MARGEN_CLUBES = 0.15


def redondear(valor):
    """A $100, con la mitad hacia arriba (212.750 -> 212.800).
    Primero a centavos: 185000 * 1.15 da 212749.999... en punto flotante."""
    return int(round(valor, 2) / 100.0 + 0.5) * 100


def tubo(caja):
    return caja / 24


# (nombre, marca, deporte, categoria, costo, margen, foto, descripcion)
PRODUCTOS = [
    # ---------------- TENIS · Pelotas · Penn ----------------
    ("Pelotas Penn Tour - Tubo x3", "Penn", "Tenis", "Pelotas", tubo(185000), MARGEN_PUBLICO, "p03_x-07_y218",
     "Tubo de 3 pelotas de tenis Penn Tour."),
    ("Pelotas Penn Marathon - Tubo x3", "Penn", "Tenis", "Pelotas", tubo(185000), MARGEN_PUBLICO, "p03_x211_y232",
     "Tubo de 3 pelotas de tenis Penn Marathon."),
    ("Pelotas Penn Championship - Tubo x3", "Penn", "Tenis", "Pelotas", tubo(180000), MARGEN_PUBLICO, "p03_x416_y233",
     "Tubo de 3 pelotas de tenis Penn Championship."),
    ("Caja Penn Tour x24 tubos", "Penn", "Tenis", "Pelotas", 185000, MARGEN_CLUBES, "p03_x-07_y218",
     "Caja de 24 tubos de pelotas de tenis Penn Tour. Ideal para profes, clubes y escuelas."),
    ("Caja Penn Marathon x24 tubos", "Penn", "Tenis", "Pelotas", 185000, MARGEN_CLUBES, "p03_x211_y232",
     "Caja de 24 tubos de pelotas de tenis Penn Marathon. Ideal para profes, clubes y escuelas."),
    ("Caja Penn Championship x24 tubos", "Penn", "Tenis", "Pelotas", 180000, MARGEN_CLUBES, "p03_x416_y233",
     "Caja de 24 tubos de pelotas de tenis Penn Championship. Ideal para profes, clubes y escuelas."),
    # en el PDF el tubo Premiere es una imagen aparte, encima de la caja: se juntan las dos
    ("Caja Penn Premiere x24 tubos", "Penn", "Tenis", "Pelotas", 175000, MARGEN_CLUBES, "p03_x399_y485+p03_x328_y479",
     "Caja de 24 tubos de pelotas de tenis Penn Premiere. Ideal para profes, clubes y escuelas."),
    ("Bolsa Penn Tournament Sello Negro x100 pelotas", "Penn", "Tenis", "Pelotas", 250000, MARGEN_CLUBES, "p04_x032_y210",
     "Bolsa de 100 pelotas de tenis Penn Tournament (sello negro), para entrenamiento con canasto."),
    ("Bolsa Penn Tournament Pro x100 pelotas", "Penn", "Tenis", "Pelotas", 250000, MARGEN_CLUBES, "p04_x385_y237",
     "Bolsa de 100 pelotas de tenis Penn Tournament Pro, para entrenamiento con canasto."),
    # ---------------- TENIS · Pelotas · AMA (baja presión, escuelita) ----------------
    ("Bolsa AMA Baja Presión Verde x48 pelotas", "AMA", "Tenis", "Pelotas", 160000, MARGEN_CLUBES, "p11_x046_y170",
     "Bolsa de 48 pelotas de tenis de baja presión AMA (verde), para escuelita y minitenis."),
    ("Bolsa AMA Baja Presión Naranja x48 pelotas", "AMA", "Tenis", "Pelotas", 160000, MARGEN_CLUBES, "p11_x351_y166",
     "Bolsa de 48 pelotas de tenis de baja presión AMA (naranja), para escuelita y minitenis."),
    ("Bolsa AMA Baja Presión Roja x48 pelotas", "AMA", "Tenis", "Pelotas", 160000, MARGEN_CLUBES, "p11_x210_y474",
     "Bolsa de 48 pelotas de tenis de baja presión AMA (roja), para escuelita y minitenis."),
    # ---------------- TENIS · Accesorios ----------------
    ("Canasto Plegable NIU", "NIU", "Tenis", "Accesorios", 215000, MARGEN_PUBLICO, "p09_x405_y173",
     "Canasto plegable para pelotas NIU, para entrenamiento."),

    # ---------------- PÁDEL · Pelotas · Penn ----------------
    ("Penn Padel x2", "Penn", "Pádel", "Pelotas", tubo(135000), MARGEN_PUBLICO, "p03_x197_y483",
     "Tubo de 2 pelotas de pádel Penn Padel."),
    ("Caja Penn Padel x3 x24 tubos", "Penn", "Pádel", "Pelotas", 185000, MARGEN_CLUBES, "p03_x-04_y474",
     "Caja de 24 tubos de 3 pelotas de pádel Penn Padel. Ideal para profes y clubes."),
    ("Caja Penn Padel x2 x24 tubos", "Penn", "Pádel", "Pelotas", 135000, MARGEN_CLUBES, "p03_x197_y483",
     "Caja de 24 tubos de 2 pelotas de pádel Penn Padel. Ideal para profes y clubes."),
    ("Bolsa Penn Padel x100 pelotas", "Penn", "Pádel", "Pelotas", 250000, MARGEN_CLUBES, "p04_x180_y448",
     "Bolsa de 100 pelotas de pádel Penn Padel, para entrenamiento con canasto."),
    # ---------------- PÁDEL · Pelotas · NIU ----------------
    ("NIU Padel x3", "NIU", "Pádel", "Pelotas", tubo(180000), MARGEN_PUBLICO, "p05_x054_y218",
     "Tubo de 3 pelotas de pádel NIU Padel."),
    ("NIU Padel x2", "NIU", "Pádel", "Pelotas", tubo(130000), MARGEN_PUBLICO, "p05_x048_y468",
     "Tubo de 2 pelotas de pádel NIU Padel."),
    ("NIU Pro x2", "NIU", "Pádel", "Pelotas", tubo(130000), MARGEN_PUBLICO, "p05_x314_y191",
     "Tubo de 2 pelotas de pádel NIU Pro."),
    ("NIU Pro Rosa x2", "NIU", "Pádel", "Pelotas", tubo(130000), MARGEN_PUBLICO, "p05_x333_y479",
     "Tubo de 2 pelotas de pádel NIU Pro, en color rosa."),
    ("Caja NIU Padel x3 x24 tubos", "NIU", "Pádel", "Pelotas", 180000, MARGEN_CLUBES, "p05_x054_y218",
     "Caja de 24 tubos de 3 pelotas de pádel NIU Padel. Ideal para profes y clubes."),
    ("Caja NIU Padel x2 x24 tubos", "NIU", "Pádel", "Pelotas", 130000, MARGEN_CLUBES, "p05_x048_y468",
     "Caja de 24 tubos de 2 pelotas de pádel NIU Padel. Ideal para profes y clubes."),
    ("Caja NIU Pro x2 x24 tubos", "NIU", "Pádel", "Pelotas", 130000, MARGEN_CLUBES, "p05_x314_y191",
     "Caja de 24 tubos de 2 pelotas de pádel NIU Pro. Ideal para profes y clubes."),
    ("Caja NIU Pro Rosa x2 x24 tubos", "NIU", "Pádel", "Pelotas", 130000, MARGEN_CLUBES, "p05_x333_y479",
     "Caja de 24 tubos de 2 pelotas de pádel NIU Pro rosa. Ideal para profes y clubes."),
    ("Bolsa NIU Pro x100 pelotas", "NIU", "Pádel", "Pelotas", 240000, MARGEN_CLUBES, "p06_x021_y172",
     "Bolsa de 100 pelotas de pádel NIU Pro, para entrenamiento con canasto."),
    ("Bolsa NIU Padel x100 pelotas", "NIU", "Pádel", "Pelotas", 240000, MARGEN_CLUBES, "p06_x329_y168",
     "Bolsa de 100 pelotas de pádel NIU Padel, para entrenamiento con canasto."),
    ("Bolsa NIU Pro Rosa x100 pelotas", "NIU", "Pádel", "Pelotas", 240000, MARGEN_CLUBES, "p06_x176_y431",
     "Bolsa de 100 pelotas de pádel NIU Pro rosa, para entrenamiento con canasto."),
    # ---------------- PÁDEL · Paletas · NIU ----------------
    ("Paleta NIU Pro Series Comfort 12K", "NIU", "Pádel", "Paletas", 160000, MARGEN_PUBLICO, "p07_x038_y188",
     "Paleta de pádel NIU Pro Series Comfort 12K."),
    ("Paleta NIU Pro Series Control 12K", "NIU", "Pádel", "Paletas", 160000, MARGEN_PUBLICO, "p07_x246_y191",
     "Paleta de pádel NIU Pro Series Control 12K."),
    ("Paleta NIU Pro Series Power 12K", "NIU", "Pádel", "Paletas", 160000, MARGEN_PUBLICO, "p07_x452_y203",
     "Paleta de pádel NIU Pro Series Power 12K."),
    ("Paleta NIU Tour Series Comfort 18K", "NIU", "Pádel", "Paletas", 160000, MARGEN_PUBLICO, "p07_x038_y473",
     "Paleta de pádel NIU Tour Series Comfort 18K."),
    ("Paleta NIU Tour Series Control 18K", "NIU", "Pádel", "Paletas", 160000, MARGEN_PUBLICO, "p07_x232_y467",
     "Paleta de pádel NIU Tour Series Control 18K."),
    ("Paleta NIU Tour Series Power 18K", "NIU", "Pádel", "Paletas", 160000, MARGEN_PUBLICO, "p07_x438_y467",
     "Paleta de pádel NIU Tour Series Power 18K."),
    # ---------------- PÁDEL · Accesorios ----------------
    ("Paletero NIU Tour Bag", "NIU", "Pádel", "Accesorios", 120000, MARGEN_PUBLICO, "p08_x198_y188",
     "Paletero NIU Tour Bag."),
    ("Bolso NIU Tote Bag", "NIU", "Pádel", "Accesorios", 65000, MARGEN_PUBLICO, "p08_x015_y174",
     "Bolso NIU Tote Bag."),
    ("Tubo Recogepelotas NIU", "NIU", "Pádel", "Accesorios", 30000, MARGEN_PUBLICO, "p08_x425_y158",
     "Tubo recogepelotas NIU."),
    # ---------------- PÁDEL · Overgrips ----------------
    ("Cubregrip NIU Azul x60", "NIU", "Pádel", "Overgrips", 74000, MARGEN_PUBLICO, "p08_x012_y513",
     "Caramelera de 60 cubregrips NIU, color azul."),
    ("Cubregrip NIU Blanco x60", "NIU", "Pádel", "Overgrips", 76000, MARGEN_PUBLICO, "p08_x228_y504",
     "Caramelera de 60 cubregrips NIU, color blanco."),
    ("Cubregrip NIU Negro x60", "NIU", "Pádel", "Overgrips", 76000, MARGEN_PUBLICO, "p08_x418_y498",
     "Caramelera de 60 cubregrips NIU, color negro."),
    # ---------------- PÁDEL · Accesorios Textil ----------------
    ("Muñequeras NIU Negras x2", "NIU", "Pádel", "Accesorios Textil", 9000, MARGEN_PUBLICO, "p09_x-25_y143",
     "Par de muñequeras NIU, color negro."),
    ("Muñequeras NIU Azules x2", "NIU", "Pádel", "Accesorios Textil", 9000, MARGEN_PUBLICO, "p09_x204_y175",
     "Par de muñequeras NIU, color azul."),
    # ---------------- PÁDEL · Protectores ----------------
    ("Protector de Paleta NIU", "NIU", "Pádel", "Protectores", 3500, MARGEN_PUBLICO, "p09_x009_y448",
     "Protector de paleta NIU."),
]


def abrir_foto(carpeta, foto):
    """'caja' o 'caja+tubo': en el segundo caso pega el tubo adelante, abajo a la izquierda."""
    from PIL import Image
    partes = [Image.open(Path(carpeta) / f"{p}.png").convert("RGBA") for p in foto.split("+")]
    im = partes[0]
    for extra in partes[1:]:
        # tapa el tubo que trae la foto de la caja (adelante, a la izquierda)
        alto = int(im.height * 0.86)
        extra = extra.crop(extra.split()[3].getbbox())
        extra = extra.resize((int(extra.width * alto / extra.height), alto), Image.LANCZOS)
        im.alpha_composite(extra, (int(im.width * 0.12), im.height - alto - int(im.height * 0.05)))
    return im


def guardar_foto(im, destino):
    """Imagen con transparencia -> JPG con fondo blanco, centrado en un cuadrado."""
    from PIL import Image
    bbox = im.split()[3].getbbox()
    if bbox:
        im = im.crop(bbox)
    lado = max(im.size)
    escala = min(1.0, (LADO_FOTO * 0.9) / lado) if lado > LADO_FOTO else (LADO_FOTO * 0.9) / lado
    im = im.resize((max(1, int(im.width * escala)), max(1, int(im.height * escala))), Image.LANCZOS)
    fondo = Image.new("RGBA", (LADO_FOTO, LADO_FOTO), (255, 255, 255, 255))
    fondo.alpha_composite(im, ((LADO_FOTO - im.width) // 2, (LADO_FOTO - im.height) // 2))
    fondo.convert("RGB").save(destino, "JPEG", quality=88, optimize=True)


def main(carpeta_fotos):
    filas, faltan = [], []
    for nombre, marca, deporte, categoria, costo, margen, foto, descripcion in PRODUCTOS:
        costo = int(round(costo))
        precio = redondear(costo * (1 + margen))
        imagen = slug(nombre) + ".jpg"
        if carpeta_fotos:
            if all((Path(carpeta_fotos) / f"{p}.png").exists() for p in foto.split("+")):
                guardar_foto(abrir_foto(carpeta_fotos, foto), DESTINO / imagen)
            else:
                faltan.append(f"{nombre} ({foto})")
        filas.append([nombre, marca, deporte, categoria, costo, precio, STOCK, imagen, descripcion])

    with open(SALIDA, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(["nombre", "marca", "deporte", "categoria", "costo", "precio", "stock", "imagen", "descripcion"])
        w.writerows(filas)

    print(f"CSV: {SALIDA} | productos: {len(filas)}")
    for f in faltan:
        print(f"  Sin foto: {f}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args and "--sin-fotos" not in sys.argv:
        sys.exit("Pasá la carpeta con los PNG sacados del PDF, o --sin-fotos")
    main(None if "--sin-fotos" in sys.argv else args[0])
