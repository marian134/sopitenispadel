"""Panel del organizador para torneos con cuadro: armar la llave, consuelo,
horarios y opciones."""
from datetime import datetime

from flask import abort, redirect, render_template, request, url_for

from models import db
from . import avisos
from . import cuadro as cdr
from . import zonas as zns
from .bp import bp, contexto
from .models import Categoria, Partido, TIPO_CUADRO, PAR_AGENDADO, PAR_BYE, PAR_EN_DISPUTA, PAR_PENDIENTE
from .panel import _mi_competencia
from .util import link_whatsapp, organizador_requerido


def _mi_categoria(comp_id, cat_id):
    comp = _mi_competencia(comp_id)
    cat = db.session.get(Categoria, cat_id)
    if not cat or cat.competencia_id != comp.id or comp.tipo != TIPO_CUADRO:
        abort(404)
    return comp, cat


def _volver(comp, error=None, ancla=""):
    args = {"comp_id": comp.id}
    if error:
        args["error"] = error
    return redirect(url_for("torneos.competencia_panel", **args) + (f"#{ancla}" if ancla else ""))


@bp.route("/panel/<int:comp_id>/cuadro/<int:cat_id>/armar", methods=["POST"])
@organizador_requerido
def cuadro_armar(comp_id, cat_id):
    comp, cat = _mi_categoria(comp_id, cat_id)
    if zns.activas(comp):
        return _volver(comp, "Este torneo empieza con zonas: armá las zonas primero.", f"cuadro-{cat.id}")
    if cdr.hay_resultados(cat):
        return _volver(comp, "El cuadro ya tiene resultados: no se puede volver a armar.", f"cuadro-{cat.id}")
    try:
        cdr.armar(cat, cdr.participantes(cat))
        cdr._borrar(cat, cdr.CONSUELO)
        cdr._borrar(cat, cdr.TERCER)
    except ValueError as e:
        db.session.rollback()
        return _volver(comp, str(e), f"cuadro-{cat.id}")
    db.session.commit()
    avisos.partidos_nuevos(cdr.partidos(cat))
    return _volver(comp, ancla=f"cuadro-{cat.id}")


@bp.route("/panel/<int:comp_id>/zonas/<int:cat_id>/armar", methods=["POST"])
@organizador_requerido
def zonas_armar(comp_id, cat_id):
    comp, cat = _mi_categoria(comp_id, cat_id)
    if zns.hay_resultados(cat) or cdr.hay_resultados(cat) or cdr.hay_resultados(cat, cdr.PLATA):
        return _volver(comp, "Las zonas ya tienen resultados: no se pueden volver a sortear.", f"cuadro-{cat.id}")
    try:
        zns.armar(cat)
    except ValueError as e:
        db.session.rollback()
        return _volver(comp, str(e), f"cuadro-{cat.id}")
    db.session.commit()
    avisos.partidos_nuevos(zns.partidos(cat))
    return _volver(comp, ancla=f"cuadro-{cat.id}")


@bp.route("/panel/<int:comp_id>/zonas/<int:cat_id>/pasar", methods=["POST"])
@organizador_requerido
def zonas_pasar(comp_id, cat_id):
    """Pasa los clasificados de las zonas al cuadro principal."""
    comp, cat = _mi_categoria(comp_id, cat_id)
    if cdr.hay_resultados(cat) or cdr.hay_resultados(cat, cdr.PLATA):
        return _volver(comp, "El cuadro ya tiene resultados: no se puede volver a armar.", f"cuadro-{cat.id}")
    try:
        zns.pasar_al_cuadro(cat)
    except ValueError as e:
        db.session.rollback()
        return _volver(comp, str(e), f"cuadro-{cat.id}")
    db.session.commit()
    avisos.partidos_nuevos(cdr.partidos(cat) + cdr.partidos(cat, cdr.PLATA))
    return _volver(comp, ancla=f"cuadro-{cat.id}")


