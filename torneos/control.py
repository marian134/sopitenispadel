"""Control de cuentas de organizadores para Sopi.

- Un WhatsApp por cuenta (se compara normalizado: con o sin 0, 15, +54).
- Plan gratis: un torneo de hasta TOPE_GRATIS jugadores.
- Posibles repetidos: mismo celular, mismo navegador, misma conexión,
  nombre de club parecido o el mismo mail con otro dominio.
- Las cuentas nuevas necesitan que Sopi las apruebe para publicar el
  primer torneo (aviso por mail a TORNEOS_AVISOS_EMAIL o VENTAS_EMAIL).
"""
import os
import re
import secrets
import unicodedata
from difflib import SequenceMatcher

from flask import current_app, request, url_for

from .models import Organizador, PLAN_GRATIS
from .util import enviar_mail, link_whatsapp

TOPE_GRATIS = 16          # jugadores por torneo en el plan gratis (una pareja = 2)
COOKIE_EQUIPO = "torneos_equipo"


# ---------------------------------------------------------
# WHATSAPP ÚNICO
# ---------------------------------------------------------
def normal_whatsapp(texto):
    """Deja el número en 10 dígitos (código de área + número), sin 0, 15 ni +54."""
    d = re.sub(r"\D", "", texto or "")
    if d.startswith("54"):
        d = d[2:]
    if d.startswith("9") and len(d) == 11:
        d = d[1:]
    if d.startswith("0"):
        d = d[1:]
    if len(d) == 12:   # código de área + 15 + número
        for corte in (2, 3, 4):
            if d[corte:corte + 2] == "15":
                d = d[:corte] + d[corte + 2:]
                break
    return d[-10:] if len(d) >= 10 else d


def whatsapp_usado(texto, salvo_id=None):
    """Devuelve el organizador que ya usa ese WhatsApp (o None)."""
    buscado = normal_whatsapp(texto)
    if len(buscado) < 8:
        return None
    for org in Organizador.query.all():
        if org.id != salvo_id and normal_whatsapp(org.whatsapp) == buscado:
            return org
    return None


# ---------------------------------------------------------
# TOPE DEL PLAN GRATIS
# ---------------------------------------------------------
def jugadores_anotados(comp):
    return sum(2 if i.jugador2_id else 1
               for cat in comp.categorias for i in cat.inscripciones if not i.baja)


def lugares_plan(comp):
    """Lugares que le quedan al torneo por el plan gratis (None si no hay tope)."""
    if comp.organizador.plan != PLAN_GRATIS:
        return None
    return max(0, TOPE_GRATIS - jugadores_anotados(comp))


def entra_en_plan(comp, cuantos):
    libres = lugares_plan(comp)
    return libres is None or libres >= cuantos


def mensaje_tope(para_organizador=True):
    if para_organizador:
        return (f"El plan gratis permite hasta {TOPE_GRATIS} jugadores por torneo. "
                "Para anotar más, pedile a SOPI el plan pago.")
    return "Este torneo ya no tiene lugares."


