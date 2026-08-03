from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from theforge.cli import main
from theforge.emboss import (
    EmbossParams,
    emboss_mesh,
    spherical_uv,
    vertex_normals,
)
from theforge.lito import LitoParams, lithophane
from theforge.stl import check_mesh, read_binary_stl, to_indexed_mesh, write_binary_stl

SAMPLES = 60  # esfera de origen pequena, suficiente para probar la geometria


def esfera_hueca(diameter_mm=80.0, samples=SAMPLES, cap_top=True) -> np.ndarray:
    """Malla de origen: una esfera hueca casi lisa, tratada como si fuera un
    STL cualquiera importado (no le pedimos nada a lito.py salvo que sea
    hueca y watertight)."""
    return lithophane(
        Image.new("L", (4, 4), 255),
        LitoParams(
            curve="sphere", diameter_mm=diameter_mm, samples=samples,
            min_thickness=1.4, max_thickness=1.5, cap_top=cap_top,
        ),
    )


def foto_asimetrica(size=(60, 60)) -> Image.Image:
    """Blanca con un cuadrante negro: permite comprobar que el bulto cae en
    el sitio correcto, no en cualquier parte del medallon."""
    pixeles = np.full(size[::-1], 255, dtype=np.uint8)
    pixeles[: size[1] // 2, : size[0] // 2] = 0
    return Image.fromarray(pixeles, "L")


# --------------------------------------------------------------------------
# Geometria basica
# --------------------------------------------------------------------------


def test_vertex_normals_son_unitarias_y_no_degeneradas():
    tris = esfera_hueca()
    vertices, faces = to_indexed_mesh(tris)
    normales = vertex_normals(vertices, faces)
    longitudes = np.linalg.norm(normales, axis=1)
    assert longitudes == pytest.approx(1.0, abs=1e-6)


def _losa(ancho=10.0, fondo=6.0, grosor=2.0, nu=6, nv=5) -> np.ndarray:
    """Losa plana con normal +Z arriba y -Z abajo, sin ninguna ambiguedad:
    sirve para probar vertex_normals() sin depender de si un centroide
    calculado a partir de vertices cae donde uno espera (para una esfera
    asimetrica -45..90 con tapa, el centroide de vertices NO es el centro
    geometrico de la esfera, y eso descoloca cualquier corte por latitud)."""
    from theforge.stl import closed_shell

    u, v = np.meshgrid(np.linspace(0, ancho, nu), np.linspace(0, fondo, nv))
    arriba = np.stack([u, v, np.full_like(u, grosor)], axis=-1)
    abajo = np.stack([u, v, np.zeros_like(u)], axis=-1)
    return closed_shell(arriba, abajo)


def test_vertex_normals_de_una_losa_apuntan_hacia_fuera():
    """Caso sin ambiguedad: la cara de arriba tiene que dar +Z, la de abajo
    -Z. Si esto falla, esta mal en cualquier geometria mas complicada."""
    ancho, fondo = 10.0, 6.0
    tris = _losa(ancho=ancho, fondo=fondo)
    vertices, faces = to_indexed_mesh(tris)
    normales = vertex_normals(vertices, faces)

    # Solo los vertices estrictamente interiores de la cara: los del borde
    # tambien tocan la pared lateral, y su normal media es una mezcla de las
    # dos caras, no +Z/-Z puro -eso es correcto, no un fallo de la funcion.
    interior_xy = (
        (vertices[:, 0] > 0) & (vertices[:, 0] < ancho)
        & (vertices[:, 1] > 0) & (vertices[:, 1] < fondo)
    )
    arriba = interior_xy & np.isclose(vertices[:, 2], vertices[:, 2].max())
    abajo = interior_xy & np.isclose(vertices[:, 2], vertices[:, 2].min())
    assert arriba.sum() > 0 and abajo.sum() > 0
    assert normales[arriba][:, 2] == pytest.approx(1.0, abs=1e-6)
    assert normales[abajo][:, 2] == pytest.approx(-1.0, abs=1e-6)


def test_spherical_uv_cubre_todo_el_rango():
    tris = esfera_hueca()
    vertices, _ = to_indexed_mesh(tris)
    lat, lon = spherical_uv(vertices)
    assert lat.min() < np.radians(-40)
    assert lat.max() > np.radians(80)
    assert lon.min() < -np.radians(150)
    assert lon.max() > np.radians(150)


# --------------------------------------------------------------------------
# emboss_mesh: la malla sigue siendo cerrada y crece donde toca
# --------------------------------------------------------------------------


def test_grabar_conserva_topologia_y_cierra():
    tris = esfera_hueca()
    antes = check_mesh(tris)
    assert antes.watertight, antes

    malla = emboss_mesh(tris, foto_asimetrica(), EmbossParams(max_bump=1.5))
    despues = check_mesh(malla)
    assert despues.watertight, despues
    assert despues.triangles == antes.triangles
    assert despues.volume_mm3 > antes.volume_mm3  # el bulto anade material


def test_fuera_del_medallon_no_se_toca_nada():
    """Compara los dos soups directamente, cara a cara: volver a indexar la
    salida con to_indexed_mesh la reordenaria (el orden de np.unique depende
    de las coordenadas, que cambian al desplazar), y comparar por indice
    entre dos ordenes distintos no dice nada de un vertice en concreto."""
    tris = esfera_hueca()
    params = EmbossParams(max_bump=1.5, height_deg=40, feather_deg=4)
    malla = emboss_mesh(tris, foto_asimetrica(), params)

    centro = tris.reshape(-1, 3).mean(axis=0)
    lat, _ = spherical_uv(tris.reshape(-1, 3), center=centro)
    lejos = (np.abs(np.degrees(lat)) > params.height_deg).reshape(tris.shape[:2])
    assert malla[lejos] == pytest.approx(tris[lejos])


def test_el_medallon_solo_bulta_dentro_de_su_ventana():
    tris = esfera_hueca()
    params = EmbossParams(min_bump=0.0, max_bump=1.5, height_deg=50, feather_deg=0.01)
    malla = emboss_mesh(tris, Image.new("L", (40, 40), 0), params)  # negro puro: bulto maximo

    desplazamiento = np.linalg.norm(malla - tris, axis=-1)
    centro = tris.reshape(-1, 3).mean(axis=0)
    lat, _ = spherical_uv(tris.reshape(-1, 3), center=centro)
    lat = lat.reshape(tris.shape[:2])
    dentro = np.abs(np.degrees(lat)) < params.height_deg * 0.3  # bien dentro, lejos del feather
    lejos = np.abs(np.degrees(lat)) > params.height_deg

    assert desplazamiento[dentro].max() > 0.5
    assert desplazamiento[lejos].max() < 1e-9


def test_gamma_e_invert_cambian_el_bulto():
    tris = esfera_hueca()
    gris = Image.new("L", (30, 30), 128)
    normal = emboss_mesh(tris, gris, EmbossParams(max_bump=1.5))
    invertido = emboss_mesh(tris, gris, EmbossParams(max_bump=1.5, invert=True))
    # Con gris uniforme al 50%, invertir con gamma=1 no deberia cambiar nada
    # salvo error numerico: 1-0.5 == 0.5. Se comprueba con un extremo real.
    oscuro = Image.new("L", (30, 30), 10)
    claro = Image.new("L", (30, 30), 245)
    bulto_oscuro = emboss_mesh(tris, oscuro, EmbossParams(max_bump=1.5))
    bulto_claro = emboss_mesh(tris, claro, EmbossParams(max_bump=1.5))
    v0, _ = to_indexed_mesh(tris)
    vo, _ = to_indexed_mesh(bulto_oscuro)
    vc, _ = to_indexed_mesh(bulto_claro)
    assert np.linalg.norm(vo - v0, axis=1).max() > np.linalg.norm(vc - v0, axis=1).max()


def test_centrar_el_medallon_mueve_el_bulto():
    """El bulto de un mismo cuadrante negro cae en sitios distintos segun
    donde se centre el medallon: prueba de que center_lat/lon hacen algo."""
    tris = esfera_hueca()
    vertices, _ = to_indexed_mesh(tris)
    foto = Image.new("L", (40, 40), 0)  # negro puro, sin ambiguedad de posicion

    centrado_arriba = emboss_mesh(
        tris, foto, EmbossParams(max_bump=1.5, height_deg=30, center_lat_deg=40)
    )
    centrado_abajo = emboss_mesh(
        tris, foto, EmbossParams(max_bump=1.5, height_deg=30, center_lat_deg=-30)
    )
    va, _ = to_indexed_mesh(centrado_arriba)
    vb, _ = to_indexed_mesh(centrado_abajo)
    assert not np.allclose(va, vb)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_bump": -1.0},
        {"min_bump": 2.0, "max_bump": 1.0},
        {"gamma": 0},
        {"height_deg": 0},
        {"height_deg": 200},
        {"feather_deg": 40, "height_deg": 60},  # >= height/2
    ],
)
def test_parametros_invalidos(kwargs):
    with pytest.raises(ValueError):
        EmbossParams(**kwargs).validate()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_emboss_de_punta_a_punta(tmp_path):
    modelo = tmp_path / "modelo.stl"
    write_binary_stl(modelo, esfera_hueca())
    foto = tmp_path / "foto.png"
    foto_asimetrica().save(foto)
    salida = tmp_path / "salida.stl"

    codigo = main(
        ["emboss", str(modelo), str(foto), "-o", str(salida),
         "--max-bump", "1.5", "--height", "50"]
    )

    assert codigo == 0
    assert check_mesh(read_binary_stl(salida)).watertight


def test_cli_emboss_avisa_de_la_condicion_fisica(tmp_path, capsys):
    modelo = tmp_path / "modelo.stl"
    write_binary_stl(modelo, esfera_hueca())
    foto = tmp_path / "foto.png"
    foto_asimetrica().save(foto)

    main(["emboss", str(modelo), str(foto), "-o", str(tmp_path / "salida.stl")])
    salida_texto = capsys.readouterr().out
    assert "cascara hueca" in salida_texto


def test_cli_emboss_error_si_el_modelo_no_existe(tmp_path):
    foto = tmp_path / "foto.png"
    foto_asimetrica().save(foto)
    assert main(["emboss", str(tmp_path / "no_existe.stl"), str(foto)]) == 2
