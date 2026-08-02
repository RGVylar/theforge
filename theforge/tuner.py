"""Ajuste interactivo de estilos de ornamento, con tkinter.

Los sliders se construyen recorriendo los campos del dataclass Style, no una
lista escrita a mano: al anadir un parametro nuevo aparece solo, sin tocar nada
aqui. Los rangos se deducen del valor por defecto, con excepciones para los
pocos donde ese rango no vale.

La ventana no guarda nada ni edita el codigo. Produce un fragmento
`Style(...)` que se copia al portapapeles y lo pegas tu en STYLES. Sin estado
oculto y sin ficheros que se desincronicen.

Ensena dos vistas a la vez -una pieza suelta y el campo completo- porque los
fallos de forma solo se ven en la pieza aislada y los de reparto solo en el
campo. Con una sola de las dos se afina a ciegas.
"""

from __future__ import annotations

import dataclasses
from dataclasses import fields

from PIL import Image

from theforge.ornament import POR_DEFECTO, STYLES, Style, ornament_field, single_piece

# Rangos donde deducirlos del valor por defecto da algo inutil.
RANGOS: dict[str, tuple[float, float]] = {
    "apertura_hija": (0.05, 1.60),  # el que separa maraña de helecho
    "merma": (0.30, 0.90),
    "merma_ancho": (0.30, 0.90),
    "dorso": (0.05, 1.00),
    "canto": (0.0, 0.02),
    "desenfoque": (0.0, 0.02),
    "ancho_minimo": (0.0, 0.03),
    "niveles": (0, 6),  # crece como hijas^niveles: pasarse llena la banda
    "hijas": (1, 5),
}

# Campos que no son un numero que tenga sentido arrastrar.
IGNORADOS = frozenset({"nombre", "forma", "ramos"})


@dataclasses.dataclass(frozen=True)
class Parametro:
    nombre: str
    valor: float
    minimo: float
    maximo: float
    entero: bool


def parametros(estilo: Style) -> list[Parametro]:
    """Los campos ajustables del estilo, con su rango.

    Sale de dataclasses.fields, asi que un campo nuevo en Style aparece aqui
    sin tocar este modulo.
    """
    salida = []
    for campo in fields(estilo):
        if campo.name in IGNORADOS or campo.type not in ("int", "float"):
            continue
        valor = getattr(estilo, campo.name)
        entero = campo.type == "int"
        if campo.name in RANGOS:
            minimo, maximo = RANGOS[campo.name]
        elif entero:
            minimo, maximo = 0, max(2, valor * 3)
        else:
            # Suficiente margen para explorar sin perder resolucion al arrastrar.
            minimo, maximo = 0.0, max(1.0, abs(valor) * 3.0)
        salida.append(Parametro(campo.name, valor, minimo, maximo, entero))
    return salida


def formatear_style(estilo: Style, nombre: str | None = None) -> str:
    """Fragmento `Style(...)` listo para pegar en STYLES.

    Solo se escriben los campos que difieren del valor por defecto, que es lo
    que hace el fragmento legible en vez de un muro de treinta lineas.
    """
    partes = [f'nombre="{nombre or estilo.nombre}"']
    for campo in fields(estilo):
        if campo.name == "nombre":
            continue
        valor = getattr(estilo, campo.name)
        if valor == campo.default:
            continue
        partes.append(f"{campo.name}={valor!r}")
    cuerpo = ",\n    ".join(partes)
    return f"Style(\n    {cuerpo},\n)"


def _previsualizaciones(estilo: Style, ancho: int) -> tuple[Image.Image, Image.Image]:
    """Pieza suelta y campo completo, a tamano de ventana."""
    return (
        single_piece((ancho, ancho // 2), estilo),
        ornament_field((ancho, ancho // 3), estilo),
    )


def abrir(estilo_inicial: str = POR_DEFECTO, ancho: int = 640, bucle: bool = True):
    """Abre la ventana de ajuste. Requiere tkinter.

    Con bucle=False monta todo y devuelve la ventana sin entrar en el bucle de
    eventos, que es la unica forma de comprobar que la GUI se construye sin
    quedarse colgada esperando a que alguien la cierre.
    """
    try:
        import tkinter as tk
        from tkinter import ttk

        from PIL import ImageTk
    except ImportError as err:  # pragma: no cover - depende de la instalacion
        raise RuntimeError(
            "hace falta tkinter para 'forge tune'; usa 'forge ornament --sheet'"
        ) from err

    raiz = tk.Tk()
    raiz.title("theforge - ajuste de ornamento")
    estado: dict[str, object] = {"estilo": STYLES[estilo_inicial], "pendiente": None}

    izquierda = ttk.Frame(raiz, padding=8)
    izquierda.grid(row=0, column=0, sticky="ns")
    derecha = ttk.Frame(raiz, padding=8)
    derecha.grid(row=0, column=1, sticky="nsew")

    lienzo_pieza = ttk.Label(derecha)
    lienzo_pieza.grid(row=0, column=0, pady=(0, 6))
    lienzo_campo = ttk.Label(derecha)
    lienzo_campo.grid(row=1, column=0)
    pie = ttk.Label(derecha, text="")
    pie.grid(row=2, column=0, sticky="w", pady=(6, 0))

    def redibujar() -> None:
        estilo = estado["estilo"]
        pieza, campo = _previsualizaciones(estilo, ancho)
        # Hay que guardar la referencia o el recolector se lleva la imagen.
        estado["img_pieza"] = ImageTk.PhotoImage(pieza)
        estado["img_campo"] = ImageTk.PhotoImage(campo)
        lienzo_pieza.configure(image=estado["img_pieza"])
        lienzo_campo.configure(image=estado["img_campo"])
        from theforge.ornament import ink_fraction

        pie.configure(text=f"{estilo.forma}  |  {ink_fraction(campo):.0%} de tinta")

    def pedir_redibujado() -> None:
        # Arrastrar un slider dispara decenas de eventos: se agrupan para no
        # encolar un redibujado por pixel.
        if estado["pendiente"] is not None:
            raiz.after_cancel(estado["pendiente"])
        estado["pendiente"] = raiz.after(60, redibujar)

    def al_mover(nombre: str, param: Parametro, etiqueta: ttk.Label):
        def manejador(valor: str) -> None:
            numero = int(float(valor)) if param.entero else round(float(valor), 4)
            estado["estilo"] = dataclasses.replace(estado["estilo"], **{nombre: numero})
            etiqueta.configure(text=f"{nombre}  {numero}")
            pedir_redibujado()

        return manejador

    def construir_sliders() -> None:
        for hijo in izquierda.winfo_children():
            hijo.destroy()

        selector = ttk.Combobox(
            izquierda, values=list(STYLES), state="readonly", width=18
        )
        selector.set(estado["estilo"].nombre)
        selector.grid(sticky="ew", pady=(0, 8))

        def cambiar_estilo(_evento) -> None:
            estado["estilo"] = STYLES[selector.get()]
            construir_sliders()
            redibujar()

        selector.bind("<<ComboboxSelected>>", cambiar_estilo)

        for param in parametros(estado["estilo"]):
            etiqueta = ttk.Label(izquierda, text=f"{param.nombre}  {param.valor}")
            etiqueta.grid(sticky="w")
            barra = ttk.Scale(
                izquierda,
                from_=param.minimo,
                to=param.maximo,
                value=param.valor,
                command=al_mover(param.nombre, param, etiqueta),
            )
            barra.grid(sticky="ew", pady=(0, 4))

        def copiar() -> None:
            raiz.clipboard_clear()
            raiz.clipboard_append(formatear_style(estado["estilo"]))
            pie.configure(text="Style copiado al portapapeles")

        ttk.Button(izquierda, text="Copiar Style", command=copiar).grid(
            sticky="ew", pady=(10, 2)
        )
        ttk.Button(izquierda, text="Reiniciar", command=cambiar_estilo_actual).grid(
            sticky="ew"
        )

    def cambiar_estilo_actual() -> None:
        estado["estilo"] = STYLES[estado["estilo"].nombre]
        construir_sliders()
        redibujar()

    construir_sliders()
    redibujar()
    if not bucle:
        return raiz
    raiz.mainloop()
    return None
