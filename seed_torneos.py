"""Datos de ejemplo para probar torneos en local (base SQLite de instance/).

Uso, desde esta carpeta:
    ..\\sopitenispadel\\venv\\Scripts\\python.exe seed_torneos.py

Crea (o vuelve a crear) un organizador de prueba con:
- una escalera de desafíos en la semana 5, con 12 jugadores y partidos jugados;
- un torneo con cuadro de 13 jugadores, algunos resultados y horarios;
- un torneo con inscripción abierta.

Cuenta de prueba del organizador (solo local):
    mail:        demo@torneos.test
    contraseña:  demo-torneos-2026
"""
import random
from datetime import date, datetime, timedelta

from werkzeug.security import generate_password_hash

import app as m
from models import db
from torneos import cuadro as cdr, escalera as esc
from torneos.models import (
    Categoria, Cobro, Competencia, Inscripcion, Jugador, Movimiento, Organizador, Partido,
    RankingSemana, Resultado,
)
from torneos.reglas import por_defecto

EMAIL, CLAVE = "demo@torneos.test", "demo-torneos-2026"
NOMBRES = [
    "Juan Pérez", "Martín Gómez", "Lucas Díaz", "Pablo Ruiz", "Diego Sosa", "Nicolás Romero",
    "Tomás Álvarez", "Federico Torres", "Agustín Molina", "Santiago Castro", "Matías Ortiz",
    "Facundo Silva", "Gonzalo Rojas", "Ezequiel Medina", "Leandro Herrera", "Bruno Acosta",
    "Ignacio Vega", "Joaquín Ríos", "Franco Luna", "Emiliano Paz", "Lautaro Correa",
    "Valentín Ponce", "Ramiro Quiroga", "Hernán Godoy", "Cristian Benítez",
]


def borrar_demo():
    org = Organizador.query.filter_by(email=EMAIL).first()
    if not org:
        return
    for comp in Competencia.query.filter_by(organizador_id=org.id).all():
        for p in Partido.query.filter_by(competencia_id=comp.id).all():
            Resultado.query.filter_by(partido_id=p.id).delete()
            db.session.delete(p)
        Movimiento.query.filter_by(competencia_id=comp.id).delete()
        RankingSemana.query.filter_by(competencia_id=comp.id).delete()
        Cobro.query.filter_by(competencia_id=comp.id).delete()
        for cat in comp.categorias:
            for i in cat.inscripciones:
                db.session.delete(i)
        db.session.delete(comp)
    Jugador.query.filter(Jugador.dni.like("4440%")).delete(synchronize_session=False)
    db.session.delete(org)
    db.session.commit()


def jugadores(cantidad, desde=0):
    lista = []
    for k in range(desde, desde + cantidad):
        nombre, apellido = NOMBRES[k % len(NOMBRES)].split()
        dni = f"4440{k:04d}"
        j = Jugador.query.filter_by(dni=dni).first()
        if not j:
            j = Jugador(dni=dni, nombre=nombre, apellido=apellido, celular="11 2832-1531",
                        email=f"jugador{k}@torneos.test")
            db.session.add(j)
            db.session.flush()
        lista.append(j)
    return lista