@bp.route("/panel/<int:comp_id>/cuadro/<int:cat_id>/consuelo", methods=["POST"])
@organizador_requerido
def cuadro_consuelo(comp_id, cat_id):
    comp, cat = _mi_categoria(comp_id, cat_id)
    if cdr.hay_resultados(cat, cdr.CONSUELO):
        return _volver(comp, "El consuelo ya tiene resultados.", f"cuadro-{cat.id}")
    try:
        cdr.armar_consuelo(cat)
    except ValueError as e:
        db.session.rollback()
        return _volver(comp, f"Consuelo: {e}", f"cuadro-{cat.id}")
    db.session.commit()
    avisos.partidos_nuevos(cdr.partidos(cat, cdr.CONSUELO))
    return _volver(comp, ancla=f"cuadro-{cat.id}")


def _error_horario(comp, p, error):
    return redirect(url_for("torneos.competencia_panel", comp_id=comp.id, error_horario=error,
                            partido_error=p.id) + f"#partido-{p.id}")


@bp.route("/panel/partido/<int:partido_id>/horario", methods=["POST"])
@organizador_requerido
def partido_horario(partido_id):
    p = db.session.get(Partido, partido_id)
    if not p:
        abort(404)
    comp = _mi_competencia(p.competencia_id)
    f = request.form
    dia, hora, cancha = (f.get("dia") or "").strip(), (f.get("hora") or "").strip(), (f.get("cancha") or "").strip()[:40]
    if dia == "otro":   # eligió "Otro día…" en la lista de días habilitados
        dia = (f.get("dia_otro") or "").strip()
    if f.get("fecha_hora") and not dia:   # formato anterior (un solo campo)
        dia, _, hora = f.get("fecha_hora").partition("T")
    faltan = [n for n, v in (("el día", dia), ("la hora", hora), ("la cancha", cancha)) if not v]
    if faltan:
        return _error_horario(comp, p, f"Para guardar el horario falta {', '.join(faltan)}.")
    try:
        nuevo = datetime.strptime(f"{dia}T{hora[:5]}", "%Y-%m-%dT%H:%M")
    except ValueError:
        return _error_horario(comp, p, "El día o la hora no son válidos.")
    cambio = (p.fecha_hora, p.cancha)
    if p.fecha_hora != nuevo:
        p.recordado = False   # si cambió el día, vuelve a salir el recordatorio
    p.fecha_hora, p.cancha = nuevo, cancha
    db.session.commit()
    if cambio != (p.fecha_hora, p.cancha):
        avisos.horario(p)
    return redirect(url_for("torneos.competencia_panel", comp_id=comp.id, guardado=p.id) + f"#partido-{p.id}")


@bp.route("/panel/<int:comp_id>/opciones", methods=["GET", "POST"])
@organizador_requerido
def opciones_cuadro(comp_id):
    comp = _mi_competencia(comp_id)
    if comp.tipo != TIPO_CUADRO:
        abort(404)
    reglas = comp.reglas
    guardado, error = False, None
    if request.method == "POST":
        f = request.form
        reglas["consuelo"] = bool(f.get("consuelo"))
        reglas["tercer_puesto"] = bool(f.get("tercer_puesto"))
        reglas["formato_partido"] = (f.get("formato_partido") or "").strip()[:100]
        reglas["selfie_obligatoria"] = bool(f.get("selfie_obligatoria"))
        try:
            zonas_cfg = {
                "activo": bool(f.get("zonas_activo")),
                "tamano": min(6, max(3, int(f.get("zonas_tamano") or 3))),
                "clasifican": min(4, max(1, int(f.get("zonas_clasifican") or 2))),
                "puntos": {k: float((f.get(f"zp_{k}") or "0").replace(",", "."))
                           for k in ("gana", "pierde", "bonus_set", "gana_wo", "pierde_wo")},
                "desempate": [c for c in (f.get(f"desempate_{n}") for n in range(1, 6))
                              if c in zns.CRITERIOS],
                "plata": bool(f.get("zonas_plata")),
                "nombre_oro": (f.get("nombre_oro") or "").strip()[:40] or "Copa de Oro",
                "nombre_plata": (f.get("nombre_plata") or "").strip()[:40] or "Copa de Plata",
            }
            plazos = {}
            for clave, _nombre in cdr.ETAPAS:
                desde, hasta = f.get(f"plazo_desde_{clave}") or "", f.get(f"plazo_hasta_{clave}") or ""
                if desde or hasta:
                    for v in (desde, hasta):
                        if v:
                            datetime.strptime(v, "%Y-%m-%d")
                    plazos[clave] = {"desde": desde, "hasta": hasta}
        except ValueError:
            error = "Revisá los números y las fechas."
        else:
            reglas["zonas"] = zonas_cfg
            reglas["plazos"] = plazos
            comp.reglas = reglas
            db.session.commit()
            guardado = True
    return render_template(
        "torneos/opciones_cuadro.html",
        **contexto(comp=comp, reglas=reglas, guardado=guardado, error=error, zonas=zns.reglas(comp),
                   criterios=zns.CRITERIOS, etapas=cdr.ETAPAS, plazos=reglas.get("plazos") or {}),
    )


