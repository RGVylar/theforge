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
| `lito.py` | generador de litofanías (plana y cilíndrica) |
| `cli.py` | `forge lito ...` |
| resto del roadmap | sin empezar |

## Uso

Sin instalar nada:

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
| `--width` | 100 | ancho de la pieza en mm; el alto sale del aspecto de la imagen |
| `--min-thickness` | 0.8 | grosor en las zonas claras |
| `--max-thickness` | 3.0 | grosor en las zonas oscuras |
| `--curve` | `flat` | `flat` o `cylindrical` |
| `--arc` | 180 | grados de arco si es cilíndrica; **360 cierra el cilindro sin costura** |
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

### Cómo funciona

Imagen → escala de grises → remuestreo a la rejilla (LANCZOS, que hace de
antialias) → grosor invertido (`oscuro = grueso`) → dos rejillas de vértices
(cara frontal con relieve y cara trasera lisa) cosidas por el borde.

La pieza sale **ya orientada para imprimir de pie**: X = ancho, Z = alto, apoyada
en Z = 0, con el grosor creciendo hacia −Y y la cara trasera en el plano Y = 0. En
la cilíndrica, el eje es Z y la cara interior es un cilindro liso de radio
`ancho / ángulo_en_radianes`. Mirando la pieza desde fuera, la imagen se ve sin
espejar.

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
