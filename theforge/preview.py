"""Simulacion de la litofania a contraluz.

Ley de Beer-Lambert: la luz transmitida cae exponencialmente con el grosor,
T = exp(-mu * t). El coeficiente del PLA blanco esta inventado, asi que esto
sirve para COMPARAR variantes entre si, no para predecir el resultado real.

Cada imagen se normaliza a su propia zona mas fina, que es lo que harias en la
realidad: subir el brillo del LED hasta que los blancos quedan blancos. Por eso
dos previsualizaciones no son comparables en brillo absoluto, solo en contraste
y en reparto de tonos.

Es la unica vista que informa de verdad sobre una litofania sin imprimirla: en
luz reflejada gana siempre la que tiene mas relieve, que a contraluz es
justamente la que se tapa.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from theforge.lito import LitoParams, thickness_map

MU = 1.0  # 1/mm, inventado. Ver el aviso de arriba.


def backlit_from_thickness(espesor: np.ndarray, mu: float = MU) -> Image.Image:
    """Mapa de grosores (mm, fila 0 abajo) -> imagen a contraluz (fila 0 arriba)."""
    transmitida = np.exp(-mu * np.asarray(espesor, dtype=float))
    maximo = transmitida.max()
    if maximo <= 0:
        raise ValueError("el mapa de grosores no deja pasar nada de luz")
    normal = transmitida / maximo
    # thickness_map da la fila 0 abajo (la pieza crece hacia +Z); para mirarla
    # hay que devolverla al orden de una imagen.
    return Image.fromarray((normal[::-1] * 255 + 0.5).astype(np.uint8), mode="L")


def backlit(image: Image.Image, params: LitoParams, mu: float = MU) -> Image.Image:
    """Imagen de origen + parametros -> como se veria encendida.

    Pasa por el mismo thickness_map que genera la malla, asi que la
    previsualizacion incluye el remuestreo, la gamma, la inversion y el marco.
    """
    return backlit_from_thickness(thickness_map(image, params), mu=mu)