def dias_habilitados(comp, p):
    """Días en que se puede jugar el partido: el plazo de su ronda (Opciones del cuadro)
    o, si no hay, las fechas del torneo. Devuelve (lista de date, texto) o ([], "")."""
    from datetime import timedelta
    plazo = cdr.plazo_de(comp, p)
    desde = (plazo or {}).get("desde") or comp.fecha_inicio
    hasta = (plazo or {}).get("hasta") or comp.fecha_fin
    if not desde or not hasta or hasta < desde or (hasta - desde).days > 60:
        return [], ""
    dias = [desde + timedelta(days=k) for k in range((hasta - desde).days + 1)]
    de_que = f"plazo de {plazo['nombre']}" if plazo and (plazo.get("desde") or plazo.get("hasta")) else "fechas del torneo"
    texto = f"Días habilitados ({de_que}): del {desde.strftime('%d/%m')} al {hasta.strftime('%d/%m')}"
    previo = _ultimo_dia_previo(p)
    if previo:
        dias = [d for d in dias if d > previo]
        if not dias:
            rango = "ninguno"
        elif len(dias) == 1:
            rango = "el " + dias[0].strftime("%d/%m")
        else:
            rango = "del " + dias[0].strftime("%d/%m") + " al " + dias[-1].strftime("%d/%m")
        texto = (f"Días habilitados: {rango}"
                 f" (la ronda anterior se juega hasta el {previo.strftime('%d/%m')}"
                 f"{'' if dias else '; elegí Otro día o cambiá los días de cada ronda'})")
    return dias, texto


def _ultimo_dia_previo(p):
    """Último día cargado en las rondas anteriores de la misma categoría: la ronda
    siguiente solo se puede jugar después."""
    if p.cuadro == cdr.ZONA:
        return None
    otros = Partido.query.filter(Partido.categoria_id == p.categoria_id, Partido.fecha_hora.isnot(None),
                                 Partido.id != p.id).all()
    if p.cuadro == cdr.TERCER:   # va después de las semis (aunque la final todavía no tenga horario)
        total = cdr.rondas_de(db.session.get(Categoria, p.categoria_id))
        previos = [x for x in otros if x.cuadro == cdr.PRINCIPAL and int(x.ronda) < total]
    else:
        previos = [x for x in otros if x.cuadro == p.cuadro and int(x.ronda or 0) < int(p.ronda or 0)]
        if p.cuadro in (cdr.PRINCIPAL, cdr.PLATA):
            previos += [x for x in otros if x.cuadro == cdr.ZONA]
    return max((x.fecha_hora.date() for x in previos), default=None)


def _orden_partido(p):
    """Zonas primero (por fecha y zona), después el cuadro por ronda; el tercer puesto antes de la final."""
    fase = 0 if p.cuadro == cdr.ZONA else 1
    ronda = int(p.ronda or 0)
    if p.cuadro == cdr.TERCER:   # entre las semis y la final
        ronda = cdr.rondas_de(db.session.get(Categoria, p.categoria_id)) - 0.5
    cuadro = {cdr.PRINCIPAL: 0, cdr.TERCER: 0, cdr.PLATA: 1}.get(p.cuadro, 2)   # en cada ronda: Oro, Plata, consuelo
    return (p.categoria_id, fase, p.semana or 0 if p.cuadro == cdr.ZONA else 0, ronda, cuadro, p.posicion or 0)


