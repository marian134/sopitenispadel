"""Planillas de Excel (.xlsx) sin librerías externas: escribir varias hojas y
leer la primera hoja de un archivo subido (también acepta .csv).

Un .xlsx es un zip con XML adentro; acá se arma lo mínimo que Excel, Google
Sheets y LibreOffice abren bien (texto y números, primera fila en negrita).
"""
import csv
import io
import re
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _col(n):
    letras = ""
    while n:
        n, r = divmod(n - 1, 26)
        letras = chr(65 + r) + letras
    return letras


def _nombre_hoja(nombre, usados):
    limpio = re.sub(r"[\[\]\*\?/\\:]", " ", nombre).strip()[:31] or "Hoja"
    base, k = limpio, 2
    while limpio.lower() in usados:
        limpio = f"{base[:28]} {k}"
        k += 1
    usados.add(limpio.lower())
    return limpio


def _celda(ref, valor, negrita):
    estilo = ' s="1"' if negrita else ""
    if valor is None or valor == "":
        return ""
    if isinstance(valor, bool):
        valor = "Sí" if valor else "No"
    if isinstance(valor, (int, float)):
        return f'<c r="{ref}"{estilo}><v>{valor}</v></c>'
    texto = escape(str(valor)).replace("\n", "&#10;")
    return f'<c r="{ref}" t="inlineStr"{estilo}><is><t xml:space="preserve">{texto}</t></is></c>'


def escribir(hojas):
    """hojas: [(nombre, filas, filas_en_negrita)] -> bytes del .xlsx.
    filas_en_negrita: índices de filas a resaltar (por defecto la primera)."""
    usados, nombres, xml_hojas = set(), [], []
    for hoja in hojas:
        nombre, filas = hoja[0], hoja[1]
        negritas = set(hoja[2]) if len(hoja) > 2 else {0}
        nombres.append(_nombre_hoja(nombre, usados))
        anchos = {}
        for fila in filas:
            for c, v in enumerate(fila, start=1):
                anchos[c] = min(60, max(anchos.get(c, 8), len(str(v if v is not None else "")) + 2))
        cols = "".join(f'<col min="{c}" max="{c}" width="{w}" customWidth="1"/>' for c, w in sorted(anchos.items()))
        filas_xml = []
        for r, fila in enumerate(filas, start=1):
            celdas = "".join(_celda(f"{_col(c)}{r}", v, (r - 1) in negritas) for c, v in enumerate(fila, start=1))
            filas_xml.append(f'<row r="{r}">{celdas}</row>')
        xml_hojas.append(
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<worksheet xmlns="{NS}">' + (f"<cols>{cols}</cols>" if cols else "")
            + f'<sheetData>{"".join(filas_xml)}</sheetData></worksheet>')
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{k}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for k in range(1, len(nombres) + 1))
                   + '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        z.writestr("xl/workbook.xml",
                   f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{NS}" xmlns:r="{NS_R}"><sheets>'
                   + "".join(f'<sheet name="{escape(n, {chr(34): "&quot;"})}" sheetId="{k}" r:id="rId{k}"/>'
                             for k, n in enumerate(nombres, start=1))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{k}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{k}.xml"/>'
                             for k in range(1, len(nombres) + 1))
                   + f'<Relationship Id="rId{len(nombres) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   '</Relationships>')
        z.writestr("xl/styles.xml",
                   f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="{NS}">'
                   '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
                   '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
                   '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                   '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
                   '</styleSheet>')
        for k, xml in enumerate(xml_hojas, start=1):
            z.writestr(f"xl/worksheets/sheet{k}.xml", xml)
    return salida.getvalue()


def _num_col(ref):
    letras = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letras:
        n = n * 26 + ord(ch) - 64
    return n


def leer(datos, nombre_archivo=""):
    """Devuelve las filas (listas de texto) de la primera hoja de un .xlsx, o de un .csv."""
    if nombre_archivo.lower().endswith(".csv") or not datos[:2] == b"PK":
        texto = datos.decode("utf-8-sig", errors="replace")
        try:
            dialecto = csv.Sniffer().sniff(texto[:2000], delimiters=",;\t")
        except csv.Error:
            dialecto = csv.excel
        return [[c.strip() for c in fila] for fila in csv.reader(io.StringIO(texto), dialecto)]
    try:
        z = zipfile.ZipFile(io.BytesIO(datos))
    except zipfile.BadZipFile:
        raise ValueError("El archivo no es una planilla de Excel (.xlsx) ni un .csv.")
    ns = {"m": NS, "r": NS_R}
    compartidos = []
    if "xl/sharedStrings.xml" in z.namelist():
        raiz = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in raiz.findall("m:si", ns):
            compartidos.append("".join(t.text or "" for t in si.iter(f"{{{NS}}}t")))
    libro = ET.fromstring(z.read("xl/workbook.xml"))
    primera = libro.find("m:sheets/m:sheet", ns)
    if primera is None:
        return []
    rid = primera.get(f"{{{NS_R}}}id")
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    destino = next(r.get("Target") for r in rels if r.get("Id") == rid)
    destino = destino.lstrip("/")
    ruta = destino if destino.startswith("xl/") else "xl/" + destino
    hoja = ET.fromstring(z.read(ruta))
    filas = []
    for fila in hoja.iter(f"{{{NS}}}row"):
        valores = {}
        for c in fila.findall("m:c", ns):
            tipo, v = c.get("t"), c.find("m:v", ns)
            if tipo == "s" and v is not None:
                texto = compartidos[int(v.text)]
            elif tipo == "inlineStr":
                texto = "".join(t.text or "" for t in c.iter(f"{{{NS}}}t"))
            else:
                texto = v.text if v is not None else ""
                if texto and re.fullmatch(r"-?\d+\.0+", texto):
                    texto = texto.split(".")[0]   # 30111222.0 -> 30111222
            valores[_num_col(c.get("r"))] = (texto or "").strip()
        if valores:
            filas.append([valores.get(k, "") for k in range(1, max(valores) + 1)])
    return filas
