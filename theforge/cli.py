"""CLI de theforge. Subcomandos: forge lito ..."""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

from theforge import __version__
from theforge.lito import (
    CONFORMAL,
    CURVES,
    CYLINDRICAL,
    FITS,
    SPHERE,
    Layout,
    LitoParams,
    horizontal_scale,
    layout,
    lithophane,
    load_grayscale,
)
from theforge.ornament import (
    POR_DEFECTO,
    STYLES,
    contact_sheet,
    ink_fraction,
    sphere_band,
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
        help="latitud del corte superior de la esfera; ignorado con --fit conformal (75)",
    )
    p.add_argument(
        "--fit",
        choices=FITS,
        default=FITS[0],
        help="reparto de la imagen sobre la esfera: stretch reparte las latitudes "
        "por igual, conformal las espacia para que las formas no se deformen (stretch)",
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


def _describe_shape(params: LitoParams, lay: Layout) -> None:
    """Resumen de la forma, con los numeros que hacen falta para imprimirla."""
    if params.curve == CYLINDRICAL:
        cerrado = " (cerrado, sin costura)" if params.wraps_u else ""
        print(
            f"forma     cilindrica, arco {params.arc_degrees:g} grados, "
            f"radio interior {params.radius_mm:.1f} mm{cerrado}"
        )
        return
    if params.curve != SPHERE:
        print("forma     plana")
        return

    radio = params.radius_mm
    lat_min, lat_max = lay.lat_degrees
    derivada = " (derivada de la imagen)" if params.fit == CONFORMAL else ""
    print(
        f"forma     esfera de {params.diameter_mm:g} mm, latitudes "
        f"{lat_min:.1f} a {lat_max:.1f} grados{derivada}"
    )
    boca = 2 * radio * math.cos(math.radians(lat_min))
    respiradero = 2 * radio * math.cos(math.radians(lat_max))
    print(f"bocas     abajo {boca:.1f} mm de diametro, arriba {respiradero:.1f} mm")

    # En una esfera la pendiente de la pared es dr/dz = -tan(latitud), asi que
    # el voladizo respecto a la vertical coincide con la latitud.
    voladizo = abs(lat_min)
    aviso = "" if voladizo <= 45 else "  <-- por encima de 45, necesita soportes"
    print(f"voladizo  {voladizo:.1f} grados en el arranque{aviso}")
    if lat_max > 80:
        print(
            f"AVISO: el corte superior queda a {lat_max:.1f} grados; por encima de 80 "
            "la pared es casi horizontal y tendria que puentear al aire"
        )
    if params.frame_mm <= 0:
        # El borde exterior esta a radio R+grosor, y el grosor lo pone la
        # imagen: sin marco el corte queda ondulado y la pieza no asienta.
        print(
            "AVISO: sin --frame el borde de apoyo queda ondulado y la esfera "
            "bailara sobre unos pocos puntos"
        )


def _describe_fit(params: LitoParams, lay: Layout) -> None:
    """Cuanto se deforma la imagen al mapearla sobre la superficie."""
    minimo, maximo = horizontal_scale(lay, params)
    if params.curve == SPHERE and params.fit == CONFORMAL:
        print("reparto   conforme: las formas no se deforman en ninguna latitud")
        return
    if abs(maximo - minimo) > 0.01:
        # Solo pasa en la esfera con fit=stretch, donde la escala va con cos(lat).
        print(
            f"reparto   la imagen queda entre el {minimo * 100:.0f}% y el "
            f"{maximo * 100:.0f}% de su ancho segun la latitud; "
            "con --fit conformal no se deforma"
        )
        return
    if not 0.87 < minimo < 1.15:
        consejo = "ajusta --repeat" if params.wraps_u else "recorta la imagen"
        print(f"AVISO: la imagen se deforma x{minimo:.2f} en horizontal; {consejo}")


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
        fit=args.fit,
    )
    params.validate()

    salida = args.output or args.image.with_suffix(".stl")
    imagen = load_grayscale(args.image)
    lay = layout(imagen, params)

    inicio = time.perf_counter()
    malla = lithophane(imagen, params)
    write_binary_stl(salida, malla, header=f"theforge lito {args.image.name}")
    tardanza = time.perf_counter() - inicio

    print(f"imagen    {args.image} ({imagen.width}x{imagen.height} px)")
    _describe_shape(params, lay)
    reparto = f" x{params.repeat}" if params.repeat > 1 else ""
    print(
        f"pieza     {lay.width_mm:.1f} x {lay.height_mm:.1f} mm de superficie{reparto}, "
        f"grosor {params.min_thickness:g}-{params.max_thickness:g} mm"
    )
    _describe_fit(params, lay)
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


