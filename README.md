# theforge

Herramientas en Python para mi proyecto paralelo de impresión 3D. Monorepo: varias
herramientas que comparten núcleo (escritor de STL, más adelante parser de G-code).
Uso personal, no una librería pública.

Sin CAD pesado: la geometría se escribe a mano como STL binario con numpy. Las
únicas dependencias son **numpy** y **pillow**.

## Estado

| Módulo | Estado |
| --- | --- |
| `stl.py` | escritura/lectura de STL binario, cosido de superficies, comprobación de malla cerrada |
| `lito.py` | generador de litofanías (plana, cilíndrica y esférica) |
| `ornament.py` | ornamento procedural y composición de bandas con medallón |
| `compose.py` | proyectos de composición: JSON con forma + fondo + fotos colocadas |
| `emboss.py` | graba una foto en relieve sobre un STL ya existente (cualquier producto) |
| `preview.py` | simulación de la litofanía a contraluz (Beer-Lambert) |
| `studio.py` | servidor local del editor: banda, contraluz, info y exportación |
| `tuner.py` | ajuste interactivo de estilos con sliders (tkinter) |
| `cli.py` | `forge lito ...`, `forge ornament ...`, `forge emboss ...`, `forge tune` |
| resto del roadmap | sin empezar |

## Instalación

Hace falta Python 3.12+ y dos paquetes:

```bash
python -m pip install numpy pillow
```

Comprueba que el intérprete que usas es el que los tiene:

```bash
python -c "import numpy, PIL; print(numpy.__version__, PIL.__version__)"
```

## Uso

Sin instalar el paquete:

```bash
python -m theforge lito foto.jpg -o foto.stl --width 100 --frame 3
```

Instalado (deja el comando `forge` en el PATH; pip se descarga `hatchling` para construir):

```bash
pip install -e .
```

Ejemplo ejecutable, que genera su propia imagen de prueba y deja tres STL en
`examples/out/`:

```bash
python examples/lito_demo.py
```

Tests:

```bash
python -m pytest
```

### Opciones de `forge lito`

| Opción | Por defecto | Qué hace |
| --- | --- | --- |
| `--width` | 100 | ancho de la pieza en mm; el alto sale del aspecto de la imagen. Ignorado en `sphere` |
| `--min-thickness` | 0.8 | grosor en las zonas claras |
| `--max-thickness` | 3.0 | grosor en las zonas oscuras |
| `--curve` | `flat` | `flat`, `cylindrical` o `sphere` |
| `--arc` | 180 | grados de arco si es cilíndrica; **360 cierra el cilindro sin costura** |
| `--diameter` | 100 | diámetro de la esfera en mm |
| `--lat-min` | −45 | latitud del corte inferior de la esfera (la boca del cableado) |
| `--lat-max` | 75 | latitud del corte superior (el respiradero); ignorado con `--fit conformal` |
| `--fit` | `stretch` | reparto de la imagen sobre la esfera: `stretch` o `conformal` |
| `--repeat` | 1 | copias de la imagen alrededor de la pieza |
| `--samples` | 300 | muestras a lo ancho; sube el detalle y el tamaño del fichero |
| `--frame` | 0 | marco macizo al grosor máximo, en mm |
| `--gamma` | 1.0 | <1 aclara los medios tonos, >1 los oscurece |
| `--invert` | — | claro = grueso en vez de oscuro = grueso |

Ejemplos:

```bash
python -m theforge lito retrato.jpg --width 120 --max-thickness 3.2 --frame 4 --gamma 0.8
```

```bash
python -m theforge lito paisaje.png --curve cylindrical --arc 360 --width 180 --samples 500
```

Lámpara esférica con la foto repetida tres veces alrededor:

```bash
python -m theforge lito retrato.jpg --curve sphere --diameter 120 --repeat 3 --samples 720 --frame 6
```

### La esfera

La esfera va truncada arriba y abajo. No es un capricho: sin truncar habría
triángulos degenerados en los polos, y además sería inimprimible. Los dos cortes
dejan la boca de abajo (portalámparas y cable) y el respiradero de arriba.

