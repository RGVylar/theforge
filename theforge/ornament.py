"""Ornamento procedural y composicion de bandas para la esfera.

No hay ninguna imagen de partida: todo se dibuja resolviendo contornos.

Cada pieza (una hoja, una lamina) se construye igual: una espina curva, un
perfil de ancho a lo largo de ella, y un borde que puede ir festoneado. Con eso
se arma un poligono cerrado -desplazando la espina a un lado y a otro por la
normal- y se rellena. Dibujar siluetas y no trazos es lo que separa una hoja de
un churro: un trazo grueso no tiene punta, ni lobulos, ni sitio donde meter las
nervaduras.

Tres cosas hacen que el relieve se lea, y las tres importan:

    canto      cada pieza lleva su contorno en un gris intermedio, de modo que
               al solaparse no se funden en una mancha: se ve cual va delante.
    nervios    lineas finas hacia la punta de cada lobulo. Es lo que convierte
               una silueta en una hoja.
    perfil     como mengua el ancho. Lento y con lobulos da acanto; rapido y
               liso da lamina afilada. El mismo codigo, otro perfil.

Todo determinista: la misma llamada da siempre el mismo dibujo.

Convenio de grises, el mismo que en lito: oscuro = grueso. El fondo va claro
para que la lampara ilumine y el ornamento oscuro para que se lea como relieve.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

FONDO = 205  # gris del fondo: pared fina, pero no la minima
TINTA = 25  # cuerpo del ornamento: casi el grosor maximo
CANTO = 115  # contorno y nervaduras: a media altura, para que hagan sombra
SUPERMUESTREO = 3  # se dibuja al triple y se reduce: el detalle fino lo pide


@dataclass(frozen=True)
class Style:
    """Los numeros que distinguen un estilo de otro."""

    nombre: str
    # "hoja" = raquis con foliolos, "llama" = haces de puas, "astilla" = maraña
    # de filamentos ramificados
    forma: str = "hoja"
    # Perfil de la pieza
    afilado: float = 1.4  # exponente del ancho; alto = afila antes
    panza: float = 0.55  # cuanto tarda en engordar desde la base
    esbeltez: float = 4.5  # largo / ancho de la hoja; bajo = concha, alto = hoja
    lobulos: int = 5  # foliolos por hoja
    foliolo: float = 0.42  # largo del foliolo respecto al de la hoja
    apertura: float = 0.85  # angulo con que brota el foliolo del raquis
    rizo: float = 1.9  # cuanto se enrosca cada foliolo
    dorso: float = 0.55  # ancho del lado interior respecto del exterior
    giro_espina: float = 1.6
    enroscado: float = 1.9  # >1 = casi recta y rizada solo en la punta

    # Como se agrupan las piezas
    hojas_por_ramo: int = 6
    ramos: tuple[tuple[float, float, float, float], ...] = ()  # x, y, angulo, escala
    pinchos: int = 0  # laminas finas sueltas que cruzan por encima

    # Solo para forma="astilla"
    semillas: int = 12  # troncos del nucleo; el doble sale radiando hacia fuera
    niveles: int = 3  # cuantas veces ramifica
    hijas: int = 3  # filamentos que brotan de cada uno
    merma: float = 0.55  # cuanto encoge de largo cada generacion
    merma_ancho: float = 0.50  # y de grosor; mas agresivo, para que acaben en pelo
    apertura_hija: float = 0.32  # angulo con que brota; el que separa maraña de helecho
    # Suelo de grosor, en fraccion del alto del lienzo. Por debajo de la
    # resolucion de impresion el filamento no sale fino: sale gris, o sea
    # grosor intermedio, que en la pieza es una papilla lisa.
    ancho_minimo: float = 0.0

    # Acabado
    nervios: bool = True
    canto: float = 0.010  # grosor del contorno, relativo al alto
    desenfoque: float = 0.0035


STYLES: dict[str, Style] = {
    # Damasco barroco: ramos grandes que se entrelazan hasta no dejar hueco.
    "acanthus": Style(
        nombre="acanthus",
        afilado=1.35,
        panza=0.60,
        esbeltez=5.2,
        foliolo=0.60,
        apertura=0.68,
        rizo=2.2,
        dorso=0.52,
        giro_espina=1.7,
        enroscado=2.1,
        # Pocos ramos y grandes, bien repartidos. Muchos y pequenos se
        # apelmazan en coliflores y dejan huecos entre medias: mal reparto,
        # no falta de densidad.
        lobulos=6,
        hojas_por_ramo=4,
        ramos=(
            (0.04, 0.44, -0.30, 1.55),
            (0.52, 0.16, 1.85, 1.35),
            (0.52, 0.84, -1.85, 1.35),
        ),
        nervios=True,
    ),
    # Laminas afiladas que se cruzan, con pinchos largos por encima.
    # Logo de black metal: nucleo enmaranado y filamentos radiando hacia fuera.
    "blackmetal": Style(
        nombre="blackmetal",
        forma="astilla",
        afilado=3.6,  # aguja pura
        panza=0.30,
        rizo=1.5,
        enroscado=1.5,
        # Cuatro niveles con dos hijas dan mas variedad que tres con tres, y
        # menos tinta: la ramificacion crece como hijas^niveles, y cada
        # filamento tiene un ancho minimo imprimible que no se puede bajar.
        semillas=6,
        niveles=4,
        hijas=2,
        merma=0.66,
        merma_ancho=0.58,
        # 0.7% del alto de la banda son ~0.9 mm en una esfera de 120: dos
        # lineas de boquilla, el filamento mas fino que se puede imprimir.
        ancho_minimo=0.007,
        apertura_hija=0.30,  # ~17 grados: casi paralelas al padre
        dorso=1.0,
        nervios=False,
        canto=0.0,  # a este grosor un contorno se comeria el filamento
        desenfoque=0.0030,
    ),
    # El anterior "tribal": lo que salio fue una fronda, y como fronda esta bien.
    "fern": Style(
        nombre="fern",
        forma="llama",
        afilado=3.2,  # bordes hundidos y punta de aguja
        panza=0.40,  # tambien afila por la base: pua, no cuchara
        esbeltez=12.0,
        # Giro largo: la pua se engancha en vez de salir disparada. Recta se
        # lee como hoja de palmera, no como garra.
        rizo=2.70,
        dorso=0.42,  # asimetrica: un lomo y un filo
        enroscado=1.7,
        hojas_por_ramo=6,  # puas por haz
        ramos=(
            (0.05, 0.50, -0.15, 0.92),
            (0.34, 0.10, 1.25, 0.80),
            (0.34, 0.90, -1.25, 0.80),
            (0.66, 0.50, 2.95, 0.86),
            (0.92, 0.16, 1.55, 0.66),
            (0.92, 0.84, -1.55, 0.66),
        ),
        pinchos=6,
        nervios=False,
        canto=0.005,
    ),
}

POR_DEFECTO = "acanthus"


# --------------------------------------------------------------------------
# Geometria de una pieza
# --------------------------------------------------------------------------


def _curva(
    base, angulo: float, largo: float, giro: float, pasos: int = 64, enroscado: float = 1.0
) -> np.ndarray:
    """Curva parametrizada por longitud de arco que gira `giro` radianes.

    Integrar el angulo paso a paso evita pelearse con centros y signos, y deja
    los puntos repartidos de forma uniforme. Con `enroscado` > 1 la curvatura
    crece hacia el final: la hoja sale casi recta y se riza en la punta, que es
    como se riza de verdad.
    """
    t = np.linspace(0.0, 1.0, pasos)
    ang = angulo + giro * t**enroscado
    paso = largo / (pasos - 1)
    puntos = np.column_stack([np.cumsum(np.cos(ang)), np.cumsum(np.sin(ang))]) * paso
    return puntos + np.asarray(base, dtype=float)


def _normales(puntos: np.ndarray) -> np.ndarray:
    """Normal unitaria a la izquierda de la marcha, en cada punto."""
    tang = np.gradient(puntos, axis=0)
    tang /= np.linalg.norm(tang, axis=1, keepdims=True) + 1e-9
    return np.column_stack([-tang[:, 1], tang[:, 0]])


def _direccion(puntos: np.ndarray, i: int) -> float:
    j = min(i + 1, len(puntos) - 1)
    dx, dy = puntos[j] - puntos[max(i - 1, 0)]
    return math.atan2(dy, dx)


def _perfil(t: np.ndarray, estilo: Style) -> np.ndarray:
    """Ancho a lo largo de la pieza, normalizado a 1 en su punto mas ancho.

    Engorda cerca de la base y afila hacia la punta. El exponente es lo que
    decide si sale hoja carnosa o aguja.
    """
    ancho = (t + 0.04) ** estilo.panza * (1.0 - 0.98 * t) ** estilo.afilado
    return ancho / ancho.max()


def _curvatura(espina: np.ndarray) -> np.ndarray:
    """Curvatura con signo en cada punto: positiva si la curva gira a izquierda."""
    tang = np.gradient(espina, axis=0)
    paso = np.linalg.norm(tang, axis=1) + 1e-9
    angulo = np.unwrap(np.arctan2(tang[:, 1], tang[:, 0]))
    return np.gradient(angulo) / paso


def limitar_por_curvatura(
    espina: np.ndarray, izquierda: np.ndarray, derecha: np.ndarray, margen: float = 0.75
) -> tuple[np.ndarray, np.ndarray]:
    """Recorta los anchos para que el contorno desplazado no se pliegue.

    Si un borde se separa de la espina mas que el radio de curvatura, la curva
    paralela se dobla sobre si misma y el relleno sale con picos: es el problema
    clasico de las curvas offset, y se veia como triangulos en el arranque de
    cada pieza. Solo hay que frenar el lado hacia el que gira la curva; el de
    fuera puede ensancharse cuanto quiera.
    """
    curvatura = _curvatura(espina)
    tope = margen / (np.abs(curvatura) + 1e-9)
    return (
        np.where(curvatura > 0, np.minimum(izquierda, tope), izquierda),
        np.where(curvatura < 0, np.minimum(derecha, tope), derecha),
    )


def _pieza(
    dibujo: ImageDraw.ImageDraw,
    espina: np.ndarray,
    izquierda: np.ndarray,
    derecha: np.ndarray,
    canto: int,
) -> np.ndarray:
    """Rellena el poligono que encierran los dos bordes y devuelve el exterior."""
    izquierda, derecha = limitar_por_curvatura(espina, izquierda, derecha)
    normal = _normales(espina)
    borde_i = espina + normal * izquierda[:, None]
    borde_d = espina - normal * derecha[:, None]
    contorno = np.vstack([borde_i, borde_d[::-1]])
    dibujo.polygon(
        [(float(x), float(y)) for x, y in contorno],
        fill=TINTA,
        # En piezas muy finas el contorno se comeria la pieza entera.
        outline=CANTO if canto > 0 else None,
        width=max(canto, 0),
    )
    return borde_i


def _foliolo(
    dibujo: ImageDraw.ImageDraw,
    base,
    angulo: float,
    largo: float,
    ancho: float,
    giro: float,
    estilo: Style,
    canto: int,
    nervio: bool,
) -> None:
    """Un lobulo suelto: pieza ancha en el arranque que acaba en punta rizada."""
    pasos = 56
    espina = _curva(base, angulo, largo, giro=giro, pasos=pasos, enroscado=estilo.enroscado)
    t = np.linspace(0.0, 1.0, pasos)
    # Nace en cero, engorda a un tercio y afila en punta larga: eso es un
    # foliolo. Si el ancho no arranca de cero, la base queda con una tapa recta
    # que delata el poligono.
    w = t**estilo.panza * (1.0 - 0.99 * t) ** estilo.afilado
    w = ancho * w / w.max()
    _pieza(dibujo, espina, w, w * estilo.dorso, canto)
    if nervio:
        dibujo.line(
            [(float(x), float(y)) for x, y in espina[: int(pasos * 0.85)]],
            fill=CANTO,
            width=max(1, int(canto * 0.7)),
        )


def _hoja(
    dibujo: ImageDraw.ImageDraw,
    base,
    angulo: float,
    largo: float,
    ancho: float,
    estilo: Style,
    lado: int,
    canto: int,
) -> np.ndarray:
    """Hoja de acanto: un raquis del que brotan foliolos alternos que menguan.

    Modelar los lobulos como piezas propias, y no como ondas del contorno, es
    lo que separa una hoja de una sierra: cada uno tiene su angulo, su rizo y
    su nervio, y unos tapan a otros.
    """
    pasos = 80
    raquis = _curva(
        base,
        angulo,
        largo,
        giro=lado * estilo.giro_espina,
        pasos=pasos,
        enroscado=estilo.enroscado,
    )
    t = np.linspace(0.0, 1.0, pasos)

    # El raquis va fino: es el soporte, no la hoja.
    nervadura = ancho * 0.30 * (1.0 - 0.95 * t) ** 0.9
    _pieza(dibujo, raquis, nervadura, nervadura, canto)

    # De la base a la punta, y alternando: asi los de delante tapan a los de
    # atras y la hoja gana profundidad. Solapados, no en fila: una hoja de
    # acanto es una mata apretada, no una rama con hojas separadas.
    for k, fraccion in enumerate(np.linspace(0.02, 0.80, estilo.lobulos)):
        i = int(fraccion * (pasos - 1))
        signo = lado if k % 2 == 0 else -lado
        merma = (1.0 - 0.75 * fraccion) ** 0.9
        _foliolo(
            dibujo,
            raquis[i],
            _direccion(raquis, i) + signo * estilo.apertura,
            largo * estilo.foliolo * merma,
            ancho * 0.78 * merma,
            giro=signo * estilo.rizo,
            estilo=estilo,
            canto=canto,
            nervio=estilo.nervios,
        )

    # Remate: el foliolo de la punta sigue la direccion del raquis.
    _foliolo(
        dibujo,
        raquis[-1],
        _direccion(raquis, pasos - 1),
        largo * estilo.foliolo * 0.5,
        ancho * 0.5,
        giro=lado * estilo.rizo * 1.3,
        estilo=estilo,
        canto=canto,
        nervio=estilo.nervios,
    )
    return raquis


def _ramo(
    dibujo: ImageDraw.ImageDraw,
    base,
    angulo: float,
    largo: float,
    ancho: float,
    estilo: Style,
    canto: int,
    lado: int = 1,
) -> None:
    """Tallo con hojas alternas que menguan, y un rizo terminal."""
    pasos = 60
    tallo = _curva(base, angulo, largo, giro=lado * 1.5, pasos=pasos)
    t = np.linspace(0.0, 1.0, pasos)
    grosor_tallo = ancho * 0.30 * (1.0 - 0.85 * t)
    _pieza(dibujo, tallo, grosor_tallo, grosor_tallo, canto)

    for k, fraccion in enumerate(np.linspace(0.04, 0.90, estilo.hojas_por_ramo)):
        i = int(fraccion * (pasos - 1))
        signo = lado if k % 2 == 0 else -lado
        largo_hoja = largo * 0.44 * (1.0 - 0.5 * fraccion)
        _hoja(
            dibujo,
            tallo[i],
            _direccion(tallo, i) + signo * 0.95,
            largo_hoja,
            largo_hoja / estilo.esbeltez,
            estilo,
            lado=signo,
            canto=canto,
        )

    # Rizo del final, que es lo que remata el ramo en vez de dejarlo cortado.
    largo_rizo = largo * 0.38
    _hoja(
        dibujo,
        tallo[-1],
        _direccion(tallo, pasos - 1),
        largo_rizo,
        largo_rizo / estilo.esbeltez,
        estilo,
        lado=lado,
        canto=canto,
    )


def _llama(
    dibujo: ImageDraw.ImageDraw,
    base,
    angulo: float,
    largo: float,
    ancho: float,
    giro: float,
    estilo: Style,
    canto: int,
) -> None:
    """Pua: puntiaguda por los dos extremos y con los bordes hundidos.

    Es lo contrario de un foliolo. La hoja tiene panza y punta roma; la pua
    afila a cero por los dos lados y su silueta se mete hacia dentro, que es
    de donde sale el aire cortante del tribal. Que el ancho llegue a cero
    exacto en la punta es lo que la deja como una aguja y no como un dedo.
    """
    pasos = 64
    espina = _curva(base, angulo, largo, giro=giro, pasos=pasos, enroscado=estilo.enroscado)
    t = np.linspace(0.0, 1.0, pasos)
    w = t**estilo.panza * (1.0 - t) ** estilo.afilado
    w = ancho * w / w.max()
    _pieza(dibujo, espina, w, w * estilo.dorso, canto)


def _fraccion_aurea(k: int) -> float:
    """Secuencia repartida en [0, 1) sin repetirse ni agruparse.

    Sirve para variar posiciones y angulos sin usar random: el dibujo sigue
    siendo el mismo en cada ejecucion, pero pierde la regularidad que delata
    que lo ha generado una maquina. Con las ramas equiespaciadas sale un
    helecho; desiguales, una maraña.
    """
    return (k * 0.6180339887498949) % 1.0


def _astilla(
    dibujo: ImageDraw.ImageDraw,
    base,
    angulo: float,
    largo: float,
    ancho: float,
    estilo: Style,
    canto: int,
    nivel: int,
    suelo: float,
    semilla: int = 0,
) -> None:
    """Filamento con puas hijas que brotan casi paralelas y ramifican.

    Lo que separa esto de un helecho es el angulo: una fronda echa las hojas a
    unos 60 grados del raquis y todas del mismo tamano. Aqui brotan a 15-20 y
    con longitudes muy dispares, y por eso el conjunto se lee como una maraña
    barrida hacia fuera en vez de como una planta.
    """
    pasos = 32
    espina = _curva(
        base, angulo, largo, giro=estilo.rizo * (0.4 + 0.5 * _fraccion_aurea(semilla)),
        pasos=pasos, enroscado=estilo.enroscado,
    )
    t = np.linspace(0.0, 1.0, pasos)
    w = t**estilo.panza * (1.0 - t) ** estilo.afilado
    w = ancho * w / w.max()
    # El suelo se aplica salvo en el ultimo tramo, para que la punta siga
    # cerrando en aguja en vez de acabar cortada a escuadra.
    w = np.maximum(w, suelo * np.minimum(1.0, 6.0 * (1.0 - t)))
    _pieza(dibujo, espina, w, w, canto)

    if nivel <= 0:
        return
    for k in range(estilo.hijas):
        mezcla = _fraccion_aurea(semilla * 3 + k + 1)
        i = int((0.12 + 0.62 * mezcla) * (pasos - 1))
        signo = 1 if (k + semilla) % 2 == 0 else -1
        _astilla(
            dibujo,
            espina[i],
            _direccion(espina, i) + signo * estilo.apertura_hija * (0.6 + 1.1 * mezcla),
            largo * estilo.merma * (0.7 + 0.7 * mezcla),
            ancho * estilo.merma_ancho,
            estilo,
            canto,
            nivel - 1,
            suelo,
            semilla=semilla * 7 + k + 1,
        )


def _marana(
    dibujo: ImageDraw.ImageDraw,
    ancho_lienzo: int,
    alto_lienzo: int,
    estilo: Style,
    canto: int,
) -> None:
    """Nucleo enmaranado del que salen filamentos radiando hacia fuera."""
    medio = alto_lienzo * 0.5
    cuantas = estilo.semillas
    suelo = alto_lienzo * estilo.ancho_minimo

    # El nucleo: trazos que se cruzan a media altura y hacen de masa central.
    for k in range(cuantas):
        f = (k + 0.5) / cuantas
        _astilla(
            dibujo,
            (ancho_lienzo * f, medio + alto_lienzo * 0.10 * (_fraccion_aurea(k) - 0.5)),
            (0.35 if k % 2 else -0.35) + 0.6 * (_fraccion_aurea(k * 5) - 0.5),
            ancho_lienzo * 0.24,
            alto_lienzo * 0.013,
            estilo,
            canto,
            nivel=estilo.niveles,
            suelo=suelo,
            semilla=k,
        )

    # Y los filamentos que salen disparados arriba y abajo, que son los que dan
    # la silueta deshilachada.
    for k in range(cuantas * 2):
        f = (k + 0.5) / (cuantas * 2)
        arriba = k % 2 == 0
        # Casi verticales en el centro y tumbados en los extremos: asi la
        # silueta se abre en alas en vez de quedar como un cepillo.
        inclinacion = (f - 0.5) * 2.2
        _astilla(
            dibujo,
            (ancho_lienzo * f, medio + (-1 if arriba else 1) * alto_lienzo * 0.06),
            (-math.pi / 2 if arriba else math.pi / 2) + inclinacion,
            alto_lienzo * (0.32 + 0.30 * _fraccion_aurea(k * 3)),
            alto_lienzo * 0.010,
            estilo,
            canto,
            nivel=estilo.niveles,
            suelo=suelo,
            semilla=k * 11 + 3,
        )


def _haz(
    dibujo: ImageDraw.ImageDraw,
    centro,
    angulo: float,
    largo: float,
    ancho: float,
    estilo: Style,
    canto: int,
    lado: int = 1,
) -> None:
    """Haz de puas que salen del mismo punto abriendose en abanico.

    De la mas larga a la mas corta: asi las cortas quedan por encima y se ve
    que se cruzan, que es la mitad del efecto.
    """
    cuantas = estilo.hojas_por_ramo
    for k in range(cuantas):
        f = k / max(cuantas - 1, 1)
        _llama(
            dibujo,
            centro,
            angulo + lado * (-0.60 + 1.55 * f),
            largo * (1.0 - 0.42 * f),
            ancho * (1.0 - 0.30 * f),
            giro=lado * estilo.rizo * (0.55 + 1.1 * f),
            estilo=estilo,
            canto=canto,
        )


# --------------------------------------------------------------------------
# Campos y bandas
# --------------------------------------------------------------------------


def ornament_field(size: tuple[int, int], estilo: Style | str = POR_DEFECTO) -> Image.Image:
    """Campo de ornamento, simetrico y que empalma al envolverlo.

    Se dibuja solo la mitad derecha y se espeja: asi el dibujo sale simetrico
    respecto del centro y respecto de los bordes, que es justo lo que hace falta
    para que el empalme case al cerrar la esfera.
    """
    if isinstance(estilo, str):
        estilo = STYLES[estilo]
    ancho_px, alto_px = size
    media = ancho_px // 2
    lienzo = Image.new("L", (media * SUPERMUESTREO, alto_px * SUPERMUESTREO), FONDO)
    dibujo = ImageDraw.Draw(lienzo)
    w, h = lienzo.size
    canto = int(h * estilo.canto) if estilo.canto > 0 else 0

    if estilo.forma == "astilla":
        _marana(dibujo, w, h, estilo, canto)
        lienzo = lienzo.resize((media, alto_px), Image.LANCZOS)
        completo = Image.new("L", size, FONDO)
        completo.paste(lienzo, (media, 0))
        completo.paste(lienzo.transpose(Image.FLIP_LEFT_RIGHT), (0, 0))
        return completo.filter(
            ImageFilter.GaussianBlur(max(0.6, alto_px * estilo.desenfoque))
        )

    for i, (x, y, angulo, escala) in enumerate(estilo.ramos):
        lado = 1 if i % 2 == 0 else -1
        if estilo.forma == "llama":
            _haz(
                dibujo,
                (w * x, h * y),
                angulo,
                h * 0.95 * escala,
                h * 0.075 * escala,
                estilo,
                canto=canto,
                lado=lado,
            )
        else:
            _ramo(
                dibujo,
                (w * x, h * y),
                angulo,
                h * 0.92 * escala,  # tallo largo: las hojas se reparten por el
                h * 0.105 * escala,
                estilo,
                canto=canto,
                lado=lado,
            )

    # Las puas sueltas van las ultimas: cruzan por encima de todo y son las que
    # atan la composicion en vez de dejar haces sueltos flotando.
    for k in range(estilo.pinchos):
        fraccion = (k + 0.5) / estilo.pinchos
        arriba = k % 2 == 0
        _llama(
            dibujo,
            (w * fraccion, h * (0.14 if arriba else 0.86)),
            (1.15 if arriba else -1.15) + (0.45 if k % 2 else -0.45),
            h * 0.62,
            h * 0.042,  # con algo de cuerpo: finas de mas se leen como aranazos
            giro=(1.0 if arriba else -1.0) * 3.0,
            estilo=estilo,
            canto=canto,
        )

    lienzo = lienzo.resize((media, alto_px), Image.LANCZOS)
    completo = Image.new("L", size, FONDO)
    completo.paste(lienzo, (media, 0))
    completo.paste(lienzo.transpose(Image.FLIP_LEFT_RIGHT), (0, 0))
    # Desenfoque corto: redondea el canto sin comerse las nervaduras.
    return completo.filter(
        ImageFilter.GaussianBlur(max(0.6, alto_px * estilo.desenfoque))
    )


def ink_fraction(campo: Image.Image) -> float:
    """Proporcion de superficie con ornamento. Util para calibrar densidades."""
    valores = np.asarray(campo, dtype=int)
    return float((valores < (FONDO + CANTO) / 2).mean())


def _prewarp_columns(imagen: Image.Image, escalas: np.ndarray) -> np.ndarray:
    """Estira cada fila horizontalmente por su factor, alrededor del centro.

    Compensa el achatamiento equirectangular: una fila que sobre la esfera se
    comprime por cos(lat) se dibuja aqui ensanchada por 1/cos(lat), y el
    resultado se ve sin deformar sobre la pieza.
    """
    origen = np.asarray(imagen, dtype=float)
    filas, columnas = origen.shape
    centro = (columnas - 1) / 2.0
    x = np.arange(columnas)[None, :] - centro
    muestra = np.clip(np.round(x / escalas[:, None] + centro), 0, columnas - 1).astype(int)
    return origen[np.arange(filas)[:, None], muestra]


def sphere_band(
    photo: Image.Image,
    size: tuple[int, int],
    lat_min_deg: float = -45.0,
    lat_max_deg: float = 75.0,
    estilo: Style | str = POR_DEFECTO,
    medallion: float = 0.82,
    ring: float = 0.05,
) -> Image.Image:
    """Banda equirectangular: un medallon con la foto y ornamento alrededor.

    `size` es el lienzo de la banda completa (360 grados de longitud). El
    medallon va centrado, y su contenido se pre-deforma para que salga circular
    sobre la esfera en vez de aperado.
    """
    ancho, alto = size
    banda = ornament_field(size, estilo)

    lat = np.radians(np.linspace(lat_max_deg, lat_min_deg, alto))  # fila 0 arriba
    # Referencia: la latitud del centro de la banda, donde la escala es 1.
    cos_centro = math.cos(math.radians((lat_min_deg + lat_max_deg) / 2))
    escalas = cos_centro / np.cos(lat)

    diametro = int(alto * medallion)
    cuadrada = photo.convert("L").resize((diametro, diametro), Image.LANCZOS)
    fila0 = (alto - diametro) // 2
    trozo = escalas[fila0 : fila0 + diametro]
    estirada = Image.fromarray(
        _prewarp_columns(cuadrada, trozo / trozo[len(trozo) // 2]).astype(np.uint8), "L"
    )

    mascara = Image.new("L", (diametro, diametro), 0)
    ImageDraw.Draw(mascara).ellipse([0, 0, diametro - 1, diametro - 1], fill=255)
    izquierda = (ancho - diametro) // 2
    banda.paste(estirada, (izquierda, fila0), mascara)

    ImageDraw.Draw(banda).ellipse(
        [izquierda, fila0, izquierda + diametro - 1, fila0 + diametro - 1],
        outline=TINTA,
        width=max(2, int(alto * ring)),
    )
    return banda


def contact_sheet(
    photo: Image.Image,
    size: tuple[int, int] = (900, 300),
    estilos: tuple[str, ...] | None = None,
    **kwargs,
) -> Image.Image:
    """Hoja de pruebas: una banda por estilo, apiladas y rotuladas.

    Mirar esto cuesta un comando y decide el estilo sin generar un solo STL.
    """
    nombres = estilos or tuple(STYLES)
    ancho, alto = size
    cabecera = 22
    hoja = Image.new("L", (ancho, (alto + cabecera) * len(nombres)), 255)
    lapiz = ImageDraw.Draw(hoja)
    for i, nombre in enumerate(nombres):
        banda = sphere_band(photo, size, estilo=nombre, **kwargs)
        y = i * (alto + cabecera)
        lapiz.text((6, y + 5), f"{nombre}  ({ink_fraction(banda):.0%} de tinta)", fill=0)
        hoja.paste(banda, (0, y + cabecera))
    return hoja
