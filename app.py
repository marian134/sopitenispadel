from flask import Flask, render_template, request, redirect, url_for, session, abort, Response
import os
import re
import csv
import io
import hmac
import unicodedata
import mercadopago
import correo_argentino as micorreo
from templates import legales
from datetime import timedelta, datetime, date
from functools import wraps
from flask_mail import Mail, Message
from sqlalchemy import inspect, text
from urllib.parse import urlencode, quote
from xml.sax.saxutils import escape
from models import (
    db, Producto, Pedido, LineaPedido, Cupon, CuponUso, parsear_talles,
    ESTADO_PENDIENTE, ESTADO_PAGADO, ESTADO_FALLIDO,
)

# =========================================================
# APP
# =========================================================

app = Flask(__name__)

POPUP = {
    "id": "cajas-profes-oct26",
    "titulo": "Cajas x24 para profes y clubes",
    "texto": "Head Pro, Head Championship y Penn Premier con envío gratis.",
    "cta": "Consultar por WhatsApp",
    "url": "https://wa.me/5491128321531?text=Hola%20SOPI!%20Quiero%20info%20de%20las%20cajas",
}
ES_PRODUCCION = os.environ.get("URL_BASE", "").startswith("https://")
BANNERS = [
    {
        "titulo": "Ya trabajamos con HEAD",
        "cta": "Ver productos",
        "url": "/catalogo/tenis?marca=Head",
        "imagen": "banner_head.png",
        "fondo": "#ffffff",
    },
    {
        "etiqueta": "Para profes y clubes",
        "titulo": "Cajas de pelotas x24",
        "subtitulo": "Head Pro, Head Championship y Penn Premier con envío gratis.",
        "cta": "Consultar",
        "url": "https://wa.me/5491128321531?text=Hola%20SOPI!%20Quiero%20info%20de%20las%20cajas",
        "imagen": "banner-cajas.jpg",          # opcional
        "imagen_movil": "banner-cajas.jpg",  # opcional
        "fondo": "#1b2a3a",                    # color si no hay imagen
    },
    {
        "etiqueta": "Pádel",
        "titulo": "Paletas 2026",
        "subtitulo": "Bullpadel, Nox, Adidas y Siux.",
        "cta": "Comprar",
        "url": "/catalogo/padel",
        "imagen": "banner-padel.jpg",
        "fondo": "#1f4d3a",
    },
]

TILES = [
    {"titulo": "Pelotas de tenis", "subtitulo": "Head y Penn", "url": "/catalogo/tenis?categoria=Pelotas", "imagen": "tile-pelotas.jpg"},
    {"titulo": "Paletas de pádel", "subtitulo": "Nuevos ingresos", "url": "/catalogo/padel?categoria=Palas", "imagen": "tile-paletas.jpg"},
    {"titulo": "Overgrips", "subtitulo": "Tourna, Solinco y más", "url": "/catalogo/tenis?categoria=Accesorios", "imagen": "tile-grips.jpg"},
]
SECRET_KEY = os.environ.get("SECRET_KEY")


@app.route("/health", methods=["GET", "HEAD"])
def health():
    return "ok", 200


@app.route("/quienes-somos")
def quienes_somos():
    return render_template(
        "quienes_somos.html",
        **obtener_contexto_base()
    )


if not SECRET_KEY:
    if ES_PRODUCCION:
        # La clave por defecto es pública (está en el repo): con ella cualquiera
        # podría falsificar la sesión, incluida la de administrador.
        raise RuntimeError("Falta la variable de entorno SECRET_KEY")
    SECRET_KEY = "clave-desarrollo-tienda-tenis"

app.secret_key = SECRET_KEY

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",   # frena CSRF en los formularios del admin
    SESSION_COOKIE_SECURE=ES_PRODUCCION,
)

# =========================================================
# AVISOS DE VENTA POR GMAIL
# =========================================================

app.config.update(
    MAIL_SERVER=os.environ.get("MAIL_SERVER", "smtp.gmail.com"),
    MAIL_PORT=int(os.environ.get("MAIL_PORT", "587")),
    MAIL_USE_TLS=os.environ.get("MAIL_USE_TLS", "true").lower() == "true",
    MAIL_USERNAME=os.environ.get("MAIL_USERNAME"),
    MAIL_PASSWORD=os.environ.get("MAIL_PASSWORD"),
    MAIL_DEFAULT_SENDER=os.environ.get("MAIL_DEFAULT_SENDER"),
)

mail = Mail(app)


VENTAS_EMAIL = os.environ.get("VENTAS_EMAIL")


def enviar_aviso_venta(asunto, cuerpo):
    """Envía un aviso por correo sin interrumpir la compra si falla."""
    if not VENTAS_EMAIL:
        app.logger.warning("Falta configurar VENTAS_EMAIL")
        return False

    if not app.config.get("MAIL_USERNAME") or not app.config.get("MAIL_PASSWORD"):
        app.logger.warning("Falta configurar las credenciales de Gmail")
        return False

    try:
        mensaje = Message(
            subject=asunto,
            recipients=[VENTAS_EMAIL],
            body=cuerpo,
        )
        mail.send(mensaje)
        return True
    except Exception:
        app.logger.exception("Error enviando aviso de venta")
        return False



def avisar_pedido_nuevo(pedido):
    """Avisa que se registró un pedido nuevo, con los datos del comprador."""
    detalle = [
        (
            f"- {nombre_con_talle(linea.nombre_producto, linea.talle)} x {linea.cantidad}: "
            f"${linea.precio_unitario * linea.cantidad:,.0f}"
        )
        for linea in pedido.lineas
    ]

    uso = CuponUso.query.filter_by(pedido_id=pedido.id).first()
    linea_cupon = []

    if uso:
        c = db.session.get(Cupon, uso.cupon_id)
        if c:
            linea_cupon = [
                f"Cupón: {c.codigo} (-${uso.descuento:,.0f})"
            ]

    if pedido.modalidad_entrega == "envio":
        datos_entrega = [
            f"Dirección: {pedido.direccion or 'No informada'}",
            f"Localidad: {pedido.localidad or 'No informada'}",
            f"Provincia: {pedido.provincia or 'No informada'}",
            f"Código postal: {pedido.codigo_postal or 'No informado'}",
            f"Envío: {pedido.servicio_envio or 'A coordinar'} (${(pedido.costo_envio or 0):,.0f})",
        ]
    else:
        datos_entrega = ["Entrega: Retiro en Quilmes"]

    cuerpo = "\n".join([
        f"Nuevo pedido #{pedido.id} en SOPI Tenis•Pádel",
        "",
        f"Estado: {pedido.estado}",
        f"Cliente: {pedido.nombre_cliente or 'No informado'}",
        f"Email: {pedido.email_cliente or 'No informado'}",
        f"Teléfono: {pedido.telefono_cliente or 'No informado'}",
        f"Entrega: {pedido.modalidad_entrega or 'No informada'}",
        *datos_entrega,
        f"Medio de pago: {pedido.medio_pago}",
        f"Total: ${pedido.total:,.0f}",
        *linea_cupon,
        "",
        "Productos:",
        *detalle,
        "",
        f"Panel de administración: {URL_PUBLICA}/admin/pedidos",
    ])

    enviar_aviso_venta(f"SOPI: nuevo pedido #{pedido.id}", cuerpo)



def avisar_pago_confirmado(pedido):
    """Avisa que Mercado Pago confirmó el cobro."""
    cuerpo = "\n".join([
        f"Pago confirmado para el pedido #{pedido.id}",
        "",
        f"Total cobrado: ${pedido.total:,.0f}",
        f"ID de pago de Mercado Pago: {pedido.mp_payment_id}",
        "",
        f"Panel de administración: {URL_PUBLICA}/admin/pedidos",
    ])

    enviar_aviso_venta(
        f"SOPI: pago confirmado del pedido #{pedido.id}",
        cuerpo,
    )

# =========================================================
# BASE DE DATOS
# =========================================================

basedir = os.path.abspath(
    os.path.dirname(__file__)
)

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    # Render entrega postgres://, SQLAlchemy 2 necesita postgresql://
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        "sqlite:///" + os.path.join(basedir, "instance", "tienda.db")
    )

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


# =========================================================
# SLUGS (URLs amigables de producto)
# Tienen que estar definidos ANTES del bloque de migración,
# porque la migración los usa al arrancar.
# =========================================================