- **`--lat-min` lo manda la impresión, no el cable.** En una esfera la pendiente
  de la pared es `dr/dz = −tan(latitud)`, así que el voladizo respecto a la
  vertical coincide con la latitud del corte. A −45° el voladizo máximo es de 45°
  y se imprime sin soportes; por debajo de eso hacen falta, justo sobre la
  superficie que se ve. El precio es una boca grande: `2·R·cos(45°) ≈ 1,41·R`.
- **`--lat-max` no debe pasar de ~80°.** Más arriba la pared se vuelve casi
  horizontal y cada capa se desplaza hacia dentro más de lo que mide el grosor,
  o sea que tendría que puentear al aire.
- **Usa `--frame` siempre en la esfera.** El borde exterior está a radio
  `R + grosor`, y el grosor lo pone la imagen: sin marco el corte inferior queda
  ondulado (~1,6 mm de diferencia) y la lámpara se apoya en cuatro puntos. El
  marco fuerza esa banda al grosor máximo y el borde sale uniforme. El CLI avisa.
- **`--repeat` fija la proporción.** Lo que manda es el trozo de superficie que le
  toca a cada copia: `(360/repeat) : banda`. Con la banda por defecto (−45° a
  75°), un tercio del ecuador es exactamente cuadrado, así que `--repeat 3` es la
  proporción correcta para una foto cuadrada, sea cual sea el diámetro.

#### Deformación: no hay opción sin coste

Una esfera no se puede desplegar en un plano sin deformar algo (Gauss). Solo se
elige **qué** se deforma:

- **`--fit stretch`** (por defecto) es la proyección **equirectangular**: las
  latitudes se reparten por igual. La escala horizontal vale entonces `cos(λ)`,
  o sea que la imagen sale fiel solo en el ecuador y comprimida hacia los polos
  (con la banda por defecto, hasta el 26 % en el borde de arriba). Eso **no es un
  fallo**: es lo que pasa al meter una foto normal donde el formato espera una
  imagen ya pre-deformada. Para envolver una esfera **completa** con una sola
  copia, la fuente correcta es un equirectangular **2:1**.
- **`--fit conformal`** espacia las latitudes según `1/cos(λ)` (Mercator
  inverso), de modo que las formas quedan correctas en toda la superficie. A
  cambio la banda deja de elegirse: sale de `--lat-min`, `--repeat` y la
  proporción de la imagen. Y como el motivo se recoloca en latitud, hay que
  mirar dónde acaba: con `--repeat 2` sube demasiado y se escorza; con
  `--repeat 3` queda bien centrado pero el corte superior baja a 57° y la pieza
  parece más un cuenco que una esfera.

Consejo práctico que vale para las tres: **recorta la foto al motivo**. Una
selfie con medio encuadre de ropa oscura convierte media lámpara en una zona
lisa de 3 mm.

## Lámpara con medallón y ornamento

Repetir la misma foto tres veces alrededor funciona, pero se nota. La
alternativa es un **medallón** con una sola foto y ornamento rellenando el
resto, que es como se resolvía esto en un objeto decorativo de verdad. Son dos
pasos:

```bash
python -m theforge ornament retrato.jpg --style acanthus -o banda.png
```

```bash
python -m theforge lito banda.png --curve sphere --diameter 120 --repeat 1 --frame 6 -o lampara.stl
```

El primer comando imprime el segundo ya montado, con las latitudes que le
correspondan.

### Estilos

Todas las piezas se construyen igual —una espina curva, un perfil de ancho, y un
polígono relleno con contorno— pero cada estilo usa una **forma** distinta,
porque no son variaciones del mismo dibujo sino lenguajes diferentes:

| Estilo | Forma | Qué es | Tinta |
| --- | --- | --- | --- |
| `acanthus` | `hoja` | raquis con folíolos alternos, nervados y solapados | ~48 % |
| `blackmetal` | `astilla` | maraña de filamentos ramificados con púas | ~37 % |
| `fern` | `llama` | haces de púas afiladas que se cruzan en abanico | ~33 % |

