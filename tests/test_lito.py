from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from theforge.cli import main
from theforge.lito import (
    LitoParams,
    horizontal_scale,
    layout,
    lithophane,
    surfaces,
    thickness_map,
)
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
        pytest.param(LitoParams(samples=SAMPLES, curve="sphere"), id="esfera"),
        pytest.param(
            LitoParams(samples=SAMPLES, curve="sphere", repeat=3), id="esfera-x3"
        ),
        pytest.param(
            LitoParams(samples=SAMPLES, curve="sphere", frame_mm=5), id="esfera-con-marco"
        ),
        pytest.param(
            LitoParams(samples=SAMPLES, curve="sphere", lat_min_deg=-80, lat_max_deg=85),
            id="esfera-casi-completa",
        ),
        pytest.param(
            LitoParams(samples=SAMPLES, curve="sphere", fit="conformal", repeat=2),
            id="esfera-conforme",
        ),
        pytest.param(
            LitoParams(
                samples=SAMPLES, curve="sphere", fit="conformal", repeat=2, frame_mm=6
            ),
            id="esfera-conforme-con-marco",
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
    alto = layout(gradient, params).height_mm

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
    lay = layout(imagen, params)
    espesor = thickness_map(imagen, params, lay)
    front, _ = surfaces(espesor, params, lay)

    grueso = espesor > (params.min_thickness + params.max_thickness) / 2
    centro = front[grueso].mean(axis=0)
    assert centro[0] < 0  # izquierda
    assert centro[2] > front[..., 2].max() / 2  # arriba


def test_el_cilindro_cerrado_tiene_el_perimetro_pedido(gradient):
    params = LitoParams(width_mm=120.0, samples=SAMPLES, curve="cylindrical", arc_degrees=360)
    assert params.radius_mm == pytest.approx(120.0 / (2 * np.pi))

    lay = layout(gradient, params)
    _, back = surfaces(thickness_map(gradient, params, lay), params, lay)
    radios = np.linalg.norm(back[..., :2], axis=-1)
    assert radios == pytest.approx(params.radius_mm)


def test_la_esfera_apoya_en_z0_y_deja_las_dos_bocas(gradient):
    params = LitoParams(
        samples=SAMPLES, curve="sphere", diameter_mm=100, lat_min_deg=-45, lat_max_deg=75
    )
    malla = lithophane(gradient, params)
    puntos = malla.reshape(-1, 3)
    radio = params.radius_mm

    assert puntos[:, 2].min() == pytest.approx(0.0)  # apoyada en la cama

    # La boca de abajo mide 2*R*cos(lat) en la cara interior. Se mide sobre los
    # vertices que estan a la altura del corte, no sobre el maximo de la pieza.
    en_el_suelo = puntos[puntos[:, 2] < puntos[:, 2].min() + 1e-6]
    assert len(en_el_suelo) > 0
    esperado = radio * np.cos(np.radians(params.lat_min_deg))
    assert np.linalg.norm(en_el_suelo[:, :2], axis=1).max() == pytest.approx(
        esperado + params.max_thickness * np.cos(np.radians(params.lat_min_deg)), rel=0.05
    )

    # Y arriba queda otro agujero: ningun vertice llega al eje.
    arriba = puntos[puntos[:, 2] > puntos[:, 2].max() - 1e-6]
    assert np.linalg.norm(arriba[:, :2], axis=1).min() > 1.0


def test_la_esfera_con_stretch_solo_es_fiel_en_el_ecuador():
    """La escala horizontal vale cos(latitud): la banda por defecto llega al 26%."""
    cuadrada = Image.new("L", (640, 640))
    params = LitoParams(curve="sphere", diameter_mm=100, repeat=3, fit="stretch")
    lay = layout(cuadrada, params)

    # Un tercio del ecuador mide lo mismo que la banda: fiel en el ecuador.
    assert lay.width_mm / 3 == pytest.approx(lay.height_mm, rel=0.01)

    minimo, maximo = horizontal_scale(lay, params)
    assert maximo == pytest.approx(1.0, rel=0.01)  # el ecuador esta dentro de la banda
    assert minimo == pytest.approx(np.cos(np.radians(75.0)), rel=0.02)


def test_la_deformacion_tiene_en_cuenta_la_proporcion_de_la_imagen():
    """Una banda 3:1 con repeat=1 llena la esfera igual que una cuadrada con 3."""
    params = LitoParams(curve="sphere", diameter_mm=120, repeat=1)
    lay = layout(Image.new("L", (3600, 1200)), params)
    minimo, maximo = horizontal_scale(lay, params)
    assert maximo == pytest.approx(1.0, rel=0.01)  # fiel en el ecuador
    assert minimo == pytest.approx(np.cos(np.radians(75.0)), rel=0.02)


def test_el_mapeo_conforme_no_deforma_en_ninguna_latitud():
    cuadrada = Image.new("L", (640, 640))
    params = LitoParams(curve="sphere", diameter_mm=120, repeat=2, fit="conformal")
    lay = layout(cuadrada, params)

    assert horizontal_scale(lay, params) == (1.0, 1.0)

    # El corte superior lo deriva de la imagen, no de lat_max_deg.
    lat_min, lat_max = lay.lat_degrees
    assert lat_min == pytest.approx(-45.0)
    assert lat_max == pytest.approx(78.1, abs=0.2)

    # Y la comprobacion de fondo: en cada fila, el paso vertical entre latitudes
    # debe seguir al horizontal, que se encoge con cos(lat).
    paso = np.diff(lay.lat)
    cos_medio = np.cos((lay.lat[:-1] + lay.lat[1:]) / 2)
    assert paso / cos_medio == pytest.approx((paso / cos_medio)[0], rel=0.01)


def test_conformal_con_imagen_apaisada_abre_menos_banda():
    """Una imagen 2:1 ocupa la mitad de banda de Mercator que una cuadrada."""
    params = LitoParams(curve="sphere", repeat=2, fit="conformal")
    alta = layout(Image.new("L", (640, 640)), params).lat_degrees[1]
    ancha = layout(Image.new("L", (1280, 640)), params).lat_degrees[1]
    assert ancha < alta


def test_el_marco_que_no_cabe_falla_en_la_esfera(gradient):
    params = LitoParams(samples=SAMPLES, curve="sphere", frame_mm=80.0)
    with pytest.raises(ValueError, match="no cabe"):
        thickness_map(gradient, params)


def test_repeat_tesela_la_imagen(gradient):
    """Cada copia del mapa de grosores debe ser identica a la siguiente."""
    params = LitoParams(samples=60, curve="sphere", repeat=3)
    espesor = thickness_map(gradient, params)
    copias = np.split(espesor, 3, axis=1)
    assert copias[0] == pytest.approx(copias[1])
    assert copias[1] == pytest.approx(copias[2])


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
        {"repeat": 0},
        {"curve": "sphere", "diameter_mm": 0},
        {"curve": "sphere", "lat_min_deg": 40, "lat_max_deg": 10},  # invertidas
        {"curve": "sphere", "lat_min_deg": -95},  # fuera del rango
        {"fit": "mercator"},  # no existe
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
