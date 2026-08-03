"""Litofania sobre un STL cualquiera: graba una foto en relieve sobre la
superficie de una malla que ya existe, en vez de generar la forma desde cero.

Esto NO reemplaza a lito.py. Es la via para "elige el producto que quieras":
importa un jarron, una funda, un adorno... cualquier STL ya diseñado, y se le
estampa la imagen encima como un mapa de relieve aditivo.

La condicion fisica que no se puede evitar con software: para que funcione
como litofania de verdad, el STL que se importe tiene que ser ya una cascara
hueca de pared fina. Grabar relieve en la superficie de un solido macizo no
sirve de nada -la luz no atraviesa un bloque de PLA, por mucho relieve que
tenga por fuera-. Esta herramienta no lo comprueba (no hay forma barata de
saber si un STL es hueco solo mirandolo), asi que es responsabilidad de quien
lo usa.

Tampoco hay forma de anadir detalle que el STL de origen no tenga: el relieve
sale tan fino como la propia malla este teselada. Un STL de baja resolucion
(pocos triangulos) da un relieve tosco, pase lo que pase con la imagen.

Como funciona:

    1. Se indexa la malla (vertices unicos + caras) con to_indexed_mesh.
    2. Cada vertice se proyecta esfericamente alrededor del centroide de la
       malla: la misma convencion de latitud/longitud que ya usa lito.py para
       la esfera (Z arriba, longitud 0 mirando hacia -Y), pero aplicada a
       vertices sueltos en vez de a una rejilla regular.
    3. Se calcula la normal de cada vertice (media de las normales de las
       caras que lo tocan, ponderada por area) y se desplaza el vertice a lo
       largo de su propia normal, hacia fuera, por una cantidad que sale del
       gris de la imagen en ese punto (oscuro = mas bulto, por defecto).
    4. Se reconstruye la malla en formato soup con las mismas caras.

Al ser puramente un desplazamiento por vertice sin tocar la conectividad, la
malla resultante es cerrada si la original lo era -salvo que el bulto sea tan
grande que la superficie se pliegue sobre si misma en una zona concava o muy
fina; eso no se detecta aqui, hay que revisar el resultado (check_mesh no
sabe ver auto-intersecciones, solo aristas y orientacion).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from theforge.lito import load_grayscale
from theforge.stl import read_binary_stl, to_indexed_mesh, triangle_normals


@dataclass
class EmbossParams:
    """Parametros del grabado. Los bultos en milimetros, los angulos en grados.

    La imagen no envuelve la esfera entera (eso solo tiene sentido para un
    patron repetible, como en ornament.py): se coloca como un medallon
    centrado en (center_lat_deg, center_lon_deg), del tamano que marca
    height_deg, e igual que el resto del repo longitud 0 mira hacia -Y. Fuera
    del medallon la superficie se queda a min_bump (a ras, sin tocar), con un
    desvanecido de feather_deg para que el borde no sea un escalon visible.
    """

    min_bump: float = 0.0  # a ras, fuera del medallon y en sus zonas claras
    max_bump: float = 1.2  # las zonas oscuras del medallon sobresalen esto
    gamma: float = 1.0
    invert: bool = False  # por defecto oscuro = mas bulto
    center_lat_deg: float = 0.0
    center_lon_deg: float = 0.0
    height_deg: float = 60.0  # cuanto ocupa el medallon en latitud
    feather_deg: float = 6.0  # desvanecido en el borde, dentro de height_deg

    def validate(self) -> None:
        if not 0 <= self.min_bump < self.max_bump:
            raise ValueError("se requiere 0 <= min_bump < max_bump")
        if self.gamma <= 0:
            raise ValueError("gamma debe ser > 0")
        if not 0 < self.height_deg <= 180:
            raise ValueError("height_deg debe estar en (0, 180]")
        if not 0 <= self.feather_deg < self.height_deg / 2:
            raise ValueError("feather_deg debe ser menor que la mitad de height_deg")


def vertex_normals(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Normal de cada vertice: media de las normales de sus caras, ponderada
    por area (una cara grande pesa mas que una diminuta en la esquina)."""
    tris = vertices[faces]
    normales_cara = triangle_normals(tris)
    areas = np.linalg.norm(
        np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1
    )

    acumulado = np.zeros_like(vertices)
    peso = (normales_cara * areas[:, None])
    for i in range(3):
        np.add.at(acumulado, faces[:, i], peso)

    longitud = np.linalg.norm(acumulado, axis=1)
    normal = np.zeros_like(acumulado)
    validos = longitud > 0
    normal[validos] = acumulado[validos] / longitud[validos, None]
    return normal


