from flask import Flask, render_template, request, redirect, url_for, session, abort, Response
import os
import re
import csv
import io
import hmac
import unicodedata
import mercadopago
from templates import legales
from datetime import timedelta, datetime, date
from functools import wraps
from flask_mail import Mail, Message
from sqlalchemy import inspect, text

from models import (
    db, Producto, Pedido, LineaPedido, Cupon, CuponUso,
    ESTADO_PENDIENTE, ESTADO_PAGADO, ESTADO_FALLIDO,
)

# =========================================================
# APP
# =========================================================

app = Flask(__name__)

ES_PRODUCCION = os.environ.get("URL_BASE", "").startswith("https://")

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
    """Avisa que se registró un pedido nuevo."""
    detalle = [
        f"- {linea.nombre_producto} x {linea.cantidad}: ${linea.precio_unitario * linea.cantidad:,.0f}"
        for linea in pedido.lineas
    ]

    uso = CuponUso.query.filter_by(pedido_id=pedido.id).first()
    linea_cupon = []
    if uso:
        c = db.session.get(Cupon, uso.cupon_id)
        linea_cupon = [f"Cupón: {c.codigo} (-${uso.descuento:,.0f})"]

    cuerpo = "\n".join([
        f"Nuevo pedido #{pedido.id} en SOPI Tenis•Pádel",
        "",
        f"Estado: {pedido.estado}",
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

    # Migración liviana: agrega costo si la tabla productos ya existía sin esa columna
    columnas_productos = [c["name"] for c in inspect(db.engine).get_columns("productos")]
    if "costo" not in columnas_productos:
        db.session.execute(text("ALTER TABLE productos ADD COLUMN costo INTEGER"))
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

DESCUENTO_EFECTIVO = 0.05

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


@app.context_processor
def seo():
    """Helpers de SEO disponibles en todas las plantillas."""
    def url_abs(ruta):
        return f"{URL_PUBLICA}{ruta}"
    return {
        "url_abs": url_abs,
        # sin query string: /catalogo/padel?orden=... apunta a la URL limpia
        "canonical_default": f"{URL_PUBLICA}{request.path}",
    }


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

        query = query.filter_by(
            categoria=filtros["categoria"]
        )

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
ORDEN_CATEGORIAS = ["Palas", "Pelotas", "Accesorios"]


def clave_categoria(categoria):
    if categoria in ORDEN_CATEGORIAS:
        return (0, ORDEN_CATEGORIAS.index(categoria), "")
    return (1, 0, categoria.lower())


def agrupar_por_categoria(productos):
    """[(categoria, [productos...]), ...] respetando el orden de ORDEN_CATEGORIAS."""
    grupos = {}
    for p in productos:
        grupos.setdefault(p.categoria or "Otros", []).append(p)
    return sorted(grupos.items(), key=lambda g: clave_categoria(g[0]))


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
# PORTADA
# =========================================================

@app.route("/")
def portada():

    contexto = obtener_contexto_base()

    return render_template(
        "portada.html",
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
    }

    productos = (
        obtener_productos_por_deporte(
            deporte_slug,
            filtros
        )
    )

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

        "marcas": marcas,

        "filtros": filtros,
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

    carrito = session.get(
        "carrito",
        {}
    )

    items = []
    total = 0

    for producto_id, cantidad in carrito.items():

        producto = db.session.get(
            Producto,
            int(producto_id)
        )

        if not producto:
            continue

        subtotal = (
            producto.precio
            * cantidad
        )

        items.append({

            "producto": producto,

            "cantidad": cantidad,

            "subtotal": subtotal,
        })

        total += subtotal

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

    if producto.stock <= 0:

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

    clave = str(
        producto_id
    )

    cantidad_actual = carrito.get(
        clave,
        0
    )

    if cantidad_actual < producto.stock:

        carrito[clave] = (
            cantidad_actual + 1
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

    clave = str(
        producto_id
    )

    if cantidad <= 0:

        carrito.pop(
            clave,
            None
        )

    else:

        cantidad = min(
            cantidad,
            producto.stock
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

    carrito.pop(
        str(producto_id),
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

def armar_items_carrito():
    """Lee el carrito de la sesión y devuelve (items, total, total_items).
    Los precios salen SIEMPRE de la base de datos, nunca del navegador."""
    carrito = session.get("carrito", {})
    items, total, total_items = [], 0, 0

    for producto_id, cantidad in carrito.items():
        producto = db.session.get(Producto, int(producto_id))
        if not producto or cantidad <= 0:
            continue
        subtotal = producto.precio * cantidad
        items.append({"producto": producto, "cantidad": cantidad, "subtotal": subtotal})
        total += subtotal
        total_items += cantidad

    return items, total, total_items


def crear_pedido(items, medio_pago, total, cupon=None, descuento=0):
    """Registra el pedido (estado pendiente) con un snapshot de cada línea."""
    pedido = Pedido(estado=ESTADO_PENDIENTE, medio_pago=medio_pago, total=int(total))
    for item in items:
        p = item["producto"]
        pedido.lineas.append(LineaPedido(
            producto_id=p.id,
            nombre_producto=p.nombre,
            precio_unitario=item.get("precio_unitario", p.precio),
            cantidad=int(item["cantidad"]),
        ))
    db.session.add(pedido)
    if cupon and descuento > 0:
        db.session.flush()
        db.session.add(CuponUso(
            cupon_id=cupon.id, pedido_id=pedido.id, descuento=int(descuento)
        ))
    db.session.commit()

    # El cliente solo puede ver los pedidos que creó en su sesión
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
        if producto:
            producto.stock = max(0, producto.stock - linea.cantidad)
    pedido.estado = ESTADO_PAGADO
    db.session.commit()


def pagar_con_mercadopago(items, total, cupon=None, descuento=0):
    if mp is None:
        return "Mercado Pago no está configurado. Falta MP_ACCESS_TOKEN.", 500

    pedido = crear_pedido(items, "mercadopago", total, cupon, descuento)

    preference_data = {
        "items": [
            {
                "title": i["producto"].nombre,
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

    # Lo que paga en efectivo (no se acumula con el cupón: gana el precio más bajo)
    total_efectivo = round(total * (1 - DESCUENTO_EFECTIVO))
    efectivo_con_cupon = bool(cupon) and total_cupon < total_efectivo
    total_efectivo_final = total_cupon if efectivo_con_cupon else total_efectivo

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
            total_efectivo_final=total_efectivo_final,
            efectivo_con_cupon=efectivo_con_cupon,
            error_cupon=error_cupon,
            descuento_efectivo=DESCUENTO_EFECTIVO * 100,
        )
    # -----------------------------------------------------
    # DATOS DEL FORMULARIO
    # -----------------------------------------------------

    medio_pago = request.form.get("medio_pago")
    modalidad_entrega = request.form.get("modalidad_entrega")

    if medio_pago not in ("mercadopago", "transferencia", "efectivo"):
        return redirect(url_for("carrito_pagar"))

    if modalidad_entrega not in ("retiro", "envio"):
        return redirect(url_for("carrito_pagar"))

    # -----------------------------------------------------
    # CONTROLAR STOCK
    # -----------------------------------------------------

    for item in items:
        if item["cantidad"] > item["producto"].stock:
            return (
                f"No hay stock suficiente de {item['producto'].nombre}.",
                400
            )

    session["modalidad_entrega"] = modalidad_entrega

    # -----------------------------------------------------
    # MERCADO PAGO
    # -----------------------------------------------------

    if medio_pago == "mercadopago":
        respuesta = pagar_con_mercadopago(items, total_cupon, cupon, descuento_cupon)
        session.pop("cupon", None)
        return respuesta

    # -----------------------------------------------------
    # TRANSFERENCIA / EFECTIVO
    # -----------------------------------------------------

    if medio_pago == "efectivo":
        total_efectivo = round(total * (1 - DESCUENTO_EFECTIVO))
        # No acumulable: se aplica el descuento que deja el precio más bajo
        if cupon and total_cupon < total_efectivo:
            total_final = total_cupon
        else:
            total_final = total_efectivo
            cupon, descuento_cupon = None, 0
            for item in items:
                item["precio_unitario"] = item["producto"].precio
    else:
        total_final = total_cupon

    # -----------------------------------------------------
    # CREAR PEDIDO
    # -----------------------------------------------------

    pedido = crear_pedido(items, medio_pago, total_final, cupon, descuento_cupon)
    session.pop("cupon", None)

    # -----------------------------------------------------
    # GUARDAR DATOS DE ENTREGA
    # -----------------------------------------------------

    pedidos_entrega = session.get("pedidos_entrega", {})
    pedidos_entrega[str(pedido.id)] = {
        "modalidad": modalidad_entrega,
        "costo_envio": 0,
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
    modalidad_entrega = datos_entrega.get("modalidad", "retiro")
    costo_envio = datos_entrega.get("costo_envio", 0)

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

        entrega_descripcion = (
            "Realizamos envíos a domicilio por Andreani "
            "o Correo Argentino. El costo del envío se "
            "coordina según destino y tamaño del paquete."
        )

    # -----------------------------------------------------
    # INFORMACIÓN DEL MEDIO DE PAGO
    # -----------------------------------------------------

    if pedido.medio_pago == "efectivo":

        medio_pago_titulo = "Efectivo"

        medio_pago_descripcion = (
            "El pedido tiene aplicado el 5% de descuento "
            "por pago en efectivo."
        )

    elif pedido.medio_pago == "transferencia":

        medio_pago_titulo = "Transferencia bancaria"

        medio_pago_descripcion = (
            "Te enviaremos los datos para realizar "
            "la transferencia."
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
        **contexto,
        pedido=pedido,
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
        "Disallow: /health",
        "",
        f"Sitemap: {URL_PUBLICA}/sitemap.xml",
    ]
    return Response("\n".join(lineas), mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    rutas = ["/", "/catalogo/tenis", "/catalogo/padel"]
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

                imagen = (fila.get("imagen") or "").strip()

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
                    if stock is not None:
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
                    db.session.add(Producto(
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
                    ))
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
