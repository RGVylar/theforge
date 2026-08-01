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

En las superficies cerradas en u (cilindro de 360 grados y esfera) la imagen se
puede repetir varias veces alrededor con `repeat`, que ademas es la forma de
que no salga estirada: lo que manda es la proporcion del trozo de superficie
que le toca a cada copia.
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
    lat_max_deg: float = 75.0  # corte superior; por encima de ~80 no cierra bien

    def validate(self) -> None:
        if self.width_mm <= 0:
            raise ValueError("width_mm debe ser > 0")
        if not 0 < self.min_thickness < self.max_thickness:
            raise ValueError("se requiere 0 < min_thickness < max_thickness")
        if self.curve not in CURVES:
            raise ValueError(f"curve desconocida: {self.curve!r}")
        if self.curve == CYLINDRICAL and not 0 < self.arc_degrees <= 360:
            raise ValueError("arc_degrees debe estar en (0, 360]")
        if self.curve == SPHERE:
            if self.diameter_mm <= 0:
                raise ValueError("diameter_mm debe ser > 0")
            if not -90 < self.lat_min_deg < self.lat_max_deg < 90:
                raise ValueError("se requiere -90 < lat_min_deg < lat_max_deg < 90")
        if self.samples < 2:
            raise ValueError("samples debe ser >= 2")
        if self.repeat < 1:
            raise ValueError("repeat debe ser >= 1")
        if self.gamma <= 0:
            raise ValueError("gamma debe ser > 0")
        if self.frame_mm < 0:
            raise ValueError("frame_mm no puede ser negativo")
        # El marco se mide sobre la superficie, asi que tiene que caber en ella.
        # En la esfera las dos medidas salen de la geometria; en las demas solo
        # se puede comprobar el ancho, que el alto depende de la imagen.
        if self.curve == SPHERE:
            ancho, alto = self._sphere_size()
            if 2 * self.frame_mm >= min(ancho, alto):
                raise ValueError("frame_mm no cabe en la superficie de la esfera")
        elif 2 * self.frame_mm >= self.width_mm:
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

    def _sphere_size(self) -> tuple[float, float]:
        """Ancho (ecuador) y alto (meridiano) de la esfera, medidos en la superficie."""
        radio = self.diameter_mm / 2.0
        span = math.radians(self.lat_max_deg - self.lat_min_deg)
        return 2 * math.pi * radio, radio * span

    def surface_size(self, image: Image.Image | None = None) -> tuple[float, float]:
        """Ancho y alto de la superficie desplegada, en mm.

        En la esfera lo fija la geometria; en las demas, el ancho lo pones tu y
        el alto sale de la proporcion de la imagen.
        """
        if self.curve == SPHERE:
            return self._sphere_size()
        if image is None:
            raise ValueError("hace falta la imagen para saber el alto")
        return self.width_mm, self.width_mm * image.height / image.width

    def stretch(self, image: Image.Image) -> float:
        """Cuanto se ensancha la imagen al mapearla. 1.0 = sin deformar."""
        ancho, alto = self.surface_size(image)
        return (ancho / self.repeat / alto) / (image.width / image.height)


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


def _grid_coords(
    nu: int, nv: int, size: tuple[float, float], wraps_u: bool
) -> tuple[np.ndarray, np.ndarray]:
    """Coordenadas del parametro (u a lo ancho, v a lo alto) como rejillas (nv, nu).

    Son longitudes de arco medidas sobre la superficie, en mm, tambien en las
    piezas curvas: asi el marco mide lo mismo en todas.
    """
    ancho, alto = size
    if wraps_u:
        # La ultima columna coincidiria con la primera, asi que se excluye.
        u = np.linspace(0.0, ancho, nu, endpoint=False)
    else:
        u = np.linspace(0.0, ancho, nu)
    v = np.linspace(0.0, alto, nv)
    return np.meshgrid(u, v)


def _grid_shape(image: Image.Image, params: LitoParams) -> tuple[int, int]:
    """Numero de muestras (nv, nu), con nu multiplo de repeat."""
    ancho, alto = params.surface_size(image)
    nu = max(params.repeat, round(params.samples / params.repeat) * params.repeat)
    nv = max(2, round(nu * alto / ancho))
    return nv, nu


def thickness_map(image: Image.Image, params: LitoParams) -> np.ndarray:
    """Mapa de grosores (nv, nu) en mm. La fila 0 es la base de la pieza."""
    params.validate()
    if image.mode != "L":
        image = image.convert("L")

    nv, nu = _grid_shape(image, params)
    # LANCZOS promedia al reducir, asi que hace de antialias del mapa de alturas.
    copia = image.resize((nu // params.repeat, nv), Image.LANCZOS)
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
        ancho, alto = params.surface_size(image)
        u, v = _grid_coords(nu, nv, (ancho, alto), params.wraps_u)
        borde = (v < params.frame_mm) | (v > alto - params.frame_mm)
        if not params.wraps_u:
            # Una superficie cerrada en u no tiene bordes verticales que enmarcar.
            borde |= (u < params.frame_mm) | (u > ancho - params.frame_mm)
        espesor[borde] = params.max_thickness

    return espesor


def surfaces(
    espesor: np.ndarray, params: LitoParams, size: tuple[float, float]
) -> tuple[np.ndarray, np.ndarray]:
    """Rejillas de vertices de la cara frontal (con relieve) y la trasera (lisa).

    La frontal es la que mira hacia fuera; su normal es du x dv.
    """
    nv, nu = espesor.shape
    ancho, alto = size
    u, v = _grid_coords(nu, nv, size, params.wraps_u)

    if params.curve == FLAT:
        x = u - ancho / 2.0
        front = np.stack([x, -espesor, v], axis=-1)
        back = np.stack([x, np.zeros_like(u), v], axis=-1)
    elif params.curve == CYLINDRICAL:
        radio = params.radius_mm
        # Arco centrado en theta = 0, que es la direccion -Y.
        theta = (u - ancho / 2.0) / radio
        front = _revolve(radio + espesor, theta, v)
        back = _revolve(radio, theta, v)
    else:
        radio = params.radius_mm
        theta = u / radio
        lat = math.radians(params.lat_min_deg) + v / radio
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
    espesor = thickness_map(img, params)
    front, back = surfaces(espesor, params, params.surface_size(img))
    return closed_shell(front, back, wrap_u=params.wraps_u)
