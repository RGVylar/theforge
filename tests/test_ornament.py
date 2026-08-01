from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from theforge.ornament import FONDO, TINTA, acanthus_field, sphere_band

TAMANO = (600, 200)


@pytest.fixture(scope="module")
def campo() -> np.ndarray:
    return np.asarray(acanthus_field(TAMANO), dtype=int)


def test_el_dibujo_es_determinista():
    """Sin random: la misma llamada tiene que dar el mismo dibujo."""
    uno = np.asarray(acanthus_field(TAMANO))
    otro = np.asarray(acanthus_field(TAMANO))
    assert np.array_equal(uno, otro)


def test_los_grises_se_quedan_en_el_rango(campo):
    assert campo.min() >= TINTA - 1
    assert campo.max() <= FONDO + 1


def test_hay_ornamento_de_verdad(campo):
    """Ni lienzo en blanco ni manchurron: entre el 10% y el 60% con tinta."""
    con_tinta = (campo < (FONDO + TINTA) / 2).mean()
    assert 0.10 < con_tinta < 0.60


def test_es_simetrico_respecto_del_centro(campo):
    assert np.array_equal(campo, campo[:, ::-1])


def test_empalma_al_envolver(campo):
    """La primera y la ultima columna son el mismo meridiano de la esfera."""
    assert np.array_equal(campo[:, 0], campo[:, -1])


def test_la_banda_lleva_el_medallon_centrado():
    # Foto negra pura: el ornamento es TINTA=25, asi que un umbral por debajo
    # de eso aisla la foto del dibujo.
    foto = Image.new("L", (200, 200), 0)
    banda = np.asarray(sphere_band(foto, TAMANO, -45, 75), dtype=int)
    assert banda.shape == (TAMANO[1], TAMANO[0])

    es_foto = banda < 12
    ancho = banda.shape[1]
    centro = es_foto[:, ancho // 3 : 2 * ancho // 3].mean()
    bordes = np.concatenate(
        [es_foto[:, : ancho // 3].ravel(), es_foto[:, 2 * ancho // 3 :].ravel()]
    ).mean()
    assert centro > 0.4
    assert bordes == 0.0  # el medallon no se sale de su tercio


def test_el_medallon_se_predeforma_ensanchando_hacia_arriba():
    """El contenido se dibuja mas ancho donde la esfera lo va a comprimir.

    La silueta del medallon es un circulo pase lo que pase, porque la mascara
    se aplica despues; lo que se estira es lo de dentro. Por eso se mide una
    franja vertical de la foto, no el borde.
    """
    pixeles = np.full((200, 200), 255, dtype=np.uint8)
    pixeles[:, 95:105] = 0
    banda = np.asarray(
        sphere_band(Image.fromarray(pixeles, "L"), (600, 200), -45, 75), dtype=int
    )
    franja = banda < 12

    filas = np.flatnonzero(franja.any(axis=1))
    alto_medallon = filas[-1] - filas[0]
    arriba = franja[filas[0] + int(alto_medallon * 0.25)].sum()
    abajo = franja[filas[0] + int(alto_medallon * 0.75)].sum()
    assert arriba > abajo * 1.15