Lo que separa una hoja de una púa no es el grosor: la hoja tiene panza y punta
roma y el ancho se queda al 1 %; la púa afila a **cero exacto** por los dos
extremos y tiene los bordes hundidos. Y lo que separa la maraña de un helecho es
el ángulo con que brota la rama hija: a 60° sale una fronda, a 17° sale una
maraña barrida hacia fuera.

La variedad de la maraña no viene de `random` sino de una secuencia áurea, así
que el dibujo es el mismo en cada ejecución pero no tiene la regularidad que
delata que lo ha generado una máquina.

Para elegir sin generar un solo STL, la hoja de pruebas:

```bash
python -m theforge ornament retrato.jpg --sheet
```

### Proyectos de composición

El paso previo al editor visual: un JSON describe la pieza entera — forma,
fondo (patrón o gris) y fotos colocadas con posición, tamaño, máscara y gamma
propios. `forge compose` lo convierte en STL:

```bash
python -m theforge compose proyecto.json -o lampara.stl --band banda.png
```

```json
{
  "version": 1,
  "shape": {"curve": "sphere", "diameter_mm": 120, "min_thickness": 0.7,
            "max_thickness": 3.0, "frame_mm": 6, "samples": 720,
            "lat_min_deg": -45.0, "lat_max_deg": 75.0},
  "background": {"pattern": "acanthus"},
  "layers": [
    {"type": "photo", "path": "retrato.png", "cx": 0.5, "cy": 0.5,
     "scale": 0.8, "mask": "circle", "ring": true, "gamma": 1.0, "prewarp": true}
  ]
}
```

**El fondo** admite tres orígenes, excluyentes entre sí:

| | Qué es |
| --- | --- |
| `{"pattern": "acanthus"}` | uno de los patrones procedurales |
| `{"image": "grabado.png", "tile": 2, "mirror": true}` | una imagen tuya |
| `{"gray": 205}` | gris liso |

`mirror` repite cada copia seguida de su reflejo. Es lo que hace que **una
imagen cualquiera empalme al cerrar la pieza** sin exigir que sea teselable: el
borde derecho de una copia es idéntico al izquierdo de la siguiente, y el
último con el primero. Apágalo solo en piezas planas.

**`prewarp`** (por capa, solo afecta a la esfera) ensancha cada fila de la foto
por `1/cos(latitud)` para compensar lo que la esfera la va a comprimir. Va
encendido por defecto, y es lo que hace que un medallón salga circular y no
aperado. **Apágalo si la imagen ya viene equirectangular** —una panorámica 2:1,
o algo que hayas pre-deformado tú— o se deformará dos veces.

Ojo con **`fit: "conformal"`** en la esfera: el reparto conforme deriva el corte
superior de la proporción de la banda e **ignora `lat_max_deg`**, que ahí solo
decide la forma del ráster. El corte real —y por tanto el diámetro de la boca de
arriba— lo reportan `forge compose` y `/api/info`, que leen el layout y no el
parámetro.

Reglas del documento: `cx`/`cy` en fracciones de banda (fila 0 arriba),
`scale` = fracción del alto, la última capa pinta encima, las rutas se
resuelven relativas al JSON, y una clave desconocida es un **error**, no un
aviso — un typo silencioso sería un STL mal generado. En la esfera cada foto
se pre-deforma alrededor de su propio centro, y en las superficies cerradas
una capa que cruza la costura reaparece por el otro lado.

Ejemplo completo en [examples/compose_demo.py](examples/compose_demo.py).

Este JSON es el documento del futuro editor web (`forge studio`, en el
roadmap): el editor solo manipulará este fichero y la banda de píxeles que
devuelve el backend, nunca recalculará geometría por su cuenta.

### Grabar una foto sobre un STL cualquiera

`forge lito` y `forge compose` generan la forma desde cero. `forge emboss` hace
lo contrario: coge un STL que **ya existe** —un jarrón, una funda, un adorno
descargado o diseñado aparte— y le graba la foto encima como un medallón en
relieve, sin tocar el resto de la superficie.

