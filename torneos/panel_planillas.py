"""Excel: bajar el torneo (inscriptos, zonas, cuadros, partidos) y cargar
jugadores desde una planilla (cambio 30)."""
import re
import unicodedata
from datetime import datetime

from flask import Response, redirect, request, url_for

from models import db
from . import cuadro as cdr
from . import planilla
from . import zonas as zns
from .bp import bp
from .models import Categoria, Inscripcion, Partido, PAGO_CONFIRMADO, PAGO_PENDIENTE, EST_CANCELADA, EST_FINALIZADA
from .panel import _mi_competencia
from .util import organizador_requerido, slug_unico  # noqa: F401

ESTADOS = {"pendiente": "Pago a revisar", "confirmado": "Pago confirmado", "rechazado": "Pago rechazado"}
TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _nombre(insc):
    if not insc:
        return ""
    return insc.jugador1.nombre_completo + (f" / {insc.jugador2.nombre_completo}" if insc.jugador2 else "")


def _resultado(p):
    if p.estado == "wo":
        return "W.O."
    if p.estado == "anulado":
        return "No jugado"
    if p.estado == "bye":
        return "Pase libre"
    res = [r for r in p.resultados if r.confirmado and not r.ausente_id]
    return res[-1].sets if res else ""


def _descarga(datos, nombre):
    return Response(datos, mimetype=TIPO_XLSX,
                    headers={"Content-Disposition": f"attachment; filename={nombre}.xlsx"})


@bp.route("/panel/<int:comp_id>/excel")
@organizador_requerido
def competencia_excel(comp_id):
    comp = _mi_competencia(comp_id)
    cats = sorted(comp.categorias, key=lambda c: c.orden)
    hojas = []

    filas = [["Categoría", "Jugador", "DNI", "Celular", "Mail", "Compañero/a", "DNI compañero/a",
              "Estado", "Cabeza de serie", "Zona", "Fecha de inscripción"]]
    for cat in cats:
        for i in sorted(cat.inscripciones, key=lambda i: i.creado_en):
            filas.append([cat.nombre, i.jugador1.nombre_completo, i.jugador1.dni, i.jugador1.celular or "",
                          i.jugador1.email or "", i.jugador2.nombre_completo if i.jugador2 else "",
                          i.jugador2.dni if i.jugador2 else "",
                          "De baja" if i.baja else ESTADOS.get(i.estado_pago, i.estado_pago),
                          i.siembra or "", i.zona or "", i.creado_en.strftime("%d/%m/%Y %H:%M")])
    hojas.append(("Inscriptos", filas))

    if zns.activas(comp):
        filas, negritas = [], []
        for cat in cats:
            for z in zns.estructura(cat):
                negritas.append(len(filas))
                filas.append([f"{cat.nombre} · Zona {z['numero']}", "PJ", "PG", "PP", "Sets", "Games", "Bonus", "Puntos"])
                for f in z["tabla"]:
                    filas.append([f"{f['posicion']}. {_nombre(f['insc'])}", f["pj"], f["pg"], f["pp"],
                                  f"{f['sets_g']}-{f['sets_p']}" if "sets_g" in f else f.get("dif_sets", ""),
                                  f"{f['games_g']}-{f['games_p']}" if "games_g" in f else f.get("dif_games", ""),
                                  f["bonus"], f["total"]])
                for fecha, lista in z["fechas"]:
                    for p in lista:
                        filas.append([f"Fecha {fecha}", _nombre(p.lado_a), "vs", _nombre(p.lado_b), _resultado(p) or "por jugar"])
                filas.append([])
        hojas.append(("Zonas", filas, negritas))

    if comp.tipo == "cuadro":
        nombres = cdr.nombres_cuadros(comp)
        filas = [["Categoría", "Cuadro", "Ronda", "Jugador", "Jugador", "Resultado", "Ganador", "Día y hora", "Cancha"]]
        etiquetas = {cdr.PRINCIPAL: nombres[cdr.PRINCIPAL], cdr.PLATA: nombres[cdr.PLATA],
                     cdr.CONSUELO: "Consuelo", cdr.TERCER: "Tercer puesto"}
        for cat in cats:
            for cuadro in (cdr.PRINCIPAL, cdr.TERCER, cdr.PLATA, cdr.CONSUELO):
                for p in sorted(cdr.partidos(cat, cuadro), key=lambda p: (int(p.ronda), p.posicion)):
                    ganador = p.lado_a if p.ganador_id == p.lado_a_id else (p.lado_b if p.ganador_id else None)
                    filas.append([cat.nombre, etiquetas[cuadro], cdr.nombre_ronda(cat, cuadro, p.ronda, p),
                                  _nombre(p.lado_a) or "—", _nombre(p.lado_b) or "—", _resultado(p),
                                  _nombre(ganador) if ganador else "",
                                  p.fecha_hora.strftime("%d/%m/%Y %H:%M") if p.fecha_hora else "", p.cancha or ""])
        if len(filas) > 1:
            hojas.append(("Cuadro", filas))
    else:
        filas = [["Categoría", "Fecha" if comp.tipo == "liga" else "Semana", "Jugador", "Jugador", "Resultado", "Estado",
                  "Día y hora", "Cancha"]]
        for p in Partido.query.filter_by(competencia_id=comp.id).order_by(Partido.semana, Partido.id):
            if not p.lado_a or not p.lado_b:
                continue
            filas.append([p.lado_a.categoria.nombre, p.semana or "", _nombre(p.lado_a), _nombre(p.lado_b), _resultado(p),
                          p.estado, p.fecha_hora.strftime("%d/%m/%Y %H:%M") if p.fecha_hora else "", p.cancha or ""])
        hojas.append(("Partidos", filas))
        if comp.tipo == "liga":
            from . import liga
            hojas.append(("Tabla", [["#", "Jugador", "Puntos", "PJ"]] + [
                [k, _nombre(f["insc"]), f["puntos"], f["pj"]] for k, f in enumerate(liga.tabla(comp), start=1)]))
    return _descarga(planilla.escribir(hojas), comp.slug)


