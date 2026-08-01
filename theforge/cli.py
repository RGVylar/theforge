"""CLI de theforge. Subcomandos: forge lito ..."""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

from theforge import __version__
from theforge.lito import (
    CURVES,
    CYLINDRICAL,
    SPHERE,
    LitoParams,
    lithophane,
    load_grayscale,
)
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
    p.add_argument("--curve", choices=CURVES, default=CURVES[0], help="forma de la pieza (flat)")
    p.add_argument(
        "--arc",
        type=float,
        default=180.0,
        help="grados de arco si es cilindrica; 360 cierra el cilindro (180)",
    )
    p.add_argument(
        "--diameter", type=float, default=100.0, help="diametro de la esfera en mm (100)"
    )
    p.add_argument(
        "--lat-min",
        type=float,
        default=-45.0,
        help="latitud del corte inferior de la esfera; -45 es el limite sin soportes (-45)",
    )
    p.add_argument(
        "--lat-max",
        type=float,
        default=75.0,
        help="latitud del corte superior de la esfera (75)",
    )
    p.add_argument(
        "--repeat", type=int, default=1, help="copias de la imagen alrededor de la pieza (1)"
    )
    p.add_argument(
        "--samples", type=int, default=300, help="muestras a lo ancho de la pieza (300)"
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


def _describe_shape(params: LitoParams) -> None:
    """Resumen de la forma, con los numeros que hacen falta para imprimirla."""
    if params.curve == CYLINDRICAL:
        cerrado = " (cerrado, sin costura)" if params.wraps_u else ""
        print(
            f"forma     cilindrica, arco {params.arc_degrees:g} grados, "
            f"radio interior {params.radius_mm:.1f} mm{cerrado}"
        )
    elif params.curve == SPHERE:
        radio = params.radius_mm
        boca = 2 * radio * math.cos(math.radians(params.lat_min_deg))
        respiradero = 2 * radio * math.cos(math.radians(params.lat_max_deg))
        print(
            f"forma     esfera de {params.diameter_mm:g} mm, "
            f"latitudes {params.lat_min_deg:g} a {params.lat_max_deg:g} grados"
        )
        print(
            f"bocas     abajo {boca:.1f} mm de diametro, arriba {respiradero:.1f} mm"
        )
        # En una esfera la pendiente de la pared es dr/dz = -tan(latitud), asi
        # que el voladizo respecto a la vertical coincide con la latitud.
        voladizo = abs(params.lat_min_deg)
        aviso = "" if voladizo <= 45 else "  <-- por encima de 45, necesita soportes"
        print(f"voladizo  {voladizo:g} grados en el arranque{aviso}")
        if params.frame_mm <= 0:
            # El borde exterior esta a radio R+grosor, y el grosor lo pone la
            # imagen: sin marco el corte queda ondulado y la pieza no asienta.
            print(
                "AVISO: sin --frame el borde de apoyo queda ondulado y la esfera "
                "bailara sobre unos pocos puntos"
            )
    else:
        print("forma     plana")


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
        repeat=args.repeat,
        diameter_mm=args.diameter,
        lat_min_deg=args.lat_min,
        lat_max_deg=args.lat_max,
    )
    params.validate()

    salida = args.output or args.image.with_suffix(".stl")
    imagen = load_grayscale(args.image)
    ancho, alto = params.surface_size(imagen)

    inicio = time.perf_counter()
    malla = lithophane(imagen, params)
    write_binary_stl(salida, malla, header=f"theforge lito {args.image.name}")
    tardanza = time.perf_counter() - inicio

    print(f"imagen    {args.image} ({imagen.width}x{imagen.height} px)")
    _describe_shape(params)
    reparto = f" x{params.repeat}" if params.repeat > 1 else ""
    print(
        f"pieza     {ancho:.1f} x {alto:.1f} mm de superficie{reparto}, "
        f"grosor {params.min_thickness:g}-{params.max_thickness:g} mm"
    )
    estirado = params.stretch(imagen)
    if not 0.87 < estirado < 1.15:
        consejo = "" if params.wraps_u else " o recorta la imagen"
        print(
            f"AVISO: la imagen se deforma x{estirado:.2f} en horizontal; "
            f"ajusta --repeat{consejo}"
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