```bash
python -m theforge emboss producto.stl retrato.jpg -o salida.stl \
  --max-bump 1.2 --height 55 --center-lat 10
```

**Antes de nada, la condición que no es de software: para que funcione como
litofanía de verdad, el STL de origen tiene que ser ya una cáscara hueca de
pared fina.** Grabar relieve en la superficie de un sólido macizo no sirve de
nada: la luz no atraviesa un bloque de PLA, por mucho relieve que tenga por
fuera. No hay forma barata de comprobar esto mirando solo el fichero —un STL no
dice si es hueco—, así que es responsabilidad de quien lo usa. `forge emboss`
lo recuerda en cada ejecución.

**Tampoco se puede añadir detalle que el STL de origen no tenga.** El relieve
sale tan fino como la propia malla esté teselada: un modelo de baja resolución
(pocos triángulos) da un relieve tosco, haga lo que haga la imagen.

Cómo funciona, por dentro:

1. La malla se indexa (`to_indexed_mesh`): vértices únicos + caras, no el
   *soup* de triángulos repetidos con el que trabaja el resto del repo.
2. Cada vértice se proyecta esféricamente alrededor del **centroide de sus
   propios vértices** — igual que la esfera de `lito.py` (Z arriba, longitud 0
   mirando hacia −Y), pero aplicado a una malla suelta en vez de a una rejilla
   regular. En formas muy asimétricas el centroide no coincide con el centro
   geométrico «intuitivo»; para casi cualquier objeto convexo razonable no se
   nota.
3. La imagen no envuelve la pieza entera —eso solo tiene sentido para un
   patrón repetible—: se coloca como un **medallón centrado**
   (`--center-lat`/`--center-lon`, `--height`), con un desvanecido
   (`--feather`) en el borde para que no quede un escalón visible. Fuera del
   medallón la superficie no se toca.
4. Cada vértice se desplaza a lo largo de su **propia normal** (media de las
   normales de las caras que lo tocan, ponderada por área) hacia fuera, la
   cantidad que marque el gris de la imagen en ese punto —oscuro = más bulto,
   por defecto, como en todo el repo.

Es un desplazamiento puro, sin tocar la conectividad: si el STL de origen era
cerrado, el resultado también lo es. Lo único que no se comprueba es si el
bulto es tan grande que la superficie se pliega sobre sí misma en una zona
cóncava o muy fina —eso `check_mesh` no lo detecta, solo mira aristas y
orientación— así que conviene revisar el resultado antes de imprimir,
especialmente con `--max-bump` alto sobre una forma poco convexa.

Ejemplo completo, con una forma de huevo escrita a mano (no generada por
`lito.py`, a propósito) en
[examples/emboss_demo.py](examples/emboss_demo.py).

**También desde el editor**, en el desplegable **Origen de la pieza** → `Importar
STL`. Cambia el panel entero: forma/fondo/capas desaparecen (no aplican a un
modelo ya existente) y solo queda un STL base + una foto + los controles del
medallón. Como el relieve no sale de una banda 2D sino de desplazar vértices
directamente, las pestañas Banda/Encendida no tienen sentido aquí —solo
**3D**— y **Exportar STL** llama a `/api/emboss` en vez de a `/api/stl`.
Guardar/cargar proyecto también funciona en este modo: el JSON lleva
`"mode": "emboss"` para que cargarlo vuelva a este mismo panel en vez del de
componer formas.

### El editor local

```bash
python -m theforge studio examples\out
```

Abre el navegador en `127.0.0.1:8756`. La carpeta que le pases es la **raíz del
proyecto**: de ahí salen las fotos que puedes elegir y ahí se guardan las que
importes.