@bp.route("/panel/planilla-modelo")
@organizador_requerido
def planilla_modelo():
    dobles = request.args.get("dobles") == "1"
    encabezado = ["Nombre", "Apellido", "DNI", "Celular", "Mail", "Pagó"]
    ejemplo = ["Juan", "Pérez", "30111222", "11 2345-6789", "juan@mail.com", "sí"]
    if dobles:
        encabezado += ["Nombre 2", "Apellido 2", "DNI 2", "Celular 2", "Mail 2"]
        ejemplo += ["Ana", "Gómez", "31222333", "11 3456-7890", ""]
    return _descarga(planilla.escribir([("Jugadores", [encabezado, ejemplo])]),
                     "modelo-jugadores-dobles" if dobles else "modelo-jugadores")


def _normal(texto):
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


def _columna(encabezado):
    """Qué dato es cada columna, por su título."""
    h = _normal(encabezado)
    segundo = bool(re.search(r"(\b2\b|compan|pareja)", h))
    sufijo = "2" if segundo else ""
    if "dni" in h or "documento" in h:
        return "dni" + sufijo
    if "nombre y apellido" in h or "apellido y nombre" in h or h in ("jugador", "jugadora", "jugador 2", "pareja"):
        return ("completo_ap" if h.startswith("apellido y") else "completo") + sufijo
    if "apellido" in h:
        return "apellido" + sufijo
    if "nombre" in h:
        return "nombre" + sufijo
    if any(x in h for x in ("cel", "tel", "whats", "movil")):
        return "celular" + sufijo
    if "mail" in h or "correo" in h:
        return "email" + sufijo
    if h.startswith("pag") or "pago" in h:
        return "pagado"
    if "serie" in h or "siembra" in h or "cabeza" in h:
        return "siembra"
    return None