def slugify(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = texto.encode("ascii", "ignore").decode("ascii").lower()
    texto = re.sub(r"[^a-z0-9]+", "-", texto).strip("-")
    return texto[:150] or "producto"


def generar_slug(nombre):
    """Slug único: 'bullpadel-vertex-04', y si ya existe '-2', '-3'..."""
    base = slugify(nombre)
    slug, n = base, 2
    while Producto.query.filter_by(slug=slug).first():
        slug = f"{base}-{n}"
        n += 1
    return slug


# =========================================================
# CREAR BASE DE DATOS Y TABLAS
# =========================================================
with app.app_context():

    os.makedirs(
        os.path.join(
            basedir,
            "instance"
        ),
        exist_ok=True
    )

    db.create_all()

    # Migración liviana: agrega medio_pago si la tabla pedidos ya existía sin esa columna
    columnas_pedidos = [c["name"] for c in inspect(db.engine).get_columns("pedidos")]
    if "medio_pago" not in columnas_pedidos:
        db.session.execute(text("ALTER TABLE pedidos ADD COLUMN medio_pago VARCHAR(20)"))
        db.session.commit()

    # Migración: datos del cliente, modalidad de entrega y envío
    columnas_pedidos = [
        c["name"] for c in inspect(db.engine).get_columns("pedidos")
    ]

    nuevas_columnas_pedidos = {
        "nombre_cliente": "VARCHAR(120)",
        "email_cliente": "VARCHAR(120)",
        "telefono_cliente": "VARCHAR(40)",
        "modalidad_entrega": "VARCHAR(20)",
        "direccion": "VARCHAR(200)",
        "localidad": "VARCHAR(100)",
        "provincia": "VARCHAR(100)",
        "codigo_postal": "VARCHAR(20)",
        "costo_envio": "INTEGER",
        "servicio_envio": "VARCHAR(80)",
    }

    for nombre_columna, tipo_columna in nuevas_columnas_pedidos.items():
        if nombre_columna not in columnas_pedidos:
            db.session.execute(
                text(
                    f"ALTER TABLE pedidos ADD COLUMN "
                    f"{nombre_columna} {tipo_columna}"
                )
            )
            db.session.commit()



    # Migración liviana: agrega costo si la tabla productos ya existía sin esa columna
    columnas_productos = [c["name"] for c in inspect(db.engine).get_columns("productos")]
    if "costo" not in columnas_productos:
        db.session.execute(text("ALTER TABLE productos ADD COLUMN costo INTEGER"))
        db.session.commit()

    # Migración liviana: stock por talle (productos) y talle comprado (líneas de pedido)
    columnas_productos = [c["name"] for c in inspect(db.engine).get_columns("productos")]
    if "talles" not in columnas_productos:
        db.session.execute(text("ALTER TABLE productos ADD COLUMN talles VARCHAR(200)"))
        db.session.commit()

    columnas_lineas = [c["name"] for c in inspect(db.engine).get_columns("lineas_pedido")]
    if "talle" not in columnas_lineas:
        db.session.execute(text("ALTER TABLE lineas_pedido ADD COLUMN talle VARCHAR(10)"))
        db.session.commit()

    # Migración liviana: agrega slug y lo rellena en los productos existentes
    columnas_productos = [c["name"] for c in inspect(db.engine).get_columns("productos")]
    if "slug" not in columnas_productos:
        db.session.execute(text("ALTER TABLE productos ADD COLUMN slug VARCHAR(200)"))
        db.session.commit()

    for p in Producto.query.filter(
        (Producto.slug == None) | (Producto.slug == "")   # noqa: E711
    ).all():
        p.slug = generar_slug(p.nombre)
        db.session.commit()

    db.session.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_productos_slug ON productos (slug)"
    ))
    db.session.commit()

    # Cupón de los jugadores del Varela Open (se crea una sola vez)
    if not Cupon.query.filter_by(codigo="VARELA5").first():
        db.session.add(Cupon(
            codigo="VARELA5",
            porcentaje=5,
            vence=date(2026, 11, 30),
            deporte="Tenis",
            excluir_nombre="Pack",
            usos_maximos=100,
        ))
        db.session.commit()

    # Los productos se cargan desde /admin/precios (CSV).

# =========================================================
# MERCADO PAGO
# =========================================================

MP_ACCESS_TOKEN = os.environ.get(
    "MP_ACCESS_TOKEN"
)

if MP_ACCESS_TOKEN:
    mp = mercadopago.SDK(
        MP_ACCESS_TOKEN
    )
else:
    mp = None

# =========================================================
# URL PÚBLICA PARA MERCADO PAGO
# =========================================================

# En Render definir URL_BASE=https://sopitenispadel.com.ar (sin barra final)
URL_PUBLICA = os.environ.get("URL_BASE", "http://127.0.0.1:5000").rstrip("/")

# Único descuento de la tienda: 5% pagando por transferencia bancaria
DESCUENTO_TRANSFERENCIA = 0.05


def es_pack(producto):
    """Los packs ya traen su propio descuento en el precio."""
    return "pack" in (producto.nombre or "").lower()


def total_con_transferencia(items):
    """5% off por transferencia en todo menos en los packs."""
    return sum(
        item["subtotal"] if es_pack(item["producto"])
        else round(item["subtotal"] * (1 - DESCUENTO_TRANSFERENCIA))
        for item in items
    )


# =========================================================
# ENVÍO POR CORREO ARGENTINO (MiCorreo)
# =========================================================

# Envío gratis cuando el subtotal (sin descuentos) llega a este monto
ENVIO_GRATIS_DESDE = 150000

# (peso por unidad en g, largo, ancho, alto en cm). Son estimaciones: ajustalas.
EMBALAJE = {
    "Palas":        (600, 50, 30, 12),
    "Raquetas":     (350, 70, 30, 10),
    "Pelotas":      (220, 25, 8, 8),     # un tubo
    "Calzado":      (1100, 35, 25, 15),
    "Indumentaria": (400, 30, 25, 5),
    "Accesorios":   (80, 20, 15, 3),
}
EMBALAJE_DEFECTO = (500, 30, 20, 10)


def embalaje_de(producto):
    categoria = producto.categoria or ""
    for clave, valores in EMBALAJE.items():
        if categoria.startswith(clave):
            return valores
    return EMBALAJE_DEFECTO


def dimensiones_carrito(items):
    """Peso total y medidas del bulto estimadas a partir del carrito."""
    peso, largo, ancho, alto = 300, 0, 0, 0  # 300 g de embalaje
    for item in items:
        p, l, a, h = embalaje_de(item["producto"])
        unidades = item["cantidad"] * (3 if es_pack(item["producto"]) else 1)
        peso += p * unidades
        largo, ancho = max(largo, l), max(ancho, a)
        alto += h * unidades
    return {
        "weight": int(peso),
        "length": int(largo),
        "width": int(ancho),
        "height": int(min(alto, 40)),
    }


def normalizar_cp(texto):
    """Extrae los 4 dígitos del código postal (acepta 'B1878ABC', '1878', etc.)."""
    m = re.search(r"\d{4}", texto or "")
    return m.group(0) if m else None


def tarifas_envio(items, subtotal, cp):
    """Opciones de envío para el carrito. Lanza MiCorreoError si la API falla."""
    tarifas = micorreo.cotizar_envio(cp, dimensiones_carrito(items))
    if subtotal >= ENVIO_GRATIS_DESDE:
        # envío gratis: solo la opción más barata, a costo 0 para el cliente
        return [dict(tarifas[0], precio_original=tarifas[0]["precio"], precio=0)]
    return tarifas


def resolver_envio(items, subtotal, cp_texto, codigo):
    """Devuelve (costo, servicio). Se recalcula SIEMPRE acá: nunca viene del navegador."""
    try:
        opciones = tarifas_envio(items, subtotal, normalizar_cp(cp_texto))
    except micorreo.MiCorreoError:
        app.logger.exception("No se pudo cotizar el envío")
        return 0, "A coordinar"
    elegida = next((o for o in opciones if o["codigo"] == codigo), opciones[0])
    return elegida["precio"], elegida["nombre"]


# Datos que se muestran al cliente que paga por transferencia
DATOS_TRANSFERENCIA = {
    "titular": os.environ.get("TRANSFER_TITULAR", ""),
    "cbu": os.environ.get("TRANSFER_CBU", ""),
    "alias": os.environ.get("TRANSFER_ALIAS", ""),
}
WHATSAPP_VENDEDOR = os.environ.get("WHATSAPP_VENDEDOR", "")

# =========================================================
# FILTROS Y HELPERS DE PLANTILLA
# =========================================================

@app.template_filter("pesos")
def filtro_pesos(valor):
    return "$" + "{:,.0f}".format(valor or 0).replace(",", ".")