| Endpoint | Qué hace |
| --- | --- |
| `GET /api/estilos` | patrones, formas y máscaras disponibles |
| `GET /api/imagenes` | imágenes de la carpeta raíz, recursivo |
| `POST /api/banda` | proyecto → PNG de la banda compuesta |
| `POST /api/encendida` | proyecto → PNG de la simulación a contraluz |
| `POST /api/info` | medidas, % de relieve y avisos de impresión |
| `POST /api/stl` | proyecto → STL binario, **409 si la malla no es cerrada** |
| `POST /api/subir` | guarda una imagen en la carpeta raíz |
| `GET /api/imagen?path=` | sirve una imagen del proyecto (miniaturas y proporciones) |
| `GET /api/stls` | STL de la carpeta raíz, para el modo «Importar STL» |
| `POST /api/subir_stl` | guarda un STL, comprobando que se puede leer como STL binario |
| `POST /api/emboss` | modelo + foto → STL grabado, **409 si no es cerrada** |

En el editor: arrastras las fotos sobre la banda, rueda para escalar, `Supr`
para borrar, y la lista de la derecha permite reordenarlas (la última se pinta
encima). Tres pestañas: **Banda**, **Encendida** y **3D** orbitable. Guardar y
cargar producen el mismo JSON que entiende `forge compose`.

Decisiones que sostienen el diseño:

- **Sin estado.** El proyecto entero viaja en cada petición y el servidor no
  guarda nada entre llamadas. No hay sesión que se desincronice del navegador,
  ni orden de peticiones que respetar, ni recarga que deje algo a medias.
- **Solo `127.0.0.1`**, y toda ruta de fichero se resuelve dentro de la carpeta
  raíz y se rechaza si escapa. Un proyecto es un JSON con rutas dentro; sin ese
  filtro, pedir `../../../windows/...` sería leer lo que le diera la gana.
- **Los nombres de subida se rechazan, no se sanean.** Guardar `../secreto.png`
  como `secreto.png` sería hacer algo distinto de lo pedido sin decirlo.
- **Exportar pasa por el servidor** porque el único sitio donde se puede
  comprobar la malla es donde se construye. Si `check_mesh` no la da cerrada,
  devuelve 409 y no hay fichero.

Dos detalles que sorprenden al usarlo y no son fallos:

- La pestaña **Banda** sale al ancho del raster (1400 px por defecto) y la de
  **Encendida** al ancho de `samples`, que es la resolución real del mapa de
  grosores. La vista encendida enseña el detalle que de verdad va a tener la
  pieza: si se ve pixelada, es que te falta `samples`.
- La vista **3D** recorta `samples` a 320 para orbitar con fluidez (~140k
  triángulos en vez de millones). Lo que exportas usa el valor que hayas puesto.

#### El visor 3D no usa librerías

Estaba previsto vendorizar `three.js`, pero un visor de STL necesita muy poco:
parsear el binario, una cámara con órbita y un shader difuso. Son ~250 líneas en
[visor3d.js](theforge/studio_web/visor3d.js) y el repo sigue sin una sola
dependencia de terceros. El sombreado es **facetado a propósito** —usa la normal
que ya trae cada triángulo del STL— porque para revisar una pieza interesa ver
las facetas del muestreo, no disimularlas.

### Ajustar un estilo

```bash
python -m theforge tune --style acanthus
```

Ventana con sliders (tkinter, que viene con Python: sin dependencias nuevas).
Regenerar el dibujo cuesta entre 11 y 55 ms a tamaño de previsualización, así
que arrastrar va fluido; los eventos se agrupan cada 60 ms para no encolar un
redibujado por píxel.

Tres decisiones de diseño que importan:

- **Los sliders salen de `dataclasses.fields(Style)`**, no de una lista escrita
  a mano. Al añadir un parámetro nuevo aparece solo. Hay un test que lo fija.
- **Enseña dos vistas a la vez**: una pieza suelta y el campo completo. Los
  fallos de forma solo se ven en la pieza aislada —el acanto parecía aceptable
  hasta que se miró una hoja sola y resultó ser una sierra— y los de reparto
  solo en el campo. Con una sola de las dos se afina a ciegas.
