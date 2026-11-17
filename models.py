from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# Estados posibles de un Pedido
ESTADO_PENDIENTE = "pendiente"
ESTADO_PAGADO = "pagado"
ESTADO_FALLIDO = "fallido"


def parsear_talles(texto):
    """'S:2, M:0 L=3' -> {'S': 2, 'M': 0, 'L': 3}. Ignora lo que no entiende."""
    resultado = {}
    for parte in (texto or "").replace(";", ",").replace(" ", ",").split(","):
        parte = parte.strip()
        if not parte:
            continue
        separador = ":" if ":" in parte else ("=" if "=" in parte else None)
        if not separador:
            continue
        talle, cantidad = parte.split(separador, 1)
        talle = talle.strip().upper()
        try:
            resultado[talle] = max(0, int(cantidad.strip()))
        except ValueError:
            continue
    return resultado


class Producto(db.Model):
    __tablename__ = "productos"

    id = db.Column(db.Integer, primary_key=True)
    deporte = db.Column(db.String(20), nullable=False, default="Tenis")
    categoria = db.Column(db.String(50), nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(200), nullable=True)
    marca = db.Column(db.String(60), nullable=False)
    precio = db.Column(db.Integer, nullable=False)
    descripcion = db.Column(db.Text, nullable=False, default="")
    imagen = db.Column(db.String(120), nullable=False, default="")
    stock = db.Column(db.Integer, nullable=False, default=0)
    costo = db.Column(db.Integer, nullable=True)  # lo que se paga al mayorista (uso interno)
    # Stock por talle, ej: "S:2,M:0,L:3". Vacío = el producto no tiene talles.
    # Cuando hay talles, `stock` es siempre la suma de todos.
    talles = db.Column(db.String(200), nullable=True)

    @property
    def stock_talles(self):
        """{'S': 2, 'M': 0, 'L': 3} en el orden en que se cargaron."""
        return parsear_talles(self.talles)

    @property
    def tiene_talles(self):
        return bool(self.stock_talles)

    def guardar_talles(self, talles_dict):
        """Guarda el stock por talle y deja `stock` como la suma."""
        talles_dict = {t: max(0, int(c)) for t, c in talles_dict.items()}
        self.talles = ",".join(f"{t}:{c}" for t, c in talles_dict.items()) or None
        if talles_dict:
            self.stock = sum(talles_dict.values())

    def stock_de(self, talle=None):
        """Stock disponible de un talle (o del producto si no tiene talles)."""
        if self.tiene_talles:
            return self.stock_talles.get(talle or "", 0)
        return self.stock or 0

    def to_dict(self):
        return {
            "id": self.id,
            "deporte": self.deporte,
            "categoria": self.categoria,
            "nombre": self.nombre,
            "marca": self.marca,
            "precio": self.precio,
            "descripcion": self.descripcion,
            "imagen": self.imagen,
            "stock": self.stock,
        }


class Pedido(db.Model):
    """
    Un pedido creado cuando el cliente inicia el pago. Arranca en
    estado 'pendiente' y el webhook de Mercado Pago lo pasa a
    'pagado' o 'fallido' según el resultado real del cobro.
    """
    __tablename__ = "pedidos"
    costo_envio = db.Column(db.Integer, default=0)
    servicio_envio = db.Column(db.String(80))
    id = db.Column(db.Integer, primary_key=True)
    estado = db.Column(db.String(20), nullable=False, default=ESTADO_PENDIENTE)
    total = db.Column(db.Integer, nullable=False, default=0)
    medio_pago = db.Column(db.String(20), nullable=True)  # mercadopago | transferencia | efectivo
    nombre_cliente = db.Column(db.String(120), nullable=True)
    email_cliente = db.Column(db.String(120), nullable=True)
    telefono_cliente = db.Column(db.String(40), nullable=True)
    modalidad_entrega = db.Column(db.String(20), nullable=True)
    direccion = db.Column(db.String(200), nullable=True)
    localidad = db.Column(db.String(100), nullable=True)
    provincia = db.Column(db.String(100), nullable=True)
    codigo_postal = db.Column(db.String(20), nullable=True)
    mp_payment_id = db.Column(db.String(50), nullable=True)
    mp_preference_id = db.Column(db.String(50), nullable=True)
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    actualizado_en = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    lineas = db.relationship(
        "LineaPedido", backref="pedido", lazy=True, cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "estado": self.estado,
            "total": self.total,
            "creado_en": self.creado_en.isoformat(),
            "lineas": [linea.to_dict() for linea in self.lineas],
        }


class LineaPedido(db.Model):
    """
    Una línea de un pedido. Guarda nombre y precio del producto en el
    momento de la compra (snapshot), para que el pedido no cambie si
    después el producto se edita o se borra.
    """
    __tablename__ = "lineas_pedido"

    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"), nullable=True)
    nombre_producto = db.Column(db.String(120), nullable=False)
    precio_unitario = db.Column(db.Integer, nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)
    talle = db.Column(db.String(10), nullable=True)

    @property
    def subtotal(self):
        return self.precio_unitario * self.cantidad

    def to_dict(self):
        return {
            "producto_id": self.producto_id,
            "nombre_producto": self.nombre_producto,
            "precio_unitario": self.precio_unitario,
            "cantidad": self.cantidad,
            "talle": self.talle,
            "subtotal": self.subtotal,
        }
class Cupon(db.Model):
    __tablename__ = "cupones"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(30), unique=True, nullable=False)
    porcentaje = db.Column(db.Integer, nullable=False)
    vence = db.Column(db.Date)                    # último día válido
    activo = db.Column(db.Boolean, default=True, nullable=False)
    deporte = db.Column(db.String(20))            # "Tenis", "Pádel" o vacío = todos
    excluir_nombre = db.Column(db.String(50))     # ej: "Pack" no aplica a esos productos
    usos_maximos = db.Column(db.Integer)          # tope total, vacío = sin tope


class CuponUso(db.Model):
    __tablename__ = "cupon_usos"

    id = db.Column(db.Integer, primary_key=True)
    cupon_id = db.Column(db.Integer, db.ForeignKey("cupones.id"), nullable=False)
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"), nullable=False)
    descuento = db.Column(db.Integer, default=0)