"""
Optimiza las imágenes de static/img (y sus subcarpetas) SIN cambiar nombres ni extensiones,
así no se rompe ninguna referencia (base de datos, CSV, plantillas).

Uso (desde la carpeta del proyecto, donde está app.py):

    pip install pillow --user
    python optimizar_imagenes.py --probar     # solo muestra cuánto ahorraría
    python optimizar_imagenes.py              # optimiza de verdad

Antes de tocar cada archivo guarda el original en ./img_originales/
(agregá esa carpeta a .gitignore para que no suba a GitHub).
"""
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageOps

CARPETA = Path("static/img")
BACKUP = Path("img_originales")

EXTENSIONES = {".jpg", ".jpeg", ".png"}
MIN_BYTES = 80 * 1024  # no vale la pena tocar archivos más chicos

# Ancho máximo según el nombre del archivo (en píxeles)
ANCHO_BANNER = 1600
ANCHO_TILE = 900
ANCHO_PRODUCTO = 1000

# Estos no se tocan: logos, favicons e imagen para compartir (tamaño fijo)
SALTEAR_PREFIJOS = ("logo", "favicon", "sopi_favicon", "og-")


def ancho_maximo(nombre):
    n = nombre.lower()
    if n.startswith("banner"):
        return ANCHO_BANNER
    if n.startswith("tile"):
        return ANCHO_TILE
    return ANCHO_PRODUCTO


def optimizar(ruta, probar):
    original = ruta.stat().st_size
    img = Image.open(ruta)
    formato = "PNG" if ruta.suffix.lower() == ".png" else "JPEG"
    img = ImageOps.exif_transpose(img)

    tope = ancho_maximo(ruta.name)
    if img.width > tope:
        alto = round(img.height * tope / img.width)
        img = img.resize((tope, alto), Image.LANCZOS)

    tmp = ruta.with_name(ruta.stem + ".tmp" + ruta.suffix)
    if formato == "JPEG":
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(tmp, "JPEG", quality=82, optimize=True, progressive=True)
    else:
        img.save(tmp, "PNG", optimize=True)

    nuevo = tmp.stat().st_size

    if nuevo >= original:           # no mejoró: se deja el original
        tmp.unlink()
        return original, original, False

    if probar:
        tmp.unlink()
        return original, nuevo, True

    destino = BACKUP / ruta.relative_to(CARPETA)   # conserva subcarpetas (ej: banners/)
    destino.parent.mkdir(parents=True, exist_ok=True)
    if not destino.exists():
        shutil.copy2(ruta, destino)
    tmp.replace(ruta)
    return original, nuevo, True


def kb(n):
    return f"{n / 1024:,.0f} KB".replace(",", ".")


def main():
    probar = "--probar" in sys.argv

    if not CARPETA.exists():
        print(f"No encuentro {CARPETA}. Corré el script desde la carpeta del proyecto.")
        sys.exit(1)

    total_antes = total_despues = 0
    # rglob: incluye subcarpetas (static/img/banners/, etc.)
    archivos = sorted(p for p in CARPETA.rglob("*")
                      if p.is_file() and p.suffix.lower() in EXTENSIONES)

    for ruta in archivos:
        if ruta.name.lower().startswith(SALTEAR_PREFIJOS):
            continue
        if ruta.stat().st_size < MIN_BYTES:
            continue
        try:
            antes, despues, mejoro = optimizar(ruta, probar)
        except Exception as e:
            print(f"  ERROR  {ruta.name}: {e}")
            continue
        total_antes += antes
        total_despues += despues
        marca = "ok " if mejoro else "sin cambio"
        nombre = str(ruta.relative_to(CARPETA))
        print(f"  {marca:<10} {nombre:<50} {kb(antes):>10} -> {kb(despues):>10}")

    print()
    print(f"Total: {kb(total_antes)} -> {kb(total_despues)}  "
          f"(ahorro {kb(total_antes - total_despues)})")
    if probar:
        print("Fue una prueba: no se modificó ningún archivo.")
    else:
        print(f"Originales guardados en {BACKUP}/")


if __name__ == "__main__":
    main()
