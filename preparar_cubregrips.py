"""
Arma el CSV de cubregrips y las fotos a partir de UNA sola descarga del portal.

Necesita en la carpeta (por defecto ~/Downloads):
  - cubregrips_productos.json (el mas reciente)  -> lo baja el script de consola
  - las fotos 01_MARCA.webp, 02_MARCA.jpg, ...    -> las baja el mismo script
Las dos cosas tienen que ser de la MISMA corrida del script de consola.

Uso (desde la raiz del proyecto, en Git Bash):
    pip install pillow
    py preparar_cubregrips.py              # busca en ~/Downloads
    py preparar_cubregrips.py RUTA_CARPETA # o en otra carpeta
Genera cubregrips_padel.csv y deja las fotos en static/img/.
Despues:
    py procesar_imagenes.py cubregrips_padel.csv
"""
import csv, json, re, sys, unicodedata
from pathlib import Path
from PIL import Image

DESTINO = Path("static/img")
EXTS = {".webp", ".jpg", ".jpeg", ".png"}
MARGEN = 0.40                      # precio = costo + 40%
EXCLUIR_MARCAS = {"HEAD"}          # Head ya lo tenes por tu cuenta con Head
EXCLUIR_NOMBRES = {                # ya cargados en la tienda
    "madma blister x3 liso",
    "odpro caramelera competition lisos x60 blancos",
}
MARCAS = {"WINAR": "Winar", "NORDIC": "Nordic", "ODPRO": "Odpro", "X-TRUST": "X-Trust",
          "IDENTITY": "Identity", "PRO GO": "Pro Go", "MADMA": "Madma", "ADIDAS": "Adidas",
          "WILSON": "Wilson", "SNAUWAERT": "Snauwaert", "AMA SPORT": "Ama Sport",
          "ENEBE": "Enebe", "CARROT": "Carrot", "SOFTEE": "Softee", "EZ LIFE": "EZ Life",
          "VIBOR-A": "Vibor-A", "NEXUS": "Nexus", "FELINA": "Felina", "LOK": "LOK",
          "NOX": "Nox", "DROP SHOT": "Drop Shot", "HEAD": "Head"}


def slug(s):
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def token(s):  # igual que 'limpiar' del script de consola, en mayusculas
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").upper()[:50]


def num(s):
    s = s.replace("$", "").strip()
    return int(s.replace(".", "")) if s and s != "0" else 0


def main(carpeta):
    carpeta = Path(carpeta).expanduser()
    if not carpeta.is_dir():
        sys.exit(f"No existe la carpeta: {carpeta}")
    jsons = sorted(carpeta.glob("cubregrips_productos*.json"), key=lambda p: p.stat().st_mtime)
    if not jsons:
        sys.exit(f"No encontre cubregrips_productos.json en {carpeta}")
    productos = json.load(open(jsons[-1], encoding="utf-8"))["productos"]
    print(f"JSON: {jsons[-1].name} | productos: {len(productos)}")

    # fotos por numero de orden (si hay repetidas, la mas nueva)
    fotos = {}
    for ruta in sorted(carpeta.iterdir(), key=lambda p: p.stat().st_mtime):
        m = re.match(r"(\d+)_(.+)$", ruta.stem)
        if m and ruta.suffix.lower() in EXTS:
            marca = re.sub(r"\s*\(\d+\)$", "", m.group(2))
            fotos.setdefault(int(m.group(1)), {})[marca] = ruta

    DESTINO.mkdir(parents=True, exist_ok=True)
    filas, excl, sin_foto, usados = [], [], [], set()
    for p in productos:
        partes = [x.strip() for x in p["texto"].split("|")]
        marca, prod, disp = partes[0], partes[1], partes[7]
        costo = num(partes[4])
        nombre = f"{MARCAS.get(marca, marca.title())} {prod}"
        motivo = None
        if costo == 0: motivo = "precio $0 en el portal"
        elif disp.startswith("No Disponible"): motivo = "no disponible"
        elif marca in EXCLUIR_MARCAS: motivo = "marca excluida"
        elif nombre.lower() in EXCLUIR_NOMBRES: motivo = "ya esta en la tienda"
        elif nombre.lower() in usados: motivo = "nombre repetido"
        if motivo:
            excl.append((nombre, motivo)); continue
        usados.add(nombre.lower())

        categoria = "Grips" if re.search(r"hesacore|hesagrip|grip padel performance", prod, re.I) else "Overgrips"
        precio = int(round(costo * (1 + MARGEN) / 100.0)) * 100
        stock = 3 if disp.startswith("Pocas") else (5 if costo >= 100000 else 10)

        imagen = ""
        ruta = fotos.get(p["orden"], {}).get(token(marca))
        if ruta:
            imagen = slug(nombre) + ".jpg"
            img = Image.open(ruta).convert("RGBA")
            fondo = Image.new("RGBA", img.size, (255, 255, 255, 255))
            fondo.alpha_composite(img)
            fondo.convert("RGB").save(DESTINO / imagen, "JPEG", quality=90, optimize=True)
        else:
            sin_foto.append(nombre)
        filas.append([nombre, MARCAS.get(marca, marca.title()), "Pádel", categoria, costo, precio, stock, imagen])

    with open("cubregrips_padel.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["nombre", "marca", "deporte", "categoria", "costo", "precio", "stock", "imagen"])
        w.writerows(filas)

    print(f"CSV: {len(filas)} productos | con foto: {len(filas) - len(sin_foto)}")
    for n in sin_foto: print("  Sin foto:", n)
    print(f"Excluidos: {len(excl)}")
    for n, m in excl: print(f"  {n} -> {m}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "~/Downloads")
