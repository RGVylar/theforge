"""Servidor local del editor: HTTP con la stdlib, sin Flask ni dependencias.

Fase 2 del editor. El servidor es deliberadamente **sin estado**: el proyecto
completo viaja en el cuerpo de cada peticion y aqui no se guarda nada entre
llamadas. Asi no hay sesion que se desincronice del navegador, no hay orden de
peticiones que respetar, y recargar la pagina no puede dejar nada a medias.

Todo lo que sirve sale de compose.py, que ya esta testeado: aqui no se calcula
geometria, solo se traduce HTTP a llamadas de esa API. Esa es la misma regla
que seguira el frontend.

Seguridad, que aunque sea local conviene: se escucha solo en 127.0.0.1, y toda
ruta de fichero se resuelve dentro de la carpeta raiz y se rechaza si escapa.
Un proyecto es un JSON con rutas dentro; sin ese filtro, pedir
"../../../../windows/system32/..." seria leer lo que le diera la gana.
"""

from __future__ import annotations

import io
import json
import mimetypes
import threading
import urllib.parse
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from theforge.compose import build_mesh, from_dict, render_band
from theforge.lito import SPHERE
from theforge.ornament import STYLES, ink_fraction
from theforge.preview import backlit_from_thickness
from theforge.stl import check_mesh, mesh_volume, triangle_normals

WEB = Path(__file__).parent / "studio_web"
CUERPO_MAXIMO = 64 * 1024 * 1024  # 64 MB: una foto grande cabe, un disparate no
DENSIDAD_PLA = 1.24  # g/cm3
EXTENSIONES_IMAGEN = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"})

# En Windows mimetypes lee del registro, y ahi .js suele estar como text/plain.
# Un modulo ES servido como text/plain lo rechaza el navegador, asi que estos
# tipos se fijan aqui en vez de fiarse del sistema.
TIPOS = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}


class ErrorPeticion(Exception):
    """Error atribuible a la peticion; se traduce a un codigo HTTP concreto."""

    def __init__(self, mensaje: str, estado: HTTPStatus = HTTPStatus.BAD_REQUEST):
        super().__init__(mensaje)
        self.estado = estado


def ruta_segura(raiz: Path, relativa: str) -> Path:
    """Resuelve `relativa` dentro de `raiz` o falla.

    Sin esto, un proyecto podria pedir cualquier fichero de la maquina.
    """
    if not relativa:
        raise ErrorPeticion("ruta vacia")
    destino = (raiz / relativa).resolve()
    if not destino.is_relative_to(raiz.resolve()):
        raise ErrorPeticion(f"ruta fuera de la carpeta del proyecto: {relativa}")
    return destino


def nombre_seguro(nombre: str) -> str:
    """Nombre de fichero para lo que se sube. Rechaza, no sanea.

    Quedarse con el ultimo tramo de "../secreto.png" y guardarlo como
    "secreto.png" seria hacer algo distinto de lo que se pidio sin decirlo.
    Si el cliente manda una ruta en vez de un nombre, es un error suyo.

    Llega percent-encoded porque las cabeceras HTTP solo admiten latin-1 y los
    nombres de fichero traen acentos, enes y a veces emoji. Sobre un nombre
    ASCII, desescapar no cambia nada.
    """
    crudo = urllib.parse.unquote((nombre or "").strip())
    if not crudo or crudo != Path(crudo).name or crudo.startswith("."):
        raise ErrorPeticion(f"nombre de fichero invalido: {nombre!r}")
    if Path(crudo).suffix.lower() not in EXTENSIONES_IMAGEN:
        raise ErrorPeticion(f"extension no admitida: {nombre!r}")
    return crudo


# --------------------------------------------------------------------------
# Logica de cada endpoint, separada del HTTP para poder testearla directamente
# --------------------------------------------------------------------------


def _composicion(datos: dict, raiz: Path):
    if not isinstance(datos, dict):
        raise ErrorPeticion("se esperaba un objeto JSON con el proyecto")
    try:
        comp = from_dict(datos, base_dir=raiz)
        # Ni las capas ni el fondo pueden apuntar fuera de la carpeta raiz.
        for ruta in [c.path for c in comp.layers] + ([comp.image] if comp.image else []):
            ruta_segura(raiz, ruta)
        comp.validate()
    except ErrorPeticion:
        raise
    except (ValueError, TypeError) as err:
        raise ErrorPeticion(str(err)) from err
    return comp


