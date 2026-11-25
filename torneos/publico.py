"""Páginas públicas: calendario, página del torneo, inscripción y panel del jugador."""
import re
from datetime import datetime

from flask import abort, redirect, render_template, request, session, url_for

from models import db
from . import cuadro as cdr
from . import zonas as zns
from . import escalera as esc
from .bp import bp, contexto, WHATSAPP_SOPI
from .models import (
    Categoria, Competencia, Inscripcion, Jugador, Partido,
    ESTADOS_PUBLICOS, EST_EN_CURSO, EST_FINALIZADA, EST_INSCRIPCION,
)
from .util import enviar_mail, guardar_archivo, link_whatsapp, organizador_actual, pesos, solo_digitos

WHATSAPP_ORGANIZAR = (
    f"https://wa.me/{WHATSAPP_SOPI}?text="
    "Hola%20SOPI!%20Quiero%20organizar%20un%20torneo%20de%20tenis"
)


def inscripcion_abierta(comp):
    # La escalera acepta jugadores nuevos durante toda la etapa (entran con su
    # nivel inicial la semana siguiente), salvo que el organizador la cierre.
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


def _competencia_publica(slug, vista_previa=False):
    """vista_previa=True: el organizador puede ver su torneo en borrador."""
    comp = Competencia.query.filter_by(slug=slug).first()
    if not comp:
        abort(404)
    if comp.estado not in ESTADOS_PUBLICOS:
        org = organizador_actual()
        if not (vista_previa and org and org.id == comp.organizador_id):
            abort(404)
    return comp


@bp.route("/<slug>")
def torneo(slug):
    comp = _competencia_publica(slug, vista_previa=True)
    escalera = None
    if comp.tipo == "escalera":
        esc.procesar(comp)
        semana = esc.semana_actual(comp)
        escalera = {
            "semana": semana, "total": esc.total_semanas(comp),
            "especial": esc.especial(comp, semana)[1] if semana else None,
            "rankings": {c.id: esc.con_semana(esc.ranking(c, semana or 1), semana) for c in comp.categorias},
        }
    categorias = [
        {"cat": c, "libres": lugares_libres(c),
         "inscriptos": [i for i in c.inscripciones if not i.baja],
         "ranking": escalera["rankings"].get(c.id) if escalera else None,
         "principal": cdr.estructura(c) if comp.tipo == "cuadro" else [],
         "consuelo": cdr.estructura(c, cdr.CONSUELO) if comp.tipo == "cuadro" else [],
         "tercer": cdr.partidos(c, cdr.TERCER) if comp.tipo == "cuadro" else [],
         "campeon": cdr.campeon(c) if comp.tipo == "cuadro" else None,
         "podio": cdr.podio(c) if comp.tipo == "cuadro" else None,
         "plata": cdr.estructura(c, cdr.PLATA) if comp.tipo == "cuadro" else [],
         "campeon_plata": cdr.campeon(c, cdr.PLATA) if comp.tipo == "cuadro" else None,
         "zonas": zns.estructura(c) if zns.activas(comp) else []}
        for c in sorted(comp.categorias, key=lambda c: c.orden)
    ]
    proximos = []
    if comp.tipo == "cuadro":
        proximos = (
            Partido.query.filter(Partido.competencia_id == comp.id, Partido.estado == "agendado",
                                 Partido.fecha_hora.isnot(None))
            .order_by(Partido.fecha_hora, Partido.cancha).all()
        )
    por_dia = []
    for p in proximos:
        if not por_dia or por_dia[-1][0] != p.fecha_hora.date():
            por_dia.append((p.fecha_hora.date(), []))
        por_dia[-1][1].append(p)
    proximos = por_dia
    lp = _datos_liga_publica(comp) if comp.tipo == "liga" else None
    return render_template(
        "torneos/torneo.html",
        **contexto(comp=comp, categorias=categorias, abierta=inscripcion_abierta(comp),
                   escalera=escalera, proximos=proximos, nombre_ronda=cdr.nombre_ronda, lp=lp,
                   ediciones=_otras_ediciones(comp),
                   plazos=[(nombre, (comp.reglas.get("plazos") or {})[clave]) for clave, nombre in cdr.ETAPAS
                           if (comp.reglas.get("plazos") or {}).get(clave)] if comp.tipo == "cuadro" else [],
                   reglas_zonas=zns.reglas(comp) if zns.activas(comp) else None),
    )


