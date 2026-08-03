"""Generador de litofanias: imagen -> mapa de grosores -> STL cerrado.

La idea es la de siempre: una placa fina cuyo grosor local depende del brillo
del pixel. Zona oscura -> mas material -> menos luz la atraviesa.

Sistema de coordenadas de la pieza (pensado para imprimir de pie, que es como
se imprimen las litofanias):

    plana        X = ancho, Z = alto, el grosor crece hacia -Y.
                 La cara trasera queda en el plano Y = 0.
    cilindrica   eje vertical Z, la imagen se envuelve alrededor y el grosor
                 crece hacia fuera. La cara interior es un cilindro liso.
    esfera       eje vertical Z, truncada arriba y abajo. Los dos cortes dejan
                 sendas bocas: la de abajo para el portalamparas y el cable, la
                 de arriba para ventilar. Sin truncar habria triangulos
                 degenerados en los polos, ademas de ser inimprimible.

En los tres casos la pieza queda apoyada en Z = 0 y la imagen se ve sin espejar
mirando la pieza desde fuera.

Sobre la deformacion en la esfera: al envolver una imagen plana sobre una
esfera la escala horizontal se encoge con el coseno de la latitud. Con `fit`
se elige que hacer con eso:

    stretch    las latitudes se reparten uniformemente. Es lo directo, pero la
               imagen sale comprimida por cos(latitud): fiel solo en el ecuador.
    conformal  las latitudes se espacian segun 1/cos(latitud) (Mercator
               inverso), de modo que la compresion vertical acompana a la
               horizontal y las formas quedan correctas en toda la superficie.
               A cambio la banda deja de elegirse: sale de lat_min, repeat y la
               proporcion de la imagen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from theforge.stl import closed_shell

FLAT = "flat"
CYLINDRICAL = "cylindrical"
SPHERE = "sphere"
CURVES = (FLAT, CYLINDRICAL, SPHERE)

STRETCH = "stretch"
CONFORMAL = "conformal"
FITS = (STRETCH, CONFORMAL)


@dataclass
class LitoParams:
    """Parametros del generador. Todas las medidas en milimetros."""

    width_mm: float = 100.0  # ignorado en curve=sphere, que va por diameter_mm
    min_thickness: float = 0.8
    max_thickness: float = 3.0
    curve: str = FLAT
    arc_degrees: float = 180.0  # solo para curve=cylindrical; 360 cierra el cilindro
    samples: int = 300  # muestras a lo ancho; el alto sale de la proporcion
    frame_mm: float = 0.0  # marco macizo al grosor maximo, 0 = sin marco
    gamma: float = 1.0  # <1 aclara los medios tonos, >1 los oscurece
    invert: bool = False  # por defecto oscuro = grueso
    repeat: int = 1  # copias de la imagen a lo ancho
    # Solo para curve=sphere:
    diameter_mm: float = 100.0
    lat_min_deg: float = -45.0  # corte inferior; -45 es el limite sin soportes
    lat_max_deg: float = 75.0  # corte superior; ignorado si fit=conformal
    fit: str = STRETCH
    # Sella la boca de arriba con dos tapas (exterior e interior) en vez de
    # dejarla abierta. La de abajo se queda siempre abierta -es el acceso
    # para el portalamparas y el cable-, capar las dos no da una bola hueca:
    # da dos cascaras SEPARADAS sin ningun punto de contacto, ver closed_shell.
    cap_top: bool = False

    def validate(self) -> None:
        if self.width_mm <= 0:
            raise ValueError("width_mm debe ser > 0")
        if not 0 < self.min_thickness < self.max_thickness:
            raise ValueError("se requiere 0 < min_thickness < max_thickness")
        if self.curve not in CURVES:
            raise ValueError(f"curve desconocida: {self.curve!r}")
        if self.fit not in FITS:
            raise ValueError(f"fit desconocido: {self.fit!r}")
        if self.curve == CYLINDRICAL and not 0 < self.arc_degrees <= 360:
            raise ValueError("arc_degrees debe estar en (0, 360]")
        if self.curve == SPHERE:
            if self.diameter_mm <= 0:
                raise ValueError("diameter_mm debe ser > 0")
            if not -90 < self.lat_min_deg < 90:
                raise ValueError("lat_min_deg debe estar en (-90, 90)")
            # Con fit=conformal el corte superior lo fija la imagen, no tu.
            if self.fit == STRETCH and not self.lat_min_deg < self.lat_max_deg < 90:
                raise ValueError("se requiere lat_min_deg < lat_max_deg < 90")
        if self.samples < 2:
            raise ValueError("samples debe ser >= 2")
        if self.repeat < 1:
            raise ValueError("repeat debe ser >= 1")
        if self.gamma <= 0:
            raise ValueError("gamma debe ser > 0")
        if self.frame_mm < 0:
            raise ValueError("frame_mm no puede ser negativo")
        if self.curve != SPHERE and 2 * self.frame_mm >= self.width_mm:
            raise ValueError("frame_mm no cabe en el ancho")

    @property
    def wraps_u(self) -> bool:
        """Cierto si la superficie se cierra sobre si misma y no hay costura."""
        if self.curve == SPHERE:
            return True
        return self.curve == CYLINDRICAL and abs(self.arc_degrees - 360.0) < 1e-9

    @property
    def radius_mm(self) -> float:
        """Radio de la cara interior."""
        if self.curve == SPHERE:
            return self.diameter_mm / 2.0
        if self.curve == CYLINDRICAL:
            return self.width_mm / math.radians(self.arc_degrees)
        raise ValueError("la pieza plana no tiene radio")


# --------------------------------------------------------------------------
# Reparto de la imagen sobre la superficie
# --------------------------------------------------------------------------


def _mercator(lat: float) -> float:
    """Latitud (rad) -> coordenada vertical de Mercator."""
    return math.log(math.tan(math.pi / 4.0 + lat / 2.0))


def _inverse_mercator(y):
    """Coordenada de Mercator -> latitud (rad). Vale para escalares y arrays."""
    return 2.0 * np.arctan(np.exp(y)) - math.pi / 2.0


@dataclass
class Layout:
    """Como queda repartida la imagen sobre la superficie, ya resuelto.

    width_mm y height_mm son longitudes de arco medidas sobre la superficie, de
    modo que el marco mide lo mismo en las tres formas. lat solo lo usa la
    esfera: es la latitud (rad) de cada fila de la rejilla.
    """

    rows: int
    cols: int
    width_mm: float
    height_mm: float
    aspect: float  # alto/ancho de la imagen de origen
    lat: np.ndarray | None = None

    @property
    def lat_degrees(self) -> tuple[float, float]:
        if self.lat is None:
            raise ValueError("solo la esfera tiene latitudes")
        return math.degrees(self.lat[0]), math.degrees(self.lat[-1])


def layout(image: Image.Image, params: LitoParams) -> Layout:
    """Resuelve la rejilla y el trozo de superficie que ocupa la imagen."""
    params.validate()
    aspecto = image.height / image.width

    # nu multiplo de repeat, para que las copias sean identicas al teselar.
    cols = max(params.repeat, round(params.samples / params.repeat) * params.repeat)
    # Se muestrea la imagen con su propia proporcion: cada copia es cuadrada si
    # la imagen lo es, independientemente de lo que mida en la superficie.
    rows = max(2, round(cols / params.repeat * aspecto))

    if params.curve != SPHERE:
        ancho = params.width_mm
        return Layout(rows, cols, ancho, ancho * aspecto, aspecto)

    radio = params.radius_mm
    lat_min = math.radians(params.lat_min_deg)
    fraccion = np.linspace(0.0, 1.0, rows)
    if params.fit == CONFORMAL:
        # Que la banda de Mercator guarde la proporcion de la imagen es lo que
        # hace que las formas no se deformen.
        span = (2 * math.pi / params.repeat) * aspecto
        lat = _inverse_mercator(_mercator(lat_min) + fraccion * span)
    else:
        lat_max = math.radians(params.lat_max_deg)
        lat = lat_min + fraccion * (lat_max - lat_min)

    return Layout(
        rows=rows,
        cols=cols,
        width_mm=2 * math.pi * radio,
        height_mm=radio * float(lat[-1] - lat[0]),
        aspect=aspecto,
        lat=lat,
    )


def horizontal_scale(lay: Layout, params: LitoParams) -> tuple[float, float]:
    """Ancho real de la imagen sobre la superficie, minimo y maximo.

    1.0 es fiel. En la esfera con fit=stretch la escala horizontal vale
    cos(latitud), asi que solo el ecuador queda fiel.
    """
    # El trozo de superficie que le toca a cada copia, comparado con la
    # proporcion de la imagen que va a ocuparlo.
    base = lay.width_mm / params.repeat / lay.height_mm * lay.aspect
    if params.curve != SPHERE:
        return base, base
    if params.fit == CONFORMAL:
        return 1.0, 1.0
    # El factor cos(lat) va referido al ecuador, donde la banda mide width/repeat.
    cos_lat = np.cos(lay.lat)
    return float(base * cos_lat.min()), float(base * cos_lat.max())


def load_grayscale(path: str | Path) -> Image.Image:
    """Abre la imagen en escala de grises, aplanando el alfa sobre blanco.

    Sobre blanco y no sobre negro para que las zonas transparentes salgan finas
    en vez de convertirse en un bloque macizo.
    """
    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
        img = img.convert("RGBA")
        fondo = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(fondo, img)
    return img.convert("L")


def _grid_coords(lay: Layout, params: LitoParams) -> tuple[np.ndarray, np.ndarray]:
    """Coordenadas del parametro (u a lo ancho, v a lo alto) como rejillas.

    Son longitudes de arco sobre la superficie, en mm, tambien en las piezas
    curvas: asi el marco mide lo mismo en todas.
    """
    if params.wraps_u:
        # La ultima columna coincidiria con la primera, asi que se excluye.
        u = np.linspace(0.0, lay.width_mm, lay.cols, endpoint=False)
    else:
        u = np.linspace(0.0, lay.width_mm, lay.cols)
    if lay.lat is None:
        v = np.linspace(0.0, lay.height_mm, lay.rows)
    else:
        # Con fit=conformal las filas no van equiespaciadas en latitud.
        v = params.radius_mm * (lay.lat - lay.lat[0])
    return np.meshgrid(u, v)


def thickness_map(
    image: Image.Image, params: LitoParams, lay: Layout | None = None
) -> np.ndarray:
    """Mapa de grosores (nv, nu) en mm. La fila 0 es la base de la pieza."""
    params.validate()
    if image.mode != "L":
        image = image.convert("L")
    if lay is None:
        lay = layout(image, params)
    if params.frame_mm > 0 and 2 * params.frame_mm >= min(lay.width_mm, lay.height_mm):
        raise ValueError("frame_mm no cabe en la superficie")

    # LANCZOS promedia al reducir, asi que hace de antialias del mapa de alturas.
    copia = image.resize((lay.cols // params.repeat, lay.rows), Image.LANCZOS)
    # PIL da la fila 0 arriba; la pieza crece hacia +Z, asi que se le da la vuelta.
    gris = np.asarray(copia, dtype=float)[::-1] / 255.0
    if params.repeat > 1:
        gris = np.tile(gris, (1, params.repeat))

    if params.gamma != 1.0:
        gris = gris**params.gamma
    if params.invert:
        gris = 1.0 - gris

    espesor = params.max_thickness - gris * (params.max_thickness - params.min_thickness)

    if params.frame_mm > 0:
        u, v = _grid_coords(lay, params)
        borde = (v < params.frame_mm) | (v > lay.height_mm - params.frame_mm)
        if not params.wraps_u:
            # Una superficie cerrada en u no tiene bordes verticales que enmarcar.
            borde |= (u < params.frame_mm) | (u > lay.width_mm - params.frame_mm)
        espesor[borde] = params.max_thickness

    return espesor


def surfaces(
    espesor: np.ndarray, params: LitoParams, lay: Layout
) -> tuple[np.ndarray, np.ndarray]:
    """Rejillas de vertices de la cara frontal (con relieve) y la trasera (lisa).

    La frontal es la que mira hacia fuera; su normal es du x dv.
    """
    u, v = _grid_coords(lay, params)

    if params.curve == FLAT:
        x = u - lay.width_mm / 2.0
        front = np.stack([x, -espesor, v], axis=-1)
        back = np.stack([x, np.zeros_like(u), v], axis=-1)
    elif params.curve == CYLINDRICAL:
        radio = params.radius_mm
        # Arco centrado en theta = 0, que es la direccion -Y.
        theta = (u - lay.width_mm / 2.0) / radio
        front = _revolve(radio + espesor, theta, v)
        back = _revolve(radio, theta, v)
    else:
        radio = params.radius_mm
        theta = u / radio
        lat = np.broadcast_to(lay.lat[:, None], u.shape)
        front = _sphere_points(radio + espesor, theta, lat)
        back = _sphere_points(radio, theta, lat)

    # Apoyada en Z = 0. En la plana y la cilindrica ya lo esta; en la esfera el
    # borde exterior del corte inferior queda por debajo del interior.
    suelo = min(front[..., 2].min(), back[..., 2].min())
    front[..., 2] -= suelo
    back[..., 2] -= suelo
    return front, back


def _revolve(rho: np.ndarray, theta: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Punto de un cilindro: theta = 0 mira hacia -Y."""
    rho = np.broadcast_to(rho, theta.shape)
    return np.stack([rho * np.sin(theta), -rho * np.cos(theta), z], axis=-1)


def _sphere_points(rho: np.ndarray, theta: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Punto de una esfera: theta = 0 y lat = 0 miran hacia -Y."""
    rho = np.broadcast_to(rho, theta.shape)
    cos_lat = np.cos(lat)
    return np.stack(
        [
            rho * cos_lat * np.sin(theta),
            -rho * cos_lat * np.cos(theta),
            rho * np.sin(lat),
        ],
        axis=-1,
    )


def lithophane(image: str | Path | Image.Image, params: LitoParams) -> np.ndarray:
    """Genera la malla (n, 3, 3) de la litofania, cerrada y orientada hacia fuera."""
    params.validate()
    img = image if isinstance(image, Image.Image) else load_grayscale(image)
    lay = layout(img, params)
    espesor = thickness_map(img, params, lay)
    front, back = surfaces(espesor, params, lay)
    cap_ends = (False, params.cap_top) if params.curve == SPHERE else (False, False)
    return closed_shell(front, back, wrap_u=params.wraps_u, cap_ends=cap_ends)
