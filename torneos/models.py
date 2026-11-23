"""Tablas del módulo de torneos.

Todas empiezan con "torneo_" y no tocan las de la tienda. Las crea solo el
db.create_all() de app.py, porque este archivo se importa antes.
"""
import json
import secrets
from datetime import datetime

from models import db

# Planes de un organizador
PLAN_GRATIS = "gratis"
PLAN_PAGO = "pago"

# Tipos de competencia
TIPO_CUADRO = "cuadro"
TIPO_ESCALERA = "escalera"
TIPO_LIGA = "liga"                 # liga por fechas (puntos por games)

# Estados de una competencia (en el orden en que avanza)
EST_BORRADOR = "borrador"          # la está armando el organizador, no se ve
EST_INSCRIPCION = "inscripcion"    # inscripción abierta
EST_EN_CURSO = "en_curso"
EST_FINALIZADA = "finalizada"
EST_CANCELADA = "cancelada"
ESTADOS_PUBLICOS = (EST_INSCRIPCION, EST_EN_CURSO, EST_FINALIZADA)

# Estados del pago de una inscripción
PAGO_PENDIENTE = "pendiente"
PAGO_CONFIRMADO = "confirmado"
PAGO_RECHAZADO = "rechazado"

# Estados de un partido (cuadro o desafío)
PAR_DESAFIO = "desafio"            # enviado, esperando respuesta
PAR_RECHAZADO = "rechazado"
PAR_VENCIDO = "vencido"            # no respondió a tiempo
PAR_AGENDADO = "agendado"
PAR_JUGADO = "jugado"              # hay resultado confirmado
PAR_EN_DISPUTA = "en_disputa"      # los resultados no coinciden
PAR_WO = "wo"
PAR_ANULADO = "anulado"            # lo anuló el organizador
PAR_PENDIENTE = "pendiente"        # cuadro: todavía falta definir uno de los rivales
PAR_BYE = "bye"                    # cuadro: pase libre (rival vacío)
PARTIDOS_ABIERTOS = (PAR_DESAFIO, PAR_AGENDADO, PAR_EN_DISPUTA)

# Valor por defecto del plan pago: $2.000 por inscripto (decidido el 19/11/2026)
PRECIO_POR_INSCRIPTO = 2000


def _token():
    return secrets.token_urlsafe(24)


class Organizador(db.Model):
    """Club, profe o circuito que usa el sistema."""
    __tablename__ = "torneo_organizador"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(120), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    clave_hash = db.Column(db.String(255), nullable=False)
    whatsapp = db.Column(db.String(40))
    logo = db.Column(db.String(255))            # URL en el servicio de imágenes
    color = db.Column(db.String(9))             # ej. "#E57E3C", solo plan pago
    plan = db.Column(db.String(10), nullable=False, default=PLAN_GRATIS)
    precio_por_inscripto = db.Column(db.Integer, nullable=False, default=PRECIO_POR_INSCRIPTO)
    datos_bancarios = db.Column(db.Text, default="")   # alias, CBU, titular
    activo = db.Column(db.Boolean, nullable=False, default=True)
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    competencias = db.relationship("Competencia", backref="organizador", lazy=True)
    colaboradores = db.relationship("Colaborador", backref="organizador", lazy=True)


class Colaborador(db.Model):
    """Ayudante de un organizador: carga resultados y horarios, no ve pagos."""
    __tablename__ = "torneo_colaborador"

    id = db.Column(db.Integer, primary_key=True)
    organizador_id = db.Column(db.Integer, db.ForeignKey("torneo_organizador.id"), nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    clave_hash = db.Column(db.String(255), nullable=False)
    activo = db.Column(db.Boolean, nullable=False, default=True)


class Jugador(db.Model):
    """Perfil único del jugador, común a todos los organizadores.
    Entra con su enlace personal secreto (sin contraseña)."""
    __tablename__ = "torneo_jugador"

    id = db.Column(db.Integer, primary_key=True)
    dni = db.Column(db.String(12), unique=True, nullable=False)
    nombre = db.Column(db.String(80), nullable=False)
    apellido = db.Column(db.String(80), nullable=False)
    celular = db.Column(db.String(40), nullable=False)
    email = db.Column(db.String(120))
    enlace = db.Column(db.String(40), unique=True, nullable=False, default=_token)
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellido}"


