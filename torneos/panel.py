"""Panel del organizador: sus competencias, categorías e inscriptos."""
import os
from datetime import datetime

from flask import abort, redirect, render_template, request, send_from_directory, url_for

from models import db
from . import escalera as esc
from . import reglas as reglas_mod
from .bp import bp, contexto
from .models import (
    Categoria, Competencia, Inscripcion, Partido, Resultado,
    PAR_AGENDADO, PAR_ANULADO, PAR_DESAFIO, PAR_EN_DISPUTA, PAR_JUGADO, PAR_WO,
    EST_BORRADOR, EST_CANCELADA, EST_EN_CURSO, EST_INSCRIPCION,
    PAGO_CONFIRMADO, PAGO_PENDIENTE, PAGO_RECHAZADO, PLAN_GRATIS,
    TIPO_CUADRO, TIPO_ESCALERA,
)
from .util import (
    CARPETA_ARCHIVOS, link_whatsapp, organizador_actual, organizador_requerido, slug_unico,
)

FILAS_CATEGORIA_NUEVAS = 3


def _mi_competencia(comp_id):
    org = organizador_actual()
    comp = db.session.get(Competencia, comp_id)
    if not comp or comp.organizador_id != org.id:
        abort(404)
    return comp


def _puede_crear(org):
    """El plan gratis permite una sola competencia (sin contar canceladas)."""
    if org.plan != PLAN_GRATIS:
        return True
    usadas = Competencia.query.filter(
        Competencia.organizador_id == org.id, Competencia.estado != EST_CANCELADA
    ).count()
    return usadas == 0


def _fecha(valor):
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date() if valor else None
    except ValueError:
        return None


def _fecha_hora(valor):
    try:
        return datetime.strptime(valor, "%Y-%m-%dT%H:%M") if valor else None
    except ValueError:
        return None


@bp.route("/panel")
@organizador_requerido
def panel():
    org = organizador_actual()
    competencias = (
        Competencia.query.filter_by(organizador_id=org.id)
        .order_by(Competencia.creado_en.desc()).all()
    )
    return render_template(
        "torneos/panel.html",
        **contexto(
            org=org, competencias=competencias, puede_crear=_puede_crear(org),
            bienvenida=request.args.get("bienvenida"),
        ),
    )


def _guardar_competencia(comp, form):
    """Pasa el formulario a la competencia. Devuelve un error o None."""
    nombre = (form.get("nombre") or "").strip()[:150]
    if not nombre:
        return "Poné un nombre."
    if comp.id is None:
        tipo = form.get("tipo")
        if tipo not in (TIPO_CUADRO, TIPO_ESCALERA):
            return "Elegí si es un torneo con cuadro o una escalera."
        comp.tipo = tipo
        comp.reglas = reglas_mod.por_defecto(tipo)
    try:
        precio = int((form.get("precio") or "0").replace(".", "").replace("$", "").strip() or 0)
    except ValueError:
        return "El precio tiene que ser un número, sin centavos."
    inicio, fin = _fecha(form.get("fecha_inicio")), _fecha(form.get("fecha_fin"))
    if inicio and fin and fin < inicio:
        return "La fecha de fin es anterior a la de inicio."

    # Categorías: filas existentes (cat_id_N) y nuevas
    filas = []
    for clave in form:
        if not clave.startswith("cat_nombre_"):
            continue
        n = clave[len("cat_nombre_"):]
        cat_nombre = (form.get(clave) or "").strip()[:80]
        cupo_txt = (form.get(f"cat_cupo_{n}") or "").strip()
        if cupo_txt and not cupo_txt.isdigit():
            return f"El cupo de \"{cat_nombre or 'una categoría'}\" tiene que ser un número."
        filas.append({
            "id": form.get(f"cat_id_{n}") or None,
            "nombre": cat_nombre,
            "modalidad": "dobles" if form.get(f"cat_modalidad_{n}") == "dobles" else "singles",
            "cupo": int(cupo_txt) if cupo_txt else None,
            "orden": int(n) if n.isdigit() else 99,
        })
    if not any(f["nombre"] for f in filas):
        return "Agregá al menos una categoría."

    comp.nombre = nombre
    comp.deporte = "Tenis"
    comp.sede = (form.get("sede") or "").strip()[:150]
    comp.localidad = (form.get("localidad") or "").strip()[:100]
    comp.descripcion = (form.get("descripcion") or "").strip()[:3000]
    comp.fecha_inicio, comp.fecha_fin = inicio, fin
    comp.cierre_inscripcion = _fecha_hora(form.get("cierre_inscripcion"))
    comp.precio = max(0, precio)
    comp.incluye = (form.get("incluye") or "").strip()[:150]
    if comp.id is None:
        comp.slug = slug_unico(Competencia, nombre)
        db.session.add(comp)
        db.session.flush()

    existentes = {str(c.id): c for c in comp.categorias}
    for f in sorted(filas, key=lambda x: x["orden"]):
        cat = existentes.get(f["id"]) if f["id"] else None
        if cat and not f["nombre"]:
            # borrar solo si no tiene inscriptos
            if not cat.inscripciones:
                db.session.delete(cat)
            continue
        if not f["nombre"]:
            continue
        if not cat:
            cat = Categoria(competencia_id=comp.id)
            db.session.add(cat)
        cat.nombre, cat.modalidad, cat.cupo, cat.orden = f["nombre"], f["modalidad"], f["cupo"], f["orden"]
    return None


