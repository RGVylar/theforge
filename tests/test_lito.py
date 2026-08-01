from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from theforge.cli import main
from theforge.lito import LitoParams, lithophane, surfaces, thickness_map
from theforge.stl import check_mesh, read_binary_stl

SAMPLES = 40  # suficiente para probar la topologia sin tardar


def uniform(valor: int, size=(32, 24)) -> Image.Image:
    return Image.new("L", size, valor)


@pytest.mark.parametrize(
    "params",
    [
        pytest.param(LitoParams(samples=SAMPLES), id="plana"),
        pytest.param(
            LitoParams(samples=SAMPLES, frame_mm=6.0), id="plana-con-marco"
        ),
        pytest.param(
            LitoParams(samples=SAMPLES, curve="cylindrical", arc_degrees=120),
            id="arco-120",
        ),
        pytest.param(
            LitoParams(samples=SAMPLES, curve="cylindrical", arc_degrees=360),
            id="cilindro-cerrado",
        ),
        pytest.param(
            LitoParams(samples=SAMPLES, curve="cylindrical", arc_degrees=360, frame_mm=5),
            id="cilindro-cerrado-con-marco",
        ),
    ],
)
def test_la_malla_es_cerrada(gradient, params):
    """Cada arista compartida por exactamente dos triangulos y bien orientada."""
    informe = check_mesh(lithophane(gradient, params))
    assert informe.watertight, informe
    assert informe.volume_mm3 > 0  # normales hacia fuera


def test_el_damero_tambien_cierra(checker):
    """Bordes duros: el peor caso para el remuestreo."""
    informe = check_mesh(lithophane(checker, LitoParams(samples=SAMPLES)))
    assert informe.watertight, informe


def test_oscuro_es_grueso_y_claro_es_fino():
    params = LitoParams(samples=SAMPLES, min_thickness=0.8, max_thickness=3.0)
    negro = thickness_map(uniform(0), params)
    blanco = thickness_map(uniform(255), params)
    assert negro == pytest.approx(3.0)
    assert blanco == pytest.approx(0.8)


def test_invert_da_la_vuelta_al_mapa():
    params = LitoParams(samples=SAMPLES, invert=True)
    assert thickness_map(uniform(0), params) == pytest.approx(params.min_thickness)


def test_el_grosor_decrece_con_el_brillo(gradient):
    """En el degradado el gris crece con x, asi que el grosor debe decrecer."""
    espesor = thickness_map(gradient, LitoParams(samples=SAMPLES))
    assert np.all(np.diff(espesor, axis=1) <= 1e-9)


def test_el_marco_llega_al_grosor_maximo(gradient):
    params = LitoParams(samples=SAMPLES, frame_mm=8.0)
    espesor = thickness_map(gradient, params)
    esquinas = espesor[[0, 0, -1, -1], [0, -1, 0, -1]]
    assert esquinas == pytest.approx(params.max_thickness)
    assert espesor[espesor.shape[0] // 2, espesor.shape[1] // 2] < params.max_thickness


def test_dimensiones_de_la_pieza_plana(gradient):
    params = LitoParams(width_mm=80.0, samples=SAMPLES)
    malla = lithophane(gradient, params)
    minimo = malla.reshape(-1, 3).min(axis=0)
    maximo = malla.reshape(-1, 3).max(axis=0)
    alto = params.height_mm(gradient)

    assert maximo[0] - minimo[0] == pytest.approx(80.0)  # ancho en X
    assert (minimo[2], maximo[2]) == pytest.approx((0.0, alto))  # apoyada en Z=0
    # El grosor crece hacia -Y, con la cara trasera en el plano Y=0.
    assert maximo[1] == pytest.approx(0.0)
    assert -params.max_thickness <= minimo[1] <= -params.min_thickness

    # Con una imagen negra entera el grosor si es exactamente el maximo.
    negra = lithophane(uniform(0), params)
    assert negra.reshape(-1, 3)[:, 1].min() == pytest.approx(-params.max_thickness)


def cuadrante_negro() -> Image.Image:
    """Blanco con el cuadrante superior izquierdo negro (marca asimetrica)."""
    pixeles = np.full((40, 40), 255, dtype=np.uint8)
    pixeles[:20, :20] = 0
    return Image.fromarray(pixeles, mode="L")


@pytest.mark.parametrize(
    "params",
    [
        pytest.param(LitoParams(samples=SAMPLES), id="plana"),
        pytest.param(
            LitoParams(samples=SAMPLES, curve="cylindrical", arc_degrees=120), id="arco"
        ),
    ],
)
def test_la_imagen_no_sale_espejada_ni_del_reves(params):
    """La marca de la imagen debe caer arriba a la izquierda mirando la pieza.

    Se mira desde fuera (desde -Y), asi que la izquierda del observador es -X.
    """
    imagen = cuadrante_negro()
    espesor = thickness_map(imagen, params)
    front, _ = surfaces(espesor, params, params.height_mm(imagen))

    grueso = espesor > (params.min_thickness + params.max_thickness) / 2
    centro = front[grueso].mean(axis=0)
    assert centro[0] < 0  # izquierda
    assert centro[2] > params.height_mm(imagen) / 2  # arriba


def test_el_cilindro_cerrado_tiene_el_perimetro_pedido(gradient):
    params = LitoParams(width_mm=120.0, samples=SAMPLES, curve="cylindrical", arc_degrees=360)
    assert params.radius_mm == pytest.approx(120.0 / (2 * np.pi))

    _, back = surfaces(thickness_map(gradient, params), params, params.height_mm(gradient))
    radios = np.linalg.norm(back[..., :2], axis=-1)
    assert radios == pytest.approx(params.radius_mm)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"width_mm": 0},
        {"min_thickness": 3.0, "max_thickness": 1.0},
        {"curve": "esferica"},
        {"curve": "cylindrical", "arc_degrees": 400},
        {"samples": 1},
        {"frame_mm": 60.0},  # no cabe en 100 mm de ancho
        {"gamma": 0},
    ],
)
def test_parametros_invalidos(kwargs):
    with pytest.raises(ValueError):
        LitoParams(**kwargs).validate()


def test_cli_genera_un_stl_cerrado(tmp_path, gradient):
    entrada = tmp_path / "prueba.png"
    salida = tmp_path / "prueba.stl"
    gradient.save(entrada)

    codigo = main(
        [
            "lito",
            str(entrada),
            "-o",
            str(salida),
            "--width",
            "60",
            "--samples",
            str(SAMPLES),
            "--frame",
            "4",
        ]
    )

    assert codigo == 0
    assert check_mesh(read_binary_stl(salida)).watertight


def test_cli_error_si_la_imagen_no_existe(tmp_path):
    assert main(["lito", str(tmp_path / "no_existe.png")]) == 2
