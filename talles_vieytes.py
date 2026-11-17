"""
Arma talles_head.csv (nombre;talles) con el stock por talle de la indumentaria
Head del mayorista Grupo Vieytes, para cargarlo en /admin/precios.

Solo actualiza los talles (y el stock total, que pasa a ser la suma):
no toca precios, costos ni fotos.

Lee:
  vieytes_hombre.json   lista de productos del portal (mismo que usa preparar_vieytes.py)
  vieytes_talles.json   {id: {"S": 9, "M": 8, ...}} con el stock de cada talle,
                        sacado de la API del portal estando logueado

Para actualizar vieytes_talles.json: entrar logueado a mayorista.grupovieytes.com,
abrir cualquier ficha de producto, pegar esto en la consola (F12) y guardar lo que
descarga como vieytes_talles.json en la raiz del proyecto:

    const ids = (await (await fetch('URL_O_RUTA_DE_vieytes_hombre.json')).json())
      .productos.map(p => p.id);   // o pegá la lista de ids a mano: ["1021657", ...]
    const out = {};
    for (const id of ids) {
      const d = await $.ajax({url: API_URL + "/api/articulo?id=" + id, method: "POST",
                              headers: {auth: usuario ? usuario.id : null, e: ID_EMPRESA}});
      const st = {};
      (d.objeto?.stocks || []).forEach(s => {
        const t = (s.talle?.nombre || "UNICO").trim().toUpperCase();
        st[t] = (st[t] || 0) + (s.cantidad || 0);
      });
      out[id] = st;
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(out)]));
    a.download = "vieytes_talles.json"; a.click();

Uso (desde la raiz del proyecto):
    py talles_vieytes.py
Despues se sube talles_head.csv en /admin/precios.
"""
import csv
import json

from preparar_vieytes import INCLUIR_MUJER, YA_CARGADOS, traducir

SALIDA = "talles_head.csv"

# Productos que en la tienda se cargaron con otro nombre (id del portal -> nombre en la tienda)
NOMBRES_TIENDA = {
    "1021611": "Short Head Play Mujer (negro)",
    "721868": "Musculosa Head Club 22 Mujer (blanco)",
}


def texto_talles(stock):
    return " ".join(f"{t}:{c}" for t, c in stock.items())


def main():
    productos = json.load(open("vieytes_hombre.json", encoding="utf-8"))["productos"]
    talles = json.load(open("vieytes_talles.json", encoding="utf-8"))

    filas, vistos, sin_talles, salteados = [], set(), [], 0
    for p in productos:
        nombre, categoria, _ = traducir(p["nombre"])
        cargado_aparte = p["id"] in YA_CARGADOS
        if not cargado_aparte:
            # mismo criterio que preparar_vieytes.py, para que el nombre coincida
            if categoria == "Indumentaria Mujer" and not INCLUIR_MUJER:
                salteados += 1
                continue
            if nombre in vistos:
                nombre += f" {p['id']}"
            vistos.add(nombre)
        nombre = NOMBRES_TIENDA.get(p["id"], nombre)

        stock = talles.get(p["id"])
        if not stock:
            sin_talles.append(nombre)
            continue
        filas.append([nombre, texto_talles(stock)])

    with open(SALIDA, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(["nombre", "talles"])
        w.writerows(filas)

    print(f"CSV: {SALIDA} | prendas con talles: {len(filas)}")
    if salteados:
        print(f"Salteadas {salteados} prendas de mujer que no estan en la tienda (INCLUIR_MUJER = False)")
    for n in sin_talles:
        print(f"  Sin datos de talles: {n}")


if __name__ == "__main__":
    main()