# ---------------------------------------------------------
# HUELLA DEL ALTA: navegador y conexión
# ---------------------------------------------------------
def ip_actual():
    return (request.headers.get("CF-Connecting-IP")
            or (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
            or request.remote_addr or "")[:64]


def equipo_actual():
    """Identificador de este navegador (cookie). Lo crea si no existe."""
    valor = request.cookies.get(COOKIE_EQUIPO, "")
    return valor if re.fullmatch(r"[\w-]{16,40}", valor) else secrets.token_urlsafe(18)


def guardar_cookie_equipo(resp, valor):
    resp.set_cookie(COOKIE_EQUIPO, valor, max_age=5 * 365 * 24 * 3600, httponly=True,
                    secure=request.is_secure or bool(os.environ.get("RENDER")), samesite="Lax")
    return resp


# ---------------------------------------------------------
# POSIBLES REPETIDOS
# ---------------------------------------------------------
_PALABRAS_COMUNES = {"club", "tenis", "padel", "torneo", "torneos", "de", "del", "la", "el", "los", "las",
                     "academia", "escuela", "atletico", "social", "deportivo", "sport", "sports", "y"}


def _normal_nombre(texto):
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    palabras = [p for p in re.findall(r"[a-z0-9]+", t) if p not in _PALABRAS_COMUNES]
    return " ".join(palabras)


def _usuario_mail(mail):
    usuario, _, dominio = (mail or "").lower().partition("@")
    usuario = usuario.split("+")[0]
    if dominio in ("gmail.com", "googlemail.com"):
        usuario = usuario.replace(".", "")
    return usuario


def parecidos(org, todos=None):
    """Lista de (otro organizador, [motivos]) que podrían ser la misma persona."""
    todos = todos if todos is not None else Organizador.query.all()
    nombre = _normal_nombre(org.nombre)
    wa = normal_whatsapp(org.whatsapp)
    usuario = _usuario_mail(org.email)
    salida = []
    for otro in todos:
        if otro.id == org.id:
            continue
        motivos = []
        if len(wa) >= 8 and normal_whatsapp(otro.whatsapp) == wa:
            motivos.append("mismo WhatsApp")
        if org.equipo and otro.equipo == org.equipo:
            motivos.append("mismo celular o computadora")
        if org.ip_alta and otro.ip_alta == org.ip_alta:
            motivos.append("misma conexión a internet")
        otro_nombre = _normal_nombre(otro.nombre)
        if nombre and otro_nombre and (nombre == otro_nombre
                                       or SequenceMatcher(None, nombre, otro_nombre).ratio() >= 0.85):
            motivos.append("nombre parecido")
        if len(usuario) >= 4 and _usuario_mail(otro.email) == usuario:
            motivos.append("mismo mail con otro dominio" if otro.email.lower() != org.email.lower() else "mismo mail")
        if motivos:
            salida.append((otro, motivos))
    return salida


# ---------------------------------------------------------
# AVISOS A SOPI
# ---------------------------------------------------------
def _destino_sopi():
    """Mail donde Sopi recibe los avisos de torneos: TORNEOS_AVISOS_EMAIL
    (si no está, el de los avisos de venta de la tienda)."""
    return (os.environ.get("TORNEOS_AVISOS_EMAIL") or os.environ.get("VENTAS_EMAIL") or "").strip()


def _ficha(org):
    return (f"Nombre: {org.nombre}\n"
            f"Mail: {org.email}\n"
            f"WhatsApp: {org.whatsapp or '-'}\n"
            f"Plan: {org.plan}\n")


def avisar_alta(org):
    """Mail a Sopi cuando se crea una cuenta de organizador."""
    lista = parecidos(org)
    alerta = ""
    if lista:
        alerta = "\n⚠️ POSIBLE CUENTA REPETIDA:\n" + "".join(
            f"- {o.nombre} ({o.email}): {', '.join(m)}\n" for o, m in lista)
    wa = link_whatsapp(org.whatsapp, f"Hola {org.nombre}! Te escribo de SOPI Torneos por tu cuenta nueva.")
    cuerpo = (
        "Se creó una cuenta nueva de organizador en SOPI Torneos.\n\n"
        + _ficha(org) + alerta
        + "\nPuede armar su torneo, pero para publicarlo tenés que aprobar la cuenta en el admin:\n"
        + url_for("torneos_admin.inicio", _external=True) + f"#org-{org.id}\n"
        + (f"\nEscribirle por WhatsApp: {wa}\n" if wa else "")
    )
    asunto = ("⚠️ " if lista else "") + f"Nuevo organizador en Torneos: {org.nombre}"
    return enviar_mail(_destino_sopi(), asunto, cuerpo)


def avisar_pide_publicar(org, comp):
    """Mail a Sopi: un organizador sin aprobar quiere publicar su torneo."""
    cuerpo = (
        f"{org.nombre} quiere publicar el torneo \"{comp.nombre}\" y su cuenta todavía no está aprobada.\n\n"
        + _ficha(org)
        + "\nAprobala desde el admin y el torneo se publica solo:\n"
        + url_for("torneos_admin.inicio", _external=True) + f"#org-{org.id}\n"
    )
    return enviar_mail(_destino_sopi(), f"Pide publicar: {comp.nombre} ({org.nombre})", cuerpo)


def avisar_aprobado(org, publicados):
    """Mail al organizador cuando Sopi aprueba su cuenta."""
    if publicados:
        detalle = "Ya publicamos tu torneo: " + ", ".join(c.nombre for c in publicados) + ". Los jugadores ya se pueden inscribir."
    else:
        detalle = "Ya podés publicar tus torneos desde el panel."
    cuerpo = (f"¡Hola {org.nombre}!\n\nAprobamos tu cuenta de SOPI Torneos. {detalle}\n\n"
              + url_for("torneos.panel", _external=True) + "\n\nCualquier duda, escribinos.\nSOPI Tenis y Pádel")
    try:
        return enviar_mail(org.email, "Tu cuenta de SOPI Torneos está aprobada", cuerpo)
    except Exception:
        current_app.logger.exception("No se pudo avisar la aprobación")
        return False
