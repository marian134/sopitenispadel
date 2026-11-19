"""Páginas públicas: calendario, página del torneo, inscripción y panel del jugador."""
from datetime import datetime

from flask import abort, redirect, render_template, request, session, url_for

from models import db
from .bp import bp, contexto, WHATSAPP_SOPI
from .models import (
    Categoria, Competencia, Inscripcion, Jugador,
    ESTADOS_PUBLICOS, EST_EN_CURSO, EST_FINALIZADA, EST_INSCRIPCION,
)
from .util import enviar_mail, guardar_archivo, link_whatsapp, pesos, solo_digitos

WHATSAPP_ORGANIZAR = (
    f"https://wa.me/{WHATSAPP_SOPI}?text="
    "Hola%20SOPI!%20Quiero%20organizar%20un%20torneo%20de%20tenis"
)


def inscripcion_abierta(comp):
    if comp.estado != EST_INSCRIPCION:
        return False
    return not comp.cierre_inscripcion or comp.cierre_inscripcion > datetime.now()


def lugares_libres(cat):
    if not cat.cupo:
        return None
    ocupados = sum(1 for i in cat.inscripciones if not i.baja)
    return max(0, cat.cupo - ocupados)


@bp.route("/")
def calendario():
    competencias = (
        Competencia.query
        .filter(Competencia.estado.in_(ESTADOS_PUBLICOS))
        .order_by(Competencia.fecha_inicio.desc().nullslast(), Competencia.id.desc())
        .all()
    )
    grupos = [
        ("Inscripción abierta", [c for c in competencias if c.estado == EST_INSCRIPCION]),
        ("En juego", [c for c in competencias if c.estado == EST_EN_CURSO]),
        ("Finalizados", [c for c in competencias if c.estado == EST_FINALIZADA]),
    ]
    return render_template(
        "torneos/calendario.html",
        **contexto(grupos=[g for g in grupos if g[1]], whatsapp_organizar=WHATSAPP_ORGANIZAR),
    )


def _competencia_publica(slug):
    comp = Competencia.query.filter_by(slug=slug).first()
    if not comp or comp.estado not in ESTADOS_PUBLICOS:
        abort(404)
    return comp


@bp.route("/<slug>")
def torneo(slug):
    comp = _competencia_publica(slug)
    categorias = [
        {"cat": c, "libres": lugares_libres(c),
         "inscriptos": [i for i in c.inscripciones if not i.baja]}
        for c in sorted(comp.categorias, key=lambda c: c.orden)
    ]
    return render_template(
        "torneos/torneo.html",
        **contexto(comp=comp, categorias=categorias, abierta=inscripcion_abierta(comp)),
    )


def _buscar_o_crear_jugador(dni, nombre, apellido, celular, email):
    """El DNI identifica al jugador. Si ya existe no se pisan sus datos:
    solo se completan los que faltaban (así nadie cambia los de otro)."""
    jugador = Jugador.query.filter_by(dni=dni).first()
    if jugador:
        if not jugador.email and email:
            jugador.email = email
        return jugador
    jugador = Jugador(dni=dni, nombre=nombre, apellido=apellido, celular=celular, email=email or None)
    db.session.add(jugador)
    db.session.flush()
    return jugador


def _leer_persona(form, sufijo):
    return {
        "dni": solo_digitos(form.get(f"dni{sufijo}"))[:12],
        "nombre": (form.get(f"nombre{sufijo}") or "").strip().title()[:80],
        "apellido": (form.get(f"apellido{sufijo}") or "").strip().title()[:80],
        "celular": (form.get(f"celular{sufijo}") or "").strip()[:40],
        "email": (form.get(f"email{sufijo}") or "").strip().lower()[:120],
    }


def _validar_persona(p, quien):
    if not (6 <= len(p["dni"]) <= 9):
        return f"Revisá el DNI {quien}: tiene que tener entre 6 y 9 números."
    if not p["nombre"] or not p["apellido"]:
        return f"Falta el nombre o el apellido {quien}."
    if len(solo_digitos(p["celular"])) < 8:
        return f"Revisá el celular {quien}."
    return None


