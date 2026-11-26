"""Dónde se guardan los archivos que suben los usuarios (comprobantes,
selfies, logos).

- En producción (Render) el disco se borra en cada actualización, así que se
  guardan en Cloudinary: alcanza con poner la variable de entorno
  CLOUDINARY_URL=cloudinary://API_KEY:API_SECRET@NOMBRE_DE_LA_CUENTA
  (la da Cloudinary en su panel; tiene plan gratis).
- Sin esa variable (en local) se guardan en instance/torneos_archivos.

Los archivos nunca se muestran con la dirección de Cloudinary: siempre pasan
por las rutas de torneos, que revisan quién puede verlos.
"""
import hashlib
import mimetypes
import os
import secrets
import time
from urllib.parse import urlparse

from flask import Response, abort, current_app, send_from_directory

CARPETA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "instance", "torneos_archivos"
)
PREFIJO_NUBE = "cld:"


def _cloudinary():
    """(cuenta, clave, secreto) de CLOUDINARY_URL, o None si no está."""
    url = os.environ.get("CLOUDINARY_URL", "").strip()
    if not url.startswith("cloudinary://"):
        return None
    p = urlparse(url)
    if not (p.username and p.password and p.hostname):
        return None
    return p.hostname, p.username, p.password


_MOTIVOS = [
    ("invalid signature", "la clave secreta (API Secret) no coincide"),
    ("unknown api key", "la API Key no existe en esa cuenta"),
    ("invalid api_key", "la API Key no es válida"),
    ("invalid cloud_name", "el nombre de la cuenta (lo que va después de la @) no existe"),
    ("cloud_name is disabled", "la cuenta de Cloudinary está deshabilitada"),
    ("stale request", "la hora del servidor no coincide con la de Cloudinary"),
]


def _motivo(respuesta):
    """Explica en castellano por qué Cloudinary rechazó el archivo."""
    try:
        texto = respuesta.json().get("error", {}).get("message", "") or respuesta.text
    except ValueError:
        texto = respuesta.text
    bajo = (texto or "").lower()
    for clave, explicacion in _MOTIVOS:
        if clave in bajo:
            return explicacion, texto[:200]
    return f"Cloudinary contestó {respuesta.status_code}", (texto or "")[:200]


def _subir(nube, datos, nombre, ext, carpeta="sopi-torneos"):
    """Sube a Cloudinary. Prueba la firma SHA-1 y, si la cuenta pide SHA-256, reintenta."""
    import requests
    cuenta, clave, secreto = nube
    params = {"folder": carpeta, "public_id": nombre, "timestamp": str(int(time.time()))}
    texto = "&".join(f"{k}={params[k]}" for k in sorted(params)) + secreto
    r = None
    for algoritmo in (hashlib.sha1, hashlib.sha256):
        r = requests.post(
            f"https://api.cloudinary.com/v1_1/{cuenta}/auto/upload",
            data={**params, "api_key": clave, "signature": algoritmo(texto.encode()).hexdigest()},
            files={"file": (nombre + ext, datos)},
            timeout=30,
        )
        if r.status_code == 200 or "signature" not in r.text.lower():
            break
    return r


def guardar(datos, ext):
    """Guarda los bytes y devuelve el nombre interno para la base de datos."""
    nombre = secrets.token_urlsafe(16)
    nube = _cloudinary()
    if nube:
        import requests
        try:
            r = _subir(nube, datos, nombre, ext)
        except requests.RequestException:
            current_app.logger.exception("No se pudo conectar con Cloudinary")
            raise ValueError("No pudimos guardar el archivo. Probá de nuevo en un momento.")
        if r.status_code != 200:
            explicacion, detalle = _motivo(r)
            current_app.logger.error("Cloudinary rechazó el archivo (%s): %s", explicacion, detalle)
            raise ValueError("No pudimos guardar el archivo. Probá de nuevo en un momento.")
        return PREFIJO_NUBE + r.json()["secure_url"]
    os.makedirs(CARPETA, exist_ok=True)
    with open(os.path.join(CARPETA, nombre + ext), "wb") as f:
        f.write(datos)
    return nombre + ext


def servir(nombre):
    """Devuelve el archivo para mostrarlo (quien llama ya revisó el permiso)."""
    if not nombre:
        abort(404)
    if nombre.startswith(PREFIJO_NUBE):
        import requests
        url = nombre[len(PREFIJO_NUBE):]
        try:
            r = requests.get(url, timeout=30)
        except requests.RequestException:
            abort(502)
        if r.status_code != 200:
            abort(404)
        tipo = r.headers.get("Content-Type") or mimetypes.guess_type(url)[0] or "application/octet-stream"
        return Response(r.content, mimetype=tipo, headers={"Cache-Control": "private, max-age=3600"})
    return send_from_directory(CARPETA, os.path.basename(nombre))


# Imagen PNG de 1x1 para probar la conexión
_PNG_PRUEBA = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c63785a67f31f00068a029fe676c4460000000049454e44ae426082")


def probar_nube():
    """Diagnóstico para el admin: revisa CLOUDINARY_URL y sube una imagen de prueba."""
    crudo = os.environ.get("CLOUDINARY_URL", "")
    if not crudo.strip():
        return {"ok": False, "texto": "No está cargada la variable CLOUDINARY_URL en Render."}
    avisos = []
    if crudo != crudo.strip():
        avisos.append("tiene espacios al principio o al final")
    if crudo.strip().upper().startswith("CLOUDINARY_URL="):
        avisos.append("empieza con \"CLOUDINARY_URL=\": hay que borrar esa parte y dejar desde cloudinary://")
    if "*" in crudo:
        avisos.append("tiene asteriscos: el API Secret quedó tapado al copiarlo")
    nube = _cloudinary()
    if not nube:
        return {"ok": False, "texto": "La variable CLOUDINARY_URL no tiene el formato "
                "cloudinary://API_KEY:API_SECRET@NOMBRE_DE_LA_CUENTA"
                + (" (" + "; ".join(avisos) + ")" if avisos else ".")}
    cuenta, clave, secreto = nube
    datos = f"Cuenta: {cuenta} · API Key terminada en {clave[-4:]} · API Secret de {len(secreto)} caracteres"
    import requests
    try:
        r = _subir(nube, _PNG_PRUEBA, "prueba-" + secrets.token_hex(4), ".png", carpeta="sopi-torneos/pruebas")
    except requests.RequestException as e:
        return {"ok": False, "datos": datos, "texto": f"No se pudo conectar con Cloudinary ({e.__class__.__name__})."}
    if r.status_code == 200:
        return {"ok": True, "datos": datos,
                "texto": "¡Funciona! Se subió una imagen de prueba a la carpeta sopi-torneos/pruebas."}
    explicacion, detalle = _motivo(r)
    return {"ok": False, "datos": datos,
            "texto": f"Cloudinary lo rechazó: {explicacion}."
                     + (" Además la variable " + "; ".join(avisos) + "." if avisos else ""),
            "detalle": detalle}
