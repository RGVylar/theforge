"""CLI de theforge. Subcomandos: forge lito ..."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from theforge import __version__
from theforge.lito import CYLINDRICAL, FLAT, LitoParams, lithophane, load_grayscale
from theforge.stl import check_mesh, write_binary_stl

# Densidad tipica del PLA; solo para dar una idea del material, no es una
# estimacion de coste (eso llegara con coste.py).
DENSIDAD_PLA = 1.24  # g/cm3


def _add_lito_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "lito",
        help="genera una litofania en STL a partir de una imagen",
        description="Imagen -> mapa de grosores invertido -> STL binario cerrado.",
    )
    p.add_argument("image", type=Path, help="imagen de entrada (png, jpg, ...)")
    p.add_argument(
        "-o", "--output", type=Path, help="STL de salida (por defecto, junto a la imagen)"
    )
    p.add_argument("--width", type=float, default=100.0, help="ancho en mm (100)")
    p.add_argument(
        "--min-thickness", type=float, default=0.8, help="grosor de las zonas claras (0.8)"
    )
    p.add_argument(
        "--max-thickness", type=float, default=3.0, help="grosor de las zonas oscuras (3.0)"
    )
    p.add_argument(
        "--curve", choices=(FLAT, CYLINDRICAL), default=FLAT, help="forma de la pieza (flat)"
    )
    p.add_argument(
        "--arc",
        type=float,
        default=180.0,
        help="grados de arco si es cilindrica; 360 cierra el cilindro (180)",
    )
    p.add_argument(
        "--samples", type=int, default=300, help="muestras a lo ancho de la imagen (300)"
    )
    p.add_argument("--frame", type=float, default=0.0, help="marco macizo en mm (0)")
    p.add_argument("--gamma", type=float, default=1.0, help="correccion de gamma (1.0)")
    p.add_argument(
        "--invert", action="store_true", help="invierte el mapa: claro = grueso"
    )
    p.add_argument(
        "--no-check",
        action="store_true",
        help="no comprobar que la malla es cerrada (mas rapido en mallas enormes)",
    )
    p.set_defaults(func=cmd_lito)


def cmd_lito(args: argparse.Namespace) -> int:
    params = LitoParams(
        width_mm=args.width,
        min_thickness=args.min_thickness,
        max_thickness=args.max_thickness,
        curve=args.curve,
        arc_degrees=args.arc,
        samples=args.samples,
        frame_mm=args.frame,
        gamma=args.gamma,
        invert=args.invert,
    )
    params.validate()

    salida = args.output or args.image.with_suffix(".stl")
    imagen = load_grayscale(args.image)
    alto = params.height_mm(imagen)

    inicio = time.perf_counter()
    malla = lithophane(imagen, params)
    write_binary_stl(salida, malla, header=f"theforge lito {args.image.name}")
    tardanza = time.perf_counter() - inicio

    print(f"imagen    {args.image} ({imagen.width}x{imagen.height} px)")
    if params.curve == CYLINDRICAL:
        cerrado = " (cilindro cerrado)" if params.closed_cylinder else ""
        print(
            f"forma     cilindrica, arco {params.arc_degrees:g} grados, "
            f"radio interior {params.radius_mm:.1f} mm{cerrado}"
        )
    else:
        print("forma     plana")
    print(
        f"pieza     {params.width_mm:g} x {alto:.1f} mm, "
        f"grosor {params.min_thickness:g}-{params.max_thickness:g} mm"
    )
    print(f"malla     {len(malla)} triangulos en {tardanza:.1f} s")

    if not args.no_check:
        informe = check_mesh(malla)
        gramos = informe.volume_mm3 / 1000.0 * DENSIDAD_PLA
        print(f"chequeo   {informe}")
        print(f"material  ~{gramos:.1f} g de PLA al 100% de relleno")
        if not informe.watertight:
            print("ERROR: la malla no es cerrada, no la imprimas", file=sys.stderr)
            return 1

    print(f"salida    {salida}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forge", description="Herramientas de impresion 3D."
    )
    parser.add_argument("--version", action="version", version=f"theforge {__version__}")
    sub = parser.add_subparsers(dest="comando", required=True)
    _add_lito_parser(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