def _png(imagen: Image.Image) -> bytes:
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    return buffer.getvalue()


def api_estilos() -> dict:
    """Lo que el editor necesita para pintar sus menus."""
    return {
        "patrones": list(STYLES),
        "formas": ["flat", "cylindrical", "sphere"],
        "mascaras": ["circle", "rect"],
    }


def api_imagenes(raiz: Path) -> dict:
    """Imagenes disponibles en la carpeta del proyecto, para elegir capa."""
    encontradas = sorted(
        p.relative_to(raiz).as_posix()
        for p in raiz.rglob("*")
        if p.is_file() and p.suffix.lower() in EXTENSIONES_IMAGEN
    )
    return {"imagenes": encontradas}


def api_banda(datos: dict, raiz: Path, ancho_px: int) -> bytes:
    return _png(render_band(_composicion(datos, raiz), width_px=ancho_px))


def api_encendida(datos: dict, raiz: Path, ancho_px: int) -> bytes:
    comp = _composicion(datos, raiz)
    banda = render_band(comp, width_px=ancho_px)
    from theforge.lito import thickness_map

    return _png(backlit_from_thickness(thickness_map(banda, comp.params)))


def api_info(datos: dict, raiz: Path, ancho_px: int) -> dict:
    """Medidas y avisos de la pieza, sin llegar a construir la malla.

    Es lo que el editor enseña mientras mueves cosas: barato de calcular y
    suficiente para decidir. La malla solo se construye al exportar.
    """
    comp = _composicion(datos, raiz)
    banda = render_band(comp, width_px=ancho_px)
    p = comp.params
    ancho_mm, alto_mm = (
        (2 * 3.141592653589793 * p.radius_mm, comp.band_aspect() * 2 * 3.141592653589793 * p.radius_mm)
        if p.curve == SPHERE
        else (p.width_mm, comp.height_mm)
    )

    info = {
        "banda": {"ancho_px": banda.width, "alto_px": banda.height},
        "superficie_mm": {"ancho": round(ancho_mm, 1), "alto": round(alto_mm, 1)},
        "relieve": round(ink_fraction(banda), 3),
        "avisos": [],
    }
    if p.curve == SPHERE:
        import math

        from theforge.lito import layout

        # Las latitudes reales salen del layout, no de los parametros: con
        # fit=conformal el corte superior lo deriva la proporcion de la banda y
        # lat_max_deg se ignora. Leer el parametro daria una boca falsa.
        lat_min, lat_max = layout(banda, p).lat_degrees
        radio = p.radius_mm
        info["esfera"] = {
            "diametro_mm": p.diameter_mm,
            "lat_min_grados": round(lat_min, 1),
            "lat_max_grados": round(lat_max, 1),
            "boca_abajo_mm": round(2 * radio * math.cos(math.radians(lat_min)), 1),
            "boca_arriba_mm": round(2 * radio * math.cos(math.radians(lat_max)), 1),
            "voladizo_grados": round(abs(lat_min), 1),
        }
        if abs(lat_min) > 45:
            info["avisos"].append("el voladizo pasa de 45 grados: necesitara soportes")
        if lat_max > 80:
            info["avisos"].append("el corte superior pasa de 80 grados: tendra que puentear")
        if p.frame_mm <= 0:
            info["avisos"].append("sin marco el borde de apoyo queda ondulado")
    return info


def api_stl(datos: dict, raiz: Path, ancho_px: int) -> bytes:
    """Construye la malla y se niega a devolverla si no es cerrada.

    Esta es la razon de que exportar pase por el servidor y no por el navegador:
    el unico sitio donde se puede comprobar la malla es donde se construye.
    """
    from theforge.stl import STL_TRIANGLE
    import struct

    import numpy as np

    comp = _composicion(datos, raiz)
    malla = build_mesh(comp, width_px=ancho_px)
    informe = check_mesh(malla)
    if not informe.watertight:
        raise ErrorPeticion(
            f"la malla no es cerrada y no se exporta: {informe}",
            estado=HTTPStatus.CONFLICT,
        )

    tris = np.asarray(malla, dtype=np.float32)
    registros = np.zeros(len(tris), dtype=STL_TRIANGLE)
    registros["vertices"] = tris
    registros["normal"] = triangle_normals(tris)
    cabecera = b"theforge studio".ljust(80, b" ")
    return cabecera + struct.pack("<I", len(registros)) + registros.tobytes()