class Competencia(db.Model):
    """Un torneo con cuadro o una escalera de desafíos."""
    __tablename__ = "torneo_competencia"

    id = db.Column(db.Integer, primary_key=True)
    organizador_id = db.Column(db.Integer, db.ForeignKey("torneo_organizador.id"), nullable=False)
    tipo = db.Column(db.String(10), nullable=False)          # cuadro | escalera
    nombre = db.Column(db.String(150), nullable=False)
    slug = db.Column(db.String(160), unique=True, nullable=False)
    deporte = db.Column(db.String(20), nullable=False, default="Tenis")
    sede = db.Column(db.String(150), default="")
    localidad = db.Column(db.String(100), default="")
    descripcion = db.Column(db.Text, default="")
    fecha_inicio = db.Column(db.Date)
    fecha_fin = db.Column(db.Date)
    cierre_inscripcion = db.Column(db.DateTime)
    precio = db.Column(db.Integer, nullable=False, default=0)
    incluye = db.Column(db.String(150), default="")           # ej. "un tubo de pelotas"
    estado = db.Column(db.String(12), nullable=False, default=EST_BORRADOR)
    # Reglas del formato en JSON (puntos, plazos, divisiones...). Así se pueden
    # sumar reglas nuevas sin cambiar la tabla.
    reglas_json = db.Column(db.Text, nullable=False, default="{}")
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    categorias = db.relationship(
        "Categoria", backref="competencia", lazy=True, cascade="all, delete-orphan"
    )

    @property
    def reglas(self):
        try:
            return json.loads(self.reglas_json or "{}")
        except ValueError:
            return {}

    @reglas.setter
    def reglas(self, valor):
        self.reglas_json = json.dumps(valor or {}, ensure_ascii=False)


class Categoria(db.Model):
    """Categoría o división de una competencia (ej. "Caballeros B", "Oro")."""
    __tablename__ = "torneo_categoria"

    id = db.Column(db.Integer, primary_key=True)
    competencia_id = db.Column(db.Integer, db.ForeignKey("torneo_competencia.id"), nullable=False)
    nombre = db.Column(db.String(80), nullable=False)
    modalidad = db.Column(db.String(10), nullable=False, default="singles")  # singles | dobles
    cupo = db.Column(db.Integer)                 # vacío = sin cupo
    orden = db.Column(db.Integer, nullable=False, default=0)

    inscripciones = db.relationship("Inscripcion", backref="categoria", lazy=True)


class Inscripcion(db.Model):
    """Un jugador (o una pareja fija) anotado en una categoría."""
    __tablename__ = "torneo_inscripcion"

    id = db.Column(db.Integer, primary_key=True)
    categoria_id = db.Column(db.Integer, db.ForeignKey("torneo_categoria.id"), nullable=False)
    jugador1_id = db.Column(db.Integer, db.ForeignKey("torneo_jugador.id"), nullable=False)
    jugador2_id = db.Column(db.Integer, db.ForeignKey("torneo_jugador.id"))
    comprobante = db.Column(db.String(255))      # URL en el servicio de imágenes
    estado_pago = db.Column(db.String(12), nullable=False, default=PAGO_PENDIENTE)
    nivel_inicial = db.Column(db.Float)          # escalera: lo asigna el organizador
    division = db.Column(db.String(40))          # escalera: división actual (Oro, Plata...)
    rechazos_seguidos = db.Column(db.Integer, nullable=False, default=0)  # escalera
    siembra = db.Column(db.Integer)              # cuadro: número de cabeza de serie
    zona = db.Column(db.Integer)                 # cuadro con zonas: número de zona
    restricciones = db.Column(db.Text, default="")   # cuándo no puede jugar
    baja = db.Column(db.Boolean, nullable=False, default=False)
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    jugador1 = db.relationship("Jugador", foreign_keys=[jugador1_id])
    jugador2 = db.relationship("Jugador", foreign_keys=[jugador2_id])


class Partido(db.Model):
    """Un partido de cuadro o un desafío de escalera."""
    __tablename__ = "torneo_partido"

    id = db.Column(db.Integer, primary_key=True)
    competencia_id = db.Column(db.Integer, db.ForeignKey("torneo_competencia.id"), nullable=False)
    categoria_id = db.Column(db.Integer, db.ForeignKey("torneo_categoria.id"))
    ronda = db.Column(db.String(20))             # cuadro: número de ronda ("1" = primera) / escalera: vacío
    cuadro = db.Column(db.String(12))            # cuadro: principal | consuelo | tercer
    semana = db.Column(db.Integer)               # escalera: número de semana de la etapa
    posicion = db.Column(db.Integer)             # cuadro: lugar en la llave
    # Lado A y lado B: una inscripción cada uno (singles o pareja fija)
    lado_a_id = db.Column(db.Integer, db.ForeignKey("torneo_inscripcion.id"))
    lado_b_id = db.Column(db.Integer, db.ForeignKey("torneo_inscripcion.id"))
    desafiante_id = db.Column(db.Integer, db.ForeignKey("torneo_inscripcion.id"))
    estado = db.Column(db.String(12), nullable=False, default=PAR_AGENDADO)
    ganador_id = db.Column(db.Integer, db.ForeignKey("torneo_inscripcion.id"))
    cancha = db.Column(db.String(40))
    fecha_hora = db.Column(db.DateTime)
    vence_en = db.Column(db.DateTime)            # escalera: plazo para responder
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    lado_a = db.relationship("Inscripcion", foreign_keys=[lado_a_id])
    lado_b = db.relationship("Inscripcion", foreign_keys=[lado_b_id])
    resultados = db.relationship(
        "Resultado", backref="partido", lazy=True, cascade="all, delete-orphan"
    )