def siguiente_id(comp):
    """El partido que conviene hacer ahora: primero los que no tienen horario,
    después los que faltan cargar (por fecha). Incluye los de zona."""
    disputa = Partido.query.filter_by(competencia_id=comp.id, estado=PAR_EN_DISPUTA).first()
    if disputa:
        return disputa.id
    ps = [p for p in Partido.query.filter(Partido.competencia_id == comp.id, Partido.estado == PAR_AGENDADO).all()
          if p.lado_a_id or p.lado_b_id]
    sin = sorted([p for p in ps if not p.fecha_hora], key=_orden_partido)
    con = sorted([p for p in ps if p.fecha_hora], key=lambda p: (p.fecha_hora, p.cancha or "") + _orden_partido(p))
    return (sin + con)[0].id if sin or con else None


def resumen_juego(comp, categorias):
    """Para los pasos del panel con el torneo en juego."""
    todos = Partido.query.filter_by(competencia_id=comp.id).all()
    agendados = [p for p in todos if p.estado == PAR_AGENDADO]
    progreso = []
    for c in categorias:
        cat = c["cat"]
        zona = [p for p in todos if p.categoria_id == cat.id and p.cuadro == cdr.ZONA]
        principal = cdr.partidos(cat)
        if zona and not principal:
            jugados = sum(1 for p in zona if p.estado in cdr.TERMINADOS)
            progreso.append(f"{cat.nombre}: zonas, {jugados} de {len(zona)} partidos jugados")
            continue
        if c["campeon"]:
            progreso.append(f"{cat.nombre}: terminado 🏆 {c['campeon'].jugador1.nombre_completo}")
            continue
        for ronda in sorted({int(p.ronda) for p in principal}):
            de_ronda = [p for p in principal if int(p.ronda) == ronda and p.estado != PAR_BYE]
            jugados = sum(1 for p in de_ronda if p.estado in cdr.TERMINADOS)
            if de_ronda and jugados < len(de_ronda):
                progreso.append(f"{cat.nombre}: {cdr.nombre_ronda(cat, cdr.PRINCIPAL, str(ronda))}, "
                                f"{jugados} de {len(de_ronda)} jugados")
                break
    return {
        "armado": bool(todos),
        "sin_horario": sum(1 for p in agendados if not p.fecha_hora),
        "para_resultado": sum(1 for p in agendados if p.fecha_hora),
        "terminado": bool(categorias) and all(c["campeon"] or not c["participantes"] for c in categorias),
        "progreso": progreso,
        # fase de zonas: ¿se jugaron todas? ¿ya se pasó a los clasificados al cuadro?
        "con_zonas": any(p.cuadro == cdr.ZONA for p in todos),
        "zonas_terminadas": all(p.estado in cdr.TERMINADOS + ("anulado",) for p in todos if p.cuadro == cdr.ZONA),
        "zonas_jugados": sum(1 for p in todos if p.cuadro == cdr.ZONA and p.estado in cdr.TERMINADOS + ("anulado",)),
        "zonas_total": sum(1 for p in todos if p.cuadro == cdr.ZONA),
        "cuadro_armado": any(p.cuadro == cdr.PRINCIPAL for p in todos),
        "cat_pasar": next((c["cat"].id for c in categorias if c.get("zonas") and not c["principal"]), None),
    }


