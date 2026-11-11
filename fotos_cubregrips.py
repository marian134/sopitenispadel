"""
Prepara las fotos de cubregrips con los nombres de la columna 'imagen' del CSV.

Las fotos deben llamarse como las baja el script de consola con
DESCARGAR_FOTOS = true: empiezan con el numero de orden del portal
(ej: 06_NORDIC.webp, 23_PRO_GO.jpg). Se emparejan por ese numero con la
columna 'orden' del CSV y se guardan como .jpg en static/img/.

Uso (desde la raiz del proyecto, en Git Bash):
    pip install pillow
    py fotos_cubregrips.py cubregrips_padel.csv RUTA_CARPETA_FOTOS
Despues:
    py procesar_imagenes.py cubregrips_padel.csv
"""
import csv, re, sys
from pathlib import Path
from PIL import Image

DESTINO = Path("static/img")
EXTS = {".webp", ".jpg", ".jpeg", ".png"}


def main(csv_path, carpeta):
    carpeta = Path(carpeta).expanduser()
    if not carpeta.is_dir():
        sys.exit(f"No existe la carpeta: {carpeta}")
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        por_orden = {int(r["orden"]): r for r in csv.DictReader(f, delimiter=";")}

    DESTINO.mkdir(parents=True, exist_ok=True)
    hechas = set()
    for ruta in sorted(carpeta.iterdir()):
        m = re.match(r"(\d+)_", ruta.stem)
        if not m or ruta.suffix.lower() not in EXTS or int(m.group(1)) not in por_orden:
            continue
        orden = int(m.group(1))
        if orden in hechas:
            continue
        img = Image.open(ruta).convert("RGBA")
        fondo = Image.new("RGBA", img.size, (255, 255, 255, 255))
        fondo.alpha_composite(img)
        fondo.convert("RGB").save(DESTINO / por_orden[orden]["imagen"], "JPEG", quality=90, optimize=True)
        hechas.add(orden)

    print(f"Listas: {len(hechas)} de {len(por_orden)}")
    for o in sorted(set(por_orden) - hechas):
        print(f"  Sin foto: {por_orden[o]['nombre']} (orden {o})")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
