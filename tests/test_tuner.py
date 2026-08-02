"""Tests de la parte del ajustador que no necesita ventana.

La GUI en si no se testea: no compensa. Lo que si se testea es lo que puede
romperse en silencio -que los sliders salgan de los campos del dataclass y que
el fragmento que copia al portapapeles vuelva a ser el mismo Style- porque de
eso depende que la ventana no se desincronice del codigo.
"""

from __future__ import annotations

import dataclasses

import pytest

from theforge.ornament import STYLES, Style, single_piece
from theforge.tuner import IGNORADOS, formatear_style, parametros


@pytest.mark.parametrize("nombre", tuple(STYLES))
def test_todos_los_estilos_producen_sliders(nombre):
    param = parametros(STYLES[nombre])
    assert len(param) > 8
    for p in param:
        assert p.minimo <= p.valor <= p.maximo, p
        assert p.minimo < p.maximo


def test_los_sliders_salen_del_dataclass_y_no_de_una_lista():
    """Un campo numerico nuevo en Style tiene que aparecer sin tocar el tuner."""
    numericos = {
        c.name
        for c in dataclasses.fields(Style)
        if c.type in ("int", "float") and c.name not in IGNORADOS
    }
    assert {p.nombre for p in parametros(STYLES["acanthus"])} == numericos


def test_no_hay_sliders_para_lo_que_no_es_un_numero():
    nombres = {p.nombre for p in parametros(STYLES["acanthus"])}
    assert "nombre" not in nombres
    assert "forma" not in nombres
    assert "ramos" not in nombres


@pytest.mark.parametrize("nombre", tuple(STYLES))
def test_el_fragmento_copiado_reconstruye_el_mismo_estilo(nombre):
    original = STYLES[nombre]
    reconstruido = eval(formatear_style(original), {"Style": Style})
    assert reconstruido == original


def test_el_fragmento_omite_lo_que_no_cambia():
    """Si escribiera los treinta campos siempre, no serviria para pegarlo."""
    tocado = dataclasses.replace(STYLES["acanthus"], rizo=2.9)
    texto = formatear_style(tocado)
    assert "rizo=2.9" in texto
    assert "semillas" not in texto  # acanthus lo deja por defecto


def test_el_fragmento_admite_renombrar():
    texto = formatear_style(STYLES["acanthus"], nombre="mi_acanto")
    assert 'nombre="mi_acanto"' in texto
    assert eval(texto, {"Style": Style}).nombre == "mi_acanto"


@pytest.mark.parametrize("nombre", tuple(STYLES))
def test_la_pieza_suelta_dibuja_algo(nombre):
    """Cada forma tiene que saber dibujarse aislada, que es la vista util."""
    import numpy as np

    pieza = np.asarray(single_piece((240, 120), nombre), dtype=int)
    assert pieza.shape == (120, 240)
    assert pieza.min() < 60  # hay tinta
    assert pieza.max() > 180  # y queda fondo