@app.template_filter("hora_ar")
def filtro_hora_ar(fecha):
    # Las fechas se guardan en UTC; Argentina es UTC-3 todo el año
    return (fecha - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M")


# Parámetros de la URL que sí merecen canonical propio (el resto apunta a la URL limpia)
PARAMS_CANONICOS = ("categoria", "sub", "marca")


def url_abs(ruta):
    """Ruta relativa -> URL absoluta (si ya es absoluta, queda igual)."""
    return ruta if ruta.startswith("http") else f"{URL_PUBLICA}{ruta}"


@app.context_processor
def seo_helpers():
    """Helpers de SEO disponibles en todas las plantillas."""
    qs = {k: request.args[k] for k in PARAMS_CANONICOS if request.args.get(k)}
    canonical = f"{URL_PUBLICA}{request.path}" + (f"?{urlencode(qs)}" if qs else "")
    return {"url_abs": url_abs, "canonical_default": canonical}


@app.template_global()
def url_producto(p):
    """URL del producto: con slug si lo tiene, si no la vieja por id (que redirige)."""
    if p.slug:
        return url_for("producto_detalle", slug=p.slug)
    return url_for("producto", producto_id=p.id)


# =========================================================
# NAVEGACIÓN
# =========================================================

NAV_DEPORTES = {
    "tenis": "Tenis",
    "padel": "Pádel",
}
@app.context_processor
def inyectar_nav_categorias():
    try:
        nav, nav_grupos = {}, {}
        for slug, nombre in NAV_DEPORTES.items():
            filas = (db.session.query(Producto.categoria)
                     .filter(Producto.deporte == nombre)
                     .distinct()
                     .all())
            nav[slug] = sorted({c for (c,) in filas if c}, key=clave_categoria)
            nav_grupos[slug] = agrupar_categorias(nav[slug])
        return {"nav_categorias": nav, "nav_grupos": nav_grupos, "nav_arbol": arbol_por_deporte()}
    except Exception:
        app.logger.exception("No se pudieron cargar las categorías del menú")
        db.session.rollback()
        return {"nav_categorias": {}, "nav_grupos": {}, "nav_arbol": {}}


def arbol_por_deporte():
    """Menú del celular, por deporte:
    [{'nombre': 'Raquetas', 'hijos': [{'genero': None, 'categoria': 'Raquetas', 'subs': ['Babolat', 'Head']}]},
     {'nombre': 'Indumentaria', 'hijos': [{'genero': 'Hombre', 'categoria': 'Indumentaria Hombre', 'subs': [...]},
                                          {'genero': 'Mujer', ...}]},
     {'nombre': 'Grips', 'hijos': [{'genero': None, 'categoria': 'Grips', 'subs': []}]}, ...]"""
    filas = db.session.query(Producto.deporte, Producto.categoria, Producto.nombre, Producto.marca).all()
    resultado = {}
    for slug, deporte in NAV_DEPORTES.items():
        productos = [
            Producto(deporte=d, categoria=c, nombre=n, marca=m)
            for d, c, n, m in filas if d == deporte and c
        ]
        subs = subcategorias_de(productos)
        grupos = {}
        for categoria in sorted({p.categoria for p in productos}, key=clave_categoria):
            grupo, genero = grupo_y_sub(categoria)
            grupos.setdefault(grupo, []).append(
                {"genero": genero, "categoria": categoria, "subs": subs.get(categoria, [])}
            )
        resultado[slug] = [{"nombre": g, "hijos": h} for g, h in grupos.items()]
    return resultado

# =========================================================
# CONTEXTO BASE
# =========================================================

def productos_destacados(deporte=None, cantidad=4):
    """Últimos productos cargados, con stock y con foto."""
    query = Producto.query.filter(
        Producto.stock > 0,
        db.func.coalesce(Producto.imagen, "") != "",
    )
    if deporte:
        query = query.filter_by(deporte=deporte)
    return query.order_by(Producto.id.desc()).limit(cantidad).all()


def obtener_contexto_base(
    deporte_slug=None
):

    carrito = session.get(
        "carrito",
        {}
    )

    total_items = sum(
        carrito.values()
    )

    destacados = productos_destacados()

    return {
        "nav_deportes": NAV_DEPORTES,
        "deporte_slug": deporte_slug,
        "total_items_carrito": total_items,
        "destacados": destacados,
    }


# =========================================================
# PRODUCTOS
# =========================================================

def obtener_productos_por_deporte(
    deporte_slug,
    filtros
):

    query = Producto.query.filter_by(
        deporte=NAV_DEPORTES[deporte_slug]
    )

    # Búsqueda
    if filtros.get("q"):

        q = f"%{filtros['q']}%"

        query = query.filter(
            (Producto.nombre.ilike(q))
            | (Producto.marca.ilike(q))
        )

    # Categoría
    if filtros.get("categoria"):
        cat = filtros["categoria"]
        if cat == "Indumentaria":
            # el grupo completo: Hombre + Mujer
            query = query.filter(Producto.categoria.like("Indumentaria%"))
        else:
            query = query.filter_by(categoria=cat)

    # Marca
    if filtros.get("marca"):

        query = query.filter_by(
            marca=filtros["marca"]
        )

    # Precio máximo
    if filtros.get("max_precio"):

        try:

            max_precio = int(
                filtros["max_precio"]
            )

            query = query.filter(
                Producto.precio <= max_precio
            )

        except ValueError:
            pass

    # Orden
    orden = filtros.get(
        "orden",
        "relevancia"
    )

    if orden == "precio_asc":

        query = query.order_by(
            Producto.precio.asc()
        )

    elif orden == "precio_desc":

        query = query.order_by(
            Producto.precio.desc()
        )

    elif orden == "nombre":

        query = query.order_by(
            Producto.nombre.asc()
        )

    elif orden == "stock":

        query = query.order_by(
            Producto.stock.desc()
        )

    return query.all()


# Orden en que se muestran las categorías en el catálogo.
# Las que no estén acá van después, por orden alfabético.
ORDEN_CATEGORIAS = [
    "Palas", "Pelotas",
    "Indumentaria Hombre", "Indumentaria Mujer",
    "Accesorios",
]


def clave_categoria(categoria):
    if categoria in ORDEN_CATEGORIAS:
        return (0, ORDEN_CATEGORIAS.index(categoria), "")
    return (1, 0, categoria.lower())


# ---------------------------------------------------------
# SUBCATEGORÍAS: salen solas del nombre o de la marca de cada producto.
#   "por": "tipo"  -> se busca alguna de las palabras en el nombre
#                     (con "primera": True, solo en la primera palabra)
#   "por": "marca" -> una subcategoría por marca (si hay más de una)
#   "resto"        -> dónde van los que no coinciden con ningún tipo
#   "titulo"       -> título de la página filtrada ({sub}, {sub_min})
# La clave es (deporte, categoría) o solo la categoría (vale para los dos deportes).
# El orden de "tipos" es el orden en que se muestran.
# ---------------------------------------------------------
REGLAS_SUB = {
    "Indumentaria Hombre": {
        "por": "tipo", "primera": True, "resto": "Otros", "titulo": "{sub} de hombre",
        "tipos": [
            ("Remeras", ("remera", "camiseta")),
            ("Chombas", ("chomba", "polo")),
            ("Camperas y buzos", ("campera", "buzo")),
            ("Shorts y bermudas", ("short", "bermuda")),
            ("Pantalones", ("pantalon",)),
        ],
    },
    "Indumentaria Mujer": {
        "por": "tipo", "primera": True, "resto": "Otros", "titulo": "{sub} de mujer",
        "tipos": [
            ("Musculosas, remeras y tops", ("musculosa", "remera", "top", "camiseta")),
            ("Camperas y buzos", ("campera", "buzo")),
            ("Calzas y shorts", ("calza", "short")),
            ("Polleras y vestidos", ("pollera", "vestido", "skort")),
            ("Pantalones", ("pantalon",)),
        ],
    },
    ("Tenis", "Raquetas"): {"por": "marca", "titulo": "Raquetas {sub}"},
    ("Tenis", "Pelotas"): {"por": "marca", "titulo": "Pelotas {sub}"},
    ("Tenis", "Overgrips"): {"por": "marca", "titulo": "Overgrips {sub}"},
    ("Tenis", "Calzado"): {
        "por": "tipo", "resto": "Unisex", "titulo": "Calzado {sub_min}",
        "tipos": [
            ("Hombre", ("men", "man", "hombre")),
            ("Mujer", ("women", "woman", "mujer")),
        ],
    },
    ("Pádel", "Paletas"): {"por": "marca", "titulo": "Paletas {sub}"},
    ("Pádel", "Pelotas"): {"por": "marca", "titulo": "Pelotas {sub}"},
    ("Pádel", "Overgrips"): {
        "por": "tipo", "resto": "Overgrips sueltos", "titulo": "{sub}",
        "tipos": [
            ("Overgrips x3", ("x3", "blister")),
            ("Cajas y carameleras", ("caramelera", "caja", re.compile(r"^x\d{2,}$"))),
        ],
    },
    ("Pádel", "Accesorios"): {
        "por": "tipo", "resto": "Otros accesorios", "titulo": "{sub}",
        "tipos": [
            ("Mochilas", ("mochila", "mochilas")),
            ("Bandoleras", ("bandolera", "bandoleras")),
            ("Paleteros", ("paletera", "paletero", "paleteros")),
            ("Bolsos", ("bolso", "bolsos")),
        ],
    },
    ("Pádel", "Accesorios Textil"): {
        "por": "tipo", "resto": "Otros textiles", "titulo": "{sub}",
        "tipos": [
            ("Medias", ("medias", "media")),
            ("Muñequeras", ("munequera", "munequeras")),
            ("Gorras y viseras", ("gorra", "gorras", "visera", "viseras")),
        ],
    },
}
SEPARADOR_SUB = " · "


def regla_de(deporte, categoria):
    return REGLAS_SUB.get((deporte, categoria)) or REGLAS_SUB.get(categoria)


# Marcas que se escriben en mayúsculas (siglas): no se pasan a "Niu" / "Ama"
MARCAS_EN_MAYUSCULAS = {"NIU", "AMA"}


def normalizar_marca(marca):
    """'HEAD' -> 'Head', 'PRO GO' -> 'Pro Go'; las que ya tienen minúsculas quedan igual.
    Las de MARCAS_EN_MAYUSCULAS quedan en mayúsculas ('Niu' -> 'NIU')."""
    marca = (marca or "").strip()
    if marca.upper() in MARCAS_EN_MAYUSCULAS:
        return marca.upper()
    return marca.title() if marca.isupper() else marca


def subcategoria_de(deporte, categoria, nombre, marca):
    """Subcategoría de un producto, o None si su categoría no tiene subcategorías."""
    regla = regla_de(deporte, categoria)
    if not regla:
        return None
    if regla["por"] == "marca":
        return normalizar_marca(marca) or "Otras marcas"
    palabras = slugify(nombre).split("-")
    if regla.get("primera"):
        palabras = palabras[:1]
    for tipo, claves in regla["tipos"]:
        for clave in claves:
            if any((clave.match(p) if hasattr(clave, "match") else p == clave) for p in palabras):
                return tipo
    return regla["resto"]


def subcategoria(producto):
    return subcategoria_de(producto.deporte, producto.categoria, producto.nombre, producto.marca)


def orden_sub(deporte, categoria, sub):
    """Para ordenar: los tipos en el orden de la regla (el resto al final); las marcas por nombre."""
    regla = regla_de(deporte, categoria) or {}
    tipos = [t for t, _ in regla.get("tipos", [])]
    if sub in tipos:
        return (0, tipos.index(sub), "")
    return (1 if regla.get("por") == "marca" else 2, 0, (sub or "").lower())


def subcategorias_de(productos):
    """{categoria: [subs ordenadas]} solo para categorías con más de una subcategoría.
    (Una categoría con una sola marca o un solo tipo no se divide.)"""
    subs = {}
    for p in productos:
        s = subcategoria(p)
        if s:
            subs.setdefault((p.deporte, p.categoria), set()).add(s)
    return {
        cat: sorted(ss, key=lambda s, d=dep, c=cat: orden_sub(d, c, s))
        for (dep, cat), ss in subs.items() if len(ss) > 1
    }


def seccion_de(producto, divididas):
    """Sección del catálogo: 'Raquetas · Head', 'Indumentaria Hombre · Remeras' o solo la categoría."""
    categoria = producto.categoria or "Otros"
    if categoria in divididas:
        return f"{categoria}{SEPARADOR_SUB}{subcategoria(producto)}"
    return categoria


def agrupar_por_categoria(productos):
    """[(seccion, [productos...]), ...] respetando el orden de ORDEN_CATEGORIAS
    y, dentro de cada categoría, el orden de sus subcategorías."""
    divididas = subcategorias_de(productos)
    deporte = productos[0].deporte if productos else ""
    grupos = {}
    for p in productos:
        grupos.setdefault(seccion_de(p, divididas), []).append(p)

    def clave(seccion):
        categoria, _, sub = seccion.partition(SEPARADOR_SUB)
        return (*clave_categoria(categoria), orden_sub(deporte, categoria, sub) if sub else (-1, 0, ""))

    return sorted(grupos.items(), key=lambda g: clave(g[0]))


@app.template_global()
def partes_seccion(seccion):
    """'Indumentaria Hombre · Remeras' -> ('Indumentaria', 'Hombre · Remeras');
    'Raquetas · Head' -> ('Raquetas', 'Head'); 'Pelotas' -> ('Pelotas', None)."""
    categoria, _, sub = seccion.partition(SEPARADOR_SUB)
    grupo, genero = grupo_y_sub(categoria)
    detalle = SEPARADOR_SUB.join(x for x in (genero, sub) if x)
    return grupo, (detalle or None)

def grupo_y_sub(categoria):
    """'Indumentaria Hombre' -> ('Indumentaria', 'Hombre'); 'Palas' -> ('Palas', None)"""
    if (categoria or "").startswith("Indumentaria "):
        return "Indumentaria", categoria.split(" ", 1)[1]
    return categoria, None


def agrupar_categorias(categorias):
    """Arma el menú: [{'nombre', 'valor', 'subs': [{'nombre', 'valor'}]}]"""
    grupos = {}
    for c in categorias:
        grupo, sub = grupo_y_sub(c)
        g = grupos.setdefault(grupo, {"nombre": grupo, "valor": grupo, "subs": []})
        if sub:
            g["subs"].append({"nombre": sub, "valor": c})
    return list(grupos.values())

def obtener_categorias_y_marcas(
    deporte_slug
):

    productos = Producto.query.filter_by(
        deporte=NAV_DEPORTES[deporte_slug]
    ).all()

    categorias = sorted(
        {p.categoria for p in productos if p.categoria},
        key=clave_categoria
    )

    marcas = sorted(
        list(
            set(
                p.marca
                for p in productos
                if p.marca
            )
        )
    )

    return categorias, marcas


# =========================================================
# SEO POR PÁGINA (título, descripción, JSON-LD)
# =========================================================

SEO_CATALOGO = {
    "padel": {
        "title": "Paletas, pelotas y accesorios de pádel | SOPI Sports",
        "desc": "Paletas de pádel Adidas, Bullpadel, Nox, Siux y más, pelotas, grips e indumentaria. Envíos a todo el país.",
        "h1": "Pádel: paletas, pelotas y accesorios",
        "intro": "Encontrá paletas de pádel de las mejores marcas, pelotas, grips, bolsos e indumentaria. Enviamos a todo el país y, si pagás por transferencia, tenés 5% de descuento.",
    },
    "tenis": {
        "title": "Raquetas, pelotas y accesorios de tenis | SOPI Sports",
        "desc": "Raquetas de tenis Head, Wilson, Babolat y Dunlop, pelotas, overgrips, calzado e indumentaria. Envíos a todo el país.",
        "h1": "Tenis: raquetas, pelotas y accesorios",
        "intro": "Raquetas, pelotas, overgrips, calzado e indumentaria de tenis. Equipamiento para jugar, entrenar y dar clases, con envíos a todo el país.",
    },
}


def seo_catalogo(deporte_slug, categoria="", marca="", categorias=(), marcas=(), sub=""):
    seo = dict(SEO_CATALOGO[deporte_slug])
    deporte = "pádel" if deporte_slug == "padel" else "tenis"

    # Solo se personaliza con valores que existen: evita títulos con texto arbitrario de la URL
    categoria = categoria if (categoria in categorias or categoria == "Indumentaria") else ""
    marca = marca if marca in marcas else ""

    if categoria and sub:
        # "Remeras de hombre de tenis", "Raquetas Head de tenis" (sub ya viene validada en catalogo())
        regla = regla_de(NAV_DEPORTES[deporte_slug], categoria) or {}
        categoria = regla.get("titulo", "{sub}").format(sub=sub, sub_min=sub.lower())

    if categoria or marca:
        nombre = f"{categoria or 'Productos'}{(' ' + marca) if marca else ''} de {deporte}"
        seo["title"] = f"{nombre} | SOPI Sports"
        seo["h1"] = nombre
        seo["desc"] = f"{nombre} con envíos a todo el país. Comprá online en SOPI Sports."
        seo["intro"] = ""  # el texto largo queda solo en la página principal del deporte
    return seo


def seo_producto(p):
    precio_visible = bool(p.precio)

    desc = f"Comprá {p.nombre}"
    desc += f" ({p.marca})" if p.marca else ""
    desc += " en SOPI Sports."
    if precio_visible:
        desc += f" Precio {filtro_pesos(p.precio)}."
    else:
        desc += " Consultá precio y disponibilidad por WhatsApp."
    desc += " Envíos a todo el país."

    img = (p.imagen or "").strip().lower() or "og-default.png"
    imagen = url_abs(url_for("static", filename=f"img/{img}"))
    url = url_abs(url_for("producto_detalle", slug=p.slug))

    ld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": p.nombre,
        "image": [imagen],
        "description": (p.descripcion or desc)[:300],
        "url": url,
    }
    if p.marca:
        ld["brand"] = {"@type": "Brand", "name": p.marca}
    if precio_visible:
        ld["offers"] = {
            "@type": "Offer",
            "url": url,
            "priceCurrency": "ARS",
            "price": str(int(p.precio)),
            "availability": "https://schema.org/InStock" if (p.stock or 0) > 0
                            else "https://schema.org/OutOfStock",
            "itemCondition": "https://schema.org/NewCondition",
        }

    return {
        "title": f"{p.nombre} | {p.marca} | SOPI Sports" if p.marca else f"{p.nombre} | SOPI Sports",
        "desc": desc[:155],
        "image": imagen,
        "jsonld": ld,
    }


# =========================================================
# PORTADA
# =========================================================

@app.route("/")
def portada():
    contexto = obtener_contexto_base()

    return render_template(
        "portada.html",
        popup=POPUP,
        banners=BANNERS,
        tiles=TILES,
        **contexto
    )

# =========================================================
# CATÁLOGO
# =========================================================

@app.route(
    "/catalogo/<deporte_slug>"
)
def catalogo(deporte_slug):

    if deporte_slug not in NAV_DEPORTES:

        return (
            "Deporte no encontrado",
            404
        )

    filtros = {

        "q": request.args.get(
            "q",
            ""
        ),

        "categoria": request.args.get(
            "categoria",
            ""
        ),

        "marca": request.args.get(
            "marca",
            ""
        ),

        "max_precio": request.args.get(
            "max_precio",
            ""
        ),

        "orden": request.args.get(
            "orden",
            "relevancia"
        ),

        "sub": request.args.get(
            "sub",
            ""
        ),
    }

    productos = (
        obtener_productos_por_deporte(
            deporte_slug,
            filtros
        )
    )

    # Subcategoría (marca o tipo): sale del nombre/marca, por eso se filtra acá.
    # Solo vale si existe dentro de la categoría elegida.
    if filtros["sub"] and filtros["sub"] in subcategorias_de(productos).get(filtros["categoria"], []):
        productos = [p for p in productos if subcategoria(p) == filtros["sub"]]
    else:
        filtros["sub"] = ""

    categorias, marcas = (
        obtener_categorias_y_marcas(
            deporte_slug
        )
    )

    destacados = productos_destacados(NAV_DEPORTES[deporte_slug])

    contexto = obtener_contexto_base(
        deporte_slug
    )

    contexto.update({

        "deporte": NAV_DEPORTES[
            deporte_slug
        ],

        "destacados": destacados,

        "productos": productos,

        "secciones": agrupar_por_categoria(productos),

        "categorias": categorias,
        "categorias_agrupadas": agrupar_categorias(categorias),
        "marcas": marcas,

        "filtros": filtros,

        "seo": seo_catalogo(
            deporte_slug,
            filtros["categoria"],
            filtros["marca"],
            categorias,
            marcas,
            filtros["sub"],
        ),
    })

    return render_template(
        "index.html",
        **contexto
    )


@app.route("/catalogo/tenis")
def catalogo_tenis():

    return catalogo(
        "tenis"
    )


@app.route("/catalogo/padel")
def catalogo_padel():

    return catalogo(
        "padel"
    )


# =========================================================
# DETALLE DE PRODUCTO
# =========================================================

@app.route("/producto/<slug>")
def producto_detalle(slug):

    producto = Producto.query.filter_by(slug=slug).first_or_404()

    contexto = obtener_contexto_base()

    contexto["producto"] = producto

    contexto["seo"] = seo_producto(producto)

    if producto.deporte == "Pádel":

        contexto["deporte_slug"] = "padel"

    else:

        contexto["deporte_slug"] = "tenis"

    return render_template(
        "product.html",
        **contexto
    )


# URL vieja (/producto/10): redirige a la nueva con 301
@app.route("/producto/<int:producto_id>")
def producto(producto_id):

    p = Producto.query.get_or_404(producto_id)

    if not p.slug:
        p.slug = generar_slug(p.nombre)
        db.session.commit()

    return redirect(url_for("producto_detalle", slug=p.slug), code=301)


# =========================================================
# CARRITO
# =========================================================

@app.route("/carrito")
def carrito_ver():

    items, total, _ = armar_items_carrito()

    contexto = obtener_contexto_base()

    contexto.update({

        "items": items,

        "total": total,
    })

    return render_template(
        "carrito.html",
        **contexto
    )