def spherical_uv(vertices: np.ndarray, center: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Latitud y longitud (rad) de cada vertice, proyectadas desde `center`.

    Misma convencion que _sphere_points en lito.py: Z arriba, longitud 0
    mirando hacia -Y, sentido horario visto desde arriba. Un vertice que
    coincida exactamente con el centro no tiene direccion definida y sale con
    latitud 0, longitud 0 (un caso raro, pero no debe romper el calculo).
    """
    centro = np.asarray(center, dtype=float) if center is not None else vertices.mean(axis=0)
    direccion = vertices - centro
    radio = np.linalg.norm(direccion, axis=1)
    radio_seguro = np.where(radio > 0, radio, 1.0)
    x, y, z = (direccion / radio_seguro[:, None]).T

    lat = np.arcsin(np.clip(z, -1.0, 1.0))
    lon = np.arctan2(x, -y)
    return lat, lon


def _sample_bilinear(imagen: np.ndarray, filas: np.ndarray, columnas: np.ndarray) -> np.ndarray:
    """Muestra `imagen` (H, W) en coordenadas (fila, columna) fraccionarias.

    Envuelve en columnas (longitud, 2*pi periodica) y recorta en filas (los
    polos no envuelven, se quedan en el borde).
    """
    alto, ancho = imagen.shape
    f0 = np.clip(np.floor(filas).astype(int), 0, alto - 1)
    f1 = np.clip(f0 + 1, 0, alto - 1)
    c0 = np.floor(columnas).astype(int) % ancho
    c1 = (c0 + 1) % ancho

    tf = np.clip(filas - f0, 0.0, 1.0)
    tc = columnas - np.floor(columnas)

    arriba = imagen[f0, c0] * (1 - tc) + imagen[f0, c1] * tc
    abajo = imagen[f1, c0] * (1 - tc) + imagen[f1, c1] * tc
    return arriba * (1 - tf) + abajo * tf


def _smoothstep(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def sample_image(image: Image.Image, filas: np.ndarray, columnas: np.ndarray) -> np.ndarray:
    """Gris (0-1) de `image` en coordenadas (fila, columna) en [0, 1]."""
    gris = np.asarray(image.convert("L"), dtype=float) / 255.0
    alto, ancho = gris.shape
    return _sample_bilinear(gris, filas * (alto - 1), columnas * (ancho - 1))


def emboss_mesh(
    tris: np.ndarray,
    image: Image.Image,
    params: EmbossParams,
    center: np.ndarray | None = None,
) -> np.ndarray:
    """Graba `image` como un medallon en relieve sobre `tris` (n, 3, 3) y
    devuelve la malla desplazada, en el mismo formato soup.

    Fuera del medallon la superficie no se toca (bulto = min_bump): es lo que
    hace que se pueda estampar una foto suelta sobre cualquier forma sin que
    se estire dando la vuelta entera, que era el problema real de mapear la
    imagen a la esfera completa.
    """
    params.validate()
    vertices, faces = to_indexed_mesh(tris)
    normales = vertex_normals(vertices, faces)
    lat, lon = spherical_uv(vertices, center=center)

    ancho_deg = params.height_deg * image.width / image.height
    center_lat = math.radians(params.center_lat_deg)
    center_lon = math.radians(params.center_lon_deg)
    dlat_deg = np.degrees(lat - center_lat)
    dlon = ((lon - center_lon + math.pi) % (2 * math.pi)) - math.pi
    dlon_deg = np.degrees(dlon) * max(math.cos(center_lat), 1e-6)

    fila = 0.5 - dlat_deg / params.height_deg
    columna = 0.5 + dlon_deg / ancho_deg

    dentro = (fila >= 0) & (fila <= 1) & (columna >= 0) & (columna <= 1)
    margen_deg = np.minimum(
        np.minimum(dlat_deg + params.height_deg / 2, params.height_deg / 2 - dlat_deg),
        np.minimum(dlon_deg + ancho_deg / 2, ancho_deg / 2 - dlon_deg),
    )
    intensidad = np.where(dentro, _smoothstep(margen_deg / max(params.feather_deg, 1e-9)), 0.0)

    gris = np.zeros(len(vertices))
    if np.any(dentro):
        gris[dentro] = sample_image(image, fila[dentro], columna[dentro])
    if params.gamma != 1.0:
        gris = gris**params.gamma
    if not params.invert:
        gris = 1.0 - gris  # oscuro (gris bajo) = bulto alto, por defecto

    relieve = params.min_bump + gris * (params.max_bump - params.min_bump)
    bulto = params.min_bump + intensidad * (relieve - params.min_bump)
    desplazados = vertices + normales * bulto[:, None]
    return desplazados[faces]


def emboss_stl(
    stl_path: str | Path,
    image_path: str | Path,
    params: EmbossParams,
) -> np.ndarray:
    """Atajo de fichero a fichero: lee el STL y la imagen, devuelve la malla."""
    tris = read_binary_stl(stl_path)
    imagen = load_grayscale(image_path)
    return emboss_mesh(tris, imagen, params)