@bp.route("/panel/nueva", methods=["GET", "POST"])
@organizador_requerido
def competencia_nueva():
    org = organizador_actual()
    if not _puede_crear(org):
        return redirect(url_for("torneos.panel"))
    comp = Competencia(organizador_id=org.id, estado=EST_BORRADOR)
    error = None
    if request.method == "POST":
        error = _guardar_competencia(comp, request.form)
        if not error:
            db.session.commit()
            return redirect(url_for("torneos.competencia_panel", comp_id=comp.id))
        db.session.rollback()
        comp = Competencia(organizador_id=org.id, estado=EST_BORRADOR)
    return render_template(
        "torneos/competencia_form.html",
        **contexto(comp=comp, error=error, form=request.form, filas_nuevas=FILAS_CATEGORIA_NUEVAS + 2),
    )


@bp.route("/panel/<int:comp_id>/editar", methods=["GET", "POST"])
@organizador_requerido
def competencia_editar(comp_id):
    comp = _mi_competencia(comp_id)
    error = None
    if request.method == "POST":
        error = _guardar_competencia(comp, request.form)
        if not error:
            db.session.commit()
            return redirect(url_for("torneos.competencia_panel", comp_id=comp.id))
        db.session.rollback()
    return render_template(
        "torneos/competencia_form.html",
        **contexto(comp=comp, error=error, form=request.form if error else None,
                   filas_nuevas=FILAS_CATEGORIA_NUEVAS),
    )


@bp.route("/panel/<int:comp_id>/estado", methods=["POST"])
@organizador_requerido
def competencia_estado(comp_id):
    """Abrir inscripción, cerrarla (empieza el juego), volver a borrador o cancelar."""
    comp = _mi_competencia(comp_id)
    accion = request.form.get("accion")
    if accion == "abrir" and comp.estado == EST_BORRADOR and comp.categorias:
        comp.estado = EST_INSCRIPCION
    elif accion == "cerrar" and comp.estado == EST_INSCRIPCION:
        comp.estado = EST_EN_CURSO
    elif accion == "borrador" and comp.estado == EST_INSCRIPCION and not _hay_inscriptos(comp):
        comp.estado = EST_BORRADOR
    elif accion == "cancelar" and comp.estado in (EST_BORRADOR, EST_INSCRIPCION):
        comp.estado = EST_CANCELADA
    db.session.commit()
    return redirect(url_for("torneos.competencia_panel", comp_id=comp.id))


def _hay_inscriptos(comp):
    return any(not i.baja for c in comp.categorias for i in c.inscripciones)


