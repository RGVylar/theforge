"""Ornamento procedural y composicion de bandas para la esfera.

No hay ninguna imagen de partida: todo se dibuja con curvas de curvatura
constante. La pieza basica es siempre la misma —una espina que se enrolla con
lobulos alternos que menguan hacia la punta— y lo que cambia de un estilo a
otro son cuatro numeros:

    punta         si el lobulo acaba romo (hoja) o afilado (pincho)
    giro_lobulo   cuanto se enrosca antes de acabar
    capas         cuantas pasadas de hojas y a que tamano, o sea la densidad
    ancho         el grosor del trazo

Con eso, el mismo codigo da acanto barroco recargado o tribal a lo tatuaje. El
barroco no es acanto "fino": es acanto en cuatro capas hasta que no queda hueco,
porque el horror vacui es el estilo, no un exceso del estilo.

Todo determinista: la misma llamada da siempre el mismo dibujo.

Convenio de grises, el mismo que en lito: oscuro = grueso. El fondo va claro
para que la lampara ilumine y el ornamento oscuro para que se lea como relieve
contra el fondo encendido.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

FONDO = 205  # gris del fondo: pared fina, pero no la minima
TINTA = 25  # gris del ornamento: casi el grosor maximo
SUPERMUESTREO = 2  # se dibuja al doble y se reduce, que es el antialias


@dataclass(frozen=True)
class Style:
    """Los numeros que distinguen un estilo de otro."""

    nombre: str
    ancho: float = 0.055  # grosor del trazo, relativo al alto de la banda
    punta: float = 0.30  # r_final / r_inicial del lobulo; bajo = pincho
    lobulos: int = 6
    giro_lobulo: float = 3.2  # radianes que gira el lobulo; alto = se enrosca
    giro_espina: float = 2.5
    largo_lobulo: float = 0.34
    # (escala, cuantas hojas) por capa. Mas capas = mas denso.
    capas: tuple[tuple[float, int], ...] = ((1.0, 2), (0.6, 4))
    desenfoque: float = 0.005
    onda_tallo: float = 0.13
    alcance: float = 0.30  # cuanto se alejan del tallo las capas exteriores


STYLES: dict[str, Style] = {
    "acanthus": Style(
        nombre="acanthus",
        ancho=0.050,
        punta=0.32,
        lobulos=7,
        giro_lobulo=3.4,
        giro_espina=2.6,
        largo_lobulo=0.36,
        # Cinco capas hasta que no queda hueco: eso es lo que lo hace barroco.
        # Un barroco sobrio es un barroco fallido.
        capas=((1.05, 2), (0.70, 4), (0.48, 7), (0.32, 10), (0.20, 14)),
        desenfoque=0.004,
        alcance=0.46,
    ),
    "tribal": Style(
        nombre="tribal",
        ancho=0.075,
        punta=0.02,  # afila a cero: el pincho es justo la gracia
        lobulos=3,
        giro_lobulo=1.5,
        giro_espina=2.2,
        largo_lobulo=0.46,
        capas=((1.15, 2), (0.55, 3)),  # pocas piezas y grandes
        desenfoque=0.004,
        onda_tallo=0.18,
    ),
    "scroll": Style(
        nombre="scroll",
        ancho=0.034,
        punta=0.18,
        lobulos=5,
        giro_lobulo=2.8,
        giro_espina=2.5,
        largo_lobulo=0.32,
        capas=((1.0, 2), (0.5, 5)),
        desenfoque=0.006,
    ),
}

POR_DEFECTO = "acanthus"


def _curva(base, angulo: float, largo: float, giro: float, pasos: int = 48) -> np.ndarray:
    """Curva de curvatura constante, parametrizada por longitud de arco.

    Sale de `base` en la direccion `angulo` y gira `giro` radianes en total.
    Integrar el angulo paso a paso evita pelearse con centros y signos, y deja
    los puntos repartidos de forma uniforme.
    """
    t = np.linspace(0.0, 1.0, pasos)
    ang = angulo + giro * t
    paso = largo / (pasos - 1)
    puntos = np.column_stack([np.cumsum(np.cos(ang)), np.cumsum(np.sin(ang))]) * paso
    return puntos + np.asarray(base, dtype=float)


def _direccion(puntos: np.ndarray, i: int) -> float:
    """Angulo de la tangente de la curva en el punto i."""
    j = min(i + 1, len(puntos) - 1)
    dx, dy = puntos[j] - puntos[max(i - 1, 0)]
    return math.atan2(dy, dx)


def _trazo(dibujo: ImageDraw.ImageDraw, puntos: np.ndarray, r0: float, r1: float) -> None:
    """Traza la curva con grosor decreciente, como discos solapados.

    PIL no sabe dibujar lineas que adelgazan, pero una ristra de circulos si, y
    de paso deja los extremos redondeados.
    """
    for (x, y), r in zip(puntos, np.linspace(r0, r1, len(puntos))):
        if r < 0.4:
            continue
        dibujo.ellipse([x - r, y - r, x + r, y + r], fill=TINTA)


def _hoja(
    dibujo: ImageDraw.ImageDraw,
    base,
    angulo: float,
    largo: float,
    ancho: float,
    estilo: Style,
    lado: int = 1,
) -> None:
    """Espina enrollada con lobulos alternos que menguan hacia la punta."""
    espina = _curva(base, angulo, largo, giro=lado * estilo.giro_espina, pasos=64)
    _trazo(dibujo, espina, r0=ancho, r1=ancho * max(estilo.punta, 0.08))

    for k, fraccion in enumerate(np.linspace(0.06, 0.78, estilo.lobulos)):
        i = int(fraccion * (len(espina) - 1))
        hacia = _direccion(espina, i)
        # Alternos: uno al exterior de la curva y el siguiente al interior.
        signo = lado if k % 2 == 0 else -lado
        merma = 1.0 - fraccion
        lobulo = _curva(
            espina[i],
            hacia + signo * 0.88,
            largo * estilo.largo_lobulo * merma,
            giro=signo * estilo.giro_lobulo,
            pasos=26,
        )
        _trazo(dibujo, lobulo, r0=ancho * 0.75 * merma, r1=ancho * estilo.punta * merma)


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
    grosor = h * estilo.ancho

    # Tallo ondulado que recorre la banda y del que cuelga todo lo demas.
    fase = np.linspace(0, 2 * math.pi, 160)
    tallo = np.column_stack(
        [np.linspace(0, w, 160), h * 0.5 + h * estilo.onda_tallo * np.sin(fase)]
    )
    _trazo(dibujo, tallo, r0=grosor * 0.45, r1=grosor * 0.45)

    for capa, (escala, cuantas) in enumerate(estilo.capas):
        # Cada capa se desplaza media casilla respecto de la anterior, para que
        # caiga en los huecos que dejo la de arriba en vez de encima.
        desfase = 0.5 / cuantas if capa % 2 else 0.0
        for i in range(cuantas):
            fraccion = (i + 0.5) / cuantas + desfase
            j = int(min(fraccion, 0.999) * (len(tallo) - 1))
            lado = 1 if (i + capa) % 2 == 0 else -1
            # Las capas finas se separan del tallo para llenar arriba y abajo.
            alejamiento = h * estilo.alcance * capa / max(len(estilo.capas) - 1, 1)
            base = (tallo[j][0], tallo[j][1] + lado * alejamiento)
            _hoja(
                dibujo,
                base,
                -lado * math.pi / 2 + lado * 0.5,
                h * 0.62 * escala,
                grosor * escala,
                estilo,
                lado=lado,
            )

    # Dos hojas mayores flanqueando el medallon, que es donde pide mas peso.
    for lado in (1, -1):
        _hoja(
            dibujo,
            (w * 0.02, h * 0.5),
            lado * 0.55,
            h * 1.05,
            grosor,
            estilo,
            lado=lado,
        )

    lienzo = lienzo.resize((media, alto_px), Image.LANCZOS)
    completo = Image.new("L", size, FONDO)
    completo.paste(lienzo, (media, 0))
    completo.paste(lienzo.transpose(Image.FLIP_LEFT_RIGHT), (0, 0))
    # El desenfoque convierte la silueta plana en relieve redondeado. Poco: lo
    # justo para matar el canto sin comerse el dibujo.
    return completo.filter(
        ImageFilter.GaussianBlur(max(1.0, alto_px * estilo.desenfoque))
    )


def ink_fraction(campo: Image.Image) -> float:
    """Proporcion de superficie con ornamento. Util para calibrar densidades."""
    valores = np.asarray(campo, dtype=int)
    return float((valores < (FONDO + TINTA) / 2).mean())


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

    # Aro del medallon, para separarlo del ornamento.
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
