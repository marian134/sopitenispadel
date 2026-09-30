from flask import Flask, render_template, request, redirect, url_for, session, abort
import os
import csv
import io
import hmac
import mercadopago
from datetime import timedelta
from functools import wraps

from sqlalchemy import inspect, text

from models import (
    db, Producto, Pedido, LineaPedido,
    ESTADO_PENDIENTE, ESTADO_PAGADO, ESTADO_FALLIDO,
)


# =========================================================
# APP
# =========================================================

app = Flask(__name__)

ES_PRODUCCION = os.environ.get("URL_BASE", "").startswith("https://")

SECRET_KEY = os.environ.get("SECRET_KEY")

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
# FILTROS DE PLANTILLA
# =========================================================

@app.template_filter("pesos")
def filtro_pesos(valor):
    return "$" + "{:,.0f}".format(valor or 0).replace(",", ".")


@app.template_filter("hora_ar")
def filtro_hora_ar(fecha):
    # Las fechas se guardan en UTC; Argentina es UTC-3 todo el año
    return (fecha - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M")


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

    destacados = (
        Producto.query
        .filter(
            Producto.stock > 0
        )
        .limit(3)
        .all()
    )

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


def obtener_categorias_y_marcas(
    deporte_slug
):

    productos = Producto.query.filter_by(
        deporte=NAV_DEPORTES[deporte_slug]
    ).all()

    categorias = sorted(
        list(
            set(
                p.categoria
                for p in productos
                if p.categoria
            )
        )
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

    destacados = (
        Producto.query
        .filter_by(
            deporte=NAV_DEPORTES[
                deporte_slug
            ]
        )
        .filter(
            Producto.stock > 0
        )
        .limit(3)
        .all()
    )

    contexto = obtener_contexto_base(
        deporte_slug
    )

    contexto.update({

        "deporte": NAV_DEPORTES[
            deporte_slug
        ],

        "destacados": destacados,

        "productos": productos,

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

@app.route(
    "/producto/<int:producto_id>"
)
def producto(producto_id):

    producto = Producto.query.get_or_404(
        producto_id
    )

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


def crear_pedido(items, medio_pago, total):
    """Registra el pedido (estado pendiente) con un snapshot de cada línea."""
    pedido = Pedido(estado=ESTADO_PENDIENTE, medio_pago=medio_pago, total=int(total))
    for item in items:
        p = item["producto"]
        pedido.lineas.append(LineaPedido(
            producto_id=p.id,
            nombre_producto=p.nombre,
            precio_unitario=p.precio,
            cantidad=int(item["cantidad"]),
        ))
    db.session.add(pedido)
    db.session.commit()

    # El cliente solo puede ver los pedidos que creó en su sesión
    pedidos = session.get("pedidos", [])
    pedidos.append(pedido.id)
    session["pedidos"] = pedidos
    session.modified = True
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


def pagar_con_mercadopago(items, total):
    if mp is None:
        return "Mercado Pago no está configurado. Falta MP_ACCESS_TOKEN.", 500

    pedido = crear_pedido(items, "mercadopago", total)

    preference_data = {
        "items": [
            {
                "title": i["producto"].nombre,
                "quantity": int(i["cantidad"]),
                "unit_price": float(i["producto"].precio),
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

    if request.method == "GET":
        return render_template(
            "pago.html", **contexto,
            items=items, total=total, total_final=total,
        )

    medio_pago = request.form.get("medio_pago")

    if medio_pago not in ("mercadopago", "transferencia", "efectivo"):
        return redirect(url_for("carrito_pagar"))

    for item in items:
        if item["cantidad"] > item["producto"].stock:
            return f"No hay stock suficiente de {item['producto'].nombre}.", 400

    if medio_pago == "mercadopago":
        return pagar_con_mercadopago(items, total)

    # Transferencia y efectivo: se registra el pedido y se muestran las instrucciones
    if medio_pago == "efectivo":
        total_final = round(total * (1 - DESCUENTO_EFECTIVO))
    else:
        total_final = total

    pedido = crear_pedido(items, medio_pago, total_final)

    session["carrito"] = {}
    session.modified = True

    return redirect(url_for("pedido_detalle", pedido_id=pedido.id))


# =========================================================
# DETALLE DE PEDIDO (transferencia / efectivo)
# =========================================================

@app.route("/pedido/<int:pedido_id>")
def pedido_detalle(pedido_id):

    if pedido_id not in session.get("pedidos", []):
        abort(404)

    pedido = db.session.get(Pedido, pedido_id)
    if not pedido:
        abort(404)

    texto_whatsapp = f"Hola! Te escribo por el pedido #{pedido.id} (total ${pedido.total:,.0f})".replace(",", ".")

    contexto = obtener_contexto_base()

    return render_template(
        "pedido.html", **contexto,
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
            confirmar_pago(pedido)
        else:
            app.logger.error("Monto pagado menor al del pedido %s", pedido.id)
    elif estado_mp in ("rejected", "cancelled") and pedido.estado != ESTADO_PAGADO:
        pedido.estado = ESTADO_FALLIDO

    db.session.commit()
    return "", 200


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
            texto = archivo.read().decode("utf-8-sig")
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

                if precio is None and costo is not None:
                    precio = precio_desde_costo(costo)

                p = Producto.query.filter(
                    db.func.lower(Producto.nombre) == nombre.lower()
                ).first()

                if p:
                    if costo is not None:
                        p.costo = costo
                    if precio is not None:
                        p.precio = precio
                    if stock is not None:
                        p.stock = stock
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
                        marca=(fila.get("marca") or "").strip(),
                        deporte=deporte,
                        categoria=(fila.get("categoria") or "").strip(),
                        descripcion=(fila.get("descripcion") or "").strip(),
                        imagen="",
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
# INICIO
# =========================================================

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
