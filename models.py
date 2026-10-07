from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# Estados posibles de un Pedido
ESTADO_PENDIENTE = "pendiente"
ESTADO_PAGADO = "pagado"
ESTADO_FALLIDO = "fallido"


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

    id = db.Column(db.Integer, primary_key=True)
    estado = db.Column(db.String(20), nullable=False, default=ESTADO_PENDIENTE)
    total = db.Column(db.Integer, nullable=False, default=0)
    medio_pago = db.Column(db.String(20), nullable=True)  # mercadopago | transferencia | efectivo
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

    @property
    def subtotal(self):
        return self.precio_unitario * self.cantidad

    def to_dict(self):
        return {
            "producto_id": self.producto_id,
            "nombre_producto": self.nombre_producto,
            "precio_unitario": self.precio_unitario,
            "cantidad": self.cantidad,
            "subtotal": self.subtotal,
        }