@app.route(
    "/carrito/agregar/<int:producto_id>",
    methods=["POST"]
)
def carrito_agregar(producto_id):

    producto = Producto.query.get_or_404(
        producto_id
    )

    talle = talle_del_form(producto)
    disponible = producto.stock_de(talle)

    # Sin stock, o falta elegir talle: vuelve a la ficha sin agregar nada
    if disponible <= 0:

        return redirect(
            request.referrer
            or url_for(
                "producto",
                producto_id=producto_id
            )
        )

    carrito = session.get(
        "carrito",
        {}
    )

    clave = clave_carrito(producto_id, talle)

    cantidad_actual = carrito.get(
        clave,
        0
    )

    # cantidad elegida en la ficha del producto (si no viene, suma 1)
    try:
        cantidad_pedida = int(request.form.get("cantidad", 1))
    except ValueError:
        cantidad_pedida = 1
    cantidad_pedida = max(cantidad_pedida, 1)

    carrito[clave] = min(
        cantidad_actual + cantidad_pedida,
        disponible
    )

    session["carrito"] = carrito

    session.modified = True

    return redirect(
        request.referrer
        or url_for(
            "producto",
            producto_id=producto_id
        )
    )


@app.route(
    "/carrito/actualizar/<int:producto_id>",
    methods=["POST"]
)
def carrito_actualizar(producto_id):

    producto = Producto.query.get_or_404(
        producto_id
    )

    try:

        cantidad = int(
            request.form.get(
                "cantidad",
                1
            )
        )

    except ValueError:

        cantidad = 1

    carrito = session.get(
        "carrito",
        {}
    )

    talle = talle_del_form(producto)

    clave = clave_carrito(producto_id, talle)

    if cantidad <= 0:

        carrito.pop(
            clave,
            None
        )

    else:

        cantidad = min(
            cantidad,
            producto.stock_de(talle)
        )

        carrito[clave] = cantidad

    session["carrito"] = carrito

    session.modified = True

    return redirect(
        url_for(
            "carrito_ver"
        )
    )


@app.route(
    "/carrito/eliminar/<int:producto_id>",
    methods=["POST"]
)
def carrito_eliminar(producto_id):

    carrito = session.get(
        "carrito",
        {}
    )

    talle = (request.form.get("talle") or "").strip().upper() or None

    carrito.pop(
        clave_carrito(producto_id, talle),
        None
    )

    session["carrito"] = carrito

    session.modified = True

    return redirect(
        url_for(
            "carrito_ver"
        )
    )


@app.route(
    "/carrito/vaciar",
    methods=["POST"]
)
def carrito_vaciar():

    session["carrito"] = {}

    session.modified = True

    return redirect(
        url_for(
            "carrito_ver"
        )
    )


# =========================================================
# CUPONES
# =========================================================

def hoy_argentina():
    return (datetime.utcnow() - timedelta(hours=3)).date()


def validar_cupon(codigo):
    """Devuelve (cupon, None) si sirve, o (None, mensaje_de_error)."""
    codigo = re.sub(r"\s+", "", codigo or "").upper()
    if not codigo:
        return None, "Ingresá un código."

    cupon = Cupon.query.filter_by(codigo=codigo).first()
    if not cupon or not cupon.activo:
        return None, "El código no es válido."
    if cupon.vence and hoy_argentina() > cupon.vence:
        return None, "El código venció."

    # Los usos en pedidos fallidos/cancelados no cuentan
    usos = (
        CuponUso.query
        .join(Pedido, Pedido.id == CuponUso.pedido_id)
        .filter(CuponUso.cupon_id == cupon.id, Pedido.estado != ESTADO_FALLIDO)
    )
    if cupon.usos_maximos and usos.count() >= cupon.usos_maximos:
        return None, "El código ya alcanzó su límite de usos."

    mis_pedidos = session.get("pedidos", [])
    if mis_pedidos and usos.filter(CuponUso.pedido_id.in_(mis_pedidos)).count() > 0:
        return None, "Ya usaste este código en una compra."

    return cupon, None


def cupon_de_sesion():
    codigo = session.get("cupon")
    if not codigo:
        return None, None
    cupon, error = validar_cupon(codigo)
    if not cupon:
        session.pop("cupon", None)
    return cupon, error


def precio_con_cupon(cupon, producto):
    if cupon.deporte and producto.deporte != cupon.deporte:
        return producto.precio
    if cupon.excluir_nombre and cupon.excluir_nombre.lower() in (producto.nombre or "").lower():
        return producto.precio
    return int(round(producto.precio * (100 - cupon.porcentaje) / 100))

def cumple_condiciones_varela(items):
    tubos = 0
    overgrips_wilson = 0

    for item in items:
        producto = item["producto"]
        cantidad = item["cantidad"]

        nombre = (producto.nombre or "").lower()
        marca = (producto.marca or "").lower()
        categoria = (producto.categoria or "").lower()
        deporte = (producto.deporte or "").lower()

        if deporte != "tenis":
            continue

        # Cuenta tubos: un tubo suelto suma 1 y un pack x3 suma 3.
        if "pelota" in categoria and "tubo" in nombre:
            tubos += cantidad * (3 if "pack" in nombre else 1)

        # Cuenta overgrips Wilson vendidos por unidad.
        if marca == "wilson" and "overgrip" in nombre:
            overgrips_wilson += cantidad

    return tubos >= 3 or (tubos >= 2 and overgrips_wilson >= 2)

@app.route("/carrito/cupon", methods=["POST"])
def cupon_aplicar():
    cupon, error = validar_cupon(request.form.get("codigo"))
    if cupon:
        session["cupon"] = cupon.codigo
        session.pop("error_cupon", None)
    else:
        session.pop("cupon", None)
        session["error_cupon"] = error
    return redirect(url_for("carrito_pagar"))


@app.route("/carrito/cupon/quitar", methods=["POST"])
def cupon_quitar():
    session.pop("cupon", None)
    return redirect(url_for("carrito_pagar"))


# =========================================================
# PEDIDOS: HELPERS
# =========================================================

def clave_carrito(producto_id, talle=None):
    """Clave del ítem en el carrito: '12' o, si tiene talle, '12|M'."""
    return f"{producto_id}|{talle}" if talle else str(producto_id)


def separar_clave(clave):
    """'12|M' -> (12, 'M'); '12' -> (12, None)."""
    producto_id, _, talle = str(clave).partition("|")
    return int(producto_id), (talle or None)


def talle_del_form(producto):
    """Talle elegido por el cliente, solo si el producto lo tiene. None si no aplica."""
    if not producto.tiene_talles:
        return None
    talle = (request.form.get("talle") or "").strip().upper()
    return talle if talle in producto.stock_talles else None


def armar_items_carrito():
    """Lee el carrito de la sesión y devuelve (items, total, total_items).
    Los precios salen SIEMPRE de la base de datos, nunca del navegador."""
    carrito = session.get("carrito", {})
    items, total, total_items = [], 0, 0

    for clave, cantidad in carrito.items():
        try:
            producto_id, talle = separar_clave(clave)
        except ValueError:
            continue
        producto = db.session.get(Producto, producto_id)
        if not producto or cantidad <= 0:
            continue
        # Si el producto tiene talles, el ítem tiene que tener uno válido (y al revés)
        if producto.tiene_talles != bool(talle) or (talle and talle not in producto.stock_talles):
            continue
        subtotal = producto.precio * cantidad
        items.append({
            "producto": producto,
            "talle": talle,
            "cantidad": cantidad,
            "stock_disponible": producto.stock_de(talle),
            "subtotal": subtotal,
        })
        total += subtotal
        total_items += cantidad

    return items, total, total_items


@app.template_global()
def palabra_talle(talle=None, producto=None):
    """'Grip' para raquetas (4 3/8), 'Talle' para ropa (M)."""
    if (producto is not None and (producto.categoria or "") == "Raquetas") or "/" in (talle or ""):
        return "Grip"
    return "Talle"


@app.template_global()
def nombre_con_talle(nombre, talle):
    return f"{nombre} ({palabra_talle(talle).lower()} {talle})" if talle else nombre



def crear_pedido(
    items,
    medio_pago,
    total,
    cupon=None,
    descuento=0,
    datos_cliente=None,
    costo_envio=0,
    servicio_envio=None,
):
    """Registra el pedido con los datos del comprador y sus productos.
    `total` ya incluye el costo de envío."""
    datos_cliente = datos_cliente or {}

    pedido = Pedido(
        estado=ESTADO_PENDIENTE,
        medio_pago=medio_pago,
        total=int(total),
        nombre_cliente=datos_cliente.get("nombre_cliente"),
        email_cliente=datos_cliente.get("email_cliente"),
        telefono_cliente=datos_cliente.get("telefono_cliente"),
        modalidad_entrega=datos_cliente.get("modalidad_entrega"),
        direccion=datos_cliente.get("direccion"),
        localidad=datos_cliente.get("localidad"),
        provincia=datos_cliente.get("provincia"),
        codigo_postal=datos_cliente.get("codigo_postal"),
        costo_envio=int(costo_envio or 0),
        servicio_envio=servicio_envio,
    )

    for item in items:
        p = item["producto"]
        pedido.lineas.append(
            LineaPedido(
                producto_id=p.id,
                nombre_producto=p.nombre,
                precio_unitario=item.get("precio_unitario", p.precio),
                cantidad=int(item["cantidad"]),
                talle=item.get("talle"),
            )
        )

    db.session.add(pedido)

    if cupon and descuento > 0:
        db.session.flush()
        db.session.add(
            CuponUso(
                cupon_id=cupon.id,
                pedido_id=pedido.id,
                descuento=int(descuento),
            )
        )

    db.session.commit()

    # El cliente solo puede ver los pedidos creados en su sesión.
    pedidos = session.get("pedidos", [])
    pedidos.append(pedido.id)
    session["pedidos"] = pedidos
    session.modified = True

    avisar_pedido_nuevo(pedido)
    return pedido



def confirmar_pago(pedido):
    """Marca el pedido como pagado y descuenta el stock (una sola vez)."""
    if pedido.estado == ESTADO_PAGADO:
        return
    for linea in pedido.lineas:
        producto = db.session.get(Producto, linea.producto_id) if linea.producto_id else None
        if not producto:
            continue
        talles = producto.stock_talles
        if linea.talle and linea.talle in talles:
            # descuenta del talle comprado; `stock` queda como la suma
            talles[linea.talle] = max(0, talles[linea.talle] - linea.cantidad)
            producto.guardar_talles(talles)
        else:
            producto.stock = max(0, producto.stock - linea.cantidad)
    pedido.estado = ESTADO_PAGADO
    db.session.commit()