def api_subir(nombre: str, cuerpo: bytes, raiz: Path) -> dict:
    """Guarda una imagen en la carpeta del proyecto.

    Se abre con PIL antes de escribirla: si no es una imagen de verdad, no se
    guarda. No queremos que el editor deje basura que luego reviente al render.
    """
    limpio = nombre_seguro(nombre)
    if not cuerpo:
        raise ErrorPeticion(f"{limpio}: no ha llegado ningun dato")
    try:
        Image.open(io.BytesIO(cuerpo)).verify()
    except (UnidentifiedImageError, OSError) as err:
        # El mensaje de PIL trae el repr del BytesIO, que no le dice nada a
        # nadie. Lo que importa es que el fichero no se puede abrir.
        raise ErrorPeticion(
            f"{limpio}: no se pudo leer como imagen "
            f"({len(cuerpo)} bytes). Prueba a reexportarla como PNG o JPG."
        ) from err

    destino = ruta_segura(raiz, limpio)
    if destino.exists():
        raiz_nombre, sufijo = destino.stem, destino.suffix
        for i in range(2, 1000):
            candidato = ruta_segura(raiz, f"{raiz_nombre}-{i}{sufijo}")
            if not candidato.exists():
                destino = candidato
                break
    destino.write_bytes(cuerpo)
    with Image.open(destino) as abierta:
        ancho, alto = abierta.size
    return {"path": destino.relative_to(raiz.resolve()).as_posix(), "ancho": ancho, "alto": alto}


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


@dataclass
class Config:
    raiz: Path
    ancho_px: int = 1400  # raster de previsualizacion; el de exportar va aparte
    ancho_export_px: int = 3600