- **No guarda nada ni edita el código.** El botón copia un `Style(...)` al
  portapapeles y lo pegas tú en `STYLES`. Sin estado oculto ni ficheros que se
  desincronicen. El fragmento omite los campos que no has tocado, y hay un test
  que comprueba que al evaluarlo sale el mismo `Style`.

La GUI en sí no está en los tests; lo que sí está es todo lo que puede romperse
en silencio (construcción de sliders y serialización).

Dos detalles del diseño:

- **El dibujo empalma solo.** Se dibuja la mitad derecha y se espeja, con lo que
  el campo es simétrico respecto del centro *y* de los bordes: la primera y la
  última columna acaban siendo idénticas, que es justo lo que hace falta al
  cerrar la esfera. Hay un test que lo comprueba.
- **El medallón se pre-deforma.** Cada fila se ensancha por `1/cos(λ)` antes de
  recortarla en círculo, así que sobre la esfera se ve circular en vez de
  aperado. Es la pre-deformación que lleva un equirectangular de verdad, y aquí
  se puede aplicar porque la imagen la generamos nosotros.

Si el ornamento se ve poco a contraluz, lo que hay que tocar es el gris del
fondo (`FONDO` en `ornament.py`), no los grosores.

### El límite que impone la boquilla

`blackmetal` tiene un `ancho_minimo` que impide que ningún filamento baje de
~0,9 mm sobre la pieza, o sea dos líneas de boquilla. No es una decisión
estética: un trazo más fino que un píxel no sale fino, **sale gris** — y un gris
intermedio en una litofanía es grosor intermedio, es decir una superficie lisa
donde debería haber un filamento.

Eso pone un techo aritmético al estilo: los filamentos crecen como
`hijas ^ niveles`, y cada uno ocupa como mínimo ese ancho. Con 5 niveles y 3
hijas la banda sale al 86 % de tinta, o sea negra. Por eso son 4 niveles y 2
hijas. **En una esfera más grande cabrían más**, porque el mínimo es absoluto en
milímetros y la superficie crece con el cuadrado del diámetro.

### Cómo funciona

Imagen → escala de grises → remuestreo a la rejilla (LANCZOS, que hace de
antialias) → grosor invertido (`oscuro = grueso`) → dos rejillas de vértices
(cara frontal con relieve y cara trasera lisa) cosidas por el borde.

La pieza sale **ya orientada para imprimir de pie**: X = ancho, Z = alto, apoyada
en Z = 0, con el grosor creciendo hacia −Y y la cara trasera en el plano Y = 0. En
la cilíndrica y la esférica el eje es Z y la cara interior es lisa. Mirando la
pieza desde fuera, la imagen se ve sin espejar.

Las tres formas comparten la misma malla: dos rejillas de vértices con idéntica
topología cosidas por el borde. Cambia solo el mapeo de `(u, v)` a coordenadas.
La esfera y el cilindro de 360° se cierran sobre sí mismos en `u`, así que tienen
topología de toro en vez de esfera — su característica de Euler es 0, no 2, y eso
es correcto.

Cada malla se valida antes de escribirla: cada arista debe aparecer en
exactamente dos triángulos y recorrida en sentidos opuestos, sin triángulos
degenerados, y el volumen con signo debe ser positivo (normales hacia fuera).
`forge lito` imprime ese informe y devuelve código de salida 1 si algo falla.

## Parámetros de impresión recomendados

> **Aviso: todavía no tengo impresora.** Nada de esto está verificado con una
> pieza real. Son los valores de partida convencionales para litofanías. Van
> marcados como `[SUPUESTO]` cuando no los he podido comprobar de ninguna forma,
> y como `[GEOMETRÍA]` cuando salen del propio generador y sí son ciertos.

Impresora prevista: Bambu Lab A1, boquilla 0.4, Bambu Studio / Orca.

- `[GEOMETRÍA]` La pieza llega al slicer de pie y apoyada en la cama: **no hay que
  rotarla y no hacen falta soportes**. Apoya sobre el canto inferior, no sobre la
  cara trasera.
