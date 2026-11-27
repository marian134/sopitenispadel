"""Panel del organizador: sus competencias, categorías e inscriptos."""
import os
import re
from datetime import datetime

from flask import abort, redirect, render_template, request, send_from_directory, url_for

from models import db
from . import avisos, cobros, control
from . import escalera as esc
from . import reglas as reglas_mod
from .bp import bp, contexto
from .models import (
    Categoria, Competencia, Inscripcion, Partido, Resultado,
    PAR_AGENDADO, PAR_ANULADO, PAR_DESAFIO, PAR_EN_DISPUTA, PAR_JUGADO, PAR_WO,
    EST_BORRADOR, EST_CANCELADA, EST_EN_CURSO, EST_FINALIZADA, EST_INSCRIPCION,
    PAGO_CONFIRMADO, PAGO_PENDIENTE, PAGO_RECHAZADO, PLAN_GRATIS,
    TIPO_CUADRO, TIPO_ESCALERA, TIPO_LIGA,
)
from .util import (
    CARPETA_ARCHIVOS, link_whatsapp, organizador_actual, organizador_requerido, pesos, slug_unico,
)


def _mi_competencia(comp_id):
    org = organizador_actual()
    comp = db.session.get(Competencia, comp_id)
    if not comp or comp.organizador_id != org.id:
        abort(404)
    return comp


def _puede_crear(org):
    """El plan gratis permite una sola competencia (sin contar canceladas).
    En el plan pago, no se puede si debe más de un cobro."""
    if org.plan != PLAN_GRATIS:
        return not cobros.bloqueado_por_deuda(org)
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
            deuda=cobros.impagos(org), pasos=_primeros_pasos(org, competencias),
            revisar={c.id: len(a_revisar(c)) for c in competencias},
        ),
    )


def _primeros_pasos(org, competencias):
    publicado = next((c for c in competencias if c.estado in (EST_INSCRIPCION, EST_EN_CURSO, EST_FINALIZADA)), None)
    return [
        {"titulo": "Cargá tus datos para transferir", "hecho": bool(org.datos_bancarios),
         "texto": "Alias, CBU y titular: se los mostramos a los jugadores al inscribirse.",
         "link": url_for("torneos.perfil"), "boton": "Cargar mis datos"},
        {"titulo": "Creá tu torneo", "hecho": bool(competencias),
         "texto": "Elegí el formato, las categorías y el precio.",
         "link": url_for("torneos.competencia_nueva"), "boton": "+ Nuevo torneo"},
        {"titulo": "Publicalo", "hecho": bool(publicado),
         "texto": "Entrá al torneo y tocá \"Publicar y abrir inscripción\".",
         "link": url_for("torneos.competencia_panel", comp_id=competencias[0].id) if competencias else None,
         "boton": "Ir al torneo"},
        {"titulo": "Compartí el link", "hecho": bool(publicado),
         "texto": "Mandalo por WhatsApp o Instagram: los jugadores se anotan solos.", "link": None},
    ]


def leer_filas_categoria(form):
    """Lee las filas de categorías del formulario (desplegables o texto).
    Devuelve (filas, error)."""
    indices = set()
    for clave in form:
        m = re.fullmatch(r"cat_(?:elegida|nombre|id|modalidad|cupo)_(\d+)", clave)
        if m:
            indices.add(int(m.group(1)))
    filas = []
    for n in sorted(indices):
        elegida = (form.get(f"cat_elegida_{n}") or "").strip()
        escrita = (form.get(f"cat_nombre_{n}") or "").strip()
        nombre = (escrita if elegida in ("", "otra") else elegida)[:80]
        borrar = form.get(f"cat_borrar_{n}") == "1"
        cat_id = form.get(f"cat_id_{n}") or None
        fila = {"id": cat_id, "nombre": nombre, "borrar": borrar, "orden": n,
                "modalidad": form.get(f"cat_modalidad_{n}") or "", "cupo": None}
        filas.append(fila)
        if borrar or (not nombre and not cat_id and not elegida):
            continue
        if elegida == "otra" and not escrita:
            return filas, "Escribí el nombre de la categoría."
        if not nombre:
            return filas, "Elegí el nombre de cada categoría."
        if fila["modalidad"] not in ("singles", "dobles"):
            return filas, f"Elegí si \"{nombre}\" es de singles o de dobles."
        cupo_txt = (form.get(f"cat_cupo_{n}") or "").strip()
        if cupo_txt == "otro":
            cupo_txt = (form.get(f"cat_cupo_otro_{n}") or "").strip()
            if not cupo_txt.isdigit() or int(cupo_txt) < 2:
                return filas, f"El cupo de \"{nombre}\" tiene que ser un número (2 o más)."
        if f"cat_cupo_{n}" in form and cupo_txt == "":
            return filas, f"Elegí el cupo de \"{nombre}\" (o \"Sin límite\")."
        if cupo_txt in ("", "sin", "0"):
            fila["cupo"] = None
        elif cupo_txt.isdigit():
            fila["cupo"] = int(cupo_txt)
        else:
            return filas, f"El cupo de \"{nombre}\" tiene que ser un número."
    return filas, None


