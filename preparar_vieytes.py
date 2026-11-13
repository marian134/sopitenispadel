"""
Arma el CSV de indumentaria Head (portal Grupo Vieytes) y baja las fotos.

Lee vieytes_hombre.json (lo baja el script de consola del navegador).

Uso (desde la raiz del proyecto, en Git Bash):
    pip install pillow
    py preparar_vieytes.py                   # busca el JSON mas reciente en ~/Downloads
    py preparar_vieytes.py RUTA_AL_JSON      # o un JSON puntual
    py preparar_vieytes.py --sin-fotos       # solo arma el CSV (para revisar nombres)
Genera indumentaria_vieytes.csv y deja las fotos en static/img/ (minuscula, .jpg).
Despues se carga el CSV en /admin/precios y las fotos se suben con git.
"""
import csv, json, re, sys, unicodedata, urllib.request
from pathlib import Path

DESTINO = Path("static/img")
SALIDA = "indumentaria_vieytes.csv"

MARCA = "Head"
DEPORTE = "Tenis"
STOCK = 5                 # stock fijo por producto, como en los demas Head
FACTOR_LISTA = 1.9        # precio de venta = precio de lista (tachado) x 1.9, redondeado a $10
INCLUIR_MUJER = False     # True para sumar tambien los productos "W ..." (Indumentaria Mujer)

# Ya cargados en la tienda: se saltean (ni CSV ni foto).
YA_CARGADOS = {"1021630", "1021660", "721922", "721868", "1021607", "1021611"}

# ---- traduccion ----
TIPOS = [  # (regex sobre el nombre en mayusculas, tipo, con_cierre)
    (r"\bTANK TOP\b", "Musculosa", False),
    (r"\bDRESS\b", "Vestido", False),
    (r"\bSKORT\b", "Pollera short", False),
    (r"\bTIGHTS?\b", "Calza", False),
    (r"\bHOODIE FZ\b", "Buzo", True),
    (r"\bHOODIE\b", "Buzo", False),
    (r"\bPOLO SHIRT\b", "Polo", False),
    (r"\bSHORTS?\b", "Short", False),
    (r"\bT-SHIRT\b", "Remera", False),
]

COLORES = [  # de mas largo a mas corto; se busca al final del nombre
    ("GREY / MELANGE", "gris"), ("GREY MELANGE", "gris"), ("GREY / MEL", "gris"), ("GREY/MEL", "gris"),
    ("DARK GREY", "gris oscuro"), ("WILLOW GREY", "gris verdoso"), ("GREY/ME", "gris"), ("ROYAL BLUE", "azul"),
    ("RED/WHITE", "rojo y blanco"), ("WHITE/BLACK", "blanco y negro"), ("NAVY/WHITE", "azul marino y blanco"),
    ("WHITE / NAV", "blanco y azul marino"), ("GRAPE FRUIT", "coral"), ("SPACY GREEN", "verde"),
    ("ALIGHT LILAC", "lila"), ("LIGHTLIME", "lima"), ("CYCLAM", "ciclamen"),
    ("BLACK", "negro"), ("WHITE", "blanco"), ("ROYAL", "azul"), ("NAVY", "azul marino"),
    ("RED", "rojo"), ("ORANGE", "naranja"), ("GREY", "gris"), ("GREEN", "verde"),
    ("BK", "negro"), ("WH", "blanco"),
]


def slug(s):
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def traducir(nombre):
    """Devuelve (nombre_es, categoria, color_dudoso)."""
    n = re.sub(r"\s+", " ", nombre.upper()).strip()
    mujer = n.startswith("W ")
    if mujer:
        n = n[2:]
    n = re.sub(r"\s*\([A-Z]{1,3}\)\s*$", "", n)          # codigos tipo (IG), (GI), (ZI)
    tipo, cierre = None, False
    for rx, t, fz in TIPOS:
        if re.search(rx, n):
            tipo, cierre = t, fz
            n = re.sub(rx, " ", n, count=1)
            break
    n = re.sub(r"\bMEN\b", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    color, dudoso = None, False
    for crudo, es in COLORES:
        if n.endswith(" " + crudo) or n == crudo:
            color = es
            n = n[: len(n) - len(crudo)].strip()
            break
    if color is None:                                    # ultimo token = codigo sin traduccion
        partes = n.rsplit(" ", 1)
        color, dudoso = (partes[1], True) if len(partes) == 2 else ("", True)
        n = partes[0]
    modelo = " ".join(w.capitalize() for w in n.split())
    modelo = re.sub(r"\bIi\b", "II", modelo)
    partes = [tipo or "Prenda", MARCA, modelo]
    if cierre:
        partes.append("con cierre")
    partes.append("Mujer" if mujer else "Hombre")
    nombre_es = " ".join(p for p in partes if p) + (f" ({color})" if color else "")
    return nombre_es, ("Indumentaria Mujer" if mujer else "Indumentaria Hombre"), dudoso


def bajar_foto(url, destino):
    from PIL import Image
    import io
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    datos = urllib.request.urlopen(req, timeout=30).read()
    img = Image.open(io.BytesIO(datos)).convert("RGBA")
    fondo = Image.new("RGBA", img.size, (255, 255, 255, 255))
    fondo.alpha_composite(img)
    fondo.convert("RGB").save(destino, "JPEG", quality=90, optimize=True)


def main(ruta_json, con_fotos):
    productos = json.load(open(ruta_json, encoding="utf-8"))["productos"]
    print(f"JSON: {ruta_json.name} | productos: {len(productos)}")

    filas, vistos, dudosos, fallidas = [], set(), [], []
    DESTINO.mkdir(parents=True, exist_ok=True)
    for p in productos:
        if p["id"] in YA_CARGADOS:
            continue
        nombre, categoria, dudoso = traducir(p["nombre"])
        if categoria == "Indumentaria Mujer" and not INCLUIR_MUJER:
            continue
        if nombre in vistos:
            nombre += f" {p['id']}"
        vistos.add(nombre)
        if dudoso:
            dudosos.append((p["nombre"], nombre))
        costo = int(p["precio"])
        base = p["precio_lista"] or costo * 1.4
        precio = int(round(base * FACTOR_LISTA / 10.0)) * 10
        imagen = slug(nombre) + ".jpg"
        if con_fotos and p.get("imagen"):
            try:
                bajar_foto(p["imagen"], DESTINO / imagen)
            except Exception as e:
                fallidas.append((nombre, str(e)[:60]))
        filas.append([nombre, MARCA, DEPORTE, categoria, costo, precio, STOCK, imagen])

    with open(SALIDA, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(["nombre", "marca", "deporte", "categoria", "costo", "precio", "stock", "imagen"])
        w.writerows(filas)

    print(f"CSV: {SALIDA} | filas: {len(filas)}")
    if con_fotos:
        print(f"Fotos listas: {len(filas) - len(fallidas)} de {len(filas)} (en {DESTINO}/)")
    for n, e in fallidas:
        print(f"  Sin foto: {n} -> {e}")
    if dudosos:
        print("REVISAR el color (el portal lo trae como codigo, edita el CSV):")
        for crudo, es in dudosos:
            print(f"  {crudo}  ->  {es}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        ruta = Path(args[0]).expanduser()
    else:
        jsons = sorted((Path.home() / "Downloads").glob("vieytes_hombre*.json"), key=lambda p: p.stat().st_mtime)
        if not jsons:
            sys.exit("No encontre vieytes_hombre.json en ~/Downloads (pasa la ruta como argumento)")
        ruta = jsons[-1]
    main(ruta, "--sin-fotos" not in sys.argv)
