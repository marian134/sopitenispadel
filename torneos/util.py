"""Funciones chicas que usan varias partes del módulo de torneos."""
import os
import re
import secrets
import unicodedata
from functools import wraps
from urllib.parse import quote

from flask import current_app, redirect, request, session, url_for
from flask_mail import Message

from models import db
from .models import Organizador

# Archivos que suben los jugadores (comprobantes, selfies). En local se
# guardan en instance/torneos_archivos; antes de publicar se pasa a un
# servicio de imágenes externo (ver "Plan técnico").
CARPETA_ARCHIVOS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "instance", "torneos_archivos"
)
EXTENSIONES_OK = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf"}
TAMANO_MAXIMO = 8 * 1024 * 1024  # 8 MB


def slugify(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = texto.encode("ascii", "ignore").decode("ascii").lower()
    texto = re.sub(r"[^a-z0-9]+", "-", texto).strip("-")
    return texto[:100] or "torneo"


# Palabras que ya usan las direcciones de /torneos: un torneo no puede llamarse así
SLUGS_RESERVADOS = {
    "organizar", "ingresar", "salir", "panel", "jugador", "recuperar-enlace", "admin", "archivo",
}


def slug_unico(modelo, nombre, excluir_id=None):
    base = slugify(nombre)
    if base in SLUGS_RESERVADOS:
        base += "-torneo"
    slug, n = base, 2
    while True:
        q = modelo.query.filter_by(slug=slug)
        if excluir_id:
            q = q.filter(modelo.id != excluir_id)
        if not q.first():
            return slug
        slug = f"{base}-{n}"
        n += 1


def pesos(valor):
    return "$" + f"{int(valor or 0):,}".replace(",", ".")


def solo_digitos(texto):
    return re.sub(r"\D", "", texto or "")


def numero_whatsapp(celular):
    """Lleva un celular argentino al formato de wa.me (549 + área + número)."""
    d = solo_digitos(celular)
    if d.startswith("00"):
        d = d[2:]
    if d.startswith("54"):
        return d
    d = d.lstrip("0")
    # "11 15 2832-1531" -> sacar el 15 después del código de área de 2 a 4 dígitos
    m = re.match(r"^(\d{2,4})15(\d{6,8})$", d)
    if m and len(m.group(1) + m.group(2)) == 10:
        d = m.group(1) + m.group(2)
    return "549" + d if len(d) == 10 else d


def link_whatsapp(celular, texto):
    numero = numero_whatsapp(celular)
    base = f"https://wa.me/{numero}" if numero else "https://wa.me/"
    return f"{base}?text={quote(texto)}"


def guardar_archivo(archivo):
    """Guarda un archivo subido y devuelve su nombre interno, o lanza
    ValueError con un mensaje para mostrar."""
    if not archivo or not archivo.filename:
        raise ValueError("Falta adjuntar el archivo.")
    ext = os.path.splitext(archivo.filename)[1].lower()
    if ext not in EXTENSIONES_OK:
        raise ValueError("El archivo tiene que ser una foto (JPG, PNG, WEBP, HEIC) o un PDF.")
    datos = archivo.read(TAMANO_MAXIMO + 1)
    if len(datos) > TAMANO_MAXIMO:
        raise ValueError("El archivo pesa más de 8 MB.")
    if not datos:
        raise ValueError("El archivo está vacío.")
    os.makedirs(CARPETA_ARCHIVOS, exist_ok=True)
    nombre = secrets.token_urlsafe(16) + ext
    with open(os.path.join(CARPETA_ARCHIVOS, nombre), "wb") as f:
        f.write(datos)
    return nombre


def enviar_mail(destino, asunto, cuerpo):
    """Manda un mail sin cortar nada si falla o si el mail no está configurado."""
    if not destino:
        return False
    if not current_app.config.get("MAIL_USERNAME") or not current_app.config.get("MAIL_PASSWORD"):
        current_app.logger.info("Mail de torneos no enviado (falta configurar el mail): %s", asunto)
        return False
    try:
        current_app.extensions["mail"].send(Message(subject=asunto, recipients=[destino], body=cuerpo))
        return True
    except Exception:
        current_app.logger.exception("Error enviando mail de torneos")
        return False


# ---------------------------------------------------------
# SESIÓN DEL ORGANIZADOR
# ---------------------------------------------------------
def organizador_actual():
    org_id = session.get("torneo_org_id")
    if not org_id:
        return None
    org = db.session.get(Organizador, org_id)
    if not org or not org.activo:
        session.pop("torneo_org_id", None)
        return None
    return org


def organizador_requerido(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if not organizador_actual():
            return redirect(url_for("torneos.ingresar", siguiente=request.path))
        return vista(*args, **kwargs)
    return envoltura
