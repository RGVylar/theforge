from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from theforge.ornament import (
    FONDO,
    STYLES,
    TINTA,
    _curva,
    _curvatura,
    contact_sheet,
    ink_fraction,
    limitar_por_curvatura,
    ornament_field,
    sphere_band,
)

TAMANO = (600, 200)


@pytest.fixture(scope="module")
def campo() -> np.ndarray:
    return np.asarray(ornament_field(TAMANO), dtype=int)


def test_el_dibujo_es_determinista():
    """Sin random: la misma llamada tiene que dar el mismo dibujo."""
    uno = np.asarray(ornament_field(TAMANO))
    otro = np.asarray(ornament_field(TAMANO))
    assert np.array_equal(uno, otro)


def test_los_grises_se_quedan_en_el_rango(campo):
    assert campo.min() >= TINTA - 1
    assert campo.max() <= FONDO + 1


@pytest.mark.parametrize("nombre", tuple(STYLES))
def test_todos_los_estilos_dibujan_algo_razonable(nombre):
    """Ni lienzo en blanco ni manchurron, y con los bordes bien puestos."""
    campo = ornament_field(TAMANO, nombre)
    assert 0.10 < ink_fraction(campo) < 0.60
    pixeles = np.asarray(campo, dtype=int)
    assert np.array_equal(pixeles, pixeles[:, ::-1])  # simetrico
    assert np.array_equal(pixeles[:, 0], pixeles[:, -1])  # empalma al envolver


def test_los_estilos_se_distinguen_de_verdad():
    """Si dos estilos dieran lo mismo, tener dos no serviria de nada."""
    campos = {n: np.asarray(ornament_field(TAMANO, n)) for n in STYLES}
    nombres = list(campos)
    for i, uno in enumerate(nombres):
        for otro in nombres[i + 1 :]:
            diferencia = np.abs(campos[uno] - campos[otro].astype(int)).mean()
            assert diferencia > 5, f"{uno} y {otro} salen casi iguales"


def test_el_acanto_es_el_mas_recargado():
    """El horror vacui es el estilo, no un exceso del estilo."""
    densidad = {n: ink_fraction(ornament_field(TAMANO, n)) for n in STYLES}
    assert densidad["acanthus"] == max(densidad.values())


def test_ningun_filamento_baja_del_ancho_imprimible():
    """El suelo de grosor existe porque un trazo subpixel no sale fino.

    Sale gris, o sea grosor intermedio, y en la pieza eso es una superficie
    lisa en vez de un filamento. Si el suelo dejara de aplicarse, el campo se
    llenaria de grises intermedios en lugar de negro y fondo.
    """
    campo = np.asarray(ornament_field((900, 300), "blackmetal"), dtype=int)
    medios = ((campo > TINTA + 40) & (campo < FONDO - 40)).mean()
    assert medios < 0.16, f"{medios:.0%} de la banda en grises intermedios"


def test_la_curvatura_de_un_circulo_es_uno_partido_por_el_radio():
    """El limite de ancho por curvatura depende de que esto este bien."""
    radio = 40.0
    angulo = np.linspace(0, 1.6 * np.pi, 300)
    circulo = np.column_stack([radio * np.cos(angulo), radio * np.sin(angulo)])
    # Se descartan los extremos, donde np.gradient usa diferencias laterales.
    interior = _curvatura(circulo)[5:-5]
    assert interior == pytest.approx(1.0 / radio, rel=0.02)


def test_el_lado_concavo_nunca_pasa_del_radio_de_curvatura():
    """La invariante que evita que el contorno se pliegue sobre si mismo."""
    espina = _curva((200, 200), 0.0, 300.0, giro=5.0, pasos=120)
    ancho = np.full(120, 90.0)  # mucho mayor que el radio de curvatura
    izquierda, derecha = limitar_por_curvatura(espina, ancho, ancho)

    radio = 1.0 / np.abs(_curvatura(espina))
    gira_a_izquierda = _curvatura(espina) > 0
    assert np.all(izquierda[gira_a_izquierda] < radio[gira_a_izquierda])
    assert np.all(derecha[~gira_a_izquierda] < radio[~gira_a_izquierda])
    # Y el lado convexo se queda como estaba: ahi ensanchar no rompe nada.
    assert np.all(derecha[gira_a_izquierda] == 90.0)


def test_una_recta_no_recorta_nada():
    recta = _curva((0, 0), 0.0, 100.0, giro=0.0, pasos=50)
    ancho = np.full(50, 30.0)
    izquierda, derecha = limitar_por_curvatura(recta, ancho, ancho)
    assert izquierda == pytest.approx(30.0)
    assert derecha == pytest.approx(30.0)


def test_la_hoja_de_pruebas_lleva_todos_los_estilos():
    hoja = contact_sheet(Image.new("L", (100, 100), 128), size=(300, 100))
    assert hoja.width == 300
    assert hoja.height > 100 * len(STYLES)


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
