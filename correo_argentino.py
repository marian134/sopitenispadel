import base64
import json
import os
import time
import urllib.error
import urllib.request

BASE_URL_TEST = "https://apitest.correoargentino.com.ar/micorreo/v1"
BASE_URL_PROD = "https://api.correoargentino.com.ar/micorreo/v1"

CP_ORIGEN = os.getenv("MICORREO_CP_ORIGEN", "1878")  # verificá el tuyo
CACHE_TARIFAS_SEG = 600

_token = {"valor": None, "vence": 0.0}
_cache = {}


class MiCorreoError(Exception):
    def __init__(self, mensaje, status=None):
        super().__init__(mensaje)
        self.status = status


def _base_url():
    ambiente = os.getenv("MICORREO_AMBIENTE", "test").lower()
    if ambiente == "test":
        return BASE_URL_TEST
    if ambiente == "prod":
        return BASE_URL_PROD
    raise MiCorreoError("Ambiente de MiCorreo inválido.")


def _solicitar(url, method="GET", headers=None, data=None):
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            contenido = response.read().decode("utf-8")
            return json.loads(contenido) if contenido else {}
    except urllib.error.HTTPError as error:
        detalle = error.read().decode("utf-8", errors="replace")
        raise MiCorreoError(
            f"Correo Argentino respondió HTTP {error.code}: {detalle}", status=error.code
        ) from error
    except urllib.error.URLError as error:
        raise MiCorreoError(f"No se pudo conectar con Correo Argentino: {error.reason}") from error


def obtener_token(forzar=False):
    if not forzar and _token["valor"] and time.time() < _token["vence"]:
        return _token["valor"]

    usuario = os.getenv("MICORREO_API_USER")
    password = os.getenv("MICORREO_API_PASSWORD")
    if not usuario or not password:
        raise MiCorreoError("Faltan las credenciales de la API de MiCorreo.")

    basic = base64.b64encode(f"{usuario}:{password}".encode("utf-8")).decode("ascii")
    token = _solicitar(
        f"{_base_url()}/token",
        method="POST",
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/json"},
        data=b"",
    )["token"]

    _token.update(valor=token, vence=time.time() + 25 * 60)
    return token


def _post_autenticado(ruta, payload):
    for intento in (1, 2):
        try:
            return _solicitar(
                f"{_base_url()}{ruta}",
                method="POST",
                headers={
                    "Authorization": f"Bearer {obtener_token(forzar=(intento == 2))}",
                    "Content-Type": "application/json",
                },
                data=json.dumps(payload).encode("utf-8"),
            )
        except MiCorreoError as e:
            if e.status == 401 and intento == 1:
                continue  # token vencido: se renueva y se reintenta una vez
            raise


def cotizar_envio(cp_destino, dimensiones, tipo="D"):
    """Devuelve [{'codigo','nombre','precio','plazo_min','plazo_max'}], de más barata a más cara."""
    customer_id = os.getenv("MICORREO_CUSTOMER_ID")
    if not customer_id:
        raise MiCorreoError("Falta configurar MICORREO_CUSTOMER_ID.")

    destino = str(cp_destino).strip()
    if not (destino.isdigit() and len(destino) == 4):
        raise MiCorreoError("Código postal de destino inválido.")

    clave = (destino, tipo, tuple(sorted(dimensiones.items())))
    hit = _cache.get(clave)
    if hit and time.time() < hit[0]:
        return hit[1]

    respuesta = _post_autenticado("/rates", {
        "customerId": customer_id,
        "postalCodeOrigin": CP_ORIGEN,
        "postalCodeDestination": destino,
        "deliveredType": tipo,
        "dimensions": dimensiones,
    })

    tarifas = []
    for t in respuesta.get("rates", []):
        precio = int(round(float(t.get("price") or 0)))
        if precio > 0:
            tarifas.append({
                "codigo": str(t.get("productType") or t.get("productName") or ""),
                "nombre": t.get("productName") or "Correo Argentino",
                "precio": precio,
                "plazo_min": t.get("deliveryTimeMin"),
                "plazo_max": t.get("deliveryTimeMax"),
            })

    if not tarifas:
        raise MiCorreoError("Correo Argentino no devolvió tarifas para ese destino.")

    tarifas.sort(key=lambda t: t["precio"])
    _cache[clave] = (time.time() + CACHE_TARIFAS_SEG, tarifas)
    return tarifas