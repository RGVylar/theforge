from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from theforge.cli import main
from theforge.compose import (
    Composition,
    PhotoLayer,
    build_mesh,
    from_dict,
    load_project,
    render_band,
    save_project,
    to_dict,
)
from theforge.lito import LitoParams
from theforge.ornament import FONDO
from theforge.stl import check_mesh, read_binary_stl

ANCHO_PX = 600  # raster pequeno: los tests miran geometria, no calidad


def foto_negra(tmp_path, nombre="negra.png", size=(40, 40)):
    ruta = tmp_path / nombre
    Image.new("L", size, 0).save(ruta)
    return ruta


def esfera(tmp_path, **capa) -> Composition:
    foto_negra(tmp_path)
    valores = {"path": "negra.png", "ring": False} | capa
    return Composition(
        params=LitoParams(curve="sphere", diameter_mm=100, samples=40),
        layers=[PhotoLayer(**valores)],
        base_dir=tmp_path,
    )


def plana(tmp_path, **capa) -> Composition:
    foto_negra(tmp_path)
    valores = {"path": "negra.png", "ring": False} | capa
    return Composition(
        params=LitoParams(curve="flat", width_mm=80, samples=40),
        height_mm=60.0,
        layers=[PhotoLayer(**valores)],
        base_dir=tmp_path,
    )


# --------------------------------------------------------------------------
# Serializacion
# --------------------------------------------------------------------------


def test_ida_y_vuelta_del_proyecto(tmp_path):
    comp = esfera(tmp_path, cx=0.3, cy=0.6, scale=0.5, mask="rect", gamma=0.8)
    comp.pattern = "acanthus"
    ruta = save_project(comp, tmp_path / "p.json")
    recargado = load_project(ruta)
    assert to_dict(recargado) == to_dict(comp)


def test_las_rutas_se_resuelven_relativas_al_json(tmp_path):
    comp = plana(tmp_path)
    ruta = save_project(comp, tmp_path / "p.json")
    # Cargado desde otra cwd da igual: la base es la carpeta del JSON.
    recargado = load_project(ruta)
    assert recargado.resolve(recargado.layers[0].path).is_file()


@pytest.mark.parametrize(
    "romper",
    [
        lambda d: d.update(version=99),
        lambda d: d.update(sorpresa=1),
        lambda d: d["shape"].update(curve="donut"),
        lambda d: d["shape"].update(diameter_mm=100),  # clave de esfera en flat
        lambda d: d["layers"][0].update(rotacion=45),  # clave desconocida en capa
        lambda d: d["layers"][0].update(type="texto"),
        lambda d: d["layers"][0].pop("path"),
        lambda d: d.update(background={"pattern": "acanthus", "gray": 100}),
    ],
)
def test_proyecto_invalido_da_error_claro(tmp_path, romper):
    datos = to_dict(plana(tmp_path))
    romper(datos)
    with pytest.raises((ValueError, TypeError)):
        from_dict(datos, base_dir=tmp_path)


@pytest.mark.parametrize(
    "cambiar",
    [
        {"cx": 1.4},
        {"scale": 0.0},
        {"mask": "estrella"},
        {"gamma": 0},
        {"path": "no_existe.png"},
    ],
)
def test_capa_invalida_no_valida(tmp_path, cambiar):
    comp = plana(tmp_path)
    for k, v in cambiar.items():
        setattr(comp.layers[0], k, v)
    with pytest.raises(ValueError):
        comp.validate()


def test_la_esfera_rechaza_height_y_la_plana_lo_exige(tmp_path):
    con_alto = esfera(tmp_path)
    con_alto.height_mm = 50.0
    with pytest.raises(ValueError, match="height_mm"):
        con_alto.validate()

    sin_alto = plana(tmp_path)
    sin_alto.height_mm = None
    with pytest.raises(ValueError, match="height_mm"):
        sin_alto.validate()


def test_patron_desconocido(tmp_path):
    comp = plana(tmp_path)
    comp.pattern = "rococo"
    with pytest.raises(ValueError, match="patron"):
        comp.validate()


# --------------------------------------------------------------------------
# Render: el contrato de coordenadas
# --------------------------------------------------------------------------


def test_la_foto_aterriza_donde_se_coloco(tmp_path):
    comp = plana(tmp_path, cx=0.25, cy=0.5, scale=0.4, mask="rect")
    banda = np.asarray(render_band(comp, width_px=ANCHO_PX), dtype=int)
    filas, columnas = np.nonzero(banda < 30)
    assert len(columnas) > 0
    assert columnas.mean() / banda.shape[1] == pytest.approx(0.25, abs=0.02)
    assert filas.mean() / banda.shape[0] == pytest.approx(0.50, abs=0.02)