def filas_para_form(form, comp):
    """Filas para volver a mostrar el formulario después de un error."""
    filas, _e = leer_filas_categoria(form)
    inscriptos = {str(c.id): len(c.inscripciones) for c in comp.categorias} if comp.id else {}
    salida = []
    for f in filas:
        if f["borrar"]:
            continue
        cupo = form.get(f"cat_cupo_{f['orden']}") or ""
        if cupo == "otro":
            cupo = form.get(f"cat_cupo_otro_{f['orden']}") or ""
        salida.append({"id": f["id"], "nombre": f["nombre"], "modalidad": f["modalidad"],
                       "cupo": cupo, "inscriptos": inscriptos.get(f["id"] or "", 0)})
    return salida or [{"id": None, "nombre": "", "modalidad": "", "cupo": ""}]


def mezcla_modalidades(comp):
    """Aviso si el nombre dice dobles (o singles) y hay categorías de la otra modalidad."""
    nombre = (comp.nombre or "").lower()
    mods = {c.modalidad for c in comp.categorias}
    if "doble" in nombre and "singles" in mods:
        return "El torneo se llama \"dobles\" pero tiene categorías de singles. Revisalas si no es a propósito."
    if "single" in nombre and "dobles" in mods:
        return "El torneo se llama \"singles\" pero tiene categorías de dobles. Revisalas si no es a propósito."
    return None


