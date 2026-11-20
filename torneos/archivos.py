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


def guardar(datos, ext):
    """Guarda los bytes y devuelve el nombre interno para la base de datos."""
    nombre = secrets.token_urlsafe(16)
    nube = _cloudinary()
    if nube:
        import requests
        cuenta, clave, secreto = nube
        params = {"folder": "sopi-torneos", "public_id": nombre, "timestamp": str(int(time.time()))}
        firma = hashlib.sha1(
            ("&".join(f"{k}={params[k]}" for k in sorted(params)) + secreto).encode()
        ).hexdigest()
        r = requests.post(
            f"https://api.cloudinary.com/v1_1/{cuenta}/auto/upload",
            data={**params, "api_key": clave, "signature": firma},
            files={"file": (nombre + ext, datos)},
            timeout=30,
        )
        if r.status_code != 200:
            current_app.logger.error("Cloudinary respondió %s: %s", r.status_code, r.text[:300])
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
