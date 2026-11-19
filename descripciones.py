"""Descripciones automáticas para productos que no tienen una propia.

Se arman a partir del nombre, la marca y la categoría: no inventan datos
técnicos (peso, materiales exactos), solo explican lo que el nombre ya dice
(versión control, liviana, femenina, carbono 12K, tubo x3, etc.) y suman la
información de compra. Si el producto tiene una descripción cargada de 80
letras o más, se usa esa.
"""
import re
import unicodedata

from fichas import frase_ficha

MINIMO_PROPIA = 80


def _norm(texto):
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return texto.lower()


def _tiene(nombre, *palabras):
    n = f" {_norm(nombre)} "
    return any(re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", n) for p in palabras)


def _paleta(p):
    n, marca = p.nombre, p.marca or ""
    partes = [f"Paleta de pádel {marca} original, nueva y con envío a todo el país." if marca not in n
              else f"La {n} es una paleta de pádel original, nueva y con envío a todo el país."]
    rasgos = []
    m = re.search(r"\b(20\d\d)\b", n)
    if m:
        rasgos.append(f"Es un modelo de la colección {m.group(1)}.")
    m = re.search(r"\b(\d{1,2})\s?k\b", _norm(n))
    if m:
        rasgos.append(f"Su cara está construida con carbono {m.group(1)}K.")
    elif _tiene(n, "carbon", "carbono"):
        rasgos.append("Tiene construcción con carbono, que aporta rigidez y potencia.")
    if _tiene(n, "ctrl", "control"):
        rasgos.append("Es la versión control: pensada para jugadores que priorizan la precisión, "
                      "la defensa y el manejo de la pelota.")
    if _tiene(n, "hrd", "hard"):
        rasgos.append("Es la versión de tacto duro: entrega más potencia en los golpes de ataque "
                      "y se recomienda para jugadores con buena técnica.")
    if _tiene(n, "soft"):
        rasgos.append("Tiene un tacto más blando, con mayor salida de bola y confort en cada golpe.")
    if _tiene(n, "hybrid", "hibrida"):
        rasgos.append("Es una versión híbrida: busca el equilibrio entre control y potencia.")
    if _tiene(n, "attack", "power"):
        rasgos.append("Está orientada al juego ofensivo y a la potencia.")
    if _tiene(n, "light", "lite", "superlight", "ultralight"):
        rasgos.append("Es una versión más liviana, fácil de manejar durante todo el partido.")
    if _tiene(n, "comfort"):
        rasgos.append("Prioriza el confort y la absorción de vibraciones.")
    if _tiene(n, "woman", "w"):
        rasgos.append("Pertenece a la línea femenina, más liviana y manejable.")
    if _tiene(n, "junior", "kids", "jr"):
        rasgos.append("Está pensada para chicos que empiezan o ya juegan.")
    if _tiene(n, "edt", "reserve", "elite", "premium"):
        rasgos.append("Es un modelo de gama alta, pensado para competir.")
    elif _tiene(n, "team", "match", "drive", "training", "advanced"):
        rasgos.append("Es ideal para jugadores en progresión que buscan dar el salto de nivel.")
    ficha = frase_ficha(p)
    if ficha:
        # con ficha técnica real no hace falta deducir rasgos del nombre
        rasgos = [r for r in rasgos if r.startswith("Es un modelo de la colección")] + [ficha]
    if not rasgos:
        rasgos.append("Una paleta para disfrutar cada partido, de una marca reconocida en el pádel.")
    partes.append(" ".join(rasgos))
    partes.append("¿No sabés si es para vos? Escribinos por WhatsApp y te ayudamos a elegir "
                  "según tu nivel y tu forma de jugar.")
    return partes


def _pelotas(p):
    n, dep = p.nombre, (p.deporte or "").lower()
    deporte = "pádel" if "p" in dep[:1] else "tenis"
    m = re.search(r"x\s?(\d+)", _norm(n))
    cant = int(m.group(1)) if m else None
    if _tiene(n, "caja"):
        texto = f"Caja de tubos de pelotas de {deporte} {p.marca}. Ideal para profes, clubes y escuelas."
    elif _tiene(n, "bolsa", "bolson", "granel"):
        texto = (f"Bolsa de {cant} pelotas de {deporte} {p.marca}" if cant else
                 f"Bolsa de pelotas de {deporte} {p.marca}") + ", ideal para entrenamientos y clases."
    elif _tiene(n, "pack"):
        texto = f"Pack de tubos de pelotas de {deporte} {p.marca}, con precio especial por cantidad."
    else:
        texto = (f"Tubo de {cant} pelotas de {deporte} {p.marca}" if cant else
                 f"Pelotas de {deporte} {p.marca}") + ", para jugar y entrenar con rebote parejo."
    return [texto, "Si sos profe o tenés un club, consultanos por precios por cantidad."]


ACCESORIOS = [
    (("paletero", "paletera"), "Paletero {marca} para llevar tus paletas, la ropa y los accesorios al club, "
                              "con compartimentos para tener todo ordenado."),
    (("mochila",), "Mochila {marca} para el club: espacio para la paleta o raqueta, ropa y accesorios."),
    (("bandolera",), "Bandolera {marca}, práctica y liviana para llevar lo justo a la cancha."),
    (("funda",), "Funda {marca} para proteger tu paleta de golpes y raspones cuando la transportás."),
    (("neceser",), "Neceser {marca} para guardar zapatillas, ropa o accesorios dentro del bolso."),
    (("monedero",), "Monedero {marca} para llevar lo esencial."),
    (("botella",), "Botella {marca} para mantenerte hidratado durante el partido."),
    (("canasto",), "Canasto de pelotas {marca}, ideal para profes, clubes y entrenamientos."),
    (("presurizador",), "Presurizador {marca}: mantiene la presión de las pelotas para que duren más."),
    (("junta",), "Junta pelotas {marca} para recoger pelotas sin agacharte."),
    (("tubo recoge", "recogepelotas"), "Tubo recoge pelotas {marca}, práctico para entrenar."),
    (("aerosol", "resina"), "Producto antideslizante {marca} para mejorar el agarre de la mano."),
    (("antivibrador", "antivibradores"), "Antivibrador {marca} para reducir las vibraciones del golpe."),
]

TEXTILES = [
    (("munequera", "munequeras"), "Muñequera {marca} que absorbe la transpiración y mantiene la mano seca."),
    (("medias", "media", "calcetines"), "Medias {marca} pensadas para el deporte: cómodas y resistentes."),
    (("gorra",), "Gorra {marca} para jugar protegido del sol."),
    (("visera",), "Visera {marca} liviana para jugar protegido del sol."),
    (("vincha",), "Vincha {marca} que mantiene el pelo y la transpiración fuera de la cara."),
    (("manga", "mangas"), "Mangas de compresión {marca} para mayor soporte muscular."),
    (("bandana",), "Bandana {marca} para la transpiración."),
    (("toalla",), "Toalla {marca} para el partido."),
]


def _por_palabras(p, reglas, generico):
    for palabras, texto in reglas:
        if _tiene(p.nombre, *palabras):
            base = texto.format(marca=p.marca or "")
            break
    else:
        base = generico.format(marca=p.marca or "", nombre=p.nombre)
    m = re.search(r"x\s?(\d+)", _norm(p.nombre))
    if m and int(m.group(1)) > 1:
        base += f" Viene en pack de {m.group(1)}" + (" pares." if _tiene(p.nombre, "medias", "pares") else " unidades.")
    if "color según stock" in (p.descripcion or "").lower() or _tiene(p.nombre, "colores", "surtidos"):
        base += " El color se envía según disponibilidad."
    return [re.sub(r"\s{2,}", " ", base)]


def _overgrip(p):
    n = p.nombre
    m = re.search(r"x\s?(\d+)", _norm(n))
    cant = f"{m.group(1)} " if m else ""
    tipo = "perforados" if _tiene(n, "perforado", "perforados", "perforated") else "lisos" if _tiene(n, "liso", "lisos") else ""
    if _tiene(n, "caramelera", "caja"):
        texto = f"Caramelera de {cant}overgrips {tipo} {p.marca}. Ideal para profes, clubes o para tener siempre a mano."
    elif _tiene(n, "relieve"):
        texto = f"Overgrip perforado con relieve {p.marca}, para un agarre firme."
    else:
        texto = f"Overgrips {tipo} {p.marca}" + (f" x{m.group(1)}" if m else "") + ": mejoran el agarre y absorben la transpiración."
    return [re.sub(r"\s{2,}", " ", texto)]


def _protector(p):
    n = p.nombre
    tipo = "símil carbono" if _tiene(n, "carbono") else "transparente" if _tiene(n, "transparente") else ""
    if re.search(r"sin (alas|aletas)", _norm(n)):
        alas = " sin alas"
    elif _tiene(n, "alas", "aletas"):
        alas = " con alas"
    else:
        alas = ""
    texto = f"Protector {tipo}{alas} {p.marca} para el marco de tu paleta: la cuida de golpes contra el piso y la pared."
    return [re.sub(r"\s{2,}", " ", texto), "Se coloca fácil y no cambia el peso de la paleta de forma notable."]


def _raqueta(p):
    n = p.nombre
    if _tiene(n, "junior", "jr", "21", "23", "25", "kids"):
        return [f"Raqueta de tenis {p.marca} para chicos, original y nueva.",
                "Consultanos por WhatsApp qué medida le conviene según la edad y la altura."]
    return [f"Raqueta de tenis {p.marca} original y nueva, con envío a todo el país.",
            "Si tiene grips para elegir, seleccioná el tuyo antes de agregarla al carrito. "
            "¿Dudas con el grip o el modelo? Escribinos por WhatsApp."]


def descripcion_producto(p):
    """Párrafos de descripción para la ficha del producto."""
    propia = (p.descripcion or "").strip()
    if len(propia) >= MINIMO_PROPIA:
        return None  # la ficha usa la descripción cargada
    cat = (p.categoria or "").lower()
    if cat in ("paletas", "palas"):
        return _paleta(p)
    if cat == "pelotas":
        return _pelotas(p)
    if cat == "accesorios textil":
        return _por_palabras(p, TEXTILES, "{nombre}, accesorio textil {marca} para la cancha.")
    if cat == "accesorios":
        return _por_palabras(p, ACCESORIOS, "{nombre}, accesorio {marca} para tu juego.")
    if cat == "overgrips":
        return _overgrip(p)
    if cat == "grips":
        return [f"Grip {p.marca} para cambiar el agarre base de tu paleta o raqueta y mejorar la comodidad."]
    if cat == "protectores":
        return _protector(p)
    if cat == "raquetas":
        return _raqueta(p)
    if cat.startswith("indumentaria"):
        return [f"{p.nombre}: ropa deportiva {p.marca} original para jugar cómodo.",
                "Elegí tu talle antes de agregarla al carrito. Si tenés dudas con el talle, escribinos."]
    if cat.startswith("calzado"):
        return [f"{p.nombre}: zapatillas {p.marca} originales para la cancha.",
                "Elegí tu talle antes de agregarlas al carrito."]
    return [f"{p.nombre}, producto {p.marca} original con envío a todo el país."]


def descripcion_corta(p):
    """Una línea para Google (meta description y datos de producto)."""
    propia = (p.descripcion or "").strip()
    if len(propia) >= MINIMO_PROPIA:
        return propia
    return " ".join(descripcion_producto(p) or [])