def _persona(datos, sufijo):
    nombre, apellido = datos.get("nombre" + sufijo, ""), datos.get("apellido" + sufijo, "")
    completo = datos.get("completo" + sufijo) or ""
    if completo and not (nombre and apellido):
        partes = completo.split()
        nombre, apellido = (" ".join(partes[:1]), " ".join(partes[1:])) if len(partes) > 1 else (completo, "")
    completo_ap = datos.get("completo_ap" + sufijo) or ""
    if completo_ap and not (nombre and apellido):
        partes = completo_ap.split()
        apellido, nombre = (partes[0], " ".join(partes[1:])) if len(partes) > 1 else (completo_ap, "")
    return {"dni": re.sub(r"\D", "", datos.get("dni" + sufijo, ""))[:12], "nombre": nombre.strip().title()[:80],
            "apellido": apellido.strip().title()[:80], "celular": datos.get("celular" + sufijo, "").strip()[:40],
            "email": datos.get("email" + sufijo, "").strip().lower()[:120]}


@bp.route("/panel/<int:comp_id>/categoria/<int:cat_id>/importar", methods=["POST"])
@organizador_requerido
def inscripcion_importar(comp_id, cat_id):
    from .publico import _buscar_o_crear_jugador, _validar_persona, lugares_libres
    comp = _mi_competencia(comp_id)
    cat = db.session.get(Categoria, cat_id)
    if not cat or cat.competencia_id != comp.id or comp.estado in (EST_FINALIZADA, EST_CANCELADA):
        return redirect(url_for("torneos.competencia_panel", comp_id=comp.id))

    def volver(texto, error=False):
        clave = "error" if error else "aviso_pago"
        return redirect(url_for("torneos.competencia_panel", comp_id=comp.id, **{clave: texto}) + f"#cat-{cat.id}")

    archivo = request.files.get("planilla")
    if not archivo or not archivo.filename:
        return volver("Elegí la planilla (Excel o CSV) para cargar.", True)
    try:
        filas = planilla.leer(archivo.read(), archivo.filename)
    except (ValueError, KeyError, StopIteration):
        return volver("No pude leer la planilla. Guardala como Excel (.xlsx) o CSV y probá de nuevo.", True)
    inicio = next((k for k, f in enumerate(filas[:20]) if any(_columna(c) and _columna(c).startswith("dni") for c in f)), None)
    if inicio is None:
        return volver("La planilla tiene que tener una fila de títulos con al menos DNI, Nombre y Apellido. Bajá la planilla modelo.", True)
    columnas = [_columna(c) for c in filas[inicio]]
    pagado_todos = bool(request.form.get("pagado"))
    agregados, errores = 0, []
    for numero, fila in enumerate(filas[inicio + 1:], start=inicio + 2):
        if not any(c.strip() for c in fila):
            continue
        datos = {col: (fila[k] if k < len(fila) else "") for k, col in enumerate(columnas) if col}
        p1 = _persona(datos, "")
        p2 = _persona(datos, "2") if cat.modalidad == "dobles" else None
        error = _validar_persona(p1, "")
        if not error and p2:
            error = _validar_persona(p2, "del compañero/a")
        if not error and lugares_libres(cat) == 0:
            error = f"la categoría llegó al cupo ({cat.cupo})"
        if not error:
            j1 = _buscar_o_crear_jugador(**p1)
            j2 = _buscar_o_crear_jugador(**p2) if p2 else None
            ids = {j1.id, j2.id if j2 else -1}
            if any(not i.baja and {i.jugador1_id, i.jugador2_id} & ids for i in cat.inscripciones):
                error = "ya estaba anotado"
        if error:
            errores.append(f"fila {numero}: {error.rstrip('.')}")
            continue
        pago = _normal(datos.get("pagado", ""))
        pagado = pagado_todos or not comp.precio or pago in ("si", "s", "x", "1", "pago", "pagado", "ok")
        siembra = datos.get("siembra", "")
        db.session.add(Inscripcion(categoria_id=cat.id, jugador1_id=j1.id, jugador2_id=j2.id if j2 else None,
                                   estado_pago=PAGO_CONFIRMADO if pagado else PAGO_PENDIENTE,
                                   siembra=int(siembra) if siembra.isdigit() and int(siembra) > 0 else None))
        db.session.flush()
        db.session.refresh(cat)
        agregados += 1
    db.session.commit()
    texto = f"Cargamos {agregados} jugador{'es' if agregados != 1 else ''} en {cat.nombre} desde la planilla."
    if errores:
        texto += f" No se cargaron {len(errores)}: " + "; ".join(errores[:8]) + ("…" if len(errores) > 8 else "") + "."
    return volver(texto)
