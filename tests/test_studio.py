"""Tests del servidor contra un servidor de verdad.

Se levanta en un puerto libre y se le hacen peticiones HTTP reales, en vez de
llamar a las funciones por dentro: lo que puede romperse aqui es justamente el
pegamento (codigos de estado, tipos de contenido, cuerpos), y eso no se ve
llamando a la funcion.
"""

from __future__ import annotations

import io
import json
import struct
import threading
from http import HTTPStatus
from http.client import HTTPConnection

import numpy as np
import pytest
from PIL import Image

from theforge.studio import EXTENSIONES_IMAGEN, ErrorPeticion, crear_servidor, nombre_seguro, ruta_segura


@pytest.fixture
def raiz(tmp_path):
    """Carpeta de proyecto con una foto dentro."""
    Image.new("L", (60, 60), 0).save(tmp_path / "foto.png")
    (tmp_path / "sub").mkdir()
    Image.new("L", (40, 40), 128).save(tmp_path / "sub" / "otra.png")
    return tmp_path


@pytest.fixture
def cliente(raiz):
    servidor = crear_servidor(raiz, puerto=0, ancho_px=300, ancho_export_px=300)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    conexion = HTTPConnection("127.0.0.1", servidor.server_address[1], timeout=30)

    def peticion(metodo, ruta, cuerpo=None, cabeceras=None):
        datos = cuerpo
        cab = dict(cabeceras or {})
        if isinstance(cuerpo, (dict, list)):
            datos = json.dumps(cuerpo).encode()
            cab["Content-Type"] = "application/json"
        conexion.request(metodo, ruta, body=datos, headers=cab)
        respuesta = conexion.getresponse()
        return respuesta.status, respuesta.headers, respuesta.read()

    yield peticion
    conexion.close()
    servidor.shutdown()
    servidor.server_close()


def proyecto_esfera(path="foto.png", **capa):
    capas = []
    if path:
        capas = [{"type": "photo", "path": path, "cx": 0.5, "cy": 0.5,
                  "scale": 0.6, "mask": "circle", "ring": True, "gamma": 1.0} | capa]
    return {
        "version": 1,
        "shape": {"curve": "sphere", "diameter_mm": 100, "samples": 40,
                  "min_thickness": 0.8, "max_thickness": 3.0, "frame_mm": 4,
                  "lat_min_deg": -45.0, "lat_max_deg": 75.0},
        "background": {"pattern": "fern"},
        "layers": capas,
    }


# --------------------------------------------------------------------------
# Rutas seguras: lo que impide que un proyecto lea toda la maquina
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "intento", ["../secreto.png", "..\\secreto.png", "sub/../../fuera.png", ""]
)
def test_una_ruta_que_escapa_de_la_raiz_se_rechaza(tmp_path, intento):
    with pytest.raises(ErrorPeticion):
        ruta_segura(tmp_path, intento)


def test_una_ruta_dentro_de_la_raiz_se_admite(tmp_path):
    assert ruta_segura(tmp_path, "sub/foto.png").name == "foto.png"


@pytest.mark.parametrize("malo", ["../x.png", "a/b.png", ".oculto.png", "script.py", "",
                                  "..%2Fx.png", "a%2Fb.png"])
def test_nombres_de_subida_invalidos(malo):
    with pytest.raises(ErrorPeticion):
        nombre_seguro(malo)


def test_avif_se_admite_si_pillow_sabe_abrirlo():
    """Regresion: la lista fija anterior no incluia avif, aunque Pillow >= 11.3
    ya lo abre de forma nativa. Aqui no se supone la version, se pregunta."""
    from PIL import Image, features

    if not features.check("avif"):
        pytest.skip("este Pillow no trae soporte AVIF")
    assert ".avif" in EXTENSIONES_IMAGEN
    nombre_seguro("foto.avif")  # no debe lanzar


@pytest.mark.parametrize(
    "enviado,esperado",
    [
        ("foto.png", "foto.png"),
        ("ni%C3%B1a%20con%20acento.png", "niña con acento.png"),
        ("caf%C3%A9.JPG", "café.JPG"),
    ],
)
def test_los_nombres_llegan_percent_encoded(enviado, esperado):
    """Las cabeceras HTTP solo admiten latin-1; un nombre con ñ hace que fetch
    lance antes de salir del navegador. Por eso viaja codificado."""
    assert nombre_seguro(enviado) == esperado


def test_el_proyecto_no_puede_apuntar_fuera(cliente):
    proyecto = proyecto_esfera(path="../fuera.png")
    estado, _, cuerpo = cliente("POST", "/api/banda", proyecto)
    assert estado == HTTPStatus.BAD_REQUEST
    assert "fuera" in json.loads(cuerpo)["error"]


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


def test_los_modulos_js_se_sirven_con_su_tipo(cliente):
    """En Windows mimetypes saca .js de text/plain, y asi el navegador rechaza
    un modulo ES. Los tipos se fijan en el codigo, no en el registro."""
    for ruta, esperado in (("/editor.js", "text/javascript"),
                           ("/visor3d.js", "text/javascript"),
                           ("/estilo.css", "text/css")):
        estado, cabeceras, cuerpo = cliente("GET", ruta)
        assert estado == HTTPStatus.OK, ruta
        assert cabeceras["Content-Type"].startswith(esperado), ruta
        assert cuerpo


def test_servir_una_imagen_del_proyecto(cliente):
    estado, cabeceras, cuerpo = cliente("GET", "/api/imagen?path=sub%2Fotra.png")
    assert estado == HTTPStatus.OK
    assert cabeceras["Content-Type"] == "image/png"
    assert Image.open(io.BytesIO(cuerpo)).size == (40, 40)


@pytest.mark.parametrize("ruta", ["/api/imagen?path=../fuera.png", "/api/imagen?path=",
                                  "/api/imagen?path=no_existe.png"])
def test_servir_imagen_rechaza_lo_que_debe(cliente, ruta):
    assert cliente("GET", ruta)[0] in (HTTPStatus.BAD_REQUEST, HTTPStatus.NOT_FOUND)


def test_la_pagina_se_sirve(cliente):
    estado, cabeceras, cuerpo = cliente("GET", "/")
    assert estado == HTTPStatus.OK
    assert cabeceras["Content-Type"].startswith("text/html")
    assert b"theforge studio" in cuerpo


def test_estilos_e_imagenes(cliente):
    _, _, cuerpo = cliente("GET", "/api/estilos")
    estilos = json.loads(cuerpo)
    assert "acanthus" in estilos["patrones"]
    assert "sphere" in estilos["formas"]
    # Las extensiones salen de lo que Pillow sabe abrir en esta maquina, no de
    # una lista escrita a mano que se desincroniza cuando Pillow suma formatos.
    assert set(estilos["extensiones"]) == EXTENSIONES_IMAGEN

    _, _, cuerpo = cliente("GET", "/api/imagenes")
    # Recursivo y con separadores de URL, no de Windows.
    assert set(json.loads(cuerpo)["imagenes"]) == {"foto.png", "sub/otra.png"}


def test_banda_devuelve_un_png(cliente):
    estado, cabeceras, cuerpo = cliente("POST", "/api/banda", proyecto_esfera())
    assert estado == HTTPStatus.OK
    assert cabeceras["Content-Type"] == "image/png"
    imagen = Image.open(io.BytesIO(cuerpo))
    assert imagen.width == 300
    assert imagen.mode == "L"


def test_encendida_es_distinta_de_la_banda(cliente):
    """La simulacion invierte el sentido: lo grueso es lo que se ve oscuro."""
    _, _, banda = cliente("POST", "/api/banda", proyecto_esfera())
    _, _, encendida = cliente("POST", "/api/encendida", proyecto_esfera())
    a = np.asarray(Image.open(io.BytesIO(banda)), dtype=float)
    b = np.asarray(Image.open(io.BytesIO(encendida)).resize(Image.open(io.BytesIO(banda)).size),
                   dtype=float)
    assert np.abs(a - b).mean() > 5


def test_info_trae_medidas_y_avisos(cliente):
    _, _, cuerpo = cliente("POST", "/api/info", proyecto_esfera())
    info = json.loads(cuerpo)
    assert info["esfera"]["diametro_mm"] == 100
    assert info["esfera"]["voladizo_grados"] == 45.0
    assert info["superficie_mm"]["ancho"] > 0
    assert info["avisos"] == []  # -45 y con marco: nada que avisar