def pagar_con_mercadopago(
    items,
    total,
    cupon=None,
    descuento=0,
    datos_cliente=None,
    costo_envio=0,
    servicio_envio=None,
):
    """`total` ya incluye el costo de envío (el webhook lo compara con lo cobrado)."""
    if mp is None:
        return "Mercado Pago no está configurado. Falta MP_ACCESS_TOKEN.", 500

    pedido = crear_pedido(
        items,
        "mercadopago",
        total,
        cupon,
        descuento,
        datos_cliente=datos_cliente,
        costo_envio=costo_envio,
        servicio_envio=servicio_envio,
    )

    preference_data = {
        "items": [
            {
                "title": nombre_con_talle(i["producto"].nombre, i.get("talle")),
                "quantity": int(i["cantidad"]),
                "unit_price": float(i.get("precio_unitario", i["producto"].precio)),
                "currency_id": "ARS",
            }
            for i in items
        ],
        "external_reference": str(pedido.id),
        "back_urls": {
            "success": f"{URL_PUBLICA}/pago/exitoso",
            "failure": f"{URL_PUBLICA}/pago/fallido",
            "pending": f"{URL_PUBLICA}/pago/pendiente",
        },
    }

    # El envío va como un ítem más para que lo cobrado coincida con pedido.total
    if costo_envio and costo_envio > 0:
        preference_data["items"].append({
            "title": f"Envío {servicio_envio or 'Correo Argentino'}",
            "quantity": 1,
            "unit_price": float(costo_envio),
            "currency_id": "ARS",
        })

    # auto_return y webhook exigen una URL pública con https
    if URL_PUBLICA.startswith("https://"):
        preference_data["auto_return"] = "approved"
        preference_data["notification_url"] = f"{URL_PUBLICA}/mp/webhook"

    try:
        resultado = mp.preference().create(preference_data)
    except Exception:
        app.logger.exception("Error al crear la preferencia de Mercado Pago")
        pedido.estado = ESTADO_FALLIDO
        db.session.commit()
        return "No se pudo crear el pago con Mercado Pago.", 500

    respuesta = resultado.get("response", {})
    if resultado.get("status") != 201 or not respuesta.get("init_point"):
        app.logger.error("Mercado Pago rechazó la preferencia: %s", resultado)
        pedido.estado = ESTADO_FALLIDO
        db.session.commit()
        return "Mercado Pago no pudo iniciar el pago.", 500

    pedido.mp_preference_id = respuesta.get("id")
    db.session.commit()
    return redirect(respuesta["init_point"])


# =========================================================
# COTIZAR ENVÍO (lo llama el checkout cuando se escribe el CP)
# =========================================================

@app.route("/envio/cotizar", methods=["POST"])
def envio_cotizar():
    items, total, _ = armar_items_carrito()
    if not items:
        return {"error": "Tu carrito está vacío."}, 400

    cp = normalizar_cp((request.get_json(silent=True) or {}).get("cp"))
    if not cp:
        return {"error": "Ingresá un código postal de 4 números."}, 400

    try:
        opciones = tarifas_envio(items, total, cp)
    except micorreo.MiCorreoError:
        app.logger.exception("Error cotizando envío")
        return {
            "error": "No pudimos cotizar el envío ahora. Podés continuar y te lo informamos."
        }, 502

    return {"opciones": opciones}


# =========================================================
# PAGAR - ELEGIR MEDIO DE PAGO
# =========================================================

@app.route("/carrito/pagar", methods=["GET", "POST"])
def carrito_pagar():

    items, total, total_items = armar_items_carrito()

    if not items:
        return redirect(url_for("carrito_ver"))

    contexto = obtener_contexto_base()

    # -----------------------------------------------------
    # CUPÓN
    # -----------------------------------------------------

    cupon, error_cupon = cupon_de_sesion()
    error_cupon = session.pop("error_cupon", None) or error_cupon
    total_cupon = total

    if cupon and cupon.codigo.upper() == "VARELA5":
        if not cumple_condiciones_varela(items):
            cupon = None
            session.pop("cupon", None)
            error_cupon = (
                "VARELA5 requiere 3 tubos de pelotas (sueltos o en pack) "
                "o 2 tubos y 2 overgrips Wilson."
            )

    if cupon:
        for item in items:
            item["precio_unitario"] = precio_con_cupon(cupon, item["producto"])

        total_cupon = sum(
            item["precio_unitario"] * item["cantidad"] for item in items
        )

        if total_cupon >= total:
            cupon = None
            total_cupon = total
            hay_pack = any(
                "pack" in (i["producto"].nombre or "").lower() for i in items
            )
            error_cupon = (
                "Los packs ya incluyen 5% de descuento y no se acumulan con VARELA5."
                if hay_pack else
                "El código no aplica a los productos de tu carrito."
            )

    descuento_cupon = total - total_cupon

    # Detalle para mostrarle al cliente cómo se aplicó el descuento
    detalle_cupon = []
    if cupon:
        for item in items:
            p = item["producto"]
            ahorro = (p.precio - item["precio_unitario"]) * item["cantidad"]
            if ahorro > 0:
                motivo = ""
            elif cupon.excluir_nombre and cupon.excluir_nombre.lower() in (p.nombre or "").lower():
                motivo = "ya incluye su descuento de pack"
            else:
                motivo = "no incluido en este cupón"
            detalle_cupon.append({
                "nombre": p.nombre,
                "cantidad": item["cantidad"],
                "ahorro": ahorro,
                "motivo": motivo,
            })

    # Lo que paga por transferencia (no se acumula con el cupón: gana el precio más bajo)
    total_transferencia = total_con_transferencia(items)
    transferencia_con_cupon = bool(cupon) and total_cupon < total_transferencia
    total_transferencia_final = total_cupon if transferencia_con_cupon else total_transferencia

    # -----------------------------------------------------
    # MOSTRAR PANTALLA DE PAGO
    # -----------------------------------------------------

    if request.method == "GET":

        return render_template(
            "pago.html",
            **contexto,
            items=items,
            total=total,
            total_final=total_cupon,
            cupon=cupon,
            descuento_cupon=descuento_cupon,
            detalle_cupon=detalle_cupon,
            total_transferencia_final=total_transferencia_final,
            transferencia_con_cupon=transferencia_con_cupon,
            hay_pack=any(es_pack(i["producto"]) for i in items),
            error_cupon=error_cupon,
            descuento_transferencia=DESCUENTO_TRANSFERENCIA * 100,
        )
    # -----------------------------------------------------
    # DATOS DEL FORMULARIO
    # -----------------------------------------------------
    medio_pago = request.form.get("medio_pago")
    modalidad_entrega = request.form.get("modalidad_entrega")

    if medio_pago not in ("mercadopago", "transferencia"):
        return redirect(url_for("carrito_pagar"))

    if modalidad_entrega not in ("retiro", "envio"):
        return redirect(url_for("carrito_pagar"))

    # Leer los datos del comprador.
    datos_cliente = {
        "nombre_cliente": request.form.get("nombre_cliente", "").strip(),
        "email_cliente": request.form.get("email_cliente", "").strip(),
        "telefono_cliente": request.form.get("telefono_cliente", "").strip(),
        "modalidad_entrega": modalidad_entrega,
        "direccion": request.form.get("direccion", "").strip(),
        "localidad": request.form.get("localidad", "").strip(),
        "provincia": request.form.get("provincia", "").strip(),
        "codigo_postal": request.form.get("codigo_postal", "").strip(),
    }

    # Validar los datos obligatorios.
    if not all((
        datos_cliente["nombre_cliente"],
        datos_cliente["email_cliente"],
        datos_cliente["telefono_cliente"],
    )):
        return "Completá tu nombre, email y teléfono para continuar.", 400

    email = datos_cliente["email_cliente"]
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        return "Ingresá un email válido para continuar.", 400

    if modalidad_entrega == "envio":
        if not all((
            datos_cliente["direccion"],
            datos_cliente["localidad"],
            datos_cliente["provincia"],
            datos_cliente["codigo_postal"],
        )):
            return (
                "Para el envío, completá dirección, localidad, "
                "provincia y código postal.",
                400,
            )

        if not normalizar_cp(datos_cliente["codigo_postal"]):
            return "Ingresá un código postal válido (4 números).", 400


    # -----------------------------------------------------
    # CONTROLAR STOCK
    # -----------------------------------------------------

    for item in items:
        if item["cantidad"] > item["stock_disponible"]:
            return (
                f"No hay stock suficiente de "
                f"{nombre_con_talle(item['producto'].nombre, item['talle'])}.",
                400
            )

    session["modalidad_entrega"] = modalidad_entrega

    # -----------------------------------------------------
    # COSTO DE ENVÍO (se recalcula en el servidor)
    # -----------------------------------------------------

    costo_envio, servicio_envio = 0, None
    if modalidad_entrega == "envio":
        costo_envio, servicio_envio = resolver_envio(
            items,
            total,
            datos_cliente["codigo_postal"],
            request.form.get("servicio_envio"),
        )

    # -----------------------------------------------------
    # MERCADO PAGO
    # -----------------------------------------------------

    if medio_pago == "mercadopago":
        respuesta = pagar_con_mercadopago(
            items,
            total_cupon + costo_envio,
            cupon,
            descuento_cupon,
            datos_cliente=datos_cliente,
            costo_envio=costo_envio,
            servicio_envio=servicio_envio,
        )
        session.pop("cupon", None)
        return respuesta

   # -----------------------------------------------------
    # TRANSFERENCIA (5% OFF, NO ACUMULABLE CON CUPÓN)
    # -----------------------------------------------------

    total_transferencia = total_con_transferencia(items)

    # Se conserva el descuento que deja el precio más bajo.
    if cupon and total_cupon < total_transferencia:
        total_final = total_cupon
    else:
        total_final = total_transferencia
        cupon, descuento_cupon = None, 0
        for item in items:
            item["precio_unitario"] = item["producto"].precio

    # -----------------------------------------------------
    # CREAR PEDIDO (el 5% va solo sobre los productos, no sobre el envío)
    # -----------------------------------------------------

    pedido = crear_pedido(
        items,
        medio_pago,
        total_final + costo_envio,
        cupon,
        descuento_cupon,
        datos_cliente=datos_cliente,
        costo_envio=costo_envio,
        servicio_envio=servicio_envio,
    )
    session.pop("cupon", None)

    # -----------------------------------------------------
    # GUARDAR DATOS DE ENTREGA
    # -----------------------------------------------------

    pedidos_entrega = session.get("pedidos_entrega", {})
    pedidos_entrega[str(pedido.id)] = {
        "modalidad": modalidad_entrega,
        "costo_envio": costo_envio,
    }
    session["pedidos_entrega"] = pedidos_entrega

    # -----------------------------------------------------
    # VACIAR CARRITO
    # -----------------------------------------------------

    session["carrito"] = {}
    session.modified = True

    return redirect(url_for("pedido_detalle", pedido_id=pedido.id))


