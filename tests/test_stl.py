from __future__ import annotations

import numpy as np
import pytest

from theforge.stl import (
    STL_TRIANGLE,
    check_mesh,
    closed_shell,
    disc_cap,
    grid_surface,
    mesh_volume,
    read_binary_stl,
    triangle_normals,
    write_binary_stl,
)


def slab(width=10.0, depth=6.0, thickness=2.0, nu=4, nv=3):
    """Losa maciza construida como dos rejillas planas cosidas."""
    u, v = np.meshgrid(np.linspace(0, width, nu), np.linspace(0, depth, nv))
    front = np.stack([u, v, np.full_like(u, thickness)], axis=-1)
    back = np.stack([u, v, np.zeros_like(u)], axis=-1)
    return closed_shell(front, back)


def tube(radio=4.0, espesor=1.0, alto=10.0, nu=12, nv=3):
    """Tubo: rejilla cerrada en u, abierta arriba y abajo."""
    theta = np.linspace(0, 2 * np.pi, nu, endpoint=False)
    z = np.linspace(0, alto, nv)
    theta, z = np.meshgrid(theta, z)
    fuera, dentro = radio + espesor, radio
    front = np.stack([fuera * np.sin(theta), -fuera * np.cos(theta), z], axis=-1)
    back = np.stack([dentro * np.sin(theta), -dentro * np.cos(theta), z], axis=-1)
    return closed_shell(front, back, wrap_u=True)


def test_grid_surface_cuenta_triangulos():
    verts = np.zeros((4, 5, 3))
    assert len(grid_surface(verts)) == 2 * 3 * 4
    assert len(grid_surface(verts, wrap_u=True)) == 2 * 3 * 5


def test_grid_surface_flip_invierte_la_normal():
    u, v = np.meshgrid(np.linspace(0, 1, 2), np.linspace(0, 1, 2))
    verts = np.stack([u, v, np.zeros_like(u)], axis=-1)
    normal = triangle_normals(grid_surface(verts))[0]
    normal_flip = triangle_normals(grid_surface(verts, flip=True))[0]
    assert normal == pytest.approx([0, 0, 1])
    assert normal_flip == pytest.approx([0, 0, -1])


def test_losa_es_cerrada_y_tiene_el_volumen_correcto():
    malla = slab()
    informe = check_mesh(malla)
    assert informe.watertight, informe
    assert informe.open_edges == 0
    assert informe.volume_mm3 == pytest.approx(10.0 * 6.0 * 2.0)


def test_tubo_cerrado_en_u_es_cerrado():
    malla = tube()
    informe = check_mesh(malla)
    assert informe.watertight, informe
    # Prisma de 12 lados: algo menos que el anillo circular ideal.
    ideal = np.pi * (5.0**2 - 4.0**2) * 10.0
    assert 0 < informe.volume_mm3 < ideal


def test_disc_cap_cierra_un_anillo_circular_plano():
    theta = np.linspace(0, 2 * np.pi, 20, endpoint=False)
    anillo = np.stack([3 * np.cos(theta), 3 * np.sin(theta), np.zeros_like(theta)], axis=-1)
    tapa = disc_cap(anillo)
    assert len(tapa) == 20
    # Area de un circulo de radio 3, aunque sea un poligono de 20 lados.
    areas = np.linalg.norm(
        np.cross(tapa[:, 1] - tapa[:, 0], tapa[:, 2] - tapa[:, 0]), axis=1
    ) / 2
    assert areas.sum() == pytest.approx(np.pi * 3**2, rel=0.02)


def test_disc_cap_flip_invierte_la_normal():
    theta = np.linspace(0, 2 * np.pi, 20, endpoint=False)
    anillo = np.stack([np.cos(theta), np.sin(theta), np.zeros_like(theta)], axis=-1)
    normal = triangle_normals(disc_cap(anillo))[0]
    normal_flip = triangle_normals(disc_cap(anillo, flip=True))[0]
    assert normal[2] == pytest.approx(-normal_flip[2])


def test_cap_ends_solo_vale_con_wrap_u():
    front = back = np.zeros((3, 4, 3))
    with pytest.raises(ValueError, match="wrap_u|cerradas en u"):
        closed_shell(front, back, wrap_u=False, cap_ends=(True, False))


