"""Escritura de STL binario y utilidades de malla.

Convenio unico en todo el repo: una malla es un array float de forma
(n, 3, 3) -> n triangulos, 3 vertices por triangulo, 3 coordenadas (x, y, z)
en milimetros. Los vertices van en orden antihorario visto desde fuera del
solido, de modo que el volumen con signo sale positivo.

Las superficies parametricas se representan como rejillas de vertices de forma
(nv, nu, 3): el indice v recorre una direccion del parametro y el indice u la
otra. La normal que se considera "hacia fuera" es du x dv.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Un registro de STL binario: normal (3f) + 3 vertices (9f) + attr (uint16).
# numpy empaqueta los dtypes estructurados sin relleno, asi que itemsize == 50,
# que es justo lo que exige el formato.
STL_TRIANGLE = np.dtype(
    [("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attr", "<u2")]
)
assert STL_TRIANGLE.itemsize == 50


# --------------------------------------------------------------------------
# Construccion de geometria
# --------------------------------------------------------------------------


def grid_surface(verts: np.ndarray, wrap_u: bool = False, flip: bool = False) -> np.ndarray:
    """Trianguliza una rejilla (nv, nu, 3) en dos triangulos por celda.

    wrap_u une la ultima columna con la primera (superficie cerrada en u).
    flip invierte el orden de los vertices, es decir, la normal.
    """
    verts = np.asarray(verts, dtype=float)
    nv, nu = verts.shape[:2]
    if nv < 2 or nu < 2:
        raise ValueError(f"rejilla demasiado pequena: {nv}x{nu}")

    i0 = np.arange(nu if wrap_u else nu - 1)
    i1 = (i0 + 1) % nu
    j0 = np.arange(nv - 1)
    j1 = j0 + 1

    a = verts[np.ix_(j0, i0)]
    b = verts[np.ix_(j0, i1)]
    c = verts[np.ix_(j1, i1)]
    d = verts[np.ix_(j1, i0)]

    lower = np.stack([a, b, c], axis=-2)
    upper = np.stack([a, c, d], axis=-2)
    tris = np.concatenate([lower.reshape(-1, 3, 3), upper.reshape(-1, 3, 3)])
    return tris[:, ::-1] if flip else tris


def _stitch_loops(front: np.ndarray, back: np.ndarray) -> np.ndarray:
    """Cose dos anillos de vertices (n, 3) recorridos en el mismo orden.

    El anillo debe recorrer el borde del dominio en sentido antihorario en el
    espacio de parametros; con ese convenio las normales salen hacia fuera.
    """
    f0 = front
    f1 = np.roll(front, -1, axis=0)
    b0 = back
    b1 = np.roll(back, -1, axis=0)
    tri1 = np.stack([f0, b0, b1], axis=-2)
    tri2 = np.stack([f0, b1, f1], axis=-2)
    return np.concatenate([tri1, tri2])


def _boundary_indices(nv: int, nu: int) -> tuple[np.ndarray, np.ndarray]:
    """Indices (j, i) del borde de la rejilla en sentido antihorario."""
    bottom_i = np.arange(nu - 1)
    right_j = np.arange(nv - 1)
    top_i = np.arange(nu - 1, 0, -1)
    left_j = np.arange(nv - 1, 0, -1)
    j = np.concatenate(
        [np.zeros(nu - 1, int), right_j, np.full(nu - 1, nv - 1), left_j]
    )
    i = np.concatenate(
        [bottom_i, np.full(nv - 1, nu - 1), top_i, np.zeros(nv - 1, int)]
    )
    return j, i


def closed_shell(front: np.ndarray, back: np.ndarray, wrap_u: bool = False) -> np.ndarray:
    """Solido cerrado entre dos rejillas con la misma topologia.

    front es la cara "hacia fuera" (normal du x dv), back la opuesta. Los bordes
    libres se cierran con paredes laterales.
    """
    front = np.asarray(front, dtype=float)
    back = np.asarray(back, dtype=float)
    if front.shape != back.shape:
        raise ValueError(f"rejillas incompatibles: {front.shape} vs {back.shape}")
    nv, nu = front.shape[:2]

    parts = [
        grid_surface(front, wrap_u=wrap_u),
        grid_surface(back, wrap_u=wrap_u, flip=True),
    ]

    if wrap_u:
        # Solo hay borde arriba y abajo; cada uno es un anillo cerrado.
        parts.append(_stitch_loops(front[0], back[0]))
        parts.append(_stitch_loops(front[-1, ::-1], back[-1, ::-1]))
    else:
        j, i = _boundary_indices(nv, nu)
        parts.append(_stitch_loops(front[j, i], back[j, i]))

    return np.concatenate(parts)


# --------------------------------------------------------------------------
# Comprobaciones de malla
# --------------------------------------------------------------------------


@dataclass
class MeshReport:
    triangles: int
    vertices: int
    edges: int
    open_edges: int  # aristas no compartidas por exactamente 2 triangulos
    flipped_edges: int  # compartidas por 2 triangulos pero con la misma direccion
    degenerate: int  # triangulos de area nula
    volume_mm3: float

    @property
    def watertight(self) -> bool:
        return self.open_edges == 0 and self.flipped_edges == 0 and self.degenerate == 0

    def __str__(self) -> str:
        estado = "cerrada" if self.watertight else "ABIERTA"
        return (
            f"malla {estado}: {self.triangles} triangulos, {self.vertices} vertices, "
            f"{self.edges} aristas, {self.open_edges} abiertas, "
            f"{self.flipped_edges} mal orientadas, {self.degenerate} degeneradas, "
            f"volumen {self.volume_mm3 / 1000.0:.2f} cm3"
        )


def weld_vertices(tris: np.ndarray, tol: float = 1e-6) -> np.ndarray:
    """Indices de vertice por triangulo (n, 3) fusionando puntos a distancia tol."""
    pts = np.asarray(tris, dtype=float).reshape(-1, 3)
    keys = np.round(pts / tol).astype(np.int64)
    _, inverse = np.unique(keys, axis=0, return_inverse=True)
    return inverse.reshape(-1, 3)


def mesh_volume(tris: np.ndarray) -> float:
    """Volumen con signo (mm3). Positivo si las normales apuntan hacia fuera."""
    tris = np.asarray(tris, dtype=float)
    v0, v1, v2 = tris[:, 0], tris[:, 1], tris[:, 2]
    return float(np.einsum("ij,ij->i", v0, np.cross(v1, v2)).sum() / 6.0)


def triangle_normals(tris: np.ndarray) -> np.ndarray:
    """Normales unitarias; los triangulos degenerados salen como (0, 0, 0)."""
    tris = np.asarray(tris, dtype=float)
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    length = np.linalg.norm(n, axis=1)
    nonzero = length > 0
    n[nonzero] /= length[nonzero, None]
    n[~nonzero] = 0.0
    return n


def check_mesh(tris: np.ndarray, tol: float = 1e-6) -> MeshReport:
    """Comprueba que la malla es un solido cerrado y orientado de forma coherente.

    Cada arista debe aparecer en exactamente dos triangulos y recorrida en
    direcciones opuestas.
    """
    tris = np.asarray(tris, dtype=float)
    faces = weld_vertices(tris, tol=tol)

    areas = np.linalg.norm(
        np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1
    )
    degenerate = int(np.count_nonzero(areas <= 0))

    directed = np.concatenate(
        [faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], axis=0
    )
    undirected = np.sort(directed, axis=1)
    _, inverse, counts = np.unique(
        undirected, axis=0, return_inverse=True, return_counts=True
    )
    inverse = inverse.reshape(-1)

    # Con orientacion coherente, las dos apariciones de una arista van en
    # sentidos opuestos y sus signos se cancelan.
    sign = np.where(directed[:, 0] < directed[:, 1], 1, -1)
    balance = np.zeros(len(counts), dtype=np.int64)
    np.add.at(balance, inverse, sign)

    return MeshReport(
        triangles=len(tris),
        vertices=int(faces.max()) + 1 if len(faces) else 0,
        edges=len(counts),
        open_edges=int(np.count_nonzero(counts != 2)),
        flipped_edges=int(np.count_nonzero((counts == 2) & (balance != 0))),
        degenerate=degenerate,
        volume_mm3=mesh_volume(tris),
    )


# --------------------------------------------------------------------------
# Entrada/salida
# --------------------------------------------------------------------------


def write_binary_stl(path: str | Path, tris: np.ndarray, header: str = "theforge") -> Path:
    """Escribe la malla como STL binario y devuelve la ruta."""
    tris = np.asarray(tris, dtype=np.float32)
    if tris.ndim != 3 or tris.shape[1:] != (3, 3):
        raise ValueError(f"se esperaba (n, 3, 3), se recibio {tris.shape}")

    records = np.zeros(len(tris), dtype=STL_TRIANGLE)
    records["vertices"] = tris
    records["normal"] = triangle_normals(tris)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        # La cabecera no puede empezar por "solid": algunos lectores lo tomarian
        # por un STL ASCII.
        fh.write(header.encode("ascii", "replace")[:80].ljust(80, b" "))
        fh.write(struct.pack("<I", len(records)))
        fh.write(records.tobytes())
    return path


def read_binary_stl(path: str | Path) -> np.ndarray:
    """Lee un STL binario y devuelve la malla (n, 3, 3) en float64."""
    data = Path(path).read_bytes()
    (count,) = struct.unpack("<I", data[80:84])
    expected = 84 + count * STL_TRIANGLE.itemsize
    if len(data) != expected:
        raise ValueError(f"tamano inesperado: {len(data)} bytes, se esperaban {expected}")
    records = np.frombuffer(data, dtype=STL_TRIANGLE, count=count, offset=84)
    return records["vertices"].astype(float)
