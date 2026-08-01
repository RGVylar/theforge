from __future__ import annotations

import numpy as np
import pytest

from theforge.stl import (
    STL_TRIANGLE,
    check_mesh,
    closed_shell,
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
