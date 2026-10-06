"""
Deja todas las fotos de producto cuadradas (800x800) con fondo blanco.
- Mantiene el MISMO nombre de archivo (no hay que tocar la base ni el CSV).
- Solo procesa las imagenes que figuran en la columna 'imagen' del CSV
  (no toca logos, favicon ni assets de redes).
- Guarda las originales en static/img_originales/ antes de modificar.

Uso (desde la raiz del proyecto, en Git Bash):
    pip install pillow
    python procesar_imagenes.py productos_padel_final.csv
"""
import csv, shutil, sys
from pathlib import Path
from PIL import Image, ImageChops

IMG_DIR = Path("static/img")
BACKUP_DIR = Path("static/img_originales")
LADO = 800          # tamaño final en px
MARGEN = 0.06       # aire alrededor del producto (6%)
UMBRAL = 12         # tolerancia para detectar fondo blanco al recortar


def a_fondo_blanco(img):
    img = img.convert("RGBA")
    base = Image.new("RGBA", img.size, (255, 255, 255, 255))
    base.alpha_composite(img)
    return base.convert("RGB")


def recortar_blanco(img):
    """Quita bordes blancos para que todos los productos ocupen similar."""
    fondo = Image.new("RGB", img.size, (255, 255, 255))
    diff = ImageChops.difference(img, fondo).convert("L").point(lambda p: 255 if p > UMBRAL else 0)
    caja = diff.getbbox()
    return img.crop(caja) if caja else img


def procesar(ruta):
    img = a_fondo_blanco(Image.open(ruta))
    img = recortar_blanco(img)
    util = int(LADO * (1 - 2 * MARGEN))
    img.thumbnail((util, util), Image.LANCZOS)
    lienzo = Image.new("RGB", (LADO, LADO), (255, 255, 255))
    lienzo.paste(img, ((LADO - img.width) // 2, (LADO - img.height) // 2))
    ext = ruta.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        lienzo.save(ruta, "JPEG", quality=90, optimize=True)
    elif ext == ".png":
        lienzo.save(ruta, "PNG", optimize=True)
    elif ext == ".webp":
        lienzo.save(ruta, "WEBP", quality=90)
    else:
        print("  formato no soportado, salteada:", ruta.name)


def main(csv_path):
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        nombres = {r["imagen"].strip() for r in csv.DictReader(f, delimiter=";") if r.get("imagen", "").strip()}
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ok, faltan = 0, []
    for nombre in sorted(nombres):
        ruta = IMG_DIR / nombre
        if not ruta.exists():
            faltan.append(nombre)
            continue
        destino = BACKUP_DIR / nombre
        if not destino.exists():
            shutil.copy2(ruta, destino)
        procesar(ruta)
        ok += 1
        print("OK ", nombre)
    print(f"\nProcesadas: {ok}")
    if faltan:
        print("NO ENCONTRADAS en static/img (revisar nombre/mayusculas):")
        for n in faltan:
            print("  -", n)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "productos_padel_final.csv")