def _tamano(texto: str) -> tuple[int, int]:
    """Convierte 3600x1200 en (3600, 1200)."""
    try:
        ancho, alto = (int(v) for v in texto.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"tamano invalido: {texto!r}, se espera ANCHOxALTO")
    if ancho < 2 or alto < 2:
        raise argparse.ArgumentTypeError("el tamano debe ser de al menos 2x2")
    return ancho, alto


def _add_ornament_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "ornament",
        help="compone la banda decorada que luego envuelve la esfera",
        description="Medallon con la foto y ornamento procedural alrededor. "
        "La salida es un PNG que se le pasa a 'forge lito --curve sphere --repeat 1'.",
    )
    p.add_argument("image", type=Path, help="foto para el medallon")
    p.add_argument("-o", "--output", type=Path, help="PNG de salida")
    p.add_argument(
        "--style", choices=tuple(STYLES), default=POR_DEFECTO, help=f"({POR_DEFECTO})"
    )
    p.add_argument(
        "--size", type=_tamano, default=(3600, 1200), help="ANCHOxALTO del PNG (3600x1200)"
    )
    p.add_argument("--lat-min", type=float, default=-45.0, help="igual que en lito (-45)")
    p.add_argument("--lat-max", type=float, default=75.0, help="igual que en lito (75)")
    p.add_argument(
        "--medallion", type=float, default=0.82, help="diametro del medallon, 0-1 (0.82)"
    )
    p.add_argument(
        "--sheet",
        action="store_true",
        help="hoja de pruebas con todos los estilos en vez de una sola banda",
    )
    p.set_defaults(func=cmd_ornament)


def cmd_ornament(args: argparse.Namespace) -> int:
    foto = load_grayscale(args.image)

    if args.sheet:
        salida = args.output or args.image.with_name("hoja_estilos.png")
        # Para elegir estilo no hace falta resolucion: se mira y se decide.
        hoja = contact_sheet(foto, size=(1200, 400))
        hoja.save(salida)
        print(f"hoja      {len(STYLES)} estilos: {', '.join(STYLES)}")
        print(f"salida    {salida}")
        return 0

    salida = args.output or args.image.with_name(f"banda_{args.style}.png")
    banda = sphere_band(
        foto,
        args.size,
        lat_min_deg=args.lat_min,
        lat_max_deg=args.lat_max,
        estilo=args.style,
        medallion=args.medallion,
    )
    banda.save(salida)

    print(f"estilo    {args.style}, {ink_fraction(banda):.0%} de la superficie con relieve")
    print(f"banda     {banda.width}x{banda.height} px, latitudes {args.lat_min:g} a {args.lat_max:g}")
    print(f"salida    {salida}")
    print(
        f"siguiente forge lito {salida} --curve sphere --repeat 1 --frame 6 "
        f"--lat-min {args.lat_min:g} --lat-max {args.lat_max:g}"
    )
    return 0


def _add_tune_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "tune",
        help="ajusta los parametros de un estilo con sliders",
        description="Ventana con sliders y dos previsualizaciones: una pieza suelta "
        "y el campo completo. No guarda nada: copia un Style(...) al portapapeles.",
    )
    p.add_argument(
        "--style", choices=tuple(STYLES), default=POR_DEFECTO, help=f"({POR_DEFECTO})"
    )
    p.add_argument("--width", type=int, default=640, help="ancho de la vista (640)")
    p.set_defaults(func=cmd_tune)


def cmd_tune(args: argparse.Namespace) -> int:
    from theforge.tuner import abrir

    try:
        abrir(args.style, ancho=args.width)
    except RuntimeError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forge", description="Herramientas de impresion 3D."
    )
    parser.add_argument("--version", action="version", version=f"theforge {__version__}")
    sub = parser.add_subparsers(dest="comando", required=True)
    _add_lito_parser(sub)
    _add_ornament_parser(sub)
    _add_tune_parser(sub)
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
