"""Módulo de torneos de tenis (escaleras de desafíos y cuadros).

Vive aparte de la tienda: carpeta torneos/, tablas "torneo_*" y plantillas
en templates/torneos/. Se publica en /torneos.

Se conecta desde app.py con:
    import torneos                                   (junto a los otros imports,
                                                      antes de db.create_all)
    torneos.init_app(app, obtener_contexto_base)     (después de definir obtener_contexto_base)

ACCESO PRIVADO (para probarlo en la web real antes del lanzamiento):
en el servidor (Render, o cuando hay DATABASE_URL) o si existe TORNEOS_LLAVE, todo
/torneos y /admin/torneos responde "no encontrado" salvo para quien entró una
vez por /torneos/llave/<TORNEOS_LLAVE> (queda guardado en ese navegador un
año). Sin TORNEOS_LLAVE cargada no entra nadie. Para abrirlo a todos:
TORNEOS_PUBLICO=1. TORNEOS_VISIBLE=0 sigue sirviendo para ocultar la pestaña.

Partes:
    models.py    tablas
    util.py      ayudas (slugs, WhatsApp, archivos, mail, sesión del organizador)
    publico.py   calendario, página del torneo, inscripción, panel del jugador
    cuentas.py   alta e ingreso de organizadores, perfil
    panel.py     competencias e inscriptos del organizador
"""
import hashlib
import hmac
import os

import unicodedata

from flask import abort, current_app, has_request_context, redirect, render_template, request, session
from werkzeug.exceptions import HTTPException

from . import models  # noqa: F401  (registra las tablas antes de db.create_all)
from .bp import bp, contexto, _estado
from . import publico, cuentas, panel, panel_cuadro, panel_liga, panel_planillas, desafios  # noqa: F401  (registran sus rutas en bp)


COOKIE_LLAVE = "torneos_llave"


def es_privado():
    """En el servidor los torneos son privados hasta que se ponga TORNEOS_PUBLICO=1."""
    if os.environ.get("TORNEOS_PUBLICO") == "1":
        return False
    # RENDER la pone Render en todos sus servidores: así queda privado aunque falte otra variable
    return bool(os.environ.get("RENDER") or os.environ.get("DATABASE_URL") or os.environ.get("TORNEOS_LLAVE"))


def _firma(llave):
    return hashlib.sha256(("sopi-torneos:" + llave).encode()).hexdigest()[:40]


def tiene_acceso():
    """True si los torneos son públicos o si este navegador entró con el enlace secreto."""
    if not es_privado():
        return True
    if has_request_context() and session.get("admin"):
        return True   # el administrador de la tienda (logueado en /admin) entra siempre
    llave = os.environ.get("TORNEOS_LLAVE", "").strip()
    if not llave or not has_request_context():
        return False
    return hmac.compare_digest(request.cookies.get(COOKIE_LLAVE, ""), _firma(llave))


def _normal_llave(texto):
    """Solo letras y números, sin tildes ni mayúsculas: el teclado del celular suele
    agregar espacios, puntos, guiones o mayúsculas."""
    t = unicodedata.normalize("NFKD", (texto or "").strip().strip(chr(34) + chr(39))).casefold()
    return "".join(ch for ch in t if ch.isalnum())


def _entrar_con_llave(ruta):
    """/torneos/llave: casillero para la palabra secreta (o /torneos/llave/<palabra>)."""
    from .bp import contexto
    llave = os.environ.get("TORNEOS_LLAVE", "").strip()
    if request.method == "POST":
        dada = request.form.get("palabra", "")
    else:
        dada = ruta[len("/torneos/llave"):].strip("/")
    error = None
    if dada and _normal_llave(llave) and hmac.compare_digest(_normal_llave(dada), _normal_llave(llave)):
        # derecho a la entrada de organizadores (o a su panel si ya ingresó)
        resp = redirect("/torneos/panel" if session.get("torneo_org_id") else "/torneos/ingresar?habilitado=1")
        resp.set_cookie(COOKIE_LLAVE, _firma(llave), max_age=365 * 24 * 3600, httponly=True,
                        secure=request.is_secure or bool(os.environ.get("RENDER")), samesite="Lax")
        return resp
    if dada and llave:
        error = "Esa palabra no coincide. Revisala y probá de nuevo."
    return render_template("torneos/llave.html", **contexto(error=error, sin_llave=not llave)), (200 if not dada else 403)


def torneos_visible():
    """La pestaña Torneos se muestra salvo que TORNEOS_VISIBLE=0, y solo a quien tiene acceso."""
    return os.environ.get("TORNEOS_VISIBLE", "1") != "0" and tiene_acceso()


