# Tienda de Tenis (Flask)

Catálogo básico de productos de tenis (raquetas, pelotas, indumentaria)
pensado como punto de partida para una tienda online.

## Cómo correrlo

```bash
cd tienda-tenis
python -m venv venv
source venv/bin/activate   # en Windows: venv\Scripts\activate
pip install -r requirements.txt
python seed.py             # crea tienda.db y carga los productos de ejemplo
python app.py
```

Abrí http://127.0.0.1:5000 en el navegador.

## Estructura

- `app.py` — rutas de la aplicación (lee productos desde SQLite)
- `models.py` — modelo `Producto` (SQLAlchemy)
- `seed.py` — crea la base y carga/resetea los productos de ejemplo
- `templates/` — HTML (Jinja2): catálogo, detalle de producto, 404
- `static/css/style.css` — estilos
- `static/img/` — poné acá las fotos reales de tus productos
- `tienda.db` — se genera al correr `seed.py` (no se versiona)

## Panel de administración

Entrá a `http://127.0.0.1:5000/admin/login`.

- Contraseña por defecto: `tenis2026` (definida en `app.py`, variable
  `ADMIN_PASSWORD`). **Cambiala** antes de usar esto en serio, o mejor,
  definila como variable de entorno:
  ```bash
  export ADMIN_PASSWORD="tu-clave-segura"
  export SECRET_KEY="otra-clave-larga-y-aleatoria"
  ```
- Desde el panel podés crear, editar y eliminar productos sin tocar código.

## Carrito de compras

Cada visitante tiene su propio carrito guardado en la sesión (no
requiere login). Desde la ficha de un producto se agrega al carrito,
y desde `/carrito` se puede ver, actualizar cantidades, eliminar
ítems o vaciarlo.

El botón "Finalizar pedido por WhatsApp" arma un mensaje automático
con el detalle del pedido. Para activarlo, definí tu número (formato
internacional, sin `+`):

```bash
export WHATSAPP_VENDEDOR="5491122334455"
```

Esto no procesa pagos: es un "carrito + consulta", pensado para
cerrar la venta por WhatsApp mientras no haya un medio de pago
integrado.

## Fotos de productos

Desde el panel (`/admin/nuevo` o `/admin/editar/<id>`) subís la foto
directamente como archivo (png, jpg, jpeg o webp, hasta 5 MB). Se
guarda en `static/img/` con el nombre `producto-<id>.<extensión>`, y
se muestra automáticamente en el catálogo y en la ficha del producto.
Si un producto no tiene foto, se ve un placeholder con la marca.

## Cobrar con Mercado Pago

1. Creá una cuenta en https://www.mercadopago.com.ar/developers/panel
   y conseguí tu **Access Token** (usá el de "credenciales de prueba"
   mientras testeás, y el de producción cuando ya quieras cobrar de verdad).
2. Definí las variables de entorno antes de correr la app:
   ```bash
   export MP_ACCESS_TOKEN="tu-access-token"
   export URL_BASE="http://127.0.0.1:5000"   # o tu dominio real cuando la despliegues
   ```
3. Desde `/carrito`, el botón "Pagar con Mercado Pago" arma una
   preferencia de pago con los productos del carrito y redirige al
   checkout de Mercado Pago. Al terminar, vuelve a `/pago/exito`,
   `/pago/fallo` o `/pago/pendiente` según el resultado.

**Nota:** esto usa Checkout Pro (la integración más simple: redirige
al sitio de Mercado Pago y vuelve). No valida el pago con un webhook
todavía — para producción real conviene sumar una notificación IPN/
webhook que confirme el pago del lado del servidor antes de dar el
pedido por confirmado, y guardar los pedidos en la base de datos.

## Próximos pasos sugeridos

1. Guardar los pedidos en la base de datos (hoy el pago se confirma
   pero no queda registrado un "pedido" en sí).
2. Sumar un webhook de Mercado Pago para validar pagos del lado del servidor.
3. Desplegarlo (Render, Railway o PythonAnywhere son opciones simples
   y con capa gratuita para arrancar).