def _guardar_competencia(comp, form):
    """Pasa el formulario a la competencia. Devuelve un error o None."""
    nombre = (form.get("nombre") or "").strip()[:150]
    if not nombre:
        return "Poné un nombre."
    if comp.id is None:
        tipo = form.get("tipo")
        if tipo not in (TIPO_CUADRO, TIPO_ESCALERA, TIPO_LIGA):
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

    filas, error = leer_filas_categoria(form)
    if error:
        return error
    if not any(f["nombre"] and not f["borrar"] for f in filas):
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
    reglas = comp.reglas
    if organizador_actual().plan != PLAN_GRATIS:
        reglas["cargo_al_jugador"] = bool(form.get("cargo_al_jugador"))
    canchas = form.get("canchas") or ""
    if canchas.isdigit() and 1 <= int(canchas) <= 20:
        reglas["canchas"] = int(canchas)
    elif "canchas" in form:
        reglas.pop("canchas", None)
    comp.reglas = reglas
    if comp.id is None:
        comp.slug = slug_unico(Competencia, nombre)
        db.session.add(comp)
        db.session.flush()

    existentes = {str(c.id): c for c in comp.categorias}
    for f in sorted(filas, key=lambda x: x["orden"]):
        cat = existentes.get(f["id"]) if f["id"] else None
        if cat and (f["borrar"] or not f["nombre"]):
            # borrar solo si no tiene inscriptos
            if not cat.inscripciones:
                db.session.delete(cat)
            continue
        if not f["nombre"] or f["borrar"]:
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
    form = request.form if request.method == "POST" else None
    return render_template(
        "torneos/competencia_form.html",
        **contexto(comp=comp, error=error, form=form,
                   filas_form=filas_para_form(form, comp) if form else None),
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
    form = request.form if error else None
    return render_template(
        "torneos/competencia_form.html",
        **contexto(comp=comp, error=error, form=form,
                   filas_form=filas_para_form(form, comp) if form else None),
    )


@bp.route("/panel/<int:comp_id>/estado", methods=["POST"])
@organizador_requerido
def competencia_estado(comp_id):
    """Abrir inscripción, cerrarla (empieza el juego), volver a borrador o cancelar."""
    comp = _mi_competencia(comp_id)
    accion = request.form.get("accion")
    if accion == "abrir" and comp.estado == EST_BORRADOR and comp.categorias and not comp.organizador.aprobado:
        # cuenta nueva: Sopi la aprueba y el torneo se publica solo
        if not comp.pide_publicar:
            comp.pide_publicar = True
            db.session.commit()
            control.avisar_pide_publicar(comp.organizador, comp)
        return redirect(url_for("torneos.competencia_panel", comp_id=comp.id, espera=1))
    if accion == "abrir" and comp.estado == EST_BORRADOR and comp.categorias:
        comp.estado = EST_INSCRIPCION
        comp.pide_publicar = False
        db.session.commit()
        return redirect(url_for("torneos.competencia_panel", comp_id=comp.id, publicado=1))
    elif accion == "cerrar" and comp.estado == EST_INSCRIPCION:
        comp.estado = EST_EN_CURSO
        if comp.tipo == TIPO_CUADRO:
            cobros.crear_cobro(comp)   # plan pago: inscriptos x precio por inscripto
    elif accion == "borrador" and comp.estado == EST_INSCRIPCION and not _hay_inscriptos(comp):
        comp.estado = EST_BORRADOR
    elif accion == "cancelar" and comp.estado in (EST_BORRADOR, EST_INSCRIPCION):
        comp.estado = EST_CANCELADA
    elif accion == "finalizar" and comp.tipo == TIPO_LIGA and comp.estado in (EST_INSCRIPCION, EST_EN_CURSO):
        # La liga la cierra el organizador al terminar la última fecha
        comp.estado = EST_FINALIZADA
        cobros.crear_cobro(comp)
    db.session.commit()
    # al cerrar la inscripción, directo al recuadro con el paso que sigue (armar el cuadro)
    ancla = "#siguiente-paso" if accion == "cerrar" else ""
    return redirect(url_for("torneos.competencia_panel", comp_id=comp.id) + ancla)


@bp.route("/panel/<int:comp_id>/copiar", methods=["POST"])
@organizador_requerido
def competencia_copiar(comp_id):
    """Nueva edición: copia datos, categorías y reglas, sin inscriptos ni partidos."""
    comp = _mi_competencia(comp_id)
    org = organizador_actual()
    if not _puede_crear(org):
        return redirect(url_for("torneos.panel"))
    reglas = comp.reglas
    for clave in ("semana_cerrada", "divisiones_aplicadas", "disponibles", "fechas"):
        reglas.pop(clave, None)
    if comp.tipo == TIPO_LIGA:
        reglas["disponibles"], reglas["fechas"] = {}, []
    reglas["edicion_de"] = reglas.get("edicion_de") or comp.id   # todas apuntan a la primera
    nombre = (request.form.get("nombre") or "").strip()[:150] or f"{comp.nombre} (nueva edición)"
    nueva = Competencia(
        organizador_id=org.id, tipo=comp.tipo, nombre=nombre, slug=slug_unico(Competencia, nombre),
        deporte=comp.deporte, sede=comp.sede, localidad=comp.localidad, descripcion=comp.descripcion,
        precio=comp.precio, incluye=comp.incluye, estado=EST_BORRADOR,
    )
    nueva.reglas = reglas
    db.session.add(nueva)
    db.session.flush()
    for cat in comp.categorias:
        db.session.add(Categoria(competencia_id=nueva.id, nombre=cat.nombre, modalidad=cat.modalidad,
                                 cupo=cat.cupo, orden=cat.orden))
    db.session.commit()
    return redirect(url_for("torneos.competencia_editar", comp_id=nueva.id))


def _hay_inscriptos(comp):
    return any(not i.baja for c in comp.categorias for i in c.inscripciones)


@bp.route("/panel/<int:comp_id>")
@organizador_requerido
def competencia_panel(comp_id, agregar=None):
    agregar = agregar or {}
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
            fila = {"i": i, "wa": link_whatsapp(i.jugador1.celular, texto)}
            if comp.precio and not i.baja and i.estado_pago != PAGO_CONFIRMADO:
                aviso = (f"Hola {i.jugador1.nombre}! Te recuerdo el pago de la inscripción en {comp.nombre} "
                         f"({cat.nombre}): {pesos(avisos.monto(i))}."
                         + (f" Datos para transferir: {comp.organizador.datos_bancarios}." if comp.organizador.datos_bancarios else "")
                         + f" Subí el comprobante desde tu enlace: {enlace}")
                fila["wa_recordar"] = link_whatsapp(i.jugador1.celular, aviso)
            filas.append(fila)
        activos = [i for i in inscriptos if not i.baja]
        categorias.append({
            "cat": cat, "filas": filas, "activos": len(activos),
            "confirmados": sum(1 for i in activos if i.estado_pago == PAGO_CONFIRMADO),
        })
    escalera = _datos_escalera(comp) if comp.tipo == TIPO_ESCALERA else None
    from .panel_cuadro import datos_cuadro
    cuadro = datos_cuadro(comp) if comp.tipo == TIPO_CUADRO else None
    from .panel_liga import datos_liga
    liga_datos = datos_liga(comp) if comp.tipo == TIPO_LIGA else None
    return render_template(
        "torneos/competencia_panel.html",
        **contexto(
            comp=comp, categorias=categorias, url_publica=url_publica,
            niveles=comp.reglas.get("niveles_iniciales", []),
            divisiones=esc.nombres_divisiones(comp), escalera=escalera, cuadro=cuadro, liga=liga_datos,
            error=request.args.get("error"), aviso_mezcla=mezcla_modalidades(comp),
            publicado=request.args.get("publicado"), guardado=request.args.get("guardado", type=int),
            espera=request.args.get("espera"), plan_libres=control.lugares_plan(comp),
            plan_anotados=control.jugadores_anotados(comp), tope_gratis=control.TOPE_GRATIS,
            cargado=request.args.get("cargado", type=int),
            error_horario=request.args.get("error_horario"), partido_error=request.args.get("partido_error", type=int),
            error_resultado=request.args.get("error_resultado"),
            agregar_abierto=agregar.get("cat"), agregar_error=agregar.get("error"),
            agregar_form=agregar.get("form") or {}, agregado=request.args.get("agregado"),
            wa_compartir=link_whatsapp("", f"{comp.nombre}: inscribite y seguí el torneo acá {url_publica}"),
            pasos=_pasos_torneo(comp, categorias, cuadro), wa_podio=_wa_podio(comp, cuadro, url_publica),
            a_revisar=a_revisar(comp), deben=deben(comp), aviso_pago=request.args.get("aviso_pago"),
        ),
    )


def _wa_podio(comp, cuadro, url_publica):
    """Texto para compartir el podio por WhatsApp al terminar."""
    if not cuadro:
        return ""
    lineas = [f"🏆 Terminó {comp.nombre}"]
    for c in cuadro["categorias"]:
        pod = c.get("podio")
        if not pod:
            continue
        nombre = lambda i: i.jugador1.nombre_completo + (f" / {i.jugador2.nombre_completo}" if i.jugador2 else "")  # noqa: E731
        lineas.append(f"{c['cat'].nombre}: 🥇 {nombre(pod['campeon'])}"
                      + (f" · 🥈 {nombre(pod['subcampeon'])}" if pod.get("subcampeon") else "")
                      + "".join(f" · 🥉 {nombre(t)}" for t in pod.get("terceros", []))
                      + (f" · 🏆 {comp.reglas.get('zonas', {}).get('nombre_plata') or 'Copa de Plata'}: {nombre(c['campeon_plata'])}"
                         if c.get("campeon_plata") else ""))
    lineas.append(f"Cuadro y resultados: {url_publica}")
    return link_whatsapp("", "\n".join(lineas))


def _pasos_torneo(comp, categorias, cuadro=None):
    """Pasos en orden del torneo, para el organizador (cambio 20)."""
    inscriptos = sum(c["activos"] for c in categorias)
    confirmados = sum(c["confirmados"] for c in categorias)
    abierto = comp.estado in (EST_EN_CURSO, EST_FINALIZADA)
    if comp.tipo == TIPO_CUADRO:
        from . import zonas as zns
        ultimo = ("Armar las zonas" if zns.activas(comp) else "Armar el cuadro",
                  "Con los inscriptos que tienen el pago confirmado.")
    elif comp.tipo == TIPO_ESCALERA:
        ultimo = ("Asignar nivel inicial y división", "En la lista de inscriptos; el ranking arranca el lunes.")
    else:
        ultimo = ("Armar los partidos de cada fecha", "Con los que se anotan para jugar esa fecha.")
    pasos = [
        {"titulo": "Publicar el torneo", "texto": "Queda visible y se abre la inscripción.",
         "hecho": comp.estado != EST_BORRADOR},
        {"titulo": "Recibir inscriptos y confirmar pagos",
         "texto": f"{inscriptos} anotado{'s' if inscriptos != 1 else ''}, {confirmados} con pago confirmado.",
         "hecho": abierto},
        {"titulo": "Cerrar la inscripción", "texto": "Nadie más se puede anotar y empieza el juego.",
         "hecho": abierto},
        {"titulo": ultimo[0], "texto": ultimo[1], "hecho": False},
    ]
    if comp.tipo != TIPO_CUADRO:
        pasos[2]["texto"] = "Opcional: los jugadores se pueden seguir sumando mientras dura."
    if cuadro and abierto:
        r = cuadro["resumen"]
        sig = f"#partido-{cuadro['siguiente']}" if cuadro.get("siguiente") else "#cuadros"
        pasos[3].update(hecho=r["armado"], ir="#cuadros", boton="Ir a armar")
        if comp.reglas.get("consuelo"):
            # aparece cuando se puede armar (todos jugaron su primer partido) y queda hecho al armarla
            listas = [c for c in cuadro["categorias"] if c.get("consuelo_listo") and not c.get("consuelo")]
            armadas = [c for c in cuadro["categorias"] if c.get("consuelo")]
            if listas or armadas:
                pasos.append({
                    "titulo": "Armar la copa de consuelo",
                    "texto": ("Ya jugaron todos su primer partido: armá la consuelo con los que perdieron ("
                              + ", ".join(c["cat"].nombre for c in listas) + ").") if listas
                             else "La consuelo ya está armada: sus partidos aparecen en la lista.",
                    "hecho": not listas, "ir": f"#cuadro-{listas[0]['cat'].id}" if listas else "#cuadros",
                    "boton": "Ir a armar la consuelo",
                })
        n = r["sin_horario"]
        pasos.append({
            "titulo": "Poner día, hora y cancha",
            "texto": (f"Hay {n} partido{'s' if n != 1 else ''} sin horario." if n
                      else "Todos los partidos que ya tienen rivales tienen horario. "
                           "Cuando se definan los de la ronda siguiente, aparecen acá."),
            "hecho": r["armado"] and not n, "ir": sig, "boton": "Ir al próximo partido",
        })
        if r["con_zonas"]:
            pasos.append({
                "titulo": "Jugar las zonas",
                "texto": f"{r['zonas_jugados']} de {r['zonas_total']} partidos de zona jugados.",
                "hecho": r["zonas_terminadas"], "ir": sig, "boton": "Ir al próximo partido",
            })
            pasos.append({
                "titulo": "Pasar los clasificados al cuadro",
                "texto": "Con las zonas terminadas, armá el cuadro con los que clasificaron"
                         + (" (y la Copa de Plata con el resto)." if (comp.reglas.get("zonas") or {}).get("plata") else "."),
                "hecho": r["cuadro_armado"],
                "ir": f"#cuadro-{r['cat_pasar']}" if r["cat_pasar"] else "#cuadros", "boton": "Ir a pasar al cuadro",
            })
        pasos.append({
            "titulo": "Cargar los resultados" + (" del cuadro" if r["con_zonas"] else ""),
            "texto": " · ".join(r["progreso"]) or "Cargá el resultado de cada partido: el ganador pasa solo a la ronda siguiente.",
            "hecho": r["terminado"], "ir": sig, "boton": "Ir al próximo partido",
        })
        pasos.append({
            "titulo": "Podio y cierre",
            "texto": "Con la final jugada se ve el podio en la página del torneo.",
            "hecho": r["terminado"], "ir": "#cuadros", "boton": "Ver el cuadro",
        })
    return pasos


@bp.route("/panel/<int:comp_id>/categoria/<int:cat_id>/agregar", methods=["POST"])
@organizador_requerido
def inscripcion_agregar(comp_id, cat_id):
    """El organizador anota a un jugador (cambio 18)."""
    from .publico import _avisar_inscripcion, _buscar_o_crear_jugador, _leer_persona, _validar_persona, lugares_libres
    comp = _mi_competencia(comp_id)
    cat = db.session.get(Categoria, cat_id)
    if not cat or cat.competencia_id != comp.id or comp.estado in (EST_FINALIZADA, EST_CANCELADA):
        abort(404)
    form = request.form
    p1, p2 = _leer_persona(form, ""), _leer_persona(form, "2")
    error = _validar_persona(p1, "")
    if not error and cat.modalidad == "dobles":
        error = _validar_persona(p2, "del compañero/a")
        if not error and p1["dni"] == p2["dni"]:
            error = "El DNI del compañero/a es igual al del jugador."
    if not error and lugares_libres(cat) == 0:
        error = f"{cat.nombre} ya llegó al cupo ({cat.cupo}). Subí el cupo en \"Editar datos y categorías\"."
    if not error and not control.entra_en_plan(comp, 2 if cat.modalidad == "dobles" else 1):
        error = control.mensaje_tope()
    if not error:
        j1 = _buscar_o_crear_jugador(**p1)
        j2 = _buscar_o_crear_jugador(**p2) if cat.modalidad == "dobles" else None
        ids = {j1.id, j2.id if j2 else -1}
        if any(not i.baja and {i.jugador1_id, i.jugador2_id} & ids for i in cat.inscripciones):
            db.session.rollback()
            error = f"Ese DNI ya está anotado en {cat.nombre}."
    if error:
        return competencia_panel(comp.id, agregar={"cat": str(cat.id), "error": error, "form": form})
    insc = Inscripcion(categoria_id=cat.id, jugador1_id=j1.id, jugador2_id=j2.id if j2 else None,
                       estado_pago=PAGO_CONFIRMADO if (form.get("pagado") or not comp.precio) else PAGO_PENDIENTE)
    db.session.add(insc)
    db.session.commit()
    _avisar_inscripcion(comp, cat, insc)
    return redirect(url_for("torneos.competencia_panel", comp_id=comp.id,
                            agregado=j1.nombre_completo) + f"#cat-{cat.id}")


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
            sets = esc.sets_texto(esc.leer_sets(request.form.get("sets"), un_set=comp.tipo == TIPO_CUADRO))
        except ValueError as e:
            if comp.tipo == TIPO_CUADRO:
                # el aviso aparece en el mismo partido
                return redirect(url_for("torneos.competencia_panel", comp_id=comp.id, error_resultado=str(e),
                                        partido_error=p.id) + f"#partido-{p.id}")
            return redirect(url_for("torneos.competencia_panel", comp_id=comp.id, error=str(e)) + "#partidos")
        db.session.add(Resultado(partido_id=p.id, cargado_por="organizador",
                                 cargado_por_id=comp.organizador_id, sets=sets, confirmado=True))
        db.session.flush()
        esc.aplicar_resultado(p, sets)
    elif accion in ("wo_a", "wo_b"):
        esc.aplicar_wo(p, p.lado_a_id if accion == "wo_a" else p.lado_b_id)
    elif accion in ("abandono_a", "abandono_b") and comp.tipo == TIPO_CUADRO:
        # Se retiró un jugador a mitad de partido: gana el otro y queda el score parcial
        parcial = " ".join((request.form.get("parcial") or "").replace(",", " ").split())[:40]
        try:
            esc._partir_sets(parcial, parcial=True)
        except ValueError:
            return redirect(url_for("torneos.competencia_panel", comp_id=comp.id,
                                    error_resultado="Escribí el score hasta el retiro como 6-1 2-0", partido_error=p.id)
                            + f"#partido-{p.id}")
        se_retira = p.lado_a_id if accion == "abandono_a" else p.lado_b_id
        db.session.add(Resultado(partido_id=p.id, cargado_por="organizador", cargado_por_id=comp.organizador_id,
                                 sets=(parcial + " ret.").strip(), confirmado=True))
        p.estado = PAR_JUGADO
        p.ganador_id = p.lado_b_id if se_retira == p.lado_a_id else p.lado_a_id
        db.session.flush()
        from . import cuadro as cdr
        cdr.avanzar(p)
    elif accion == "anular" and (comp.tipo != TIPO_CUADRO or p.cuadro == "zona"):
        # "No jugado": no suma para nadie (en la llave no se puede: rompería el cuadro)
        p.estado = PAR_ANULADO
    db.session.commit()
    if comp.tipo == TIPO_CUADRO:
        # seguimos con el partido que viene
        from .panel_cuadro import siguiente_id
        sig = siguiente_id(comp)
        return redirect(url_for("torneos.competencia_panel", comp_id=comp.id, cargado=p.id)
                        + (f"#partido-{sig}" if sig else "#pasos"))
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
    antes = insc.estado_pago
    mensaje = None
    if accion == "confirmar":
        insc.estado_pago = PAGO_CONFIRMADO
    elif accion == "rechazar":
        insc.estado_pago = PAGO_RECHAZADO
    elif accion == "recordar":
        db.session.commit()
        enviados = avisos.recordar_pago(insc)
        return redirect(url_for("torneos.competencia_panel", comp_id=comp.id,
                                aviso_pago=_texto_recordados(enviados, 1)) + f"#cat-{insc.categoria_id}")
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
    if insc.estado_pago != antes and insc.estado_pago in (PAGO_CONFIRMADO, PAGO_RECHAZADO):
        avisos.pago(insc)   # mail al jugador: dado de alta o revisar el pago
    return redirect(url_for("torneos.competencia_panel", comp_id=comp.id, aviso_pago=mensaje) + f"#cat-{insc.categoria_id}")


def _texto_recordados(enviados, total):
    if not total:
        return "No hay pagos pendientes."
    if not enviados:
        return "No salió ningún mail (falta el mail del jugador o el mail no está configurado). Usá el botón de WhatsApp."
    return f"Le mandamos el recordatorio por mail a {enviados} jugador{'es' if enviados != 1 else ''}."


def deben(comp):
    """Inscripciones activas sin el pago confirmado (solo si la inscripción tiene precio)."""
    if not comp.precio:
        return []
    return [i for c in comp.categorias for i in c.inscripciones if not i.baja and i.estado_pago != PAGO_CONFIRMADO]


def a_revisar(comp):
    """Pagos que esperan que el organizador los revise."""
    return [i for c in comp.categorias for i in c.inscripciones if not i.baja and i.estado_pago == PAGO_PENDIENTE]


@bp.route("/panel/<int:comp_id>/recordar-pagos", methods=["POST"])
@organizador_requerido
def recordar_pagos(comp_id):
    comp = _mi_competencia(comp_id)
    lista = deben(comp)
    enviados = sum(1 for i in lista if avisos.recordar_pago(i))
    return redirect(url_for("torneos.competencia_panel", comp_id=comp.id,
                            aviso_pago=_texto_recordados(enviados, len(lista))) + "#pagos")


@bp.route("/panel/inscripcion/<int:insc_id>/comprobante")
@organizador_requerido
def comprobante(insc_id):
    """El comprobante solo lo ve el organizador de esa competencia."""
    insc = db.session.get(Inscripcion, insc_id)
    if not insc or not insc.comprobante:
        abort(404)
    _mi_competencia(insc.categoria.competencia_id)
    from .archivos import servir
    return servir(insc.comprobante)
