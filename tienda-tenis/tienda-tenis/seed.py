"""
Crea la base de datos SQLite y carga los productos iniciales.
Ejecutar una sola vez (o cada vez que quieras resetear los datos de ejemplo):

    python seed.py
"""

from app import app
from models import db, Producto

PRODUCTOS_INICIALES = [
    dict(
        deporte="Tenis", categoria="Raquetas", nombre="Wilson Blade 100", marca="Wilson",
        precio=350000, descripcion="Raqueta de control para jugadores intermedios/avanzados.",
        imagen="raqueta_wilson.jpg", stock=8,
    ),
    dict(
        deporte="Tenis", categoria="Raquetas", nombre="Babolat Pure Drive", marca="Babolat",
        precio=380000, descripcion="Potencia y spin, ideal para juego agresivo desde el fondo.",
        imagen="raqueta_babolat.jpg", stock=5,
    ),
    dict(
        deporte="Tenis", categoria="Pelotas", nombre="Penn Championship (tubo x3)", marca="Penn",
        precio=25000, descripcion="Pelotas de tenis estándar para uso recreativo y competitivo.",
        imagen="pelotas_penn.jpg", stock=40,
    ),
    dict(
        deporte="Tenis", categoria="Pelotas", nombre="Wilson US Open (tubo x3)", marca="Wilson",
        precio=27000, descripcion="Pelota oficial de torneos, alta durabilidad.",
        imagen="pelotas_wilson.jpg", stock=35,
    ),
    dict(
        deporte="Tenis", categoria="Indumentaria", nombre="Remera Adidas Club", marca="Adidas",
        precio=45000, descripcion="Remera transpirable para entrenamiento y partidos.",
        imagen="remera_adidas.jpg", stock=20,
    ),
    dict(
        deporte="Tenis", categoria="Indumentaria", nombre="Short Nike Court", marca="Nike",
        precio=42000, descripcion="Short liviano con bolsillo para pelota.",
        imagen="short_nike.jpg", stock=15,
    ),
]


def seed():
    with app.app_context():
        db.create_all()

        if Producto.query.count() > 0:
            respuesta = input(
                "Ya hay productos cargados. ¿Borrar todo y recargar? (s/n): "
            )
            if respuesta.strip().lower() != "s":
                print("Cancelado.")
                return
            Producto.query.delete()

        for datos in PRODUCTOS_INICIALES:
            db.session.add(Producto(**datos))

        db.session.commit()
        print(f"Se cargaron {len(PRODUCTOS_INICIALES)} productos.")


if __name__ == "__main__":
    seed()