def _datos_liga_publica(comp):
    from . import liga
    prox = liga.proxima_fecha(comp)
    pa, pb = liga.puntos_partido(comp, comp.reglas.get("wo_como") or "6-0 6-0")
    return {
        "fechas": liga.estado_fechas(comp), "tabla": liga.tabla(comp), "resultados": liga.resultados(comp),
        "ejemplo": liga.ejemplo(comp),
        "wo_texto": f"tu rival suma {int(pa) if float(pa).is_integer() else pa} y vos {int(pb) if float(pb).is_integer() else pb}",
        "proximos": [p for p in Partido.query.filter_by(competencia_id=comp.id, semana=prox, estado="agendado")
                     .order_by(Partido.fecha_hora).all()] if prox else [],
    }


def _otras_ediciones(comp):
    """Las otras ediciones públicas del mismo torneo (copiadas una de otra)."""
    raiz = comp.reglas.get("edicion_de") or comp.id
    todas = [c for c in Competencia.query.filter_by(organizador_id=comp.organizador_id).all()
             if (c.reglas.get("edicion_de") or c.id) == raiz and c.id != comp.id and c.estado in ESTADOS_PUBLICOS]
    return sorted(todas, key=lambda c: c.id, reverse=True)


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
            if not error and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", p1["email"]):
                error = "Poné tu mail: ahí te llega el enlace para seguir el torneo."
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
    bloques, bloques_cuadro, bloques_liga = {}, {}, {}
    for insc in inscripciones:
        comp = insc.categoria.competencia
        if comp.tipo == "escalera":
            esc.procesar(comp)
            bloques[insc.id] = _bloque_escalera(insc, j)
        elif comp.tipo == "liga":
            if not insc.baja:
                bloques_liga[insc.id] = _bloque_liga(insc)
        elif not insc.baja:
            bloques_cuadro[insc.id] = _bloque_cuadro(insc, j)
    from .desafios import MENSAJES
    return render_template(
        "torneos/jugador.html",
        **contexto(
            j=j, inscripciones=inscripciones, bloques=bloques, bloques_cuadro=bloques_cuadro,
            bloques_liga=bloques_liga,
            mensaje=MENSAJES.get(request.args.get("msj", "")),
            error=MENSAJES.get(request.args.get("error", "")) or request.args.get("error_texto"),
        ),
    )


def _texto_sets(p, insc):
    res = [r for r in p.resultados if r.confirmado and not r.ausente_id]
    if p.estado == "wo":
        return "W.O."
    if not res:
        return ""
    return res[-1].sets if insc.id == p.lado_a_id else esc.invertir(res[-1].sets)


def _bloque_liga(insc):
    """Lo que el jugador ve de una liga: próxima fecha, su partido, sus puntos."""
    from . import liga
    comp = insc.categoria.competencia
    tabla = liga.tabla(comp)
    mia = next((f for f in tabla if f["insc"].id == insc.id), None)
    prox = liga.proxima_fecha(comp)
    partidos = []
    for p in Partido.query.filter_by(competencia_id=comp.id).all():
        if insc.id not in (p.lado_a_id, p.lado_b_id) or p.estado not in ("agendado", "en_disputa"):
            continue
        rival = p.lado_b if p.lado_a_id == insc.id else p.lado_a

        def ver(res, p=p):
            if not res:
                return None
            return "W.O." if res.ausente_id else (res.sets if insc.id == p.lado_a_id else esc.invertir(res.sets))
        mio, suyo = esc.resultado_de_jugador(p, insc), esc.resultado_de_jugador(p, rival)
        dia = liga.fecha_numero(comp, p.semana)
        partidos.append({
            "p": p, "rival": rival, "soy_desafiante": False,
            "ronda": f"Fecha {p.semana}" + (f" ({dia.strftime('%d/%m')})" if dia else ""),
            "mio": mio, "suyo": suyo, "mio_txt": ver(mio), "suyo_txt": ver(suyo),
            "wa": link_whatsapp(rival.jugador1.celular,
                                f"Hola {rival.jugador1.nombre}! Jugamos en la fecha {p.semana} de {comp.nombre}."),
        })
    historial = []
    for numero, dia, filas in liga.resultados(comp):
        for r in filas:
            if insc.id in (r["ganador"].id, r["perdedor"].id):
                gane = r["ganador"].id == insc.id
                historial.append({
                    "fecha": numero, "rival": r["perdedor"] if gane else r["ganador"], "gane": gane,
                    "sets": r["sets"] if gane or r["sets"] == "W.O." else esc.invertir(r["sets"]),
                    "puntos": r["pts_ganador"] if gane else r["pts_perdedor"],
                })
    return {
        "mia": mia, "total": len(tabla), "prox": prox,
        "prox_dia": liga.fecha_numero(comp, prox) if prox else None,
        "anotado": liga.esta_disponible(comp, insc, prox) if prox else False,
        "partidos": partidos, "historial": historial, "participa": liga.participa(insc),
    }


def _bloque_cuadro(insc, j):
    """Partidos del jugador en un torneo con cuadro."""
    cat = insc.categoria
    comp = cat.competencia
    mios = [p for p in Partido.query.filter_by(categoria_id=cat.id).all()
            if insc.id in (p.lado_a_id, p.lado_b_id)]
    partidos, esperando, historial = [], [], []
    for p in sorted(mios, key=lambda p: (p.cuadro != "principal", int(p.ronda or 0))):
        rival = p.lado_b if p.lado_a_id == insc.id else p.lado_a
        ronda = cdr.nombre_ronda(cat, p.cuadro, p.ronda, p) + (" (consuelo)" if p.cuadro == "consuelo" else "")
        plazo = cdr.plazo_de(comp, p)
        if p.estado in ("agendado", "en_disputa") and rival:
            def ver(res, p=p):
                if not res:
                    return None
                if res.ausente_id:
                    return "W.O."
                return res.sets if insc.id == p.lado_a_id else esc.invertir(res.sets)
            mio, suyo = esc.resultado_de_jugador(p, insc), esc.resultado_de_jugador(p, rival)
            texto = f"Hola {rival.jugador1.nombre}! Somos rivales en {comp.nombre} ({ronda}). ¿Cómo estás?"
            partidos.append({
                "p": p, "rival": rival, "soy_desafiante": False, "ronda": ronda, "plazo": plazo,
                "mio": mio, "suyo": suyo, "mio_txt": ver(mio), "suyo_txt": ver(suyo),
                "wa": link_whatsapp(rival.jugador1.celular, texto),
            })
        elif p.estado == "pendiente":
            previo = Partido.query.filter_by(
                categoria_id=cat.id, cuadro=p.cuadro, ronda=str(int(p.ronda) - 1),
                posicion=p.posicion * 2 + (1 if p.lado_a_id == insc.id else 0),
            ).first()
            de = "el partido entre " + " y ".join(
                x.jugador1.nombre_completo for x in (previo.lado_a, previo.lado_b) if x
            ) if previo and (previo.lado_a or previo.lado_b) else "la ronda anterior"
            esperando.append({"p": p, "ronda": ronda, "de": de})
        elif p.estado in ("jugado", "wo"):
            historial.append({"ronda": ronda, "rival": rival, "gane": p.ganador_id == insc.id,
                              "sets": _texto_sets(p, insc)})
        elif p.estado == "bye":
            historial.append({"ronda": ronda, "rival": None, "gane": True, "sets": "pase libre"})
    campeon = cdr.campeon(cat)
    podio = cdr.podio(cat)
    puesto = None
    if podio and not (campeon and campeon.id == insc.id):
        if podio["subcampeon"] and podio["subcampeon"].id == insc.id:
            puesto = "🥈 ¡Subcampeón" + ("es" if insc.jugador2 else "") + "!"
        elif any(t.id == insc.id for t in podio["terceros"]):
            puesto = "🥉 Tercer puesto"
    return {
        "puesto": puesto, "terminado": bool(podio),
        "partidos": partidos, "esperando": esperando, "historial": historial,
        "armado": bool(mios) or bool(cdr.partidos(cat)), "campeon": campeon and campeon.id == insc.id,
        "bloque": None,
    }


def _bloque_escalera(insc, j):
    """Todo lo que el jugador necesita ver de una escalera."""
    comp = insc.categoria.competencia
    semana = esc.semana_actual(comp)
    datos = {
        "en_juego": esc.en_juego(comp), "semana": semana, "total": esc.total_semanas(comp),
        "especial": esc.especial(comp, semana)[1] if semana else None,
        "participa": esc.participa(insc), "sin_fecha": not comp.fecha_inicio,
    }
    if not datos["participa"] or not semana:
        return datos
    grupos = esc.con_semana(esc.ranking(insc.categoria, semana), semana)
    division, grupo, mia = esc.fila_de(grupos, insc)
    enlace_panel = url_for("torneos.jugador", enlace=j.enlace, _external=True)
    torneo_url = url_for("torneos.torneo", slug=comp.slug, _external=True)

    def rival(p):
        return p.lado_b if p.lado_a_id == insc.id else p.lado_a

    partidos = esc.partidos_de(insc)
    abiertos = [p for p in partidos if p.estado in ("desafio", "agendado", "en_disputa")]
    filas_partidos = []
    for p in abiertos:
        r = rival(p)
        mio = esc.resultado_de_jugador(p, insc)
        suyo = esc.resultado_de_jugador(p, r)
        def ver(res):
            if not res:
                return None
            if res.ausente_id:
                return "W.O."
            return res.sets if insc.id == p.lado_a_id else esc.invertir(res.sets)
        texto_wa = (
            f"Hola {r.jugador1.nombre}! Te desafié en {comp.nombre}. "
            f"Entrá a tu enlace personal para aceptarlo (lo tenés en tu mail). {torneo_url}"
            if p.estado == "desafio" and p.lado_a_id == insc.id else
            f"Hola {r.jugador1.nombre}! ¿Cuándo jugamos nuestro partido de {comp.nombre}?"
        )
        filas_partidos.append({
            "p": p, "rival": r, "soy_desafiante": p.lado_a_id == insc.id,
            "mio": mio, "suyo": suyo, "mio_txt": ver(mio), "suyo_txt": ver(suyo),
            "wa": link_whatsapp(r.jugador1.celular, texto_wa),
        })
    jugados = [p for p in partidos if p.estado in ("jugado", "wo")][:5]
    historial = []
    for p in jugados:
        r = rival(p)
        res = next((x for x in p.resultados if not x.ausente_id), None)
        historial.append({
            "p": p, "rival": r, "gane": p.ganador_id == insc.id,
            "sets": ("W.O." if p.estado == "wo" else
                     (res.sets if insc.id == p.lado_a_id else esc.invertir(res.sets)) if res else ""),
        })
    libres_total = int(comp.reglas.get("semanas_libres") or 0)
    datos.update(
        division=division, grupo=grupo, mia=mia,
        desafiables=esc.desafiables(insc, grupos, semana) if datos["en_juego"] else [],
        partidos=filas_partidos, historial=historial,
        puntos_semana=esc.puntos_semana(insc, semana),
        libres_restantes=libres_total - esc.semanas_libres_usadas(insc),
        libre_proxima=esc.tiene_semana_libre(insc, semana + 1),
        libre_actual=esc.tiene_semana_libre(insc, semana),
        puede_rechazar=(insc.rechazos_seguidos or 0) < int(comp.reglas.get("rechazos_seguidos_max") or 1),
        max_puestos=comp.reglas.get("desafio_max_puestos_arriba"),
        enlace_panel=enlace_panel,
    )
    return datos


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
