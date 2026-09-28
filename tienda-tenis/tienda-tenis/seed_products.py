from app import app, db
from models import Producto

NAV_DEPORTES = {
    'tenis': 'Tenis',
    'padel': 'Pádel'
}

productos_ficticios = [
    # ===== TENIS =====
    Producto(
        deporte=NAV_DEPORTES['tenis'],
        categoria="Raquetas",
        nombre="Wilson Pro Staff 97",
        marca="Wilson",
        precio=45000,
        descripcion="Raqueta profesional de alto rendimiento.",
        imagen="raqueta-wilson.jpg",
        stock=8
    ),
    Producto(
        deporte=NAV_DEPORTES['tenis'],
        categoria="Raquetas",
        nombre="Head Radical Pro",
        marca="Head",
        precio=38000,
        descripcion="Raqueta versátil con gran potencia.",
        imagen="raqueta-head.jpg",
        stock=5
    ),
    Producto(
        deporte=NAV_DEPORTES['tenis'],
        categoria="Raquetas",
        nombre="Yonex VCORE 100",
        marca="Yonex",
        precio=52000,
        descripcion="Raqueta de control con excelente precisión.",
        imagen="raqueta-yonex.jpg",
        stock=3
    ),
    Producto(
        deporte=NAV_DEPORTES['tenis'],
        categoria="Pelotas",
        nombre="Wilson US Open",
        marca="Wilson",
        precio=1800,
        descripcion="Pelotas oficiales de US Open.",
        imagen="pelota-wilson.jpg",
        stock=25
    ),
    Producto(
        deporte=NAV_DEPORTES['tenis'],
        categoria="Pelotas",
        nombre="Dunlop Australian Open",
        marca="Dunlop",
        precio=2100,
        descripcion="Pelotas oficiales de Australian Open.",
        imagen="pelota-dunlop.jpg",
        stock=18
    ),
    Producto(
        deporte=NAV_DEPORTES['tenis'],
        categoria="Indumentaria",
        nombre="Short Adidas Club",
        marca="Adidas",
        precio=3500,
        descripcion="Short cómodo y transpirable para tenis.",
        imagen="short-adidas.jpg",
        stock=12
    ),
    Producto(
        deporte=NAV_DEPORTES['tenis'],
        categoria="Indumentaria",
        nombre="Remera Nike Court Dri-FIT",
        marca="Nike",
        precio=4200,
        descripcion="Remera técnica con tecnología Dri-FIT.",
        imagen="remera-nike.jpg",
        stock=15
    ),
    Producto(
        deporte=NAV_DEPORTES['tenis'],
        categoria="Accesorios",
        nombre="Bolso Head Elite",
        marca="Head",
        precio=8500,
        descripcion="Bolso para raquetas.",
        imagen="bolso-head.jpg",
        stock=6
    ),
    Producto(
        deporte=NAV_DEPORTES['tenis'],
        categoria="Accesorios",
        nombre="Grip Wilson Pro",
        marca="Wilson",
        precio=850,
        descripcion="Grip antideslizante. Pack de 3.",
        imagen="grip-wilson.jpg",
        stock=30
    ),
    Producto(
        deporte=NAV_DEPORTES['tenis'],
        categoria="Raquetas",
        nombre="Babolat Pure Drive",
        marca="Babolat",
        precio=41000,
        descripcion="Raqueta versátil con excelente potencia.",
        imagen="raqueta-babolat.jpg",
        stock=7
    ),
    
    # ===== PÁDEL =====
    Producto(
        deporte=NAV_DEPORTES['padel'],
        categoria="Raquetas",
        nombre="Babolat Viper Tour",
        marca="Babolat",
        precio=35000,
        descripcion="Raqueta de pádel de alta gama.",
        imagen="padel-babolat-viper.jpg",
        stock=7
    ),
    Producto(
        deporte=NAV_DEPORTES['padel'],
        categoria="Raquetas",
        nombre="NOX Equation",
        marca="NOX",
        precio=29000,
        descripcion="Raqueta versátil.",
        imagen="padel-nox-equation.jpg",
        stock=10
    ),
    Producto(
        deporte=NAV_DEPORTES['padel'],
        categoria="Raquetas",
        nombre="Siux Crossover",
        marca="Siux",
        precio=32000,
        descripcion="Raqueta con forma de diamante.",
        imagen="padel-siux-crossover.jpg",
        stock=4
    ),
    Producto(
        deporte=NAV_DEPORTES['padel'],
        categoria="Pelotas",
        nombre="Babolat Padel Tour",
        marca="Babolat",
        precio=2500,
        descripcion="Pelotas de competición profesional.",
        imagen="padel-babolat-pelota.jpg",
        stock=20
    ),
    Producto(
        deporte=NAV_DEPORTES['padel'],
        categoria="Pelotas",
        nombre="Dunlop Fort",
        marca="Dunlop",
        precio=2200,
        descripcion="Pelotas resistentes.",
        imagen="padel-dunlop-fort.jpg",
        stock=22
    ),
    Producto(
        deporte=NAV_DEPORTES['padel'],
        categoria="Indumentaria",
        nombre="Pantalón Siux Premium",
        marca="Siux",
        precio=4800,
        descripcion="Pantalón especialmente diseñado para pádel.",
        imagen="padel-siux-pantalon.jpg",
        stock=9
    ),
    Producto(
        deporte=NAV_DEPORTES['padel'],
        categoria="Indumentaria",
        nombre="Polo Babolat Team",
        marca="Babolat",
        precio=3900,
        descripcion="Polo transpirable.",
        imagen="padel-babolat-polo.jpg",
        stock=14
    ),
    Producto(
        deporte=NAV_DEPORTES['padel'],
        categoria="Accesorios",
        nombre="Mochila Padel NOX",
        marca="NOX",
        precio=6500,
        descripcion="Mochila con compartimiento.",
        imagen="padel-nox-mochila.jpg",
        stock=8
    ),
    Producto(
        deporte=NAV_DEPORTES['padel'],
        categoria="Accesorios",
        nombre="Overgrip Tourna",
        marca="Tourna",
        precio=950,
        descripcion="Overgrip antideslizante.",
        imagen="padel-tourna-overgrip.jpg",
        stock=28
    ),
    Producto(
        deporte=NAV_DEPORTES['padel'],
        categoria="Raquetas",
        nombre="HEAD Graphene Radical",
        marca="HEAD",
        precio=38000,
        descripcion="Control y potencia equilibrados.",
        imagen="padel-head-graphene.jpg",
        stock=6
    ),
]

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        db.session.query(Producto).delete()
        
        for producto in productos_ficticios:
            db.session.add(producto)
        
        db.session.commit()
        print(f"✅ {len(productos_ficticios)} productos cargados exitosamente")
