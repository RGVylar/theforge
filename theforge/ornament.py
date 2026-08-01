"""Ornamento barroco procedural y composicion de bandas para la esfera.

No hay ninguna imagen de partida: las hojas de acanto se dibujan con espirales
logaritmicas. Un acanto es, en el fondo, una voluta que se enrolla y de la que
brotan volutas mas pequenas en lados alternos; con eso y un desenfoque para
redondear el relieve se llega bastante lejos.

Todo es determinista (nada de random), asi que la misma llamada da siempre el
mismo dibujo y se puede testear.

Convenio de grises, el mismo que en lito: oscuro = grueso. El fondo va claro
para que la lampara ilumine, y el ornamento oscuro para que se lea como una
tracería en relieve contra el fondo encendido.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

FONDO = 205  # gris del fondo: pared fina, pero no la minima
TINTA = 25  # gris del ornamento: casi el grosor maximo
SUPERMUESTREO = 2  # se dibuja al doble y se reduce, que es el antialias


def _log_spiral(pasos: int, vueltas: float, decaimiento: float) -> np.ndarray:
    """Espiral logaritmica que arranca en radio 1 y se enrolla hacia dentro."""
    theta = np.linspace(0.0, vueltas * 2 * math.pi, pasos)
    radio = np.exp(-decaimiento * theta)
    return np.column_stack([radio * np.cos(theta), radio * np.sin(theta)])


def _colocar(puntos: np.ndarray, centro, angulo: float, escala: float) -> np.ndarray:
    """Rota, escala y traslada una curva unitaria."""
    c, s = math.cos(angulo), math.sin(angulo)
    rot = np.array([[c, -s], [s, c]])
    return puntos @ rot.T * escala + np.asarray(centro, dtype=float)


def _trazo(dibujo: ImageDraw.ImageDraw, puntos: np.ndarray, r0: float, r1: float) -> None:
    """Traza la curva con grosor decreciente, como discos solapados.

    PIL no sabe dibujar lineas que adelgazan, pero una ristra de circulos si, y
    de paso deja los extremos redondeados, que es lo que quiere una hoja.
    """
    radios = np.linspace(r0, r1, len(puntos))
    for (x, y), r in zip(puntos, radios):
        if r < 0.4:
            continue
        dibujo.ellipse([x - r, y - r, x + r, y + r], fill=TINTA)


def _voluta(
    dibujo: ImageDraw.ImageDraw,
    centro,
    angulo: float,
    escala: float,
    profundidad: int,
    lado: int = 1,
) -> None:
    """Voluta de acanto: se enrolla y echa volutas hijas en lados alternos."""
    puntos = _log_spiral(140, vueltas=1.15, decaimiento=0.34)
    puntos[:, 1] *= lado  # el lado decide hacia donde se enrolla
    puntos = _colocar(puntos, centro, angulo, escala)
    # Trazo fino: el ornamento tiene que leerse como traceria, no como mancha.
    _trazo(dibujo, puntos, r0=escala * 0.055, r1=escala * 0.004)

    if profundidad <= 0:
        return
    # Las hijas salen del tramo ancho, que es donde de verdad brota la hoja.
    for fraccion, giro, merma in ((0.14, 1.25, 0.46), (0.40, 1.0, 0.32)):
        i = int(fraccion * (len(puntos) - 1))
        tangente = puntos[min(i + 1, len(puntos) - 1)] - puntos[i]
        base = math.atan2(tangente[1], tangente[0])
        _voluta(
            dibujo,
            puntos[i],
            base + lado * giro,
            escala * merma,
            profundidad - 1,
            lado=-lado,
        )


def acanthus_field(size: tuple[int, int], escala: float = 0.34) -> Image.Image:
    """Campo continuo de acanto, simetrico y que tesela sin costura en horizontal.

    Se dibuja solo la mitad derecha y se espeja: asi el dibujo es simetrico
    respecto del centro y respecto de los bordes, que es justo lo que hace falta
    para que al envolverlo el empalme case.
    """
    ancho, alto = size
    media = ancho // 2
    lienzo = Image.new("L", (media * SUPERMUESTREO, alto * SUPERMUESTREO), FONDO)
    dibujo = ImageDraw.Draw(lienzo)

    w, h = lienzo.size
    unidad = h * escala

    # Tallo ondulado que recorre la banda y cose las volutas entre si.
    fase = np.linspace(0, 2 * math.pi, 120)
    tallo = np.column_stack([np.linspace(0, w, 120), h * 0.5 + h * 0.10 * np.sin(fase)])
    _trazo(dibujo, tallo, r0=unidad * 0.030, r1=unidad * 0.030)

    # Volutas colgadas del tallo, alternando arriba y abajo. Se apoyan sobre el
    # propio tallo para que no queden flotando.
    for i, fraccion in enumerate(np.linspace(0.12, 0.94, 6)):
        lado = 1 if i % 2 == 0 else -1
        j = int(fraccion * (len(tallo) - 1))
        _voluta(dibujo, tallo[j], -lado * math.pi / 2, unidad * 0.62, 2, lado=lado)

    # Dos hojas mayores flanqueando el medallon, que es donde pide mas peso.
    for lado in (1, -1):
        _voluta(dibujo, (w * 0.06, h * 0.5), lado * 0.5, unidad * 0.95, 2, lado=lado)

    lienzo = lienzo.resize((media, alto), Image.LANCZOS)
    completo = Image.new("L", size, FONDO)
    completo.paste(lienzo, (media, 0))
    completo.paste(lienzo.transpose(Image.FLIP_LEFT_RIGHT), (0, 0))
    # El desenfoque convierte la silueta plana en relieve redondeado.
    return completo.filter(ImageFilter.GaussianBlur(max(1.0, alto * 0.012)))


def _prewarp_columns(imagen: Image.Image, escalas: np.ndarray) -> np.ndarray:
    """Estira cada fila horizontalmente por su factor, alrededor del centro.

    Sirve para compensar el achatamiento equirectangular: una fila que sobre la
    esfera se comprime por cos(lat) se dibuja aqui ensanchada por 1/cos(lat), y
    el resultado se ve sin deformar sobre la pieza.
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
    lat_min_deg: float,
    lat_max_deg: float,
    medallion: float = 0.82,
    ring_mm: float = 0.05,
) -> Image.Image:
    """Banda equirectangular: un medallon con la foto y acanto alrededor.

    `size` es el lienzo de la banda completa (360 grados de longitud). El
    medallon va centrado, y su contenido se pre-deforma para que salga circular
    sobre la esfera en vez de aperado.
    """
    ancho, alto = size
    banda = acanthus_field(size)

    lat = np.radians(np.linspace(lat_max_deg, lat_min_deg, alto))  # fila 0 arriba
    # Referencia: la latitud del centro de la banda. Ahi la escala es 1.
    cos_centro = math.cos(math.radians((lat_min_deg + lat_max_deg) / 2))
    escalas = cos_centro / np.cos(lat)

    diametro = int(alto * medallion)
    cuadrada = photo.convert("L").resize((diametro, diametro), Image.LANCZOS)
    # Se pre-deforma solo la franja de filas que ocupa el medallon.
    fila0 = (alto - diametro) // 2
    trozo = escalas[fila0 : fila0 + diametro]
    estirada = Image.fromarray(
        _prewarp_columns(cuadrada, trozo / trozo[len(trozo) // 2]).astype(np.uint8), "L"
    )

    mascara = Image.new("L", (diametro, diametro), 0)
    ImageDraw.Draw(mascara).ellipse([0, 0, diametro - 1, diametro - 1], fill=255)
    banda.paste(estirada, ((ancho - diametro) // 2, fila0), mascara)

    # Aro del medallon, para separarlo del ornamento.
    grosor = max(2, int(alto * ring_mm))
    aro = ImageDraw.Draw(banda)
    caja = [
        (ancho - diametro) // 2,
        fila0,
        (ancho - diametro) // 2 + diametro - 1,
        fila0 + diametro - 1,
    ]
    aro.ellipse(caja, outline=TINTA, width=grosor)
    return banda