class Manejador(BaseHTTPRequestHandler):
    config: Config  # lo inyecta crear_servidor
    protocol_version = "HTTP/1.1"

    def log_message(self, formato, *args):  # pragma: no cover - ruido en consola
        pass

    # -- utilidades de respuesta ------------------------------------------

    def _responder(self, cuerpo: bytes, tipo: str, estado=HTTPStatus.OK, cabeceras=None):
        self.send_response(estado)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        # Sin cache: cada peticion refleja el proyecto que se acaba de mandar.
        self.send_header("Cache-Control", "no-store")
        for clave, valor in (cabeceras or {}).items():
            self.send_header(clave, valor)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(cuerpo)

    def _json(self, datos, estado=HTTPStatus.OK):
        self._responder(
            json.dumps(datos, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            estado,
        )

    def _error(self, mensaje: str, estado=HTTPStatus.BAD_REQUEST):
        self._json({"error": mensaje}, estado)

    def _cuerpo(self) -> bytes:
        """Lee el cuerpo entero. Hay que llamarla SIEMPRE antes de responder.

        Con HTTP/1.1 la conexion se reutiliza: un cuerpo sin consumir se queda
        en el socket y se interpreta como la peticion siguiente, que sale
        desincronizada. Por eso se lee aunque la ruta no exista.
        """
        longitud = int(self.headers.get("Content-Length") or 0)
        if longitud > CUERPO_MAXIMO:
            # No se puede vaciar sin leerlo entero, asi que se corta la conexion.
            self.close_connection = True
            raise ErrorPeticion(
                "cuerpo demasiado grande", HTTPStatus.REQUEST_ENTITY_TOO_LARGE
            )
        return self.rfile.read(longitud) if longitud else b""

    @staticmethod
    def _proyecto(crudo: bytes) -> dict:
        if not crudo:
            raise ErrorPeticion("falta el proyecto en el cuerpo de la peticion")
        try:
            return json.loads(crudo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            raise ErrorPeticion(f"JSON invalido: {err}") from err

    # -- rutas -------------------------------------------------------------

    def do_GET(self):  # noqa: N802 - lo impone BaseHTTPRequestHandler
        try:
            ruta = self.path.split("?", 1)[0]
            if ruta == "/api/estilos":
                return self._json(api_estilos())
            if ruta == "/api/imagenes":
                return self._json(api_imagenes(self.config.raiz))
            if ruta == "/api/imagen":
                consulta = urllib.parse.parse_qs(
                    self.path.split("?", 1)[1] if "?" in self.path else ""
                )
                relativa = (consulta.get("path") or [""])[0]
                fichero = ruta_segura(self.config.raiz, relativa)
                if not fichero.is_file():
                    return self._error("no encontrado", HTTPStatus.NOT_FOUND)
                tipo = mimetypes.guess_type(fichero.name)[0] or "application/octet-stream"
                return self._responder(fichero.read_bytes(), tipo)
            if ruta.startswith("/api/"):
                return self._error("endpoint desconocido", HTTPStatus.NOT_FOUND)
            return self._estatico(ruta)
        except ErrorPeticion as err:
            return self._error(str(err), err.estado)
        except Exception as err:  # pragma: no cover - red de seguridad
            return self._error(f"error interno: {err}", HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    def do_POST(self):  # noqa: N802
        try:
            # Lo primero, pase lo que pase con la ruta: ver _cuerpo().
            crudo = self._cuerpo()
            ruta = self.path.split("?", 1)[0]
            cfg = self.config
            if ruta == "/api/banda":
                return self._responder(
                    api_banda(self._proyecto(crudo), cfg.raiz, cfg.ancho_px), "image/png"
                )
            if ruta == "/api/encendida":
                return self._responder(
                    api_encendida(self._proyecto(crudo), cfg.raiz, cfg.ancho_px), "image/png"
                )
            if ruta == "/api/info":
                return self._json(api_info(self._proyecto(crudo), cfg.raiz, cfg.ancho_px))
            if ruta == "/api/stl":
                cuerpo = api_stl(self._proyecto(crudo), cfg.raiz, cfg.ancho_export_px)
                return self._responder(
                    cuerpo,
                    "application/octet-stream",
                    cabeceras={"Content-Disposition": 'attachment; filename="pieza.stl"'},
                )
            if ruta == "/api/subir":
                nombre = self.headers.get("X-Nombre-Fichero", "")
                return self._json(api_subir(nombre, crudo, cfg.raiz))
            return self._error("endpoint desconocido", HTTPStatus.NOT_FOUND)
        except ErrorPeticion as err:
            return self._error(str(err), err.estado)
        except Exception as err:  # pragma: no cover - red de seguridad
            return self._error(f"error interno: {err}", HTTPStatus.INTERNAL_SERVER_ERROR)

    def _estatico(self, ruta: str):
        nombre = "index.html" if ruta in ("/", "") else ruta.lstrip("/")
        try:
            fichero = ruta_segura(WEB, nombre)
        except ErrorPeticion:
            return self._error("no encontrado", HTTPStatus.NOT_FOUND)
        if not fichero.is_file():
            return self._error("no encontrado", HTTPStatus.NOT_FOUND)
        tipo = TIPOS.get(
            fichero.suffix.lower(),
            mimetypes.guess_type(fichero.name)[0] or "application/octet-stream",
        )
        self._responder(fichero.read_bytes(), tipo)


def crear_servidor(raiz: Path | str, puerto: int = 8756, **kwargs) -> ThreadingHTTPServer:
    """Servidor listo para servir, escuchando solo en localhost.

    Con puerto=0 el sistema asigna uno libre, que es lo que usan los tests.
    """
    raiz = Path(raiz).resolve()
    if not raiz.is_dir():
        raise ValueError(f"la carpeta del proyecto no existe: {raiz}")

    manejador = type("ManejadorConfigurado", (Manejador,), {"config": Config(raiz, **kwargs)})
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), manejador)
    servidor.daemon_threads = True
    return servidor


def servir(raiz: Path | str, puerto: int = 8756, abrir_navegador: bool = True, **kwargs) -> None:
    servidor = crear_servidor(raiz, puerto, **kwargs)
    url = f"http://127.0.0.1:{servidor.server_address[1]}/"
    print(f"studio    {url}")
    print(f"carpeta   {Path(raiz).resolve()}")
    print("           Ctrl+C para parar")
    if abrir_navegador:
        import webbrowser

        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nparado")
    finally:
        servidor.server_close()