@bp.route("/panel/<int:comp_id>")
@organizador_requerido
def competencia_panel(comp_id):
    comp = _mi_competencia(comp_id)
    esc.procesar(comp)
    url_publica = url_for("torneos.torneo", slug=comp.slug, _external=True)
    categorias = []
    for cat in sorted(comp.categorias, key=lambda c: c.orden):
        inscriptos = sorted(cat.inscripciones, key=lambda i: (i.baja, i.creado_en))
        filas = []
        for i in inscriptos:
            enlace = url_for("torneos.jugador", enlace=i.jugador1.enlace, _external=True)
            texto = (
                f"Hola {i.jugador1.nombre}! Confirmamos tu inscripción en {comp.nombre} "
                f"({cat.nombre}). Desde este enlace seguís todo: {enlace}"
            )
            filas.append({"i": i, "wa": link_whatsapp(i.jugador1.celular, texto)})
        activos = [i for i in inscriptos if not i.baja]
        categorias.append({
            "cat": cat, "filas": filas, "activos": len(activos),
            "confirmados": sum(1 for i in activos if i.estado_pago == PAGO_CONFIRMADO),
        })
    escalera = _datos_escalera(comp) if comp.tipo == TIPO_ESCALERA else None
    from .panel_cuadro import datos_cuadro
    cuadro = datos_cuadro(comp) if comp.tipo == TIPO_CUADRO else None
    return render_template(
        "torneos/competencia_panel.html",
        **contexto(
            comp=comp, categorias=categorias, url_publica=url_publica,
            niveles=comp.reglas.get("niveles_iniciales", []),
            divisiones=esc.nombres_divisiones(comp), escalera=escalera, cuadro=cuadro,
            error=request.args.get("error"),
        ),
    )


def _datos_escalera(comp):
    semana = esc.semana_actual(comp)
    datos = {
        "semana": semana, "total": esc.total_semanas(comp), "en_juego": esc.en_juego(comp),
        "especial": esc.especial(comp, semana)[1] if semana else None,
        "cerrada": comp.reglas.get("semana_cerrada") or 0,
    }
    partidos = Partido.query.filter_by(competencia_id=comp.id).order_by(Partido.creado_en.desc()).all()
    datos["disputas"] = [p for p in partidos if p.estado == PAR_EN_DISPUTA]
    datos["agendados"] = [p for p in partidos if p.estado in (PAR_AGENDADO, PAR_DESAFIO)]
    datos["jugados"] = [p for p in partidos if p.estado in (PAR_JUGADO, PAR_WO)][:20]
    datos["rankings"] = [
        (cat, esc.ranking(cat, semana or 1)) for cat in sorted(comp.categorias, key=lambda c: c.orden)
    ]
    cambio = esc.semana_cambio_pendiente(comp)
    datos["cambio_semana"] = cambio
    datos["propuesta"] = (
        [(cat, esc.propuesta_divisiones(cat, cambio)) for cat in comp.categorias] if cambio else []
    )
    return datos


@bp.route("/panel/partido/<int:partido_id>", methods=["POST"])
@organizador_requerido
def partido_resolver(partido_id):
    """El organizador define un partido: resultado, W.O. o anulado."""
    p = db.session.get(Partido, partido_id)
    if not p:
        abort(404)
    comp = _mi_competencia(p.competencia_id)
    if p.estado not in (PAR_AGENDADO, PAR_EN_DISPUTA, PAR_DESAFIO):
        return redirect(url_for("torneos.competencia_panel", comp_id=comp.id))
    accion = request.form.get("accion")
    if accion == "resultado":
        try:
            sets = esc.sets_texto(esc.leer_sets(request.form.get("sets"), un_set=comp.tipo != TIPO_ESCALERA))
        except ValueError as e:
            return redirect(url_for("torneos.competencia_panel", comp_id=comp.id, error=str(e)) + "#partidos")
        db.session.add(Resultado(partido_id=p.id, cargado_por="organizador",
                                 cargado_por_id=comp.organizador_id, sets=sets, confirmado=True))
        db.session.flush()
        esc.aplicar_resultado(p, sets)
    elif accion in ("wo_a", "wo_b"):
        esc.aplicar_wo(p, p.lado_a_id if accion == "wo_a" else p.lado_b_id)
    elif accion == "anular" and comp.tipo == TIPO_ESCALERA:   # en un cuadro no se anula: rompería la llave
        p.estado = PAR_ANULADO
    db.session.commit()
    return redirect(url_for("torneos.competencia_panel", comp_id=comp.id) + "#partidos")


