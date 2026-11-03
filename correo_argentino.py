
import json
import os
import base64
import urllib.request
import urllib.error


BASE_URL_TEST = "https://apitest.correoargentino.com.ar/micorreo/v1"
BASE_URL_PROD = "https://api.correoargentino.com.ar/micorreo/v1"

CP_ORIGEN = "1978"

DIMENSIONES = {
    "weight": 2000,
    "height": 15,
    "width": 30,
    "length": 40,
}


class MiCorreoError(Exception):
    """Error controlado de comunicación con MiCorreo."""


def _base_url():
    ambiente = os.getenv("MICORREO_AMBIENTE", "test").lower()

    if ambiente == "test":
        return BASE_URL_TEST

    if ambiente == "prod":
        return BASE_URL_PROD

    raise MiCorreoError("Ambiente de MiCorreo inválido.")


def _solicitar(url, method="GET", headers=None, data=None):
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers or {},
        method=method
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            contenido = response.read().decode("utf-8")
            return json.loads(contenido) if contenido else {}

    except urllib.error.HTTPError as error:
        detalle = error.read().decode("utf-8", errors="replace")
        raise MiCorreoError(
            f"Correo Argentino respondió HTTP {error.code}: {detalle}"
        ) from error

    except urllib.error.URLError as error:
        raise MiCorreoError(
            f"No se pudo conectar con Correo Argentino: {error.reason}"
        ) from error


def obtener_token():
    usuario = os.getenv("MICORREO_API_USER")
    password = os.getenv("MICORREO_API_PASSWORD")

    if not usuario or not password:
        raise MiCorreoError(
            "Faltan las credenciales de la API de MiCorreo."
        )

    credenciales = f"{usuario}:{password}".encode("utf-8")
    basic_auth = base64.b64encode(credenciales).decode("ascii")

    return _solicitar(
        f"{_base_url()}/token",
        method="POST",
        headers={
            "Authorization": f"Basic {basic_auth}",
            "Content-Type": "application/json"
        },
        data=b""
    )["token"]


def cotizar_envio(codigo_postal_destino):
    customer_id = os.getenv("MICORREO_CUSTOMER_ID")

    if not customer_id:
        raise MiCorreoError(
            "Falta configurar MICORREO_CUSTOMER_ID."
        )

    destino = str(codigo_postal_destino).strip()

    if not destino or len(destino) > 10:
        raise MiCorreoError("Código postal de destino inválido.")

    token = obtener_token()

    payload = {
        "customerId": customer_id,
        "postalCodeOrigin": CP_ORIGEN,
        "postalCodeDestination": destino,
        "deliveredType": "D",
        "dimensions": DIMENSIONES
    }

    respuesta = _solicitar(
        f"{_base_url()}/rates",
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        data=json.dumps(payload).encode("utf-8")
    )

    tarifas = respuesta.get("rates", [])

    if not tarifas:
        raise MiCorreoError(
            "Correo Argentino no devolvió tarifas para ese destino."
        )

    return tarifas