def torneos_abiertos(cantidad=3):
    """Competencias con inscripción abierta, para la promo de la portada."""
    from .models import Competencia, EST_INSCRIPCION
    try:
        return (Competencia.query.filter_by(estado=EST_INSCRIPCION)
                .order_by(Competencia.fecha_inicio.asc().nullslast(), Competencia.id.desc())
                .limit(cantidad).all())
    except Exception:
        current_app.logger.exception("No se pudieron leer los torneos abiertos")
        return []


def rutas_sitemap():
    """Direcciones públicas de torneos para el mapa del sitio de Google."""
    from flask import url_for
    from .models import Competencia, ESTADOS_PUBLICOS
    rutas = [url_for("torneos.calendario"), url_for("torneos.organizar")]
    rutas += [url_for("torneos.torneo", slug=c.slug)
              for c in Competencia.query.filter(Competencia.estado.in_(ESTADOS_PUBLICOS)).order_by(Competencia.id)]
    return rutas


def init_app(app, contexto_base):
    """Registra las rutas. contexto_base es obtener_contexto_base de app.py."""
    _estado["contexto_base"] = contexto_base

    @app.before_request
    def _solo_con_llave():
        """Acceso privado: sin el enlace secreto, torneos no existe."""
        ruta = request.path
        if not (ruta.startswith("/torneos") or ruta.startswith("/admin/torneos")):
            return None
        if ruta.rstrip("/") == "/torneos/llave" or ruta.startswith("/torneos/llave/"):
            return _entrar_con_llave(ruta)
        if not tiene_acceso():
            abort(404)
        return None

    app.register_blueprint(bp)
    from .admin import admin_bp
    app.register_blueprint(admin_bp)   # /admin/torneos, con la clave de admin de la tienda
    with app.app_context():
        _agregar_columnas_nuevas()

    @app.context_processor
    def _torneos():
        return {"torneos_visible": torneos_visible(), "torneos_abiertos": torneos_abiertos}

    @app.template_filter("pts")
    def _pts(valor, signo=False):
        """Puntos como se escriben acá: 13, 11,5, +1,5 (coma decimal, sin ",0")."""
        try:
            v = round(float(valor), 2)
        except (TypeError, ValueError):
            return valor
        texto = (f"{v:+.2f}" if signo else f"{v:.2f}").rstrip("0").rstrip(".").replace(".", ",")
        return "0" if texto in ("+0", "-0") else texto

    @app.template_filter("tipo_torneo")
    def _tipo_torneo(tipo):
        return {"escalera": "Escalera de desafíos", "liga": "Liga por fechas"}.get(tipo, "Torneo con cuadro")

    @app.cli.command("torneos-recordatorios")
    def _recordatorios():
        """Mail a los que juegan mañana. Correrlo una vez por día (tarea programada de Render)."""
        from .avisos import recordatorios
        with app.test_request_context(base_url=os.environ.get("TORNEOS_URL_BASE", "https://sopitenispadel.com.ar")):
            partidos, mails = recordatorios()
        print(f"Recordatorios: {partidos} partidos, {mails} mails enviados.")

    @app.context_processor
    def _nombres_cuadros():
        from .cuadro import nombres_cuadros
        return {"cdr_nombres": nombres_cuadros}

    @app.template_filter("nombre_cat")
    def _nombre_cat(cat):
        """"Caballeros B · singles", sin repetir la modalidad si el nombre ya la dice."""
        nombre = cat.nombre or ""
        bajo = nombre.lower()
        if cat.modalidad in bajo or ("single" in bajo and cat.modalidad == "singles") or ("doble" in bajo and cat.modalidad == "dobles"):
            return nombre
        return f"{nombre} · {cat.modalidad}"


def _agregar_columnas_nuevas():
    """Migración liviana: agrega las columnas de models.COLUMNAS_NUEVAS que
    falten (db.create_all crea tablas nuevas pero no toca las existentes)."""
    from sqlalchemy import inspect, text
    from models import db

    inspector = inspect(db.engine)
    tablas = set(inspector.get_table_names())
    for tabla, columna, tipo in models.COLUMNAS_NUEVAS:
        if tabla not in tablas:
            continue
        if columna not in {c["name"] for c in inspector.get_columns(tabla)}:
            db.session.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}"))
            db.session.commit()


# ---------------------------------------------------------
# ERRORES: un problema en torneos muestra su propia página
# y no arrastra a la tienda.
# ---------------------------------------------------------
@bp.errorhandler(Exception)
def _error_torneos(error):
    if isinstance(error, HTTPException):
        return error
    current_app.logger.exception("Error en torneos")
    try:
        from models import db
        db.session.rollback()
        return render_template("torneos/error.html", **contexto()), 500
    except Exception:
        return "Tuvimos un problema con los torneos. Probá de nuevo en un momento.", 500