@bp.route("/panel/<int:comp_id>/divisiones", methods=["POST"])
@organizador_requerido
def divisiones_aplicar(comp_id):
    comp = _mi_competencia(comp_id)
    semana = esc.semana_cambio_pendiente(comp)
    if semana and request.form.get("semana", type=int) == semana:
        if request.form.get("accion") == "aplicar":
            esc.aplicar_divisiones(comp, semana)
        else:   # saltear este cambio
            reglas = comp.reglas
            reglas["divisiones_aplicadas"] = (reglas.get("divisiones_aplicadas") or []) + [semana]
            comp.reglas = reglas
            db.session.commit()
    return redirect(url_for("torneos.competencia_panel", comp_id=comp.id))


# Reglas editables de la escalera: (clave, texto, tipo)
REGLAS_NUMERICAS = [
    ("semanas", "Duración de la etapa (semanas)", int),
    ("desafio_max_puestos_arriba", "Hasta cuántos puestos arriba se puede desafiar", int),
    ("plazo_respuesta_dias", "Días para responder un desafío", int),
    ("rechazos_seguidos_max", "Rechazos seguidos permitidos", int),
    ("minimo_partidos_semana", "Partidos mínimos por semana (0 = sin mínimo)", int),
    ("semanas_libres", "Semanas libres por etapa", int),
    ("piso_bajo_inicial", "Puntos máximos que se puede bajar del nivel inicial", float),
    ("ascensos_cada_semanas", "Ascensos y descensos cada (semanas, 0 = nunca)", int),
]
PUNTOS = [
    ("gana_2_sets", "Gana en 2 sets"), ("gana_super_tiebreak", "Gana en súper tie-break"),
    ("gana_wo", "Gana por W.O."), ("pierde_super_tiebreak", "Pierde en súper tie-break"),
    ("pierde_2_sets", "Pierde en 2 sets"), ("pierde_wo", "Pierde por W.O."),
    ("inactividad_semanal", "Semana sin jugar"),
]
NOMBRES_ESPECIALES_FORM = {"doble": "doble", "paga_perdedor": "paga perdedor", "1vs1": "1vs1"}


def _numero(n):
    return str(int(n)) if float(n).is_integer() else str(n)


def _texto_divisiones(reglas):
    return "\n".join(
        f"{d['nombre']}: {', '.join(_numero(n) for n in d.get('niveles', []))}"
        for d in reglas.get("divisiones") or []
    )


def _texto_especiales(reglas):
    items = sorted((reglas.get("semanas_especiales") or {}).items(), key=lambda x: int(x[0]))
    return "\n".join(f"{k}: {NOMBRES_ESPECIALES_FORM.get(v, v)}" for k, v in items)


def _lista_numeros(texto):
    vals = [float(x) for x in (texto or "").replace(";", ",").split(",") if x.strip()]
    return [int(n) if n.is_integer() else n for n in vals]


