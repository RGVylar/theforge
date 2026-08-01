"""Imagenes sinteticas para los tests: nada de ficheros binarios en el repo."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image


def gradient_image(width: int = 64, height: int = 48) -> Image.Image:
    """Degradado diagonal con esquinas negras y blancas puras.

    Los extremos puros permiten comprobar que el mapa de grosores llega
    exactamente a min_thickness y max_thickness.
    """
    x = np.linspace(0.0, 1.0, width)[None, :]
    y = np.linspace(0.0, 1.0, height)[:, None]
    valores = np.clip((x + y) / 2.0, 0.0, 1.0)
    return Image.fromarray((valores * 255).round().astype(np.uint8), mode="L")


def checker_image(width: int = 64, height: int = 64, cell: int = 8) -> Image.Image:
    """Damero: bordes duros para provocar la peor triangulacion posible."""
    xs = np.arange(width)[None, :] // cell
    ys = np.arange(height)[:, None] // cell
    patron = (xs + ys) % 2
    return Image.fromarray((patron * 255).astype(np.uint8), mode="L")


@pytest.fixture
def gradient() -> Image.Image:
    return gradient_image()


@pytest.fixture
def checker() -> Image.Image:
    return checker_image()
