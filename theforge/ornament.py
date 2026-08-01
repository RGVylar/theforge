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


def _curva(base, angulo: float, largo: float, giro: float, pasos: int = 48) -> np.ndarray:
    """Curva de curvatura constante, parametrizada por longitud de arco.

    Sale de `base` en la direccion `angulo` y gira `giro` radianes en total.
    Integrar el angulo paso a paso evita tener que pelearse con centros y
    signos, y da los puntos ya repartidos de forma uniforme.
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
    de paso deja los extremos redondeados, que es lo que quiere una hoja.
    """
    radios = np.linspace(r0, r1, len(puntos))
    for (x, y), r in zip(puntos, radios):
        if r < 0.4:
            continue
        dibujo.ellipse([x - r, y - r, x + r, y + r], fill=TINTA)


def _hoja(
    dibujo: ImageDraw.ImageDraw,
    base,
    angulo: float,
    largo: float,
    ancho: float,
    lado: int = 1,
    lobulos: int = 6,
) -> None:
    """Hoja de acanto: una espina que se enrolla con lobulos alternos.

    Los lobulos son lo que la distingue de una simple voluta: trazos cortos,
    anchos y curvados hacia la punta, que le dan la carnosidad de la hoja.
    Menguan segun se avanza por la espina, como en la hoja de verdad.
    """
    espina = _curva(base, angulo, largo, giro=lado * 2.5, pasos=64)
    _trazo(dibujo, espina, r0=ancho, r1=ancho * 0.22)

    for k, fraccion in enumerate(np.linspace(0.06, 0.78, lobulos)):
        i = int(fraccion * (len(espina) - 1))
        hacia = _direccion(espina, i)
        # Alternos: uno al exterior de la curva y el siguiente al interior.
        signo = lado if k % 2 == 0 else -lado
        merma = 1.0 - fraccion
        lobulo = _curva(
            espina[i],
            hacia + signo * 0.85,
            largo * 0.34 * merma,
            # Giro largo: el lobulo se enrosca en vez de salir disparado, y
            # acaba en punta roma. Un lobulo que afila queda a pincho.
            giro=signo * 3.2,
            pasos=26,
        )
        _trazo(dibujo, lobulo, r0=ancho * 0.72 * merma, r1=ancho * 0.30 * merma)


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
    grosor = h * 0.055 * escala / 0.34

    # Tallo ondulado que recorre la banda y cose las hojas entre si.
    fase = np.linspace(0, 2 * math.pi, 160)
    tallo = np.column_stack([np.linspace(0, w, 160), h * 0.5 + h * 0.13 * np.sin(fase)])
    _trazo(dibujo, tallo, r0=grosor * 0.45, r1=grosor * 0.45)

    # Dos hojas grandes flanqueando el medallon, que es donde pide mas peso.
    for lado in (1, -1):
        _hoja(dibujo, (w * 0.02, h * 0.5), lado * 0.55, h * 1.05, grosor, lado=lado)

    # Hojas colgadas del tallo, alternando arriba y abajo.
    for i, fraccion in enumerate(np.linspace(0.30, 0.97, 4)):
        lado = 1 if i % 2 == 0 else -1
        j = int(fraccion * (len(tallo) - 1))
        _hoja(
            dibujo,
            tallo[j],
            -lado * math.pi / 2 + lado * 0.5,
            h * 0.62,
            grosor * 0.8,
            lado=lado,
        )

    # Y una menor en cada esquina, que si no quedan vacias. Sin pasarse: el
    # fondo claro es el que ilumina, y comerselo apaga la lampara.
    for lado in (1, -1):
        _hoja(
            dibujo,
            (w * 0.62, h * (0.5 + lado * 0.42)),
            -lado * math.pi / 2 - lado * 0.9,
            h * 0.30,
            grosor * 0.5,
            lado=-lado,
            lobulos=4,
        )

    lienzo = lienzo.resize((media, alto), Image.LANCZOS)
    completo = Image.new("L", size, FONDO)
    completo.paste(lienzo, (media, 0))
    completo.paste(lienzo.transpose(Image.FLIP_LEFT_RIGHT), (0, 0))
    # El desenfoque convierte la silueta plana en relieve redondeado. Poco: lo
    # justo para matar el canto, sin comerse el dibujo.
    return completo.filter(ImageFilter.GaussianBlur(max(1.0, alto * 0.005)))


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