@bp.route("/<slug>/inscripcion", methods=["GET", "POST"])
def inscripcion(slug):
    comp = _competencia_publica(slug)
    if not inscripcion_abierta(comp):
        return redirect(url_for("torneos.torneo", slug=comp.slug))
    categorias = sorted(comp.categorias, key=lambda c: c.orden)
    error = None

    if request.method == "POST":
        form = request.form
        cat = db.session.get(Categoria, form.get("categoria", type=int) or 0)
        p1 = _leer_persona(form, "")
        p2 = _leer_persona(form, "2")
        if not cat or cat.competencia_id != comp.id:
            error = "Elegí una categoría."
        elif lugares_libres(cat) == 0:
            error = f"La categoría {cat.nombre} ya no tiene lugares."
        else:
            error = _validar_persona(p1, "")
            if not error and cat.modalidad == "dobles":
                error = _validar_persona(p2, "de tu compañero/a")
                if not error and p2["dni"] == p1["dni"]:
                    error = "El DNI del compañero/a es igual al tuyo."
        if not error and not form.get("acepto"):
            error = "Tenés que aceptar el reglamento del torneo."

        comprobante = None
        if not error and comp.precio:
            try:
                comprobante = guardar_archivo(request.files.get("comprobante"))
            except ValueError as e:
                error = f"Comprobante: {e}"

        if not error:
            j1_nuevo = not Jugador.query.filter_by(dni=p1["dni"]).first()
            j1 = _buscar_o_crear_jugador(**p1)
            j2 = _buscar_o_crear_jugador(**p2) if cat.modalidad == "dobles" else None
            ya = [
                i for i in cat.inscripciones
                if not i.baja and {i.jugador1_id, i.jugador2_id} & {j1.id, j2.id if j2 else -1}
            ]
            if ya:
                db.session.rollback()
                error = f"Ese DNI ya está anotado en {cat.nombre}."
            else:
                insc = Inscripcion(
                    categoria_id=cat.id, jugador1_id=j1.id, jugador2_id=j2.id if j2 else None,
                    comprobante=comprobante,
                    restricciones=(form.get("restricciones") or "").strip()[:500],
                )
                db.session.add(insc)
                db.session.commit()
                _avisar_inscripcion(comp, cat, insc)
                # El enlace personal solo se muestra en pantalla si el jugador es
                # nuevo. Si el DNI ya existía, el enlace va únicamente por mail:
                # así nadie obtiene el enlace de otro anotándose con su DNI.
                session["torneo_insc_ok"] = {"insc": insc.id, "mostrar_enlace": j1_nuevo}
                return redirect(url_for("torneos.inscripcion_ok", slug=comp.slug))

    return render_template(
        "torneos/inscripcion.html",
        **contexto(
            comp=comp, categorias=categorias, error=error, form=request.form,
            libres={c.id: lugares_libres(c) for c in categorias},
        ),
    )


def _avisar_inscripcion(comp, cat, insc):
    for jugador in filter(None, [insc.jugador1, insc.jugador2]):
        enlace = url_for("torneos.jugador", enlace=jugador.enlace, _external=True)
        enviar_mail(
            jugador.email,
            f"Inscripción recibida: {comp.nombre}",
            "\n".join([
                f"Hola {jugador.nombre}!",
                "",
                f"Recibimos tu inscripción en {comp.nombre} ({cat.nombre}).",
                "El organizador va a revisar el pago y te confirma.",
                "",
                "Desde este enlace personal seguís tus torneos, tus partidos y tu ranking:",
                enlace,
                "",
                "Guardalo: es tuyo y no hace falta contraseña.",
                "",
                "SOPI Torneos",
            ]),
        )


@bp.route("/<slug>/inscripcion/listo")
def inscripcion_ok(slug):
    comp = _competencia_publica(slug)
    datos = session.get("torneo_insc_ok") or {}
    insc = db.session.get(Inscripcion, datos.get("insc") or 0)
    if not insc or insc.categoria.competencia_id != comp.id:
        return redirect(url_for("torneos.torneo", slug=comp.slug))
    jugador = insc.jugador1
    org = comp.organizador
    texto = f"Hola! Me inscribí en {comp.nombre} ({insc.categoria.nombre}). Soy {jugador.nombre_completo}."
    return render_template(
        "torneos/inscripcion_ok.html",
        **contexto(
            comp=comp, insc=insc, jugador=jugador,
            enlace_jugador=(
                url_for("torneos.jugador", enlace=jugador.enlace, _external=True)
                if datos.get("mostrar_enlace") else None
            ),
            wa_organizador=link_whatsapp(org.whatsapp, texto) if org.whatsapp else None,
        ),
    )


@bp.route("/jugador/<enlace>")
def jugador(enlace):
    j = Jugador.query.filter_by(enlace=enlace).first_or_404()
    inscripciones = (
        Inscripcion.query
        .filter((Inscripcion.jugador1_id == j.id) | (Inscripcion.jugador2_id == j.id))
        .order_by(Inscripcion.creado_en.desc()).all()
    )
    return render_template(
        "torneos/jugador.html",
        **contexto(j=j, inscripciones=inscripciones, robots_noindex=True),
    )


@bp.route("/recuperar-enlace", methods=["GET", "POST"])
def recuperar_enlace():
    """Reenvía el enlace personal por mail. Siempre responde lo mismo, para no
    revelar qué DNI están cargados."""
    enviado = False
    if request.method == "POST":
        dni = solo_digitos(request.form.get("dni"))
        email = (request.form.get("email") or "").strip().lower()
        j = Jugador.query.filter_by(dni=dni).first() if dni else None
        if j and j.email and j.email == email:
            enviar_mail(
                j.email, "Tu enlace de SOPI Torneos",
                f"Hola {j.nombre}! Este es tu enlace personal:\n"
                f"{url_for('torneos.jugador', enlace=j.enlace, _external=True)}\n",
            )
        enviado = True
    return render_template("torneos/recuperar.html", **contexto(enviado=enviado))