# =========================================================
# DETALLE DE PEDIDO
# =========================================================

@app.route("/pedido/<int:pedido_id>")
def pedido_detalle(pedido_id):

    if pedido_id not in session.get("pedidos", []):
        abort(404)

    pedido = db.session.get(Pedido, pedido_id)

    if not pedido:
        abort(404)

    # -----------------------------------------------------
    # OBTENER MODALIDAD DE ENTREGA
    # -----------------------------------------------------

    pedidos_entrega = session.get("pedidos_entrega", {})
    datos_entrega = pedidos_entrega.get(str(pedido.id), {})
    modalidad_entrega = pedido.modalidad_entrega or datos_entrega.get("modalidad", "retiro")
    costo_envio = pedido.costo_envio or 0

    # -----------------------------------------------------
    # INFORMACIÓN DE ENTREGA
    # -----------------------------------------------------

    if modalidad_entrega == "retiro":

        entrega_titulo = "Retiro en Quilmes"

        entrega_descripcion = (
            "Podés retirar tu pedido en Quilmes. "
            "Te vamos a contactar para coordinar día y horario."
        )

    else:

        entrega_titulo = "Envío a domicilio"

        if pedido.servicio_envio and pedido.servicio_envio != "A coordinar":
            entrega_descripcion = (
                f"Enviamos tu pedido por Correo Argentino ({pedido.servicio_envio}). "
                "El costo del envío ya está incluido en el total."
            )
        else:
            entrega_descripcion = (
                "Enviamos tu pedido por Correo Argentino. "
                "Te vamos a informar el costo del envío según destino y tamaño del paquete."
            )

    # -----------------------------------------------------
    # INFORMACIÓN DEL MEDIO DE PAGO
    # -----------------------------------------------------

    if pedido.medio_pago == "transferencia":
        medio_pago_titulo = "Transferencia bancaria"
        medio_pago_descripcion = (
            "Al pagar por transferencia aplicamos el 5% de descuento "
            "(no incluye packs) o tu cupón, si te conviene más."
        )

    elif pedido.medio_pago == "mercadopago":
        medio_pago_titulo = "Mercado Pago"
        medio_pago_descripcion = (
            "El pago se realiza mediante Mercado Pago."
        )

    else:
        medio_pago_titulo = pedido.medio_pago
        medio_pago_descripcion = ""

    # -----------------------------------------------------
    # WHATSAPP
    # -----------------------------------------------------

    texto_whatsapp = (
        f"Hola! Te escribo por el pedido "
        f"#{pedido.id} "
        f"(total ${pedido.total:,.0f})"
    ).replace(",", ".")

    # -----------------------------------------------------
    # CONTEXTO
    # -----------------------------------------------------

    contexto = obtener_contexto_base()

    contexto.update({

        "pedido": pedido,

        "modalidad_entrega": modalidad_entrega,

        "entrega_titulo": entrega_titulo,

        "entrega_descripcion": entrega_descripcion,

        "costo_envio": costo_envio,

        "medio_pago_titulo": medio_pago_titulo,

        "medio_pago_descripcion": medio_pago_descripcion,

    })

    return render_template(
        "pedido.html",
        **contexto,  # ya incluye "pedido"
        transferencia=DATOS_TRANSFERENCIA,
        whatsapp=WHATSAPP_VENDEDOR,
        texto_whatsapp=texto_whatsapp,
    )


# =========================================================
# RESULTADO DEL PAGO (vuelta desde Mercado Pago)
# Solo informativo: el estado real lo confirma el webhook.
# =========================================================

def resultado_pago(estado):

    if estado in ("exito", "pendiente"):
        session["carrito"] = {}
        session.modified = True

    contexto = obtener_contexto_base()

    return render_template(
        "pago_resultado.html", **contexto,
        estado=estado,
        payment_id=request.args.get("payment_id"),
        status=request.args.get("status"),
    )


@app.route("/pago/exitoso")
def pago_exitoso():
    return resultado_pago("exito")


@app.route("/pago/pendiente")
def pago_pendiente():
    return resultado_pago("pendiente")


@app.route("/pago/fallido")
def pago_fallido():
    return resultado_pago("fallo")


# =========================================================
# WEBHOOK MERCADO PAGO
# =========================================================

@app.route("/mp/webhook", methods=["POST"])
def mp_webhook():

    if mp is None:
        return "", 200

    data = request.get_json(silent=True) or {}
    tipo = request.args.get("type") or data.get("type")
    payment_id = request.args.get("data.id") or (data.get("data") or {}).get("id")

    if tipo != "payment" or not payment_id:
        return "", 200

    # Se consulta el pago a la API de MP: no se confía en lo que llega en el POST
    r = mp.payment().get(payment_id)
    if r.get("status") != 200:
        return "", 500  # MP reintenta

    pago = r["response"]

    try:
        pedido = db.session.get(Pedido, int(pago.get("external_reference") or 0))
    except ValueError:
        return "", 200

    if not pedido or pedido.medio_pago != "mercadopago":
        return "", 200

    pedido.mp_payment_id = str(payment_id)
    estado_mp = pago.get("status")

    if estado_mp == "approved":
        if float(pago.get("transaction_amount", 0)) >= pedido.total:
            if pedido.estado != ESTADO_PAGADO:
                confirmar_pago(pedido)
                avisar_pago_confirmado(pedido)
        else:
            app.logger.error(
                "Monto pagado menor al del pedido %s",
                pedido.id,
            )
    elif estado_mp in ("rejected", "cancelled") and pedido.estado != ESTADO_PAGADO:
        pedido.estado = ESTADO_FALLIDO

    db.session.commit()
    return "", 200

# =========================================================
# FEED DE GOOGLE MERCHANT CENTER
# =========================================================

def feed_titulo(p):
    t = (p.nombre or "").strip()
    cat = (p.categoria or "").lower()
    marca = (p.marca or "").strip()

    # Títulos en MAYÚSCULAS (zapatillas Head): pasar a formato normal
    if t.isupper():
        t = t.title()

    # Las zapatillas tienen que decir que son zapatillas
    if cat.startswith("calzado") and "zapatilla" not in t.lower():
        t = f"Zapatillas {marca.title()} {t}".replace("  ", " ")

    return t


def feed_categoria_google(p):
    """Solo categorías generales de la taxonomía de Google, para evitar rechazos."""
    cat = (p.categoria or "").lower()
    if cat.startswith("calzado"):
        return "Apparel & Accessories > Shoes"
    if cat.startswith("indumentaria"):
        return "Apparel & Accessories > Clothing"
    return "Sporting Goods"


@app.route("/feed/google.xml")
def feed_google():
    productos = (
        Producto.query
        .filter(
            Producto.stock > 0,
            Producto.precio > 0,
            Producto.slug != None,                      # noqa: E711
            db.func.coalesce(Producto.imagen, "") != "",
        )
        .order_by(Producto.id)
        .all()
    )

    items = []
    for p in productos:
        titulo = feed_titulo(p)
        marca = (p.marca or "SOPI").strip()
        descripcion = (p.descripcion or "").strip() or f"{titulo} - {marca}"
        imagen = (p.imagen or "").strip().lower()       # corrige el 404 por mayúsculas

        link = url_abs(url_for("producto_detalle", slug=p.slug))
        image_link = url_abs(url_for("static", filename=f"img/{imagen}"))

        items.append(f"""<item>
<g:id>{p.id}</g:id>
<g:title>{escape(titulo)}</g:title>
<g:description>{escape(descripcion)}</g:description>
<g:link>{escape(link)}</g:link>
<g:image_link>{escape(image_link)}</g:image_link>
<g:availability>in_stock</g:availability>
<g:price>{int(p.precio)}.00 ARS</g:price>
<g:brand>{escape(marca)}</g:brand>
<g:condition>new</g:condition>
<g:google_product_category>{escape(feed_categoria_google(p))}</g:google_product_category>
<g:identifier_exists>no</g:identifier_exists>
</item>""")

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss xmlns:g="http://base.google.com/ns/1.0" version="2.0">\n'
        "<channel>\n"
        "<title>SOPI Sports</title>\n"
        f"<link>{URL_PUBLICA}</link>\n"
        "<description>Productos de pádel y tenis</description>\n"
        + "\n".join(items)
        + "\n</channel>\n</rss>"
    )
    return Response(xml, mimetype="application/xml")

# =========================================================
# SEO: ROBOTS.TXT Y SITEMAP.XML
# =========================================================

