"""
Medición propia de visitas (anónima), guardada en la base de la tienda.

- Cada página vista por un cliente queda registrada (sin bots, sin el admin).
- Al visitante se lo reconoce por una cookie anónima "sopi_v" (no se guarda IP ni nombre).
- Los clics a WhatsApp, agregar al carrito, iniciar compra y búsquedas llegan por /evento.
- Se borra solo lo que tiene más de DIAS_GUARDADO días.

Lo engancha dashboard_admin.init_app(); no hace falta tocar app.py.
"""
import re
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import request, session, jsonify

from models import db

COOKIE = "sopi_v"
DIAS_GUARDADO = 180

# Rutas que no son visitas de clientes
NO_MEDIR = ("/admin", "/static", "/health", "/feed", "/sitemap", "/robots", "/favicon",
            "/mp/", "/google", "/evento", "/envio/")
BOTS = re.compile(r"bot|crawl|spider|slurp|facebookexternalhit|uptimerobot|preview|lighthouse|"
                  r"headless|python|curl|wget|monitor|scan", re.I)
MOVIL = re.compile(r"mobi|android|iphone|ipad", re.I)

# Eventos que acepta /evento (los mismos nombres que usa sopiEvento en base.html)
EVENTOS = {"add_to_cart", "begin_checkout", "contacto_whatsapp", "search", "generate_lead"}


class Visita(db.Model):
    __tablename__ = "visitas"

    id = db.Column(db.Integer, primary_key=True)
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    visitante = db.Column(db.String(24), nullable=False, index=True)
    tipo = db.Column(db.String(30), nullable=False, default="vista")  # vista | nombre del evento
    ruta = db.Column(db.String(200), nullable=False, default="")
    origen = db.Column(db.String(60), nullable=True)      # Instagram, Google, WhatsApp, Directo...
    dispositivo = db.Column(db.String(10), nullable=True)  # Celular | Compu
    detalle = db.Column(db.String(150), nullable=True)     # producto, búsqueda, botón de WhatsApp...


def clasificar_origen(referrer, utm, host_propio):
    """De dónde llegó la persona. None = navegación dentro de la tienda."""
    utm = (utm or "").lower()
    if utm:
        if utm in ("ig", "instagram"):
            return "Instagram"
        if utm in ("fb", "facebook"):
            return "Facebook"
        if "whatsapp" in utm or utm == "wa":
            return "WhatsApp"
        if "google" in utm:
            return "Google"
        return utm[:60]
    if not referrer:
        return "Directo"
    dominio = (urlparse(referrer).hostname or "").lower()
    if not dominio or dominio == host_propio or dominio.endswith("." + host_propio):
        return None
    for clave, nombre in (("instagram", "Instagram"), ("facebook", "Facebook"), ("fb.", "Facebook"),
                          ("whatsapp", "WhatsApp"), ("wa.me", "WhatsApp"), ("google", "Google"),
                          ("bing", "Bing"), ("mercadopago", "Mercado Pago"), ("mercadolibre", "Mercado Libre")):
        if clave in dominio:
            return nombre
    return dominio[:60]


def _es_cliente():
    ua = request.headers.get("User-Agent", "")
    return bool(ua) and not BOTS.search(ua) and not session.get("admin")


def _visitante():
    vid = request.cookies.get(COOKIE)
    if vid and re.fullmatch(r"[A-Za-z0-9_-]{8,24}", vid):
        return vid, False
    return secrets.token_urlsafe(12)[:16], True


def _dispositivo():
    return "Celular" if MOVIL.search(request.headers.get("User-Agent", "")) else "Compu"


def borrar_viejas():
    limite = datetime.utcnow() - timedelta(days=DIAS_GUARDADO)
    Visita.query.filter(Visita.creado_en < limite).delete(synchronize_session=False)
    db.session.commit()


