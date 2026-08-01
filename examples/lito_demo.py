"""Ejemplo ejecutable: dos litofanias a partir de una imagen sintetica.

    python examples/lito_demo.py

Deja los STL en examples/out/ (ignorado por git) y comprueba que las mallas
son cerradas antes de darlas por buenas.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

# Para poder ejecutar el ejemplo sin instalar el paquete.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from theforge.lito import LitoParams, lithophane  # noqa: E402
from theforge.stl import check_mesh, write_binary_stl  # noqa: E402

SALIDA = Path(__file__).parent / "out"


def imagen_de_prueba(width: int = 800, height: int = 600) -> Image.Image:
    """Degradado radial con unas figuras encima, para ver tonos y bordes duros."""
    y, x = np.mgrid[0:height, 0:width]
    distancia = np.hypot(x - width / 2, y - height / 2)
    fondo = 255 * (1.0 - np.clip(distancia / (0.55 * width), 0.0, 1.0))
    img = Image.fromarray(fondo.astype(np.uint8), mode="L")

    dibujo = ImageDraw.Draw(img)
    dibujo.ellipse([width * 0.30, height * 0.20, width * 0.70, height * 0.60], fill=235)
    dibujo.rectangle([width * 0.10, height * 0.72, width * 0.90, height * 0.80], fill=20)
    for i in range(8):
        x0 = width * (0.12 + i * 0.10)
        dibujo.rectangle([x0, height * 0.84, x0 + width * 0.05, height * 0.92], fill=i * 32)
    return img


def generar(nombre: str, imagen: Image.Image, params: LitoParams) -> None:
    malla = lithophane(imagen, params)
    informe = check_mesh(malla)
    ruta = write_binary_stl(SALIDA / f"{nombre}.stl", malla, header=f"theforge {nombre}")
    print(f"{nombre:<12} {informe}")
    print(f"{'':<12} -> {ruta} ({ruta.stat().st_size / 1e6:.1f} MB)")
    if not informe.watertight:
        raise SystemExit(f"{nombre}: la malla no es cerrada")


def main() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    imagen = imagen_de_prueba()
    imagen.save(SALIDA / "fuente.png")

    # Placa de sobremesa: 100 mm de ancho, marco de 3 mm.
    generar(
        "lito_plana",
        imagen,
        LitoParams(width_mm=100, min_thickness=0.8, max_thickness=3.0, frame_mm=3.0),
    )

    # Media luna para poner delante de una tira LED.
    generar(
        "lito_arco",
        imagen,
        LitoParams(width_mm=120, curve="cylindrical", arc_degrees=140, samples=400),
    )

    # Pantalla de lampara: cilindro completo, sin costura.
    generar(
        "lito_cilindro",
        imagen,
        LitoParams(width_mm=180, curve="cylindrical", arc_degrees=360, samples=400),
    )

    # Lampara esferica: la imagen repetida 3 veces, que con la banda de latitud
    # por defecto la deja sin deformar. El marco hace que el borde de apoyo salga
    # plano en vez de ondulado.
    generar(
        "lito_esfera",
        imagen,
        LitoParams(curve="sphere", diameter_mm=120, repeat=3, samples=480, frame_mm=6),
    )


if __name__ == "__main__":
    main()
