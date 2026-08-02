"""Ejemplo del flujo de composicion: proyecto JSON -> STL.

    python examples/compose_demo.py

Genera una foto sintetica, escribe el proyecto en examples/out/ y construye
la lampara. El mismo JSON se puede regenerar luego con:

    python -m theforge compose examples/out/proyecto_demo.json
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from theforge.compose import Composition, PhotoLayer, build_mesh, save_project  # noqa: E402
from theforge.lito import LitoParams  # noqa: E402
from theforge.stl import check_mesh, write_binary_stl  # noqa: E402

SALIDA = Path(__file__).parent / "out"


def retrato_de_prueba(lado: int = 600) -> Image.Image:
    """Un 'retrato' sintetico: viñeta radial con unas formas reconocibles."""
    y, x = np.mgrid[0:lado, 0:lado]
    d = np.hypot(x - lado / 2, y - lado / 2)
    img = Image.fromarray(
        (255 * (1 - np.clip(d / (0.7 * lado), 0, 1))).astype(np.uint8), "L"
    )
    dibujo = ImageDraw.Draw(img)
    dibujo.ellipse([lado * 0.30, lado * 0.18, lado * 0.70, lado * 0.62], fill=225)
    dibujo.rectangle([lado * 0.22, lado * 0.66, lado * 0.78, lado * 0.94], fill=60)
    return img


def main() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    retrato_de_prueba().save(SALIDA / "retrato_demo.png")

    proyecto = Composition(
        params=LitoParams(
            curve="sphere", diameter_mm=120, samples=720,
            min_thickness=0.7, max_thickness=3.0, frame_mm=6,
        ),
        pattern="acanthus",
        layers=[
            # El medallon principal, centrado.
            PhotoLayer(path="retrato_demo.png", cx=0.5, cy=0.5, scale=0.8),
            # Y otro pequeno en la cara opuesta (cruza la costura: cx=0).
            PhotoLayer(path="retrato_demo.png", cx=0.0, cy=0.42, scale=0.35),
        ],
        base_dir=SALIDA,
    )

    ruta_json = save_project(proyecto, SALIDA / "proyecto_demo.json")
    malla = build_mesh(proyecto)
    informe = check_mesh(malla)
    ruta_stl = write_binary_stl(SALIDA / "proyecto_demo.stl", malla, header="theforge compose demo")

    print(f"proyecto  {ruta_json}")
    print(f"chequeo   {informe}")
    print(f"salida    {ruta_stl} ({ruta_stl.stat().st_size / 1e6:.1f} MB)")
    if not informe.watertight:
        raise SystemExit("la malla no es cerrada")


if __name__ == "__main__":
    main()