def test_info_reporta_la_latitud_real_no_la_pedida(cliente):
    """Con fit=conformal el corte superior lo deriva el reparto, e ignora
    lat_max_deg. Reportar el parametro daria un diametro de boca falso."""
    proyecto = proyecto_esfera()
    _, _, recto = cliente("POST", "/api/info", proyecto)
    proyecto["shape"]["fit"] = "conformal"
    _, _, conforme = cliente("POST", "/api/info", proyecto)

    a = json.loads(recto)["esfera"]
    b = json.loads(conforme)["esfera"]
    assert a["lat_max_grados"] == pytest.approx(75.0)
    assert b["lat_max_grados"] < 70.0
    assert b["boca_arriba_mm"] > a["boca_arriba_mm"]  # corta mas abajo = boca mayor


def test_info_refleja_cap_top_y_avisa_del_puente(cliente):
    proyecto = proyecto_esfera()
    proyecto["shape"]["cap_top"] = True
    _, _, cuerpo = cliente("POST", "/api/info", proyecto)
    info = json.loads(cuerpo)
    assert info["esfera"]["cap_top"] is True
    assert any("puente" in a for a in info["avisos"])


def test_stl_con_cap_top_da_malla_cerrada_de_verdad(cliente):
    proyecto = proyecto_esfera()
    proyecto["shape"]["cap_top"] = True
    estado, _, cuerpo = cliente("POST", "/api/stl", proyecto)
    assert estado == HTTPStatus.OK
    (cuantos,) = struct.unpack("<I", cuerpo[80:84])
    assert len(cuerpo) == 84 + cuantos * 50


def test_info_avisa_de_lo_que_no_se_va_a_imprimir_bien(cliente):
    proyecto = proyecto_esfera()
    proyecto["shape"]["lat_min_deg"] = -70.0
    proyecto["shape"]["frame_mm"] = 0.0
    _, _, cuerpo = cliente("POST", "/api/info", proyecto)
    avisos = " ".join(json.loads(cuerpo)["avisos"])
    assert "soportes" in avisos
    assert "marco" in avisos


def test_stl_es_binario_valido_y_cerrado(cliente):
    estado, cabeceras, cuerpo = cliente("POST", "/api/stl", proyecto_esfera())
    assert estado == HTTPStatus.OK
    assert cabeceras["Content-Type"] == "application/octet-stream"
    assert "attachment" in cabeceras["Content-Disposition"]
    assert not cuerpo.startswith(b"solid")  # no debe parecer STL ASCII
    (cuantos,) = struct.unpack("<I", cuerpo[80:84])
    assert len(cuerpo) == 84 + cuantos * 50


# --------------------------------------------------------------------------
# Errores
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "romper,esperado",
    [
        (lambda p: p.update(version=99), "version"),
        (lambda p: p["shape"].update(curve="donut"), "curve"),
        (lambda p: p["layers"][0].update(scale=9.0), "scale"),
        (lambda p: p["layers"][0].update(path="no_existe.png"), "no existe"),
        (lambda p: p.update(background={"pattern": "rococo"}), "patron"),
    ],
)
def test_proyecto_invalido_da_400_con_mensaje(cliente, romper, esperado):
    proyecto = proyecto_esfera()
    romper(proyecto)
    estado, _, cuerpo = cliente("POST", "/api/banda", proyecto)
    assert estado == HTTPStatus.BAD_REQUEST
    assert esperado in json.loads(cuerpo)["error"]


def test_json_roto_y_cuerpo_vacio(cliente):
    estado, _, cuerpo = cliente("POST", "/api/banda", b"{no es json",
                                {"Content-Type": "application/json"})
    assert estado == HTTPStatus.BAD_REQUEST
    assert "JSON" in json.loads(cuerpo)["error"]

    estado, _, _ = cliente("POST", "/api/banda")
    assert estado == HTTPStatus.BAD_REQUEST


def test_endpoints_desconocidos(cliente):
    assert cliente("GET", "/api/inventado")[0] == HTTPStatus.NOT_FOUND
    assert cliente("POST", "/api/inventado", {})[0] == HTTPStatus.NOT_FOUND
    assert cliente("GET", "/no_existe.js")[0] == HTTPStatus.NOT_FOUND


