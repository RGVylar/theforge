"""theforge: herramientas de impresion 3D.

Nucleo compartido:
    stl   -- escritura/lectura de STL binario y utilidades de malla
    lito  -- generador de litofanias
"""

from theforge.lito import LitoParams, lithophane, thickness_map
from theforge.stl import (
    MeshReport,
    check_mesh,
    closed_shell,
    grid_surface,
    mesh_volume,
    read_binary_stl,
    write_binary_stl,
)

__version__ = "0.1.0"

__all__ = [
    "LitoParams",
    "MeshReport",
    "check_mesh",
    "closed_shell",
    "grid_surface",
    "lithophane",
    "mesh_volume",
    "read_binary_stl",
    "thickness_map",
    "write_binary_stl",
]
