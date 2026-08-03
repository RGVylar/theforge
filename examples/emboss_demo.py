"""Ejemplo de forge emboss: graba una foto sobre un STL que no hemos generado
con lito.py, para probar el caso de uso real (importar un producto y
estamparle la foto encima).

    python examples/emboss_demo.py

Genera un "adorno" en forma de huevo (una esfera deformada, no un producto de
theforge) como si fuera un STL descargado de otro sitio, y le graba un
medallon con una foto sintetica. El mismo STL de origen se puede reemplazar
por cualquier otro:

    python -m theforge emboss examples/out/huevo_demo.stl mi_foto.jpg -o salida.stl
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from theforge.emboss import EmbossParams, emboss_mesh  # noqa: E402
from theforge.stl import check_mesh, closed_shell, write_binary_stl  # noqa: E402

SALIDA = Path(__file__).parent / "out"


def huevo_hueco(radio_mm: float = 45.0, achatado: float = 0.72, grosor_mm: float = 1.6,
                nu: int = 200, nv: int = 100) -> np.ndarray:
    """Cascara hueca con forma de huevo: una esfera estirada en Z.

    Nada de esto sale de lito.py -es geometria escrita a mano, a proposito,
    para probar emboss.py con una forma que theforge no sabe generar por su
    cuenta-. La condicion que emboss.py exige (cascara hueca de pared fina)
    esta garantizada aqui porque la construyo yo mismo con esa intencion.
    """
    lat = np.linspace(-np.pi / 2 + 0.02, np.pi / 2 - 0.02, nv)  # evita el polo exacto
    lon = np.linspace(0, 2 * np.pi, nu, endpoint=False)
    lat, lon = np.meshgrid(lat, lon, indexing="ij")

    def superficie(radio):
        x = radio * np.cos(lat) * np.sin(lon)
        y = -radio * np.cos(lat) * np.cos(lon)
        z = radio * achatado * np.sin(lat) * (1.15 - 0.15 * np.sin(lat))  # mas puntiagudo arriba
        return np.stack([x, y, z], axis=-1)

    exterior = superficie(radio_mm)
    interior = superficie(radio_mm - grosor_mm)
    malla = closed_shell(exterior, interior, wrap_u=True, cap_ends=(True, True))
    # Con los dos polos casi cerrados (0.02 rad de margen) los dos extremos
    # son bolsillos ciegos genuinos, no dos cascaras separadas: hay geometria
    # de sobra en ambos anillos para que closed_shell los tape bien.
    return malla


def foto_de_prueba(lado: int = 500) -> Image.Image:
    y, x = np.mgrid[0:lado, 0:lado]
    d = np.hypot(x - lado / 2, y - lado * 0.55)
    img = Image.fromarray(
        (255 * (1 - np.clip(d / (0.6 * lado), 0, 1))).astype(np.uint8), "L"
    )
    dibujo = ImageDraw.Draw(img)
    dibujo.ellipse([lado * 0.32, lado * 0.20, lado * 0.68, lado * 0.60], fill=230)
    dibujo.rectangle([lado * 0.20, lado * 0.68, lado * 0.80, lado * 0.95], fill=50)
    return img


def main() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    foto_de_prueba().save(SALIDA / "foto_emboss_demo.png")

    origen = huevo_hueco()
    informe_origen = check_mesh(origen)
    print(f"origen    {len(origen)} triangulos, {informe_origen}")
    if not informe_origen.watertight:
        raise SystemExit("el huevo de partida no es cerrado, revisa huevo_hueco()")
    ruta_origen = write_binary_stl(SALIDA / "huevo_demo.stl", origen, header="theforge demo: huevo")

    params = EmbossParams(min_bump=0.0, max_bump=1.1, height_deg=55, feather_deg=8)
    malla = emboss_mesh(origen, foto_de_prueba(), params)
    informe = check_mesh(malla)
    ruta_salida = write_binary_stl(SALIDA / "huevo_grabado.stl", malla, header="theforge emboss demo")

    print(f"origen    {ruta_origen}")
    print(f"grabado   {ruta_salida} ({ruta_salida.stat().st_size / 1e6:.1f} MB)")
    print(f"chequeo   {informe}")
    if not informe.watertight:
        raise SystemExit("la malla grabada no es cerrada")


if __name__ == "__main__":
    main()