def test_la_conexion_no_se_desincroniza_tras_un_error(cliente):
    """Regresion: responder sin leer el cuerpo rompe la conexion siguiente.

    Con HTTP/1.1 el socket se reutiliza. Si una respuesta sale sin consumir el
    cuerpo de su peticion, ese cuerpo se queda ahi y se interpreta como la
    peticion siguiente: la de despues respondia 501 sin motivo aparente.
    """
    grande = proyecto_esfera()
    grande["layers"][0]["path"] = "no_existe.png"  # provoca 400 con cuerpo largo
    assert cliente("POST", "/api/banda", grande)[0] == HTTPStatus.BAD_REQUEST
    assert cliente("POST", "/api/inventado", grande)[0] == HTTPStatus.NOT_FOUND
    # Y despues de los dos errores, la conexion sigue sana.
    estado, cabeceras, _ = cliente("POST", "/api/banda", proyecto_esfera())
    assert estado == HTTPStatus.OK
    assert cabeceras["Content-Type"] == "image/png"


# --------------------------------------------------------------------------
# Subida
# --------------------------------------------------------------------------


def test_subir_una_imagen(cliente, raiz):
    buffer = io.BytesIO()
    Image.new("RGB", (30, 20), (10, 200, 10)).save(buffer, format="PNG")
    estado, _, cuerpo = cliente(
        "POST", "/api/subir", buffer.getvalue(), {"X-Nombre-Fichero": "nueva.png"}
    )
    assert estado == HTTPStatus.OK
    datos = json.loads(cuerpo)
    assert datos == {"path": "nueva.png", "ancho": 30, "alto": 20}
    assert (raiz / "nueva.png").is_file()


def test_subir_dos_veces_no_pisa_la_anterior(cliente, raiz):
    buffer = io.BytesIO()
    Image.new("L", (10, 10), 0).save(buffer, format="PNG")
    cliente("POST", "/api/subir", buffer.getvalue(), {"X-Nombre-Fichero": "foto.png"})
    # foto.png ya existia en la raiz, asi que la nueva va con sufijo.
    assert (raiz / "foto-2.png").is_file()


def test_subir_algo_que_no_es_imagen(cliente, raiz):
    estado, _, cuerpo = cliente(
        "POST", "/api/subir", b"esto no es un png", {"X-Nombre-Fichero": "falsa.png"}
    )
    assert estado == HTTPStatus.BAD_REQUEST
    error = json.loads(cuerpo)["error"]
    assert "falsa.png" in error and "imagen" in error
    # El repr del BytesIO de PIL no le dice nada a quien lo lee.
    assert "BytesIO" not in error
    assert not (raiz / "falsa.png").exists()


def test_subir_sin_datos(cliente):
    estado, _, cuerpo = cliente("POST", "/api/subir", b"", {"X-Nombre-Fichero": "vacia.png"})
    assert estado == HTTPStatus.BAD_REQUEST
    assert "ningun dato" in json.loads(cuerpo)["error"]


def test_subir_con_nombre_con_acentos(cliente, raiz):
    buffer = io.BytesIO()
    Image.new("L", (12, 8), 0).save(buffer, format="PNG")
    estado, _, cuerpo = cliente(
        "POST", "/api/subir", buffer.getvalue(),
        {"X-Nombre-Fichero": "ni%C3%B1a%20cumplea%C3%B1os.png"},
    )
    assert estado == HTTPStatus.OK
    assert json.loads(cuerpo)["path"] == "niña cumpleaños.png"
    assert (raiz / "niña cumpleaños.png").is_file()


def test_subir_con_nombre_peligroso(cliente):
    buffer = io.BytesIO()
    Image.new("L", (10, 10), 0).save(buffer, format="PNG")
    estado, _, _ = cliente(
        "POST", "/api/subir", buffer.getvalue(), {"X-Nombre-Fichero": "../fuera.png"}
    )
    assert estado == HTTPStatus.BAD_REQUEST


def test_la_carpeta_raiz_tiene_que_existir(tmp_path):
    with pytest.raises(ValueError, match="no existe"):
        crear_servidor(tmp_path / "no_existe", puerto=0)
