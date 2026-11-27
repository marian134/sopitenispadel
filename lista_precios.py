"""Lista de precios en Excel para mandar a clientes (se descarga desde el panel).

Solo usa datos públicos: producto, marca, precio de lista, precio por
transferencia y link. Nunca costos ni márgenes.
"""
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.table import Table, TableStyleInfo

ARIAL = "Arial"
NAVY = "060D1C"
NARANJA = "E57E3C"
GRIS = "555555"

ORDEN_DEPORTE = {"Pádel": 0, "Tenis": 1}
ORDEN_CATEGORIA = ["Paletas", "Raquetas", "Pelotas", "Overgrips", "Grips", "Protectores", "Accesorios",
                   "Accesorios Textil", "Indumentaria Hombre", "Indumentaria Mujer", "Calzado"]


def _orden(p):
    cat = p.categoria or ""
    return (ORDEN_DEPORTE.get(p.deporte, 9),
            ORDEN_CATEGORIA.index(cat) if cat in ORDEN_CATEGORIA else 99,
            (p.marca or "").lower(), (p.nombre or "").lower())


def armar_excel(productos, *, precio_transferencia, url_producto, hoy, negocio, envio_gratis_desde,
                aviso_promo=None):
    """Devuelve el Excel (BytesIO) con la lista de precios.

    precio_transferencia(p) -> precio pagando por transferencia (o None si no tiene descuento)
    url_producto(p) -> link absoluto a la página del producto
    aviso_promo -> texto opcional de una promo vigente (ej. Black Friday)
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Lista de precios"
    borde = Border(bottom=Side(style="thin", color="D9DEE7"))

    ws["A1"] = f"{negocio.get('nombre', 'SOPI Sports')} · Lista de precios"
    ws["A1"].font = Font(name=ARIAL, size=16, bold=True, color=NAVY)
    ws["A2"] = (f"Actualizada al {hoy:%d/%m/%Y}. Precios en pesos argentinos, sujetos a cambio y a "
                f"disponibilidad de stock. Envíos a todo el país · gratis desde "
                f"${envio_gratis_desde:,.0f}.".replace(",", "."))
    ws["A3"] = (f"WhatsApp {negocio.get('whatsapp_texto', '')} · {negocio.get('email', '')} · "
                "sopitenispadel.com.ar")
    for c in ("A2", "A3"):
        ws[c].font = Font(name=ARIAL, size=10, color=GRIS)
    ws["A5"] = "Pagando por transferencia: 5% de descuento (no aplica a los packs, que ya traen el suyo)."
    ws["A5"].font = Font(name=ARIAL, size=10, bold=True, color=NAVY)
    if aviso_promo:
        ws["A6"] = aviso_promo
        ws["A6"].font = Font(name=ARIAL, size=10, bold=True, color=NARANJA)

    encabezados = ["Deporte", "Categoría", "Marca", "Producto", "Precio", "Precio por transferencia",
                   "Ver en la tienda"]
    fila0 = 8
    for i, titulo in enumerate(encabezados, start=1):
        c = ws.cell(row=fila0, column=i, value=titulo)
        c.font = Font(name=ARIAL, size=10, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=NAVY)
        c.alignment = Alignment(vertical="center", wrap_text=True)

    r = fila0
    for p in sorted(productos, key=_orden):
        r += 1
        transf = precio_transferencia(p) or p.precio
        valores = [p.deporte, p.categoria, p.marca, p.nombre, p.precio, transf]
        for col, v in enumerate(valores, start=1):
            c = ws.cell(row=r, column=col, value=v)
            c.font = Font(name=ARIAL, size=10, bold=(col == 5))
            c.border = borde
            if col in (5, 6):
                c.number_format = '"$"#,##0'
        link = ws.cell(row=r, column=7, value="Ver producto")
        link.hyperlink = url_producto(p)
        link.font = Font(name=ARIAL, size=10, color="1155CC", underline="single")
        link.border = borde
    ultima = max(r, fila0 + 1)

    tabla = Table(displayName="ListaPrecios", ref=f"A{fila0}:G{ultima}")
    tabla.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=True)
    ws.add_table(tabla)
    ws.cell(row=ultima + 2, column=1,
            value="Consultá precios por cantidad para clubes y profes.").font = Font(
        name=ARIAL, size=9, italic=True, color=GRIS)

    for col, ancho in zip("ABCDEFG", (10, 20, 16, 52, 14, 16, 16)):
        ws.column_dimensions[col].width = ancho
    ws.row_dimensions[fila0].height = 30
    ws.freeze_panes = f"A{fila0 + 1}"
    ws.sheet_view.showGridLines = False
    ws.print_title_rows = f"{fila0}:{fila0}"
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    salida = io.BytesIO()
    wb.save(salida)
    salida.seek(0)
    return salida