def init_app(app):
    with app.app_context():
        Visita.__table__.create(db.engine, checkfirst=True)

    @app.after_request
    def registrar_visita(resp):
        try:
            if (request.method != "GET" or resp.status_code != 200
                    or resp.mimetype != "text/html"
                    or request.path.startswith(NO_MEDIR) or not _es_cliente()):
                return resp
            vid, nuevo = _visitante()
            db.session.add(Visita(
                visitante=vid, tipo="vista", ruta=request.path[:200],
                origen=clasificar_origen(request.referrer, request.args.get("utm_source"), request.host.split(":")[0]),
                dispositivo=_dispositivo(),
            ))
            db.session.commit()
            if nuevo:
                resp.set_cookie(COOKIE, vid, max_age=365 * 24 * 3600, samesite="Lax",
                                secure=request.is_secure, httponly=True)
        except Exception:
            db.session.rollback()  # la medición nunca rompe la página
        return resp

    @app.route("/evento", methods=["POST"])
    def evento():
        datos = request.get_json(silent=True, force=True) or {}
        nombre = str(datos.get("nombre", ""))
        if nombre not in EVENTOS or not _es_cliente():
            return ("", 204)
        info = datos.get("datos") or {}
        items = info.get("items") or [{}]
        detalle = (info.get("origen") or info.get("search_term")
                   or (items[0].get("item_name") if isinstance(items[0], dict) else "") or "")
        vid, _ = _visitante()
        try:
            db.session.add(Visita(
                visitante=vid, tipo=nombre,
                ruta=str(info.get("pagina") or urlparse(request.referrer or "").path or "")[:200],
                dispositivo=_dispositivo(), detalle=str(detalle)[:150],
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
        return ("", 204)


def datos_visitas(desde_utc, pagados, nombre_por_slug):
    """Resumen de visitas para el dashboard."""
    filas = Visita.query.filter(Visita.creado_en >= desde_utc).all()
    # Solo se comparan las compras hechas desde que se empezó a medir
    inicio = min((f.creado_en for f in filas), default=None)
    cant_pagados = sum(1 for p in pagados if inicio and p.creado_en >= inicio)
    vistas = [f for f in filas if f.tipo == "vista"]
    visitantes = {f.visitante for f in vistas}

    # Origen: el primero externo de cada visitante en el período
    origen_de = {}
    for f in sorted(vistas, key=lambda f: f.creado_en):
        if f.origen and f.visitante not in origen_de:
            origen_de[f.visitante] = f.origen
    origenes = {}
    for o in origen_de.values():
        origenes[o] = origenes.get(o, 0) + 1

    dispositivos = {}
    for f in vistas:
        dispositivos.setdefault(f.dispositivo or "Compu", set()).add(f.visitante)

    productos_vistos = {}
    for f in vistas:
        if f.ruta.startswith("/producto/"):
            slug = f.ruta.split("/")[2]
            nombre = nombre_por_slug.get(slug, slug)
            p = productos_vistos.setdefault(nombre, {"nombre": nombre, "vistas": 0, "personas": set()})
            p["vistas"] += 1
            p["personas"].add(f.visitante)

    paginas = {}
    for f in vistas:
        paginas[f.ruta] = paginas.get(f.ruta, 0) + 1

    def personas(tipo):
        return len({f.visitante for f in filas if f.tipo == tipo})

    whatsapp = {}
    for f in filas:
        if f.tipo == "contacto_whatsapp":
            whatsapp[f.detalle or "otro"] = whatsapp.get(f.detalle or "otro", 0) + 1

    busquedas = {}
    for f in filas:
        if f.tipo == "search" and f.detalle:
            clave = f.detalle.strip().lower()
            busquedas[clave] = busquedas.get(clave, 0) + 1

    embudo = [
        ("Entraron a la tienda", len(visitantes)),
        ("Vieron un producto", len({f.visitante for f in vistas if f.ruta.startswith("/producto/")})),
        ("Agregaron al carrito", personas("add_to_cart")),
        ("Iniciaron la compra", personas("begin_checkout")),
        ("Pagaron", cant_pagados),
    ]

    return dict(
        v_vistas=len(vistas), v_visitantes=len(visitantes),
        v_whatsapp=sum(whatsapp.values()), v_whatsapp_personas=personas("contacto_whatsapp"),
        v_origenes=sorted(origenes.items(), key=lambda kv: kv[1], reverse=True),
        v_dispositivos=sorted(((d, len(s)) for d, s in dispositivos.items()), key=lambda kv: kv[1], reverse=True),
        v_productos=sorted(({"nombre": p["nombre"], "vistas": p["vistas"], "personas": len(p["personas"])}
                            for p in productos_vistos.values()), key=lambda p: p["vistas"], reverse=True)[:10],
        v_paginas=sorted(paginas.items(), key=lambda kv: kv[1], reverse=True)[:8],
        v_whatsapp_botones=sorted(whatsapp.items(), key=lambda kv: kv[1], reverse=True),
        v_busquedas=sorted(busquedas.items(), key=lambda kv: kv[1], reverse=True)[:8],
        v_embudo=embudo, v_pagados=cant_pagados,
    )