@bp.route("/panel/<int:comp_id>/reglas", methods=["GET", "POST"])
@organizador_requerido
def reglas_escalera(comp_id):
    comp = _mi_competencia(comp_id)
    if comp.tipo != TIPO_ESCALERA:
        abort(404)
    reglas = comp.reglas
    error, guardado = None, False
    if request.method == "POST":
        f = request.form
        try:
            for clave, _texto, tipo in REGLAS_NUMERICAS:
                reglas[clave] = tipo((f.get(clave) or "0").replace(",", "."))
            reglas["puntos"] = {k: float((f.get(f"p_{k}") or "0").replace(",", ".")) for k, _ in PUNTOS}
            reglas["niveles_iniciales"] = _lista_numeros(f.get("niveles"))
            divisiones = []
            for linea in (f.get("divisiones") or "").splitlines():
                if ":" in linea:
                    nombre, nums = linea.split(":", 1)
                    divisiones.append({"nombre": nombre.strip()[:40], "niveles": _lista_numeros(nums)})
            reglas["divisiones"] = divisiones
            reglas["cambios_division"] = [
                {"suben": int(f.get(f"suben_{k}") or 0), "bajan": int(f.get(f"bajan_{k}") or 0)}
                for k in range(max(0, len(divisiones) - 1))
            ]
            claves = {v: k for k, v in NOMBRES_ESPECIALES_FORM.items()}
            especiales = {}
            for linea in (f.get("especiales") or "").splitlines():
                if ":" in linea:
                    n, modo = linea.split(":", 1)
                    if n.strip().isdigit():
                        especiales[n.strip()] = claves.get(modo.strip().lower(), modo.strip()[:30])
            reglas["semanas_especiales"] = especiales
            reglas["selfie_obligatoria"] = bool(f.get("selfie_obligatoria"))
            reglas["formato_partido"] = (f.get("formato_partido") or "").strip()[:100]
        except ValueError:
            error = "Revisá los números: usá solo números (con coma o punto para decimales)."
        else:
            comp.reglas = reglas
            db.session.commit()
            guardado = True
    return render_template(
        "torneos/reglas.html",
        **contexto(
            comp=comp, reglas=reglas, error=error, guardado=guardado,
            numericas=REGLAS_NUMERICAS, puntos=PUNTOS,
            texto_divisiones=_texto_divisiones(reglas), texto_especiales=_texto_especiales(reglas),
        ),
    )


@bp.route("/panel/inscripcion/<int:insc_id>", methods=["POST"])
@organizador_requerido
def inscripcion_accion(insc_id):
    insc = db.session.get(Inscripcion, insc_id)
    if not insc:
        abort(404)
    comp = _mi_competencia(insc.categoria.competencia_id)
    accion = request.form.get("accion")
    if accion == "confirmar":
        insc.estado_pago = PAGO_CONFIRMADO
    elif accion == "rechazar":
        insc.estado_pago = PAGO_RECHAZADO
    elif accion == "pendiente":
        insc.estado_pago = PAGO_PENDIENTE
    elif accion == "baja":
        insc.baja = True
    elif accion == "alta":
        insc.baja = False
    elif accion == "nivel":
        valor = (request.form.get("nivel") or "").replace(",", ".").strip()
        try:
            insc.nivel_inicial = float(valor) if valor else None
        except ValueError:
            pass
        else:
            # la división arranca según el nivel inicial (después la cambian los ascensos)
            insc.division = esc.division_por_nivel(comp, insc.nivel_inicial)
    elif accion == "siembra":
        valor = (request.form.get("siembra") or "").strip()
        insc.siembra = int(valor) if valor.isdigit() and int(valor) > 0 else None
    elif accion == "division":
        nombre = request.form.get("division") or None
        if nombre is None or nombre in esc.nombres_divisiones(comp):
            insc.division = nombre
    db.session.commit()
    return redirect(url_for("torneos.competencia_panel", comp_id=comp.id) + f"#cat-{insc.categoria_id}")


@bp.route("/panel/inscripcion/<int:insc_id>/comprobante")
@organizador_requerido
def comprobante(insc_id):
    """El comprobante solo lo ve el organizador de esa competencia."""
    insc = db.session.get(Inscripcion, insc_id)
    if not insc or not insc.comprobante:
        abort(404)
    _mi_competencia(insc.categoria.competencia_id)
    nombre = os.path.basename(insc.comprobante)
    return send_from_directory(CARPETA_ARCHIVOS, nombre)