class Resultado(db.Model):
    """Lo que carga cada jugador (o el organizador). Si dos cargas no
    coinciden, el partido queda en disputa y decide el organizador."""
    __tablename__ = "torneo_resultado"

    id = db.Column(db.Integer, primary_key=True)
    partido_id = db.Column(db.Integer, db.ForeignKey("torneo_partido.id"), nullable=False)
    cargado_por = db.Column(db.String(20), nullable=False)   # jugador | organizador | colaborador
    cargado_por_id = db.Column(db.Integer)
    sets = db.Column(db.String(60), nullable=False)          # ej. "6-4 3-6 10-8"
    selfie = db.Column(db.String(255))                       # obligatoria si carga un jugador
    ausente_id = db.Column(db.Integer)                       # W.O.: inscripción que no se presentó
    confirmado = db.Column(db.Boolean, nullable=False, default=False)
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class Movimiento(db.Model):
    """Cada suma o resta de puntos. El ranking es la suma de estos
    movimientos: nunca se pisa, y se puede recalcular si se corrige algo."""
    __tablename__ = "torneo_movimiento"

    id = db.Column(db.Integer, primary_key=True)
    competencia_id = db.Column(db.Integer, db.ForeignKey("torneo_competencia.id"), nullable=False)
    jugador_id = db.Column(db.Integer, db.ForeignKey("torneo_jugador.id"), nullable=False)
    inscripcion_id = db.Column(db.Integer, db.ForeignKey("torneo_inscripcion.id"))
    partido_id = db.Column(db.Integer, db.ForeignKey("torneo_partido.id"))
    semana = db.Column(db.Integer)
    puntos = db.Column(db.Float, nullable=False)
    motivo = db.Column(db.String(30), nullable=False)   # victoria, derrota, wo, inactividad...
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class RankingSemana(db.Model):
    """Foto del ranking al cerrar cada semana de una escalera."""
    __tablename__ = "torneo_ranking_semana"

    id = db.Column(db.Integer, primary_key=True)
    competencia_id = db.Column(db.Integer, db.ForeignKey("torneo_competencia.id"), nullable=False)
    semana = db.Column(db.Integer, nullable=False)
    jugador_id = db.Column(db.Integer, db.ForeignKey("torneo_jugador.id"), nullable=False)
    inscripcion_id = db.Column(db.Integer, db.ForeignKey("torneo_inscripcion.id"))
    puntos = db.Column(db.Float, nullable=False)
    posicion = db.Column(db.Integer, nullable=False)
    division = db.Column(db.String(40))


class Cobro(db.Model):
    """Lo que Sopi le cobra a un organizador del plan pago."""
    __tablename__ = "torneo_cobro"

    id = db.Column(db.Integer, primary_key=True)
    organizador_id = db.Column(db.Integer, db.ForeignKey("torneo_organizador.id"), nullable=False)
    competencia_id = db.Column(db.Integer, db.ForeignKey("torneo_competencia.id"), nullable=False)
    inscriptos = db.Column(db.Integer, nullable=False)
    precio_unitario = db.Column(db.Integer, nullable=False)
    pagado = db.Column(db.Boolean, nullable=False, default=False)
    pagado_en = db.Column(db.DateTime)
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    @property
    def monto(self):
        return self.inscriptos * self.precio_unitario


# Columnas agregadas después de crear las tablas: (tabla, columna, tipo SQL).
# init_app las agrega si faltan (db.create_all no modifica tablas existentes).
COLUMNAS_NUEVAS = [
    ("torneo_inscripcion", "division", "VARCHAR(40)"),
    ("torneo_inscripcion", "rechazos_seguidos", "INTEGER NOT NULL DEFAULT 0"),
    ("torneo_resultado", "ausente_id", "INTEGER"),
    ("torneo_movimiento", "inscripcion_id", "INTEGER"),
    ("torneo_ranking_semana", "inscripcion_id", "INTEGER"),
    ("torneo_inscripcion", "siembra", "INTEGER"),
    ("torneo_partido", "cuadro", "VARCHAR(12)"),
    ("torneo_inscripcion", "zona", "INTEGER"),
]
