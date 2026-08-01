"""Generador de litofanias: imagen -> mapa de grosores -> STL cerrado.

La idea es la de siempre: una placa fina cuyo grosor local depende del brillo
del pixel. Zona oscura -> mas material -> menos luz la atraviesa.

Sistema de coordenadas de la pieza (pensado para imprimir de pie, que es como
se imprimen las litofanias):

    plana        X = ancho, Z = alto, el grosor crece hacia -Y.
                 La cara trasera queda en el plano Y = 0 y la base en Z = 0.
    cilindrica   eje vertical Z, la imagen se envuelve alrededor y el grosor
                 crece hacia fuera. La cara interior es un cilindro liso.

En ambos casos la imagen se ve sin espejar mirando la pieza desde fuera.
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


@dataclass
class LitoParams:
    """Parametros del generador. Todas las medidas en milimetros."""

    width_mm: float = 100.0
    min_thickness: float = 0.8
    max_thickness: float = 3.0
    curve: str = FLAT
    arc_degrees: float = 180.0  # solo para curve=cylindrical; 360 cierra el cilindro
    samples: int = 300  # muestras a lo ancho; el alto sale del aspecto de la imagen
    frame_mm: float = 0.0  # marco macizo al grosor maximo, 0 = sin marco
    gamma: float = 1.0  # <1 aclara los medios tonos, >1 los oscurece
    invert: bool = False  # por defecto oscuro = grueso

    def validate(self) -> None:
        if self.width_mm <= 0:
            raise ValueError("width_mm debe ser > 0")
        if not 0 < self.min_thickness < self.max_thickness:
            raise ValueError("se requiere 0 < min_thickness < max_thickness")
        if self.curve not in (FLAT, CYLINDRICAL):
            raise ValueError(f"curve desconocida: {self.curve!r}")
        if self.curve == CYLINDRICAL and not 0 < self.arc_degrees <= 360:
            raise ValueError("arc_degrees debe estar en (0, 360]")
        if self.samples < 2:
            raise ValueError("samples debe ser >= 2")
        if self.frame_mm < 0 or 2 * self.frame_mm >= self.width_mm:
            raise ValueError("frame_mm no cabe en el ancho")
        if self.gamma <= 0:
            raise ValueError("gamma debe ser > 0")

    @property
    def closed_cylinder(self) -> bool:
        """Cierto si el arco da la vuelta completa y no hay costura que cerrar."""
        return self.curve == CYLINDRICAL and abs(self.arc_degrees - 360.0) < 1e-9

    @property
    def radius_mm(self) -> float:
        """Radio interior del cilindro que da el ancho pedido para ese arco."""
        if self.curve != CYLINDRICAL:
            raise ValueError("solo aplica a curve=cylindrical")
        return self.width_mm / math.radians(self.arc_degrees)

    def height_mm(self, image: Image.Image) -> float:
        return self.width_mm * image.height / image.width


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
    nu: int, nv: int, height_mm: float, params: LitoParams
) -> tuple[np.ndarray, np.ndarray]:
    """Coordenadas del parametro (u a lo ancho, v a lo alto) como rejillas (nv, nu)."""
    if params.closed_cylinder:
        # La ultima columna coincidiria con la primera, asi que se excluye.
        u = np.linspace(0.0, params.width_mm, nu, endpoint=False)
    else:
        u = np.linspace(0.0, params.width_mm, nu)
    v = np.linspace(0.0, height_mm, nv)
    return np.meshgrid(u, v)


def thickness_map(image: Image.Image, params: LitoParams) -> np.ndarray:
    """Mapa de grosores (nv, nu) en mm. La fila 0 es la base de la pieza."""
    params.validate()
    if image.mode != "L":
        image = image.convert("L")

    nu = params.samples
    height_mm = params.height_mm(image)
    # Muestreo aproximadamente isotropo: misma densidad en ambos ejes.
    nv = max(2, round(nu * height_mm / params.width_mm))

    # LANCZOS promedia al reducir, asi que hace de antialias del mapa de alturas.
    resized = image.resize((nu, nv), Image.LANCZOS)
    # PIL da la fila 0 arriba; la pieza crece hacia +Z, asi que se le da la vuelta.
    gris = np.asarray(resized, dtype=float)[::-1] / 255.0

    if params.gamma != 1.0:
        gris = gris**params.gamma
    if params.invert:
        gris = 1.0 - gris

    espesor = params.max_thickness - gris * (params.max_thickness - params.min_thickness)

    if params.frame_mm > 0:
        u, v = _grid_coords(nu, nv, height_mm, params)
        borde = (v < params.frame_mm) | (v > height_mm - params.frame_mm)
        if not params.closed_cylinder:
            # Un cilindro cerrado no tiene bordes verticales que enmarcar.
            borde |= (u < params.frame_mm) | (u > params.width_mm - params.frame_mm)
        espesor[borde] = params.max_thickness

    return espesor


def surfaces(
    espesor: np.ndarray, params: LitoParams, height_mm: float
) -> tuple[np.ndarray, np.ndarray]:
    """Rejillas de vertices de la cara frontal (con relieve) y la trasera (lisa)."""
    nv, nu = espesor.shape
    u, v = _grid_coords(nu, nv, height_mm, params)

    if params.curve == FLAT:
        x = u - params.width_mm / 2.0
        front = np.stack([x, -espesor, v], axis=-1)
        back = np.stack([x, np.zeros_like(u), v], axis=-1)
        return front, back

    radio = params.radius_mm
    # Arco centrado en theta = 0, que es la direccion -Y.
    theta = (u - params.width_mm / 2.0) / radio
    sin_t, cos_t = np.sin(theta), np.cos(theta)
    rho = radio + espesor
    front = np.stack([rho * sin_t, -rho * cos_t, v], axis=-1)
    back = np.stack([radio * sin_t, -radio * cos_t, v], axis=-1)
    return front, back


def lithophane(image: str | Path | Image.Image, params: LitoParams) -> np.ndarray:
    """Genera la malla (n, 3, 3) de la litofania, cerrada y orientada hacia fuera."""
    params.validate()
    img = image if isinstance(image, Image.Image) else load_grayscale(image)
    espesor = thickness_map(img, params)
    front, back = surfaces(espesor, params, params.height_mm(img))
    return closed_shell(front, back, wrap_u=params.closed_cylinder)