@app.route("/robots.txt")
def robots():
    lineas = [
        "User-agent: *",
        "Disallow: /admin",
        "Disallow: /carrito",
        "Disallow: /pedido",
        "Disallow: /pago",
        "Disallow: /mp/",
        "Disallow: /envio/",
        "Disallow: /health",
        "Disallow: /*?*q=",
        "Disallow: /*?*orden=",
        "Disallow: /*?*max_precio=",
        "",
        f"Sitemap: {URL_PUBLICA}/sitemap.xml",
    ]
    return Response("\n".join(lineas), mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    rutas = ["/", "/catalogo/tenis", "/catalogo/padel", url_for("quienes_somos")]

    # Una URL por categoría que tenga productos (ej: /catalogo/padel?categoria=Palas)
    slug_por_deporte = {nombre: slug for slug, nombre in NAV_DEPORTES.items()}
    filas = (
        db.session.query(Producto.deporte, Producto.categoria)
        .filter(Producto.categoria != "")
        .distinct()
        .order_by(Producto.deporte, Producto.categoria)
    )
    for deporte, categoria in filas:
        slug = slug_por_deporte.get(deporte)
        if slug and categoria:
            rutas.append(f"/catalogo/{slug}?categoria={quote(categoria)}")

    rutas += [
        url_for("producto_detalle", slug=slug)
        for (slug,) in db.session.query(Producto.slug)
        .filter(Producto.slug != None)   # noqa: E711
        .order_by(Producto.id)
    ]

    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for ruta in rutas:
        xml.append(f"  <url><loc>{URL_PUBLICA}{ruta}</loc></url>")
    xml.append("</urlset>")

    return Response("\n".join(xml), mimetype="application/xml")


# =========================================================
# ADMIN
# =========================================================

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")


def admin_requerido(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return vista(*args, **kwargs)
    return envoltura


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():

    error = None

    if request.method == "POST":
        # Tolera distintos nombres de campo para no obligarte a tocar tu template
        clave = ""
        for nombre in ("password", "clave", "contrasena", "contraseña", "pass"):
            if request.form.get(nombre):
                clave = request.form[nombre]
                break
        else:
            clave = next(iter(request.form.values()), "")
        if ADMIN_PASSWORD and hmac.compare_digest(clave.encode(), ADMIN_PASSWORD.encode()):
            session["admin"] = True
            return redirect(url_for("admin_pedidos"))
        error = "Contraseña incorrecta."

    contexto = obtener_contexto_base()

    return render_template("admin_login.html", **contexto, error=error)


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("portada"))


@app.route("/admin/pedidos")
@admin_requerido
def admin_pedidos():

    estado = request.args.get("estado", "")

    query = Pedido.query
    if estado in (ESTADO_PENDIENTE, ESTADO_PAGADO, ESTADO_FALLIDO):
        query = query.filter_by(estado=estado)

    pedidos = query.order_by(Pedido.creado_en.desc()).limit(200).all()

    contexto = obtener_contexto_base()

    return render_template("admin_pedidos.html", **contexto, pedidos=pedidos, estado=estado)


@app.route("/admin/pedidos/<int:pedido_id>/pagado", methods=["POST"])
@admin_requerido
def admin_pedido_pagado(pedido_id):
    pedido = db.get_or_404(Pedido, pedido_id)
    confirmar_pago(pedido)  # descuenta stock una sola vez
    return redirect(url_for("admin_pedidos", estado=request.form.get("volver", "")))


@app.route("/admin/pedidos/<int:pedido_id>/cancelar", methods=["POST"])
@admin_requerido
def admin_pedido_cancelar(pedido_id):
    pedido = db.get_or_404(Pedido, pedido_id)
    if pedido.estado == ESTADO_PENDIENTE:
        pedido.estado = ESTADO_FALLIDO
        db.session.commit()
    return redirect(url_for("admin_pedidos", estado=request.form.get("volver", "")))


# =========================================================
# ADMIN: CARGA DE PRECIOS, COSTOS Y STOCK POR CSV
# =========================================================

# Margen sobre el costo. Se puede cambiar con la variable de entorno MARGEN (ej: 0.35)
MARGEN = float(os.environ.get("MARGEN", "0.40"))


def precio_desde_costo(costo):
    """Costo + margen, redondeado al múltiplo de $100 más cercano."""
    return int(round(costo * (1 + MARGEN) / 100.0)) * 100


def a_entero(valor):
    valor = (valor or "").strip()
    return int(float(valor)) if valor else None


@app.route("/admin/precios", methods=["GET", "POST"])
@admin_requerido
def admin_precios():

    resultado = None

    if request.method == "POST":
        archivo = request.files.get("csv")
        creados, actualizados, errores = 0, 0, []

        if archivo:
            datos = archivo.read()
            try:
                texto = datos.decode("utf-8-sig")
            except UnicodeDecodeError:
                texto = datos.decode("cp1252")   # CSV guardado por Excel

            try:
                dialecto = csv.Sniffer().sniff(texto[:2048], delimiters=",;")
            except csv.Error:
                dialecto = csv.excel

            for n, fila in enumerate(csv.DictReader(io.StringIO(texto), dialect=dialecto), start=2):
                nombre = (fila.get("nombre") or "").strip()
                if not nombre:
                    continue

                try:
                    costo = a_entero(fila.get("costo"))
                    precio = a_entero(fila.get("precio"))
                    stock = a_entero(fila.get("stock"))
                except ValueError:
                    errores.append(f"Fila {n} ({nombre}): número inválido")
                    continue

                imagen = (fila.get("imagen") or "").strip().lower()

                # Columna opcional "talles", ej: "S:2 M:3 L:0" (si viene, manda sobre "stock")
                talles_csv = parsear_talles(fila.get("talles"))
                if (fila.get("talles") or "").strip() and not talles_csv:
                    errores.append(f"Fila {n} ({nombre}): talles inválidos (formato: S:2 M:3 L:0)")
                    continue

                if precio is None and costo is not None:
                    precio = precio_desde_costo(costo)

                # Se busca por slug (columna opcional), luego por nombre y,
                # por último, por el slug que sale del nombre.
                slug_csv = (fila.get("slug") or "").strip()
                p = None
                if slug_csv:
                    p = Producto.query.filter_by(slug=slug_csv).first()
                if not p:
                    p = Producto.query.filter(
                        db.func.lower(db.func.trim(Producto.nombre)) == nombre.lower()
                    ).first()
                if not p:
                    p = Producto.query.filter_by(slug=generar_slug(nombre)).first()

                if p:
                    if costo is not None:
                        p.costo = costo
                    if precio is not None:
                        p.precio = precio
                    if talles_csv:
                        p.guardar_talles(talles_csv)
                    elif stock is not None and not p.tiene_talles:
                        p.stock = stock
                    if imagen:
                        p.imagen = imagen
                    descripcion = (fila.get("descripcion") or "").strip()
                    if descripcion:
                        p.descripcion = descripcion
                    categoria = (fila.get("categoria") or "").strip()
                    marca = (fila.get("marca") or "").strip()
                    deporte = (fila.get("deporte") or "").strip()
                    if categoria:
                        p.categoria = categoria
                    if marca:
                        p.marca = marca
                    if deporte in ("Tenis", "Pádel"):
                        p.deporte = deporte
                    actualizados += 1
                else:
                    deporte = (fila.get("deporte") or "").strip()
                    if deporte not in ("Tenis", "Pádel") or precio is None:
                        errores.append(
                            f"Fila {n} ({nombre}): producto nuevo, falta deporte (Tenis/Pádel) o precio/costo"
                        )
                        continue
                    nuevo = Producto(
                        nombre=nombre,
                        slug=generar_slug(nombre),
                        marca=(fila.get("marca") or "").strip(),
                        deporte=deporte,
                        categoria=(fila.get("categoria") or "").strip(),
                        descripcion=(fila.get("descripcion") or "").strip(),
                        imagen=imagen,
                        costo=costo,
                        precio=precio,
                        stock=stock or 0,
                    )
                    if talles_csv:
                        nuevo.guardar_talles(talles_csv)
                    db.session.add(nuevo)
                    creados += 1

            db.session.commit()

        resultado = {"creados": creados, "actualizados": actualizados, "errores": errores}

    contexto = obtener_contexto_base()

    return render_template(
        "admin_precios.html", **contexto,
        resultado=resultado, margen=MARGEN,
    )


# =========================================================
# ADMIN: INICIO Y LISTADO DE PRODUCTOS
# =========================================================

@app.route("/admin/")
@admin_requerido
def admin_inicio():
    return redirect(url_for("admin_pedidos"))


@app.route("/admin/productos")
@admin_requerido
def admin_productos():

    productos = (
        Producto.query
        .order_by(Producto.deporte, Producto.categoria, Producto.nombre)
        .all()
    )

    contexto = obtener_contexto_base()

    return render_template("admin_productos.html", **contexto, productos=productos)


@app.route("/admin/productos/<int:producto_id>/talles", methods=["POST"])
@admin_requerido
def admin_producto_talles(producto_id):
    """Carga el stock por talle desde el listado, ej: 'S:2 M:3 L:0'.
    Vacío = el producto deja de usar talles (conserva su stock actual)."""
    producto = db.get_or_404(Producto, producto_id)
    texto = (request.form.get("talles") or "").strip()
    talles = parsear_talles(texto)
    if talles:
        producto.guardar_talles(talles)
    elif not texto:
        producto.talles = None
    db.session.commit()
    return redirect(url_for("admin_productos") + f"#p{producto.id}")


@app.route("/admin/productos/<int:producto_id>/borrar", methods=["POST"])
@admin_requerido
def admin_producto_borrar(producto_id):
    producto = db.get_or_404(Producto, producto_id)

    # Los pedidos conservan nombre y precio (snapshot): solo se suelta la referencia
    LineaPedido.query.filter_by(producto_id=producto.id).update({"producto_id": None})

    db.session.delete(producto)
    db.session.commit()
    return redirect(url_for("admin_productos"))


# =========================================================
# COMPATIBILIDAD
# =========================================================

@app.route(
    "/productos"
)
def productos():

    return redirect(
        url_for(
            "catalogo_tenis"
        )
    )

# =========================================================
# PÁGINAS LEGALES
# =========================================================
legales.init_app(app, obtener_contexto_base)
# =========================================================
# INICIO
# =========================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