- `[SUPUESTO]` Altura de capa **0.08–0.12 mm**. Al imprimirse de pie, la altura de
  capa es la resolución vertical de la imagen: más fina = degradados más suaves y
  mucho más tiempo.
- `[SUPUESTO]` **Relleno 100 %** y perímetros suficientes para que no queden huecos
  internos: cualquier hueco se ve como una mancha al trasluz.
- `[SUPUESTO]` Grosor mínimo **0.8 mm** = 2 líneas de 0.4. Bajar de ahí deja pasar
  más luz pero la pieza queda frágil y con riesgo de huecos.
- `[SUPUESTO]` Grosor máximo **3.0–3.2 mm** con PLA blanco. Más grueso no aporta
  más negro y sí mucho tiempo.
- `[SUPUESTO]` Material: **PLA blanco o natural, opaco y mate**. Los translúcidos y
  los brillantes dispersan mal y bajan el contraste. Nada de PLA con purpurina.
- `[SUPUESTO]` Velocidad baja (~30–50 mm/s) en paredes externas y refrigeración al
  100 %: son paredes finas y muy altas.
- `[SUPUESTO]` **Brim**: la huella es una línea de 1–3 mm de ancho y la pieza es
  alta.
- `[SUPUESTO]` La A1 mueve la cama en Y. Una placa alta y plana con la cara
  perpendicular a Y presenta la máxima superficie al eje que acelera; si sale con
  fantasmas (*ringing*), probar a girarla 90° en el plato.
- `[SUPUESTO]` `--gamma 0.8` suele hacer falta con fotos oscuras: si no, los medios
  tonos se van todos a grosor máximo y la litofanía sale "quemada" en negro.
- `[SUPUESTO]` Retroiluminar con LED difuso blanco cálido, no con un LED puntual.

Para la lámpara esférica, además:

- `[GEOMETRÍA]` Con `--lat-min -45` el voladizo máximo es de 45°, en el arranque.
  No necesita soportes si tu perfil aguanta 45°, que es lo normal.
- `[GEOMETRÍA]` La pieza apoya en un círculo del diámetro de la boca inferior. Es
  un chaflán a 45°, o sea que la primera capa es una línea muy fina que se
  ensancha enseguida. **Brim obligatorio.**
- `[SUPUESTO]` El LED va dentro, así que el calor se acumula: de ahí el
  respiradero de arriba. Con LED es poca cosa, pero no la cierres del todo.
- `[SUPUESTO]` Una esfera de 120 mm son ~120 g de PLA y bastantes horas. Antes de
  lanzarla, imprime una litofanía plana con la misma foto y los mismos grosores
  para validar el contraste.

Cuando tenga la A1 y una tirada real, este apartado se reescribe con números
medidos y desaparecen los `[SUPUESTO]`.

## Roadmap

Nada de esto está implementado todavía.

- **`coste.py`** — lee un `.gcode`, saca gramos y tiempo reales del fichero (no
  estimaciones a ojo), y calcula precio de venta y margen. Sustituirá los números
  inventados de mis notas.
- **`gcode.py`** — análisis previo del fichero: voladizos, puentes, tiempo por
  capa, dónde se va a atascar.
- **`gridfinity.py`** — organizadores de cajón paramétricos, reaprovechando el
  escritor de STL y el cosido de superficies de `stl.py`.
- **`bambu.py`** — control local por MQTT en modo LAN-only, cuando tenga la A1.
- **Editor web** — ~~las tres fases~~ **hecho**: `compose.py`, `studio.py` y el
  editor de [studio_web/](theforge/studio_web/). Quedan ideas para más adelante:
  rotación de capas, patrón por regiones en vez de fondo completo, presets con
  nombre, y varias piezas en un mismo proyecto.

## Estructura

```
theforge/
  theforge/
    __init__.py
    __main__.py     # python -m theforge
    stl.py          # STL binario + utilidades de malla
    lito.py         # generador de litofanías
    cli.py          # subcomandos: forge lito ...
  tests/
  examples/
  pyproject.toml
```

Los STL y los G-code no se versionan (ver `.gitignore`).