def esfera_hueca(samples=40, lat_min_deg=-45.0, lat_max_deg=75.0):
    """Front/back de una esfera de verdad: el grosor separa front y back en Z
    en los extremos, que es justo lo que hace falta para que capar cada
    extremo por separado tenga sentido (ver limite documentado en
    closed_shell para el caso degenerado en que coinciden)."""
    from PIL import Image

    from theforge.lito import LitoParams, layout, surfaces, thickness_map

    img = Image.new("L", (64, 64), 128)
    params = LitoParams(
        curve="sphere", diameter_mm=120, samples=samples,
        min_thickness=0.8, max_thickness=3.0,
        lat_min_deg=lat_min_deg, lat_max_deg=lat_max_deg,
    )
    lay = layout(img, params)
    espesor = thickness_map(img, params, lay)
    return surfaces(espesor, params, lay)


def test_un_extremo_capado_es_bolsillo_ciego_no_tunel():
    """Sin capar, ambos extremos abiertos dan una rosquilla: ya esta cerrada
    (0 aristas abiertas) pero con un agujero pasante -caracteristica de Euler
    0, genero 1-. Capar un extremo la convierte en un bolsillo ciego -Euler 2,
    genero 0-, accesible solo por el otro extremo. Euler y no el volumen,
    porque el volumen no distingue estos dos casos si front y back coinciden
    en Z en el extremo capado (ver limite documentado en closed_shell)."""
    front, back = esfera_hueca()

    sin_capar = closed_shell(front, back, wrap_u=True)
    informe_sin_capar = check_mesh(sin_capar)
    assert informe_sin_capar.watertight, informe_sin_capar
    euler_sin_capar = (
        informe_sin_capar.vertices - informe_sin_capar.edges + informe_sin_capar.triangles
    )
    assert euler_sin_capar == 0  # rosquilla: tunel de un extremo al otro

    capado_arriba = closed_shell(front, back, wrap_u=True, cap_ends=(False, True))
    informe = check_mesh(capado_arriba)
    assert informe.watertight, informe
    euler = informe.vertices - informe.edges + informe.triangles
    assert euler == 2  # bolsillo ciego: ya no hay tunel

    # Capar los DOS extremos no da una bola hueca cerrada: sin ningun punto
    # donde front y back se toquen, salen dos solidos SEPARADOS (la cascara
    # exterior sellada por su cuenta, la interior por la suya) - cada uno
    # genero 0 por separado, y Euler los suma: 2+2=4. Watertight por pieza,
    # pero imprimible como un disparate (una pieza flotando sin conexion
    # dentro de la otra). Por eso el generador nunca ofrece capar los dos.
    capado_los_dos = closed_shell(front, back, wrap_u=True, cap_ends=(True, True))
    informe_dos = check_mesh(capado_los_dos)
    assert informe_dos.watertight, informe_dos
    euler_dos = informe_dos.vertices - informe_dos.edges + informe_dos.triangles
    assert euler_dos == 4


def test_check_mesh_detecta_agujeros():
    informe = check_mesh(slab()[:-1])
    assert not informe.watertight
    assert informe.open_edges == 3


def test_check_mesh_detecta_triangulos_mal_orientados():
    malla = slab()
    malla[0] = malla[0][::-1]
    informe = check_mesh(malla)
    assert not informe.watertight
    assert informe.open_edges == 0
    assert informe.flipped_edges == 3


def test_volumen_negativo_si_la_malla_esta_del_reves():
    malla = slab()[:, ::-1]
    assert mesh_volume(malla) < 0


def test_ida_y_vuelta_de_stl_binario(tmp_path):
    malla = slab()
    ruta = write_binary_stl(tmp_path / "losa.stl", malla)
    assert ruta.stat().st_size == 84 + len(malla) * STL_TRIANGLE.itemsize
    assert not ruta.read_bytes()[:5] == b"solid"  # no debe parecer un STL ASCII
    leida = read_binary_stl(ruta)
    assert leida.shape == malla.shape
    assert leida == pytest.approx(malla, abs=1e-5)
