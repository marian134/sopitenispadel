from flask import Flask, render_template, request, redirect, url_for, session
import os
import mercadopago

from models import db, Producto


# =========================================================
# APP
# =========================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "clave-desarrollo-tienda-tenis"
)


# =========================================================
# BASE DE DATOS
# =========================================================

basedir = os.path.abspath(
    os.path.dirname(__file__)
)

app.config["SQLALCHEMY_DATABASE_URI"] = (
    "sqlite:///"
    + os.path.join(
        basedir,
        "instance",
        "tienda.db"
    )
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


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

URL_PUBLICA = (
    "https://maintain-market-disclosure-switch.trycloudflare.com"
)

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
# PAGAR - CHECKOUT PRO
# =========================================================

@app.route(
    "/carrito/pagar",
    methods=["GET", "POST"]
)
def carrito_pagar():

    carrito = session.get(
        "carrito",
        {}
    )

    if not carrito:

        return redirect(
            url_for(
                "carrito_ver"
            )
        )

    contexto = obtener_contexto_base()

    items = []

    total = 0

    total_items = 0

    # ---------------------------------------------------------
    # ARMAR CARRITO
    # ---------------------------------------------------------

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

            "subtotal": subtotal
        })

        total += subtotal

        total_items += cantidad

    # ---------------------------------------------------------
    # POST
    # ---------------------------------------------------------

    if request.method == "POST":

        medio_pago = request.form.get(
            "medio_pago"
        )

        # =====================================================
        # MERCADO PAGO
        # =====================================================

        if medio_pago == "mercadopago":

            if mp is None:

                return (
                    "Mercado Pago no está configurado. "
                    "Falta MP_ACCESS_TOKEN.",
                    500
                )

            items_mp = []

            for item in items:

                producto = item[
                    "producto"
                ]

                cantidad = item[
                    "cantidad"
                ]

                if cantidad <= 0:
                    continue

                if cantidad > producto.stock:

                    return (
                        f"No hay stock suficiente de "
                        f"{producto.nombre}.",
                        400
                    )

                items_mp.append({

                    "title":
                        producto.nombre,

                    "quantity":
                        int(cantidad),

                    "unit_price":
                        float(
                            producto.precio
                        ),

                    "currency_id":
                        "ARS"
                })

            if not items_mp:

                return redirect(
                    url_for(
                        "carrito_ver"
                    )
                )

            # -------------------------------------------------
            # PREFERENCIA MERCADO PAGO
            # -------------------------------------------------
            preference_data = {
                "items": items_mp,
                "back_urls": {
                    "success": (
                        f"{URL_PUBLICA}/pago/exitoso"
                    ),
                    "failure": (
                        f"{URL_PUBLICA}/pago/fallido"
                    ),
                    "pending": (
                        f"{URL_PUBLICA}/pago/pendiente"
                    )
                },
                "auto_return": "approved",
                "external_reference": (
                    f"TIENDA-"
                    f"{total_items}-"
                    f"{int(total)}"
                )
            }

            # -------------------------------------------------
            # CREAR PREFERENCIA
            # -------------------------------------------------

            try:

                resultado = (
                    mp
                    .preference()
                    .create(
                        preference_data
                    )
                )

                print(
                    "RESPUESTA MERCADO PAGO:"
                )

                print(
                    resultado
                )

                status_code = (
                    resultado.get(
                        "status"
                    )
                )

                response = (
                    resultado.get(
                        "response",
                        {}
                    )
                )

                # -------------------------------------------------
                # ERROR MERCADO PAGO
                # -------------------------------------------------

                if status_code != 201:

                    print(
                        "STATUS MERCADO PAGO:",
                        status_code
                    )

                    return (
                        "Mercado Pago rechazó "
                        "la creación del pago. "
                        "Revisá la consola.",
                        500
                    )

                # -------------------------------------------------
                # LINK CHECKOUT PRO
                # -------------------------------------------------

                init_point = (
                    response.get(
                        "init_point"
                    )
                )

                if not init_point:

                    print(
                        "NO SE ENCONTRÓ INIT_POINT"
                    )

                    print(
                        "RESPONSE:",
                        response
                    )

                    return (
                        "Mercado Pago no devolvió "
                        "el enlace de pago.",
                        500
                    )

                print(
                    "INIT POINT:"
                )

                print(
                    init_point
                )

                return redirect(
                    init_point
                )

            except Exception as e:

                print(
                    "ERROR MERCADO PAGO:"
                )

                print(
                    repr(e)
                )

                return (
                    "No se pudo crear el pago "
                    "con Mercado Pago.",
                    500
                )

        # =====================================================
        # EFECTIVO
        # =====================================================

        if medio_pago == "efectivo":

            total_final = (
                total * 0.95
            )

        else:

            total_final = total

        return render_template(

            "pago.html",

            **contexto,

            items=items,

            total=total,

            total_final=total_final,

            medio_pago=medio_pago
        )

    # ---------------------------------------------------------
    # GET
    # ---------------------------------------------------------

    return render_template(

        "pago.html",

        **contexto,

        items=items,

        total=total,

        total_final=total
    )


# =========================================================
# RESULTADO PAGO EXITOSO
# =========================================================

@app.route(
    "/pago/exitoso"
)
def pago_exitoso():

    payment_id = request.args.get(
        "payment_id"
    )

    status = request.args.get(
        "status"
    )

    contexto = obtener_contexto_base()

    return render_template(

        "pago_resultado.html",

        **contexto,

        estado="success",

        payment_id=payment_id,

        status=status
    )


# =========================================================
# RESULTADO PAGO PENDIENTE
# =========================================================

@app.route(
    "/pago/pendiente"
)
def pago_pendiente():

    payment_id = request.args.get(
        "payment_id"
    )

    status = request.args.get(
        "status"
    )

    contexto = obtener_contexto_base()

    return render_template(

        "pago_resultado.html",

        **contexto,

        estado="pending",

        payment_id=payment_id,

        status=status
    )


# =========================================================
# RESULTADO PAGO FALLIDO
# =========================================================

@app.route(
    "/pago/fallido"
)
def pago_fallido():

    payment_id = request.args.get(
        "payment_id"
    )

    status = request.args.get(
        "status"
    )

    contexto = obtener_contexto_base()

    return render_template(

        "pago_resultado.html",

        **contexto,

        estado="failure",

        payment_id=payment_id,

        status=status
    )


# =========================================================
# ADMIN LOGIN
# =========================================================

@app.route(
    "/admin/login"
)
def admin_login():

    contexto = obtener_contexto_base()

    return render_template(
        "admin_login.html",
        **contexto
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

if __name__ == "__main__":

    with app.app_context():

        db.create_all()

    app.run(
        debug=True,
        port=5000
    )