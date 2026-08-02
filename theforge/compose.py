"""Composicion de piezas: un proyecto JSON -> banda de grises -> malla.

Este modulo es el documento del futuro editor. Un proyecto dice que forma
tiene la pieza, que patron (o gris liso) hace de fondo, y que fotos van
colocadas encima, donde y a que tamano. Todo lo demas -mapa de grosores,
malla, comprobaciones- se reutiliza de lito.py tal cual.

El contrato de coordenadas, que es donde este tipo de editores se rompe:

    - Una capa se coloca con (cx, cy) en fracciones de la banda: cx=0.5,
      cy=0.5 es el centro. La fila 0 es ARRIBA (lat_max en la esfera).
    - scale es la fraccion del ALTO de la banda que ocupa la capa.
    - El editor manipulara exactamente este espacio: la banda que devuelve
      render_band es el mismo raster del que sale el mapa de grosores, asi
      que lo que se ve es lo que se imprime por construccion, no porque dos
      codigos coincidan.

En la esfera cada foto se pre-deforma alrededor de su propio centro (el
mismo 1/cos(lat) del medallon de ornament.py, generalizado a cualquier
posicion). En las superficies cerradas una capa que cruza la costura se pega
dos veces, desplazada un ancho de banda, y el empalme queda continuo.

El orden de la lista de capas es el orden de pintado: la ultima queda encima.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from theforge.lito import SPHERE, LitoParams, lithophane, load_grayscale
from theforge.ornament import FONDO, STYLES, TINTA, _prewarp_columns, ornament_field

VERSION = 1

CIRCLE = "circle"
RECT = "rect"
MASKS = (CIRCLE, RECT)


@dataclass
class PhotoLayer:
    """Una foto colocada sobre la banda. path se guarda tal como se escribio
    en el proyecto y se resuelve relativo a la carpeta del JSON."""

    path: str
    cx: float = 0.5
    cy: float = 0.5
    scale: float = 0.8
    mask: str = CIRCLE
    ring: bool = True
    gamma: float = 1.0
    # Pre-deformacion equirectangular en la esfera: cada fila se ensancha por
    # 1/cos(lat) para compensar lo que la esfera la va a comprimir, y asi la
    # foto se ve sin aperar. Se apaga cuando la fuente YA viene equirectangular
    # (una panoramica 2:1, o algo pre-deformado a mano): en ese caso volver a
    # aplicarla la deformaria dos veces.
    prewarp: bool = True


@dataclass
class Composition:
    params: LitoParams
    height_mm: float | None = None  # solo flat/cylindrical; en la esfera lo fija la geometria
    # Fondo: un patron procedural, una imagen propia, o un gris liso. Excluyentes.
    pattern: str | None = None
    image: str | None = None
    tile: int = 1  # cuantas veces se repite la imagen de fondo a lo ancho
    # Espeja cada repeticion. Una imagen cualquiera no empalma al cerrar la
    # esfera; espejada, si, por construccion. Es el mismo truco del ornamento.
    mirror: bool = True
    gray: int = FONDO
    layers: list[PhotoLayer] = field(default_factory=list)
    base_dir: Path = field(default_factory=Path)  # para resolver rutas; no se serializa

    def resolve(self, ruta: str) -> Path:
        p = Path(ruta)
        return p if p.is_absolute() else self.base_dir / p

    def validate(self) -> None:
        self.params.validate()
        if self.params.repeat != 1:
            raise ValueError("una composicion es la banda completa: repeat debe ser 1")
        if self.params.curve == SPHERE:
            if self.height_mm is not None:
                raise ValueError("height_mm no aplica a la esfera: lo fija la geometria")
        else:
            if not self.height_mm or self.height_mm <= 0:
                raise ValueError(f"la forma {self.params.curve} necesita height_mm > 0")
        if self.pattern is not None and self.image is not None:
            raise ValueError("background: pattern e image son excluyentes")
        if self.pattern is not None and self.pattern not in STYLES:
            raise ValueError(
                f"patron desconocido: {self.pattern!r}; hay {', '.join(STYLES)}"
            )
        if self.image is not None and not self.resolve(self.image).is_file():
            raise ValueError(f"fondo: no existe el fichero {self.resolve(self.image)}")
        if self.tile < 1:
            raise ValueError("tile debe ser >= 1")
        if not 0 <= self.gray <= 255:
            raise ValueError("gray debe estar entre 0 y 255")
        for i, capa in enumerate(self.layers):
            donde = f"capa {i} ({capa.path})"
            if not self.resolve(capa.path).is_file():
                raise ValueError(f"{donde}: no existe el fichero {self.resolve(capa.path)}")
            if not 0.0 <= capa.cx <= 1.0 or not 0.0 <= capa.cy <= 1.0:
                raise ValueError(f"{donde}: cx y cy deben estar en [0, 1]")
            if not 0.0 < capa.scale <= 1.5:
                raise ValueError(f"{donde}: scale debe estar en (0, 1.5]")
            if capa.mask not in MASKS:
                raise ValueError(f"{donde}: mask debe ser una de {MASKS}")
            if capa.gamma <= 0:
                raise ValueError(f"{donde}: gamma debe ser > 0")

    def band_aspect(self) -> float:
        """Alto/ancho del raster de la banda.

        Con fit=conformal, ojo: este aspecto decide el corte superior real de
        la pieza, no al reves. El reparto conforme deriva lat_max de la
        proporcion de lo que se le da, asi que `lat_max_deg` solo sirve aqui
        para elegir la forma del raster. El corte de verdad lo dice el layout,
        y es lo que reportan `forge compose` y /api/info.
        """
        if self.params.curve == SPHERE:
            span = math.radians(self.params.lat_max_deg - self.params.lat_min_deg)
            return span / (2 * math.pi)
        return self.height_mm / self.params.width_mm


# --------------------------------------------------------------------------
# Serializacion. Estricta a proposito: una clave desconocida es un error, no
# un aviso, porque un typo silencioso en un proyecto es un STL mal generado.
# --------------------------------------------------------------------------

_SHAPE_COMUN = {"curve", "min_thickness", "max_thickness", "frame_mm", "samples"}
_SHAPE_POR_CURVA = {
    "flat": {"width_mm", "height_mm"},
    "cylindrical": {"width_mm", "height_mm", "arc_degrees"},
    "sphere": {"diameter_mm", "lat_min_deg", "lat_max_deg", "fit"},
}
_CLAVES_CAPA = {"type", "path", "cx", "cy", "scale", "mask", "ring", "gamma", "prewarp"}


def _rechazar_desconocidas(d: dict, permitidas: set[str], contexto: str) -> None:
    sobran = set(d) - permitidas
    if sobran:
        raise ValueError(f"{contexto}: claves desconocidas {sorted(sobran)}")


def from_dict(datos: dict, base_dir: Path | str = ".") -> Composition:
    _rechazar_desconocidas(datos, {"version", "shape", "background", "layers"}, "proyecto")
    if datos.get("version") != VERSION:
        raise ValueError(f"version {datos.get('version')!r} no soportada, se espera {VERSION}")

    shape = dict(datos.get("shape") or {})
    curve = shape.get("curve", "flat")
    if curve not in _SHAPE_POR_CURVA:
        raise ValueError(f"curve desconocida: {curve!r}")
    _rechazar_desconocidas(shape, _SHAPE_COMUN | _SHAPE_POR_CURVA[curve] | {"curve"}, "shape")
    height_mm = shape.pop("height_mm", None)
    params = LitoParams(**shape)

    fondo = datos.get("background") or {"gray": FONDO}
    _rechazar_desconocidas(fondo, {"pattern", "image", "tile", "mirror", "gray"}, "background")
    elegidos = [c for c in ("pattern", "image", "gray") if c in fondo]
    if len(elegidos) > 1:
        raise ValueError(f"background: {' y '.join(elegidos)} son excluyentes")

    capas = []
    for i, cruda in enumerate(datos.get("layers") or []):
        _rechazar_desconocidas(cruda, _CLAVES_CAPA, f"capa {i}")
        if cruda.get("type") != "photo":
            raise ValueError(f"capa {i}: type debe ser 'photo', no {cruda.get('type')!r}")
        if "path" not in cruda:
            raise ValueError(f"capa {i}: falta path")
        capas.append(PhotoLayer(**{k: v for k, v in cruda.items() if k != "type"}))

    return Composition(
        params=params,
        height_mm=height_mm,
        pattern=fondo.get("pattern"),
        image=fondo.get("image"),
        tile=int(fondo.get("tile", 1)),
        mirror=bool(fondo.get("mirror", True)),
        gray=int(fondo.get("gray", FONDO)),
        layers=capas,
        base_dir=Path(base_dir),
    )


def to_dict(comp: Composition) -> dict:
    p = comp.params
    shape: dict = {"curve": p.curve, "min_thickness": p.min_thickness,
                   "max_thickness": p.max_thickness, "frame_mm": p.frame_mm,
                   "samples": p.samples}
    if p.curve == SPHERE:
        shape |= {"diameter_mm": p.diameter_mm, "lat_min_deg": p.lat_min_deg,
                  "lat_max_deg": p.lat_max_deg, "fit": p.fit}
    else:
        shape |= {"width_mm": p.width_mm, "height_mm": comp.height_mm}
        if p.curve == "cylindrical":
            shape["arc_degrees"] = p.arc_degrees

    if comp.pattern:
        fondo = {"pattern": comp.pattern}
    elif comp.image:
        fondo = {"image": comp.image, "tile": comp.tile, "mirror": comp.mirror}
    else:
        fondo = {"gray": comp.gray}
    capas = [
        {"type": "photo", "path": c.path, "cx": c.cx, "cy": c.cy, "scale": c.scale,
         "mask": c.mask, "ring": c.ring, "gamma": c.gamma, "prewarp": c.prewarp}
        for c in comp.layers
    ]
    return {"version": VERSION, "shape": shape, "background": fondo, "layers": capas}


def load_project(path: str | Path) -> Composition:
    path = Path(path)
    try:
        datos = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise ValueError(f"{path}: JSON invalido ({err})") from err
    comp = from_dict(datos, base_dir=path.parent)
    comp.validate()
    return comp


def save_project(comp: Composition, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(to_dict(comp), indent=2) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------


def _fondo_desde_imagen(comp: Composition, size: tuple[int, int]) -> Image.Image:
    """Fondo a partir de una imagen propia, repetida y opcionalmente espejada.

    Con mirror, cada repeticion es la imagen seguida de su reflejo. Asi el
    borde derecho de una copia es identico al izquierdo de la siguiente, y al
    cerrar la pieza el ultimo empalma con el primero: la costura desaparece sin
    tener que exigir que la imagen sea teselable.
    """
    ancho, alto = size
    fuente = load_grayscale(comp.resolve(comp.image))
    unidad = max(2, ancho // comp.tile)

    if comp.mirror:
        media = max(1, unidad // 2)
        izquierda = fuente.resize((media, alto), Image.LANCZOS)
        celda = Image.new("L", (media * 2, alto))
        celda.paste(izquierda, (0, 0))
        celda.paste(izquierda.transpose(Image.FLIP_LEFT_RIGHT), (media, 0))
    else:
        celda = fuente.resize((unidad, alto), Image.LANCZOS)

    banda = Image.new("L", size)
    for x in range(0, ancho, celda.width):
        banda.paste(celda, (x, 0))
    return banda


def _recorte_cuadrado(img: Image.Image) -> Image.Image:
    lado = min(img.size)
    x0 = (img.width - lado) // 2
    y0 = (img.height - lado) // 2
    return img.crop((x0, y0, x0 + lado, y0 + lado))


def _pegar_foto(banda: Image.Image, capa: PhotoLayer, comp: Composition,
                lats: np.ndarray | None) -> None:
    W, H = banda.size
    img = load_grayscale(comp.resolve(capa.path))

    if capa.mask == CIRCLE:
        # Recorte centrado, no aplastado: es lo que se espera de un medallon.
        img = _recorte_cuadrado(img)
        dh = dw = max(2, int(round(H * capa.scale)))
    else:
        dh = max(2, int(round(H * capa.scale)))
        dw = max(2, int(round(dh * img.width / img.height)))
    img = img.resize((dw, dh), Image.LANCZOS)

    arr = np.asarray(img, dtype=float) / 255.0
    if capa.gamma != 1.0:
        arr = arr**capa.gamma
    img = Image.fromarray((arr * 255 + 0.5).astype(np.uint8), "L")

    x0 = int(round(capa.cx * W - dw / 2))
    y0 = int(round(capa.cy * H - dh / 2))

    if lats is not None and capa.prewarp:
        # Pre-deformacion alrededor del centro de ESTA capa: cada fila se
        # ensancha por lo que la esfera la va a comprimir.
        filas = np.clip(np.arange(y0, y0 + dh), 0, H - 1)
        centro = lats[np.clip(int(round(capa.cy * H)), 0, H - 1)]
        escalas = math.cos(centro) / np.cos(lats[filas])
        img = Image.fromarray(
            _prewarp_columns(img, escalas).astype(np.uint8), "L"
        )

    mascara = None
    if capa.mask == CIRCLE:
        mascara = Image.new("L", (dw, dh), 0)
        ImageDraw.Draw(mascara).ellipse([0, 0, dw - 1, dh - 1], fill=255)

    posiciones = [x0]
    if comp.params.wraps_u:
        # En una superficie cerrada la capa que cruza la costura reaparece
        # por el otro lado.
        posiciones += [x0 - W, x0 + W]

    dibujo = ImageDraw.Draw(banda)
    grosor_aro = max(2, int(dh * 0.045))
    for x in posiciones:
        banda.paste(img, (x, y0), mascara)
        if capa.ring:
            caja = [x, y0, x + dw - 1, y0 + dh - 1]
            if capa.mask == CIRCLE:
                dibujo.ellipse(caja, outline=TINTA, width=grosor_aro)
            else:
                dibujo.rectangle(caja, outline=TINTA, width=grosor_aro)


def render_band(comp: Composition, width_px: int = 3600) -> Image.Image:
    """La banda de grises completa, lista para lithophane().

    Es el mismo raster que vera el editor y del que saldra el mapa de
    grosores: no hay otro espacio de coordenadas.
    """
    comp.validate()
    W = max(4, width_px - width_px % 2)  # par: el patron se dibuja a mitades
    H = max(2, round(W * comp.band_aspect()))

    if comp.pattern:
        banda = ornament_field((W, H), comp.pattern)
    elif comp.image:
        banda = _fondo_desde_imagen(comp, (W, H))
    else:
        banda = Image.new("L", (W, H), comp.gray)

    lats = None
    if comp.params.curve == SPHERE:
        # Fila 0 arriba = lat_max, como en ornament.sphere_band.
        lats = np.radians(
            np.linspace(comp.params.lat_max_deg, comp.params.lat_min_deg, H)
        )

    for capa in comp.layers:
        _pegar_foto(banda, capa, comp, lats)
    return banda


def build_mesh(comp: Composition, width_px: int = 3600) -> np.ndarray:
    """Proyecto -> malla (n, 3, 3), pasando por la banda."""
    banda = render_band(comp, width_px=width_px)
    return lithophane(banda, comp.params)