def datos_cuadro(comp):
    """Lo que el panel necesita de cada categoría con cuadro."""
    avisos = cdr.avisos_horarios(comp)
    categorias = []
    for cat in sorted(comp.categorias, key=lambda c: c.orden):
        participantes = cdr.participantes(cat)
        t = cdr.tamano(len(participantes)) if len(participantes) >= 2 else 0
        entrantes, pendientes = cdr.entrantes_consuelo(cat) if cdr.partidos(cat) else ([], 0)
        zonas = zns.estructura(cat) if zns.activas(comp) else []
        categorias.append({
            "cat": cat,
            "zonas": zonas,
            "zonas_armadas": bool(zonas),
            "zonas_pendientes": sum(z["pendientes"] for z in zonas),
            "zonas_con_resultados": zns.hay_resultados(cat) if zonas else False,
            "participantes": len(participantes),
            "tamano": t, "byes": t - len(participantes) if t else 0, "max_cabezas": cdr.max_cabezas(t),
            "principal": cdr.estructura(cat),
            "consuelo": cdr.estructura(cat, cdr.CONSUELO),
            "tercer": cdr.partidos(cat, cdr.TERCER),
            "campeon": cdr.campeon(cat), "podio": cdr.podio(cat),
            "plata": cdr.estructura(cat, cdr.PLATA), "campeon_plata": cdr.campeon(cat, cdr.PLATA),
            "campeon_consuelo": cdr.campeon(cat, cdr.CONSUELO),
            "con_resultados": cdr.hay_resultados(cat),
            "consuelo_listo": not pendientes and len(entrantes) >= 2,
            "consuelo_entrantes": len(entrantes), "consuelo_pendientes": pendientes,
        })
    por_jugar = (
        Partido.query.filter(Partido.competencia_id == comp.id,
                             Partido.estado.in_((PAR_AGENDADO, PAR_PENDIENTE, PAR_EN_DISPUTA)))
        .all()
    )
    # también los partidos de zona: se les pone horario y resultado igual que al cuadro
    por_jugar = [p for p in por_jugar if p.lado_a_id or p.lado_b_id]
    por_jugar.sort(key=lambda p: (p.fecha_hora is None, p.fecha_hora or datetime.max) + _orden_partido(p))
    filas = []
    for p in por_jugar:
        cat = p.lado_a.categoria if p.lado_a else p.lado_b.categoria
        if p.estado == PAR_EN_DISPUTA:
            etapa = "disputa"   # los jugadores cargaron resultados distintos: decide el organizador
        elif p.estado == PAR_AGENDADO:
            etapa = "resultado" if p.fecha_hora else "horario"
        else:
            etapa = "espera"   # falta saber quién es el rival
        avisos_wa = []
        if p.estado == PAR_AGENDADO and p.fecha_hora:
            cuando = p.fecha_hora.strftime("%d/%m a las %H:%M")
            for yo, rival in ((p.lado_a, p.lado_b), (p.lado_b, p.lado_a)):
                texto = (f"Hola {yo.jugador1.nombre}! Tu partido de {comp.nombre} ({cat.nombre}, "
                         f"{cdr.nombre_ronda(cat, p.cuadro, p.ronda, p)}) es el {cuando}"
                         f"{' en la cancha ' + p.cancha if p.cancha else ''} contra {rival.jugador1.nombre_completo}.")
                avisos_wa.append((yo.jugador1.nombre, link_whatsapp(yo.jugador1.celular, texto)))
        dias, dias_texto = dias_habilitados(comp, p)
        filas.append({
            "dias": dias, "dias_texto": dias_texto,
            "p": p, "cat": cat, "ronda": cdr.nombre_ronda(cat, p.cuadro, p.ronda, p),
            "avisos": avisos.get(p.id, []), "wa": avisos_wa, "etapa": etapa,
        })
    # primero lo que hay que hacer ya: sin horario, después por jugar (por fecha), al final los que esperan rival
    filas.sort(key=lambda f: {"disputa": 0, "horario": 1, "resultado": 2, "espera": 3}[f["etapa"]])
    siguiente = siguiente_id(comp)
    return {
        "siguiente": siguiente, "resumen": resumen_juego(comp, categorias),
        "categorias": categorias, "por_jugar": filas, "zonas_activas": zns.activas(comp),
        "reglas_zonas": zns.reglas(comp), "vencidos": cdr.plazos_vencidos(comp),
        "plazos": [(nombre, (comp.reglas.get("plazos") or {}).get(clave)) for clave, nombre in cdr.ETAPAS
                   if (comp.reglas.get("plazos") or {}).get(clave)],
    }