def cargar():
    borrar_demo()
    org = Organizador(nombre="Club Demo Tenis", slug="club-demo-tenis", email=EMAIL,
                      clave_hash=generate_password_hash(CLAVE), whatsapp="11 2832-1531",
                      datos_bancarios="Alias: club.demo.tenis\nTitular: Club Demo", plan="gratis")
    db.session.add(org)
    db.session.flush()
    hace_mucho = datetime.now() - timedelta(days=60)

    # --- Escalera en la semana 5
    inicio = date.today() - timedelta(days=28)
    esc_comp = Competencia(organizador_id=org.id, tipo="escalera", nombre="Desafíos de Primavera",
                           slug="desafios-de-primavera", estado="inscripcion", fecha_inicio=inicio,
                           fecha_fin=inicio + timedelta(days=83), precio=40000, incluye="un tubo de pelotas",
                           localidad="Quilmes", sede="Club Demo Tenis",
                           descripcion="Escalera de singles con las reglas de los Desafíos Nivel Prado.\n"
                                       "Partidos al mejor de 3 sets con súper tie-break.")
    esc_comp.reglas = por_defecto("escalera")
    db.session.add(esc_comp)
    db.session.flush()
    cat = Categoria(competencia_id=esc_comp.id, nombre="Singles", modalidad="singles")
    db.session.add(cat)
    db.session.flush()
    niveles = [13, 13, 11, 11, 9, 9, 7, 7, 5, 5, 3, 1]
    ins = []
    for j, nv in zip(jugadores(12), niveles):
        i = Inscripcion(categoria_id=cat.id, jugador1_id=j.id, estado_pago="confirmado", nivel_inicial=nv,
                        division=esc.division_por_nivel(esc_comp, nv), creado_en=hace_mucho)
        db.session.add(i)
        ins.append(i)
    db.session.flush()
    rng = random.Random(5)
    for semana in range(1, 5):
        for div in ("Oro", "Plata", "Bronce"):
            grupo = [i for i in ins if i.division == div]
            rng.shuffle(grupo)
            for a, b in zip(grupo[::2], grupo[1::2]):
                p = Partido(competencia_id=esc_comp.id, categoria_id=cat.id, semana=semana, lado_a_id=a.id,
                            lado_b_id=b.id, desafiante_id=a.id, estado="agendado")
                db.session.add(p)
                db.session.flush()
                sets = rng.choice(["6-4 6-3", "6-2 7-5", "4-6 6-3 10-6", "3-6 4-6", "6-7 6-4 8-10"])
                db.session.add(Resultado(partido_id=p.id, cargado_por="jugador", cargado_por_id=a.id, sets=sets))
                db.session.flush()
                esc.aplicar_resultado(p, sets)
    # un desafío abierto esta semana
    db.session.add(Partido(competencia_id=esc_comp.id, categoria_id=cat.id, semana=5, lado_a_id=ins[3].id,
                           lado_b_id=ins[2].id, desafiante_id=ins[3].id, estado="desafio",
                           vence_en=datetime.now() + timedelta(days=2)))
    db.session.commit()
    esc.procesar(esc_comp)

    # --- Cuadro de 13 con algunos resultados y horarios
    cdr_comp = Competencia(organizador_id=org.id, tipo="cuadro", nombre="Abierto de Verano",
                           slug="abierto-de-verano", estado="en_curso", precio=35000, localidad="Quilmes",
                           sede="Club Demo Tenis", fecha_inicio=date.today(), fecha_fin=date.today() + timedelta(days=2),
                           descripcion="Cuadro de eliminación directa. Partidos al mejor de 3 sets con súper tie-break.")
    reglas = por_defecto("cuadro")
    reglas.update(consuelo=True, tercer_puesto=True)
    cdr_comp.reglas = reglas
    db.session.add(cdr_comp)
    db.session.flush()
    cat2 = Categoria(competencia_id=cdr_comp.id, nombre="Caballeros B", modalidad="singles")
    db.session.add(cat2)
    db.session.flush()
    for k, j in enumerate(jugadores(13, desde=12)):
        db.session.add(Inscripcion(categoria_id=cat2.id, jugador1_id=j.id, estado_pago="confirmado",
                                   siembra=k + 1 if k < 4 else None, creado_en=hace_mucho))
    db.session.flush()
    cdr.armar(cat2, cdr.participantes(cat2), rng=random.Random(7))
    hora = datetime.combine(date.today() + timedelta(days=1), datetime.min.time()) + timedelta(hours=9)
    for n, p in enumerate([p for p in cdr.partidos(cat2) if p.estado == "agendado"]):
        if n < 3:
            sets = ["6-3 6-4", "4-6 6-2 10-7", "3-6 4-6"][n]
            db.session.add(Resultado(partido_id=p.id, cargado_por="organizador", cargado_por_id=org.id,
                                     sets=sets, confirmado=True))
            db.session.flush()
            esc.aplicar_resultado(p, sets)
        else:
            p.fecha_hora, p.cancha = hora + timedelta(hours=n), str(1 + n % 2)
    db.session.commit()

    # --- Torneo con inscripción abierta (para probar inscribirse)
    abierto = Competencia(organizador_id=org.id, tipo="cuadro", nombre="Torneo de Dobles Mixto",
                          slug="torneo-de-dobles-mixto", estado="inscripcion", precio=30000,
                          fecha_inicio=date.today() + timedelta(days=14), localidad="Quilmes",
                          cierre_inscripcion=datetime.now() + timedelta(days=10),
                          descripcion="Dobles mixto, fin de semana. Incluye almuerzo.")
    abierto.reglas = por_defecto("cuadro")
    db.session.add(abierto)
    db.session.flush()
    db.session.add(Categoria(competencia_id=abierto.id, nombre="Mixto", modalidad="dobles", cupo=16))
    db.session.add(Categoria(competencia_id=abierto.id, nombre="Singles Damas", modalidad="singles", cupo=16))
    org.plan = "pago"   # para poder tener más de un torneo y probar la marca propia
    db.session.commit()

    print("Listo. Torneos de ejemplo cargados.")
    print("Panel del jugador (escalera):", f"/torneos/jugador/{ins[3].jugador1.enlace}  ({ins[3].jugador1.nombre_completo})")
    print("Panel del jugador (desafiado):", f"/torneos/jugador/{ins[2].jugador1.enlace}  ({ins[2].jugador1.nombre_completo})")


if __name__ == "__main__":
    with m.app.app_context():
        cargar()
