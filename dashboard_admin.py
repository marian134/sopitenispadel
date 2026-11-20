"""
Dashboard de movimientos de la tienda: /admin/dashboard

Se engancha desde app.py con:
    import dashboard_admin
    dashboard_admin.init_app(app, admin_requerido, obtener_contexto_base, vencer_pedidos_viejos)
"""
from datetime import datetime, timedelta

from flask import render_template, request

from models import db, Producto, Pedido, Cupon, CuponUso, ESTADO_PAGADO, ESTADO_PENDIENTE, ESTADO_FALLIDO

PERIODOS = {"7": "7 días", "30": "30 días", "90": "90 días", "365": "12 meses"}
STOCK_BAJO = 2  # avisa los productos con este stock o menos


def _dia_ar(fecha):
    # Las fechas se guardan en UTC; Argentina es UTC-3 todo el año
    return (fecha - timedelta(hours=3)).date()


def datos_dashboard(dias):
    hoy_ar = _dia_ar(datetime.utcnow())
    desde_ar = hoy_ar - timedelta(days=dias - 1)
    desde_utc = datetime.combine(desde_ar, datetime.min.time()) + timedelta(hours=3)

    pedidos = (
        Pedido.query.filter(Pedido.creado_en >= desde_utc)
        .order_by(Pedido.creado_en.desc()).all()
    )
    pagados = [p for p in pedidos if p.estado == ESTADO_PAGADO]
    productos = {p.id: p for p in Producto.query.all()}

    # Ventas, costo (con el costo actual de cada producto) y rankings
    ingresos = sum(p.total or 0 for p in pagados)
    envios = sum(p.costo_envio or 0 for p in pagados)
    unidades = costo_total = sin_costo = 0
    por_producto, por_deporte = {}, {}
    for p in pagados:
        for l in p.lineas:
            unidades += l.cantidad
            prod = productos.get(l.producto_id)
            if prod and prod.costo:
                costo_total += prod.costo * l.cantidad
            else:
                sin_costo += l.cantidad
            fila = por_producto.setdefault(
                l.nombre_producto, {"nombre": l.nombre_producto, "unidades": 0, "monto": 0})
            fila["unidades"] += l.cantidad
            fila["monto"] += l.subtotal
            deporte = prod.deporte if prod else "Otro"
            por_deporte[deporte] = por_deporte.get(deporte, 0) + l.subtotal
    ventas_productos = ingresos - envios

    # Serie por día (o por semana desde 90 días), con los días sin ventas en cero
    por_dia = {desde_ar + timedelta(days=i): {"monto": 0, "pedidos": 0} for i in range(dias)}
    for p in pagados:
        d = _dia_ar(p.creado_en)
        if d in por_dia:
            por_dia[d]["monto"] += p.total or 0
            por_dia[d]["pedidos"] += 1
    if dias >= 90:
        grupos = {}
        for d, v in por_dia.items():
            g = grupos.setdefault(d - timedelta(days=d.weekday()), {"monto": 0, "pedidos": 0})
            g["monto"] += v["monto"]
            g["pedidos"] += v["pedidos"]
        serie = [{"etiqueta": "Sem " + d.strftime("%d/%m"), **v} for d, v in sorted(grupos.items())]
    else:
        serie = [{"etiqueta": d.strftime("%d/%m"), **v} for d, v in sorted(por_dia.items())]

    medios = {}
    for p in pagados:
        m = medios.setdefault(p.medio_pago or "sin dato", {"pedidos": 0, "monto": 0})
        m["pedidos"] += 1
        m["monto"] += p.total or 0

    cupones = (
        db.session.query(Cupon.codigo, db.func.count(CuponUso.id),
                         db.func.coalesce(db.func.sum(CuponUso.descuento), 0))
        .join(CuponUso, CuponUso.cupon_id == Cupon.id)
        .join(Pedido, Pedido.id == CuponUso.pedido_id)
        .filter(Pedido.creado_en >= desde_utc, Pedido.estado == ESTADO_PAGADO)
        .group_by(Cupon.codigo).all()
    )

    return dict(
        desde=desde_ar, hasta=hoy_ar,
        ingresos=ingresos, envios=envios, ventas_productos=ventas_productos,
        costo_total=costo_total, ganancia=ventas_productos - costo_total, sin_costo=sin_costo,
        cant_pagados=len(pagados), unidades=unidades,
        ticket=(ingresos // len(pagados)) if pagados else 0,
        conversion=round(len(pagados) * 100 / (len(pedidos) or 1)),
        serie=serie, maximo=max([s["monto"] for s in serie] + [1]),
        top=sorted(por_producto.values(), key=lambda f: f["monto"], reverse=True)[:10],
        por_deporte=sorted(por_deporte.items(), key=lambda kv: kv[1], reverse=True),
        medios=sorted(medios.items(), key=lambda kv: kv[1]["monto"], reverse=True),
        estados={
            "pendientes": sum(1 for p in pedidos if p.estado == ESTADO_PENDIENTE),
            "cancelados": sum(1 for p in pedidos if p.estado == ESTADO_FALLIDO),
            "para_preparar": sum(1 for p in pagados if (p.entrega_estado or "") in ("", "preparando")),
        },
        cupones=cupones,
        stock_bajo=Producto.query.filter(Producto.stock <= STOCK_BAJO)
                   .order_by(Producto.stock, Producto.nombre).all(),
        stock_bajo_limite=STOCK_BAJO,
        valor_stock=sum((p.costo or 0) * max(p.stock or 0, 0) for p in productos.values()),
        ultimos=pedidos[:8],
    )


def init_app(app, admin_requerido, obtener_contexto_base, vencer_pedidos_viejos):

    @admin_requerido
    def admin_dashboard():
        vencer_pedidos_viejos()
        periodo = request.args.get("dias", "30")
        if periodo not in PERIODOS:
            periodo = "30"
        return render_template(
            "admin_dashboard.html", **obtener_contexto_base(),
            periodo=periodo, periodos=PERIODOS, **datos_dashboard(int(periodo)),
        )

    app.add_url_rule("/admin/dashboard", "admin_dashboard", admin_dashboard)