def test_el_orden_de_capas_es_el_orden_de_pintado(tmp_path):
    foto_negra(tmp_path)
    blanca = tmp_path / "blanca.png"
    Image.new("L", (40, 40), 255).save(blanca)
    comp = plana(tmp_path)
    comp.layers = [
        PhotoLayer(path="negra.png", scale=0.5, mask="rect", ring=False),
        PhotoLayer(path="blanca.png", scale=0.3, mask="rect", ring=False),
    ]
    banda = np.asarray(render_band(comp, width_px=ANCHO_PX), dtype=int)
    centro = banda[banda.shape[0] // 2, banda.shape[1] // 2]
    assert centro > 200  # la blanca, que va despues, tapa a la negra


def test_una_capa_que_cruza_la_costura_reaparece_por_el_otro_lado(tmp_path):
    comp = esfera(tmp_path, cx=0.0, cy=0.5, scale=0.4, mask="circle")
    banda = np.asarray(render_band(comp, width_px=ANCHO_PX), dtype=int)
    H, W = banda.shape
    fila = banda[H // 2]
    assert fila[2] < 30  # borde izquierdo: dentro del circulo
    assert fila[W - 3] < 30  # y borde derecho: la otra mitad
    assert fila[W // 2] > 100  # el centro de la banda queda libre


def test_en_la_plana_no_hay_costura_que_cruzar(tmp_path):
    comp = plana(tmp_path, cx=0.0, cy=0.5, scale=0.4, mask="circle")
    banda = np.asarray(render_band(comp, width_px=ANCHO_PX), dtype=int)
    assert banda[banda.shape[0] // 2, -3] > 100  # no reaparece por la derecha


def test_en_la_esfera_la_foto_se_predeforma_alrededor_de_su_centro(tmp_path):
    """Una franja vertical colocada arriba sale mas ancha por su borde alto."""
    pixeles = np.full((80, 80), 255, dtype=np.uint8)
    pixeles[:, 36:44] = 0
    ruta = tmp_path / "franja.png"
    Image.fromarray(pixeles, "L").save(ruta)

    comp = esfera(tmp_path, path="franja.png", cy=0.3, scale=0.45, mask="rect")
    banda = np.asarray(render_band(comp, width_px=ANCHO_PX), dtype=int)
    franja = banda < 30
    filas = np.flatnonzero(franja.any(axis=1))
    alto = filas[-1] - filas[0]
    arriba = franja[filas[0] + int(alto * 0.15)].sum()
    abajo = franja[filas[0] + int(alto * 0.85)].sum()
    assert arriba > abajo * 1.05


def test_gamma_por_capa(tmp_path):
    gris = tmp_path / "gris.png"
    Image.new("L", (40, 40), 128).save(gris)
    clara = plana(tmp_path, path="gris.png", mask="rect", gamma=0.5)
    oscura = plana(tmp_path, path="gris.png", mask="rect", gamma=2.0)
    b_clara = np.asarray(render_band(clara, width_px=ANCHO_PX), dtype=int)
    b_oscura = np.asarray(render_band(oscura, width_px=ANCHO_PX), dtype=int)
    centro = (b_clara.shape[0] // 2, b_clara.shape[1] // 2)
    assert b_clara[centro] > 128 > b_oscura[centro]


def test_fondo_gris_configurable(tmp_path):
    comp = plana(tmp_path, scale=0.2)
    comp.gray = 240
    banda = np.asarray(render_band(comp, width_px=ANCHO_PX), dtype=int)
    assert banda[2, 2] == 240
    assert comp.pattern is None


# --------------------------------------------------------------------------
# De punta a punta
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "forma",
    [
        {"curve": "flat", "width_mm": 80},
        {"curve": "cylindrical", "width_mm": 80, "arc_degrees": 120},
        {"curve": "cylindrical", "width_mm": 120, "arc_degrees": 360},
        {"curve": "sphere", "diameter_mm": 100},
    ],
    ids=["plana", "arco", "cilindro-cerrado", "esfera"],
)
def test_el_proyecto_acaba_en_malla_cerrada(tmp_path, forma):
    foto_negra(tmp_path)
    params = LitoParams(samples=40, **forma)
    alto = None if forma["curve"] == "sphere" else 40.0
    comp = Composition(
        params=params,
        height_mm=alto,
        layers=[PhotoLayer(path="negra.png", scale=0.4)],
        base_dir=tmp_path,
    )
    informe = check_mesh(build_mesh(comp, width_px=ANCHO_PX))
    assert informe.watertight, informe
    assert informe.volume_mm3 > 0


def test_cli_compose(tmp_path, gradient):
    entrada = tmp_path / "foto.png"
    gradient.save(entrada)
    proyecto = save_project(
        Composition(
            params=LitoParams(curve="sphere", diameter_mm=100, samples=40),
            pattern="fern",
            layers=[PhotoLayer(path="foto.png", scale=0.6)],
            base_dir=tmp_path,
        ),
        tmp_path / "p.json",
    )
    salida = tmp_path / "p.stl"
    banda = tmp_path / "banda.png"

    codigo = main(
        ["compose", str(proyecto), "-o", str(salida), "--band", str(banda),
         "--width-px", str(ANCHO_PX)]
    )

    assert codigo == 0
    assert banda.is_file()
    assert check_mesh(read_binary_stl(salida)).watertight


def test_cli_compose_proyecto_roto(tmp_path):
    roto = tmp_path / "roto.json"
    roto.write_text("{esto no es json", encoding="utf-8")
    assert main(["compose", str(roto)]) == 2
