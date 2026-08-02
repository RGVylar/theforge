// Editor de composiciones.
//
// Regla que sostiene todo esto: el frontend NUNCA calcula geometria. La banda
// que devuelve el servidor es el mismo raster del que sale el mapa de
// grosores, asi que aqui solo se traducen pixeles de pantalla a fracciones de
// esa banda. Lo que ves es lo que se imprime por construccion, no porque dos
// codigos coincidan.
//
// El estado vive en `proyecto`, que es literalmente el JSON que entiende
// compose.py. Guardar es volcarlo; cargar es reemplazarlo.

import { crearVisor } from "./visor3d.js";

const $ = (id) => document.getElementById(id);

const CAMPOS_FORMA = {
  flat: [["width_mm", "Ancho (mm)"], ["height_mm", "Alto (mm)"]],
  cylindrical: [["width_mm", "Ancho (mm)"], ["height_mm", "Alto (mm)"],
                ["arc_degrees", "Arco (°)"]],
  sphere: [["diameter_mm", "Diámetro (mm)"], ["lat_min_deg", "Latitud abajo (°)"],
           ["lat_max_deg", "Latitud arriba (°)"]],
};

const PREDETERMINADOS = {
  flat: { width_mm: 120, height_mm: 90 },
  cylindrical: { width_mm: 160, height_mm: 110, arc_degrees: 360 },
  sphere: { diameter_mm: 120, lat_min_deg: -45, lat_max_deg: 75 },
};

let proyecto = {
  version: 1,
  shape: { curve: "sphere", min_thickness: 0.7, max_thickness: 3.0,
           frame_mm: 6, samples: 300, ...PREDETERMINADOS.sphere },
  background: { pattern: "acanthus" },
  layers: [],
};

let seleccion = -1;
let vista = "banda";
let visor = null;
let temporizador = null;
const aspectos = new Map();  // ruta -> alto/ancho, para dibujar bien las cajas

// --- red ------------------------------------------------------------------

async function pedir(ruta, cuerpo) {
  const r = await fetch(ruta, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cuerpo),
  });
  if (!r.ok) {
    const detalle = await r.json().catch(() => ({}));
    throw new Error(detalle.error || `${r.status} ${r.statusText}`);
  }
  return r;
}

// Devuelve el aspecto ya conocido, o 1 mientras se carga. Es sincrona a
// proposito: pintarCajas() corre dentro de un arrastre y no puede permitirse
// un await, que dejaria el DOM a medias entre dos movimientos del raton.
function aspectoDe(ruta) {
  if (aspectos.has(ruta)) return aspectos.get(ruta);
  aspectos.set(ruta, 1);
  const img = new Image();
  img.onload = () => {
    aspectos.set(ruta, img.naturalHeight / img.naturalWidth);
    pintarCajas();
  };
  img.src = "/api/imagen?path=" + encodeURIComponent(ruta);
  return 1;
}

// --- render ---------------------------------------------------------------

function pedirRefresco(ms = 220) {
  clearTimeout(temporizador);
  temporizador = setTimeout(refrescar, ms);
}

async function refrescar() {
  $("estado").textContent = "generando…";
  $("avisos").textContent = "";
  try {
    if (vista === "modelo") {
      // Para orbitar no hace falta la resolucion de exportar: se manda una
      // copia con menos muestras y baja de millones de triangulos a miles.
      // 320 deja ~140k triangulos, que WebGL mueve de sobra, y el relieve ya
      // no se ve escalonado como a 200.
      const ligero = structuredClone(proyecto);
      ligero.shape.samples = Math.min(proyecto.shape.samples, 320);
      const buffer = await (await pedir("/api/stl", ligero)).arrayBuffer();
      const malla = visor.cargar(buffer);
      $("estado").textContent = `${malla.triangulos.toLocaleString("es")} triángulos` +
        `\ncaja ${malla.max.map((m, i) => (m - malla.min[i]).toFixed(0)).join(" × ")} mm`;
      return;
    }

    const r = await pedir("/api/" + vista, proyecto);
    const anterior = $("vista").src;
    $("vista").src = URL.createObjectURL(await r.blob());
    if (anterior.startsWith("blob:")) URL.revokeObjectURL(anterior);

    const info = await (await pedir("/api/info", proyecto)).json();
    const e = info.esfera;
    $("estado").textContent =
      `${info.superficie_mm.ancho} × ${info.superficie_mm.alto} mm` +
      `  ·  ${Math.round(info.relieve * 100)}% con relieve` +
      (e ? `\nbocas ${e.boca_abajo_mm} / ${e.boca_arriba_mm} mm · voladizo ${e.voladizo_grados}°` : "");
    $("avisos").textContent = (info.avisos || []).join("\n");
  } catch (err) {
    $("estado").textContent = "error: " + err.message;
  }
}

// --- capas sobre la banda -------------------------------------------------

// Reutiliza los divs existentes en vez de rehacerlos. Recrearlos en cada
// movimiento destruia el elemento que tenia capturado el puntero a mitad del
// arrastre: la captura se perdia y el arrastre se soltaba solo.
function pintarCajas() {
  const overlay = $("capas-overlay");
  while (overlay.children.length > proyecto.layers.length) overlay.lastChild.remove();
  while (overlay.children.length < proyecto.layers.length) {
    overlay.appendChild(document.createElement("div"));
  }

  const altoBanda = bandaAspecto();
  proyecto.layers.forEach((capa, i) => {
    const aspecto = capa.mask === "circle" ? 1 : aspectoDe(capa.path);
    // scale es fraccion del ALTO de la banda; el ancho sale de la proporcion.
    const alto = capa.scale;
    const ancho = (capa.scale * altoBanda) / aspecto;

    const caja = overlay.children[i];
    caja.className = "caja" + (i === seleccion ? " activa" : "");
    caja.dataset.indice = String(i);
    caja.dataset.mask = capa.mask;
    caja.style.left = `${(capa.cx - ancho / 2) * 100}%`;
    caja.style.top = `${(capa.cy - alto / 2) * 100}%`;
    caja.style.width = `${ancho * 100}%`;
    caja.style.height = `${alto * 100}%`;
  });
}

function bandaAspecto() {
  // alto/ancho de la banda, para convertir "fraccion de alto" a "fraccion de
  // ancho" al dibujar las cajas. Sale de la propia imagen que sirve el backend.
  const img = $("vista");
  return img.naturalWidth ? img.naturalHeight / img.naturalWidth : 1 / 3;
}

function instalarArrastre() {
  const overlay = $("capas-overlay");
  let arrastre = null;

  overlay.addEventListener("pointerdown", (ev) => {
    const caja = ev.target.closest(".caja");
    if (!caja) return;
    seleccionar(Number(caja.dataset.indice));
    const rect = $("vista").getBoundingClientRect();
    const capa = proyecto.layers[seleccion];
    arrastre = {
      rect,
      dx: capa.cx - (ev.clientX - rect.left) / rect.width,
      dy: capa.cy - (ev.clientY - rect.top) / rect.height,
    };
    caja.classList.add("arrastrando");
    // Con un puntero sintetico (tests) no hay puntero activo que capturar.
    try { caja.setPointerCapture(ev.pointerId); } catch { /* da igual */ }
    ev.preventDefault();
  });

  overlay.addEventListener("pointermove", (ev) => {
    if (!arrastre) return;
    const capa = proyecto.layers[seleccion];
    // Unica conversion de coordenadas del frontend: pixel de pantalla ->
    // fraccion de banda. Ninguna geometria, solo regla de tres.
    const cx = (ev.clientX - arrastre.rect.left) / arrastre.rect.width + arrastre.dx;
    const cy = (ev.clientY - arrastre.rect.top) / arrastre.rect.height + arrastre.dy;
    capa.cx = Math.min(1, Math.max(0, cx));
    capa.cy = Math.min(1, Math.max(0, cy));
    pintarCajas();
    pedirRefresco();
  });

  const soltar = () => {
    if (!arrastre) return;
    arrastre = null;
    overlay.querySelectorAll(".arrastrando").forEach((c) => c.classList.remove("arrastrando"));
    refrescar();
  };
  overlay.addEventListener("pointerup", soltar);
  overlay.addEventListener("pointercancel", soltar);

  overlay.addEventListener("wheel", (ev) => {
    const caja = ev.target.closest(".caja");
    if (!caja) return;
    ev.preventDefault();
    const capa = proyecto.layers[Number(caja.dataset.indice)];
    capa.scale = Math.min(1.4, Math.max(0.05, capa.scale * (1 - ev.deltaY * 0.0012)));
    seleccionar(Number(caja.dataset.indice));
    pintarCajas();
    pedirRefresco();
  }, { passive: false });

  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Delete" && ev.key !== "Backspace") return;
    if (document.activeElement !== document.body) return;  // no robar teclas a los inputs
    if (seleccion < 0) return;
    borrarCapa();
  });
}

// --- lista de capas -------------------------------------------------------

function pintarLista() {
  const lista = $("lista-capas");
  lista.textContent = "";
  proyecto.layers.forEach((capa, i) => {
    const li = document.createElement("li");
    li.setAttribute("aria-selected", String(i === seleccion));
    const img = document.createElement("img");
    img.src = "/api/imagen?path=" + encodeURIComponent(capa.path);
    img.alt = "";
    const nombre = document.createElement("span");
    nombre.textContent = capa.path;
    li.append(img, nombre);
    li.onclick = () => seleccionar(i);
    lista.appendChild(li);
  });

  const capa = proyecto.layers[seleccion];
  $("detalle-capa").hidden = !capa;
  if (capa) {
    $("capa-scale").value = capa.scale;
    $("capa-gamma").value = capa.gamma;
    $("capa-mask").value = capa.mask;
    $("capa-ring").checked = capa.ring;
  }
}

function seleccionar(i) {
  seleccion = i;
  pintarLista();
  pintarCajas();
}

function anadirCapa(ruta) {
  proyecto.layers.push({
    type: "photo", path: ruta, cx: 0.5, cy: 0.5,
    scale: 0.6, mask: "circle", ring: true, gamma: 1.0,
  });
  seleccionar(proyecto.layers.length - 1);
  refrescar();
}

function borrarCapa() {
  proyecto.layers.splice(seleccion, 1);
  seleccion = Math.min(seleccion, proyecto.layers.length - 1);
  pintarLista();
  pintarCajas();
  refrescar();
}

function moverCapa(salto) {
  const destino = seleccion + salto;
  if (destino < 0 || destino >= proyecto.layers.length) return;
  const [capa] = proyecto.layers.splice(seleccion, 1);
  proyecto.layers.splice(destino, 0, capa);
  seleccionar(destino);
  refrescar();
}

// --- panel de forma -------------------------------------------------------

function pintarCamposForma() {
  const contenedor = $("campos-forma");
  contenedor.textContent = "";
  for (const [clave, titulo] of CAMPOS_FORMA[proyecto.shape.curve]) {
    const label = document.createElement("label");
    label.className = "medio";
    label.textContent = titulo;
    label.htmlFor = "forma-" + clave;
    const input = document.createElement("input");
    input.type = "number";
    input.id = "forma-" + clave;
    input.step = "1";
    input.value = proyecto.shape[clave];
    input.onchange = () => {
      proyecto.shape[clave] = parseFloat(input.value);
      refrescar();
    };
    contenedor.append(label, input);
  }
}

function cambiarForma(curva) {
  const s = proyecto.shape;
  for (const campos of Object.values(CAMPOS_FORMA)) {
    for (const [clave] of campos) delete s[clave];
  }
  Object.assign(s, { curve: curva }, PREDETERMINADOS[curva]);
  pintarCamposForma();
  refrescar();
}

// --- proyecto -------------------------------------------------------------

function guardarProyecto() {
  const blob = new Blob([JSON.stringify(proyecto, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  Object.assign(document.createElement("a"), { href: url, download: "proyecto.json" }).click();
  URL.revokeObjectURL(url);
  $("estado").textContent = "proyecto guardado";
}

async function cargarProyecto(fichero) {
  try {
    const datos = JSON.parse(await fichero.text());
    if (datos.version !== 1) throw new Error(`versión ${datos.version} no soportada`);
    proyecto = datos;
    seleccion = proyecto.layers.length ? 0 : -1;
    $("curve").value = proyecto.shape.curve;
    sincronizarPanel();
    await refrescar();
    pintarLista();
    pintarCajas();
  } catch (err) {
    $("estado").textContent = "no se pudo cargar: " + err.message;
  }
}

async function exportar() {
  $("estado").textContent = "construyendo y comprobando la malla…";
  try {
    const r = await pedir("/api/stl", proyecto);
    const url = URL.createObjectURL(await r.blob());
    Object.assign(document.createElement("a"), { href: url, download: "pieza.stl" }).click();
    URL.revokeObjectURL(url);
    $("estado").textContent = "STL descargado";
  } catch (err) {
    $("estado").textContent = "no exportado: " + err.message;
  }
}

function sincronizarPanel() {
  for (const clave of ["min_thickness", "max_thickness", "frame_mm", "samples"]) {
    $(clave).value = proyecto.shape[clave];
  }
  $("pattern").value = proyecto.background.pattern || "";
  $("fila-gris").hidden = Boolean(proyecto.background.pattern);
  if (proyecto.background.gray !== undefined) $("gray").value = proyecto.background.gray;
  pintarCamposForma();
}

// --- arranque -------------------------------------------------------------

async function inicio() {
  const est = await (await fetch("/api/estilos")).json();
  $("curve").innerHTML = est.formas.map((f) =>
    `<option value="${f}"${f === proyecto.shape.curve ? " selected" : ""}>${f}</option>`).join("");
  $("pattern").innerHTML = '<option value="">(gris liso)</option>' +
    est.patrones.map((p) =>
      `<option${p === proyecto.background.pattern ? " selected" : ""}>${p}</option>`).join("");
  $("capa-mask").innerHTML = est.mascaras.map((m) => `<option>${m}</option>`).join("");

  await recargarImagenes();
  sincronizarPanel();
  visor = crearVisor($("visor"));
  instalarArrastre();
  await refrescar();
  pintarCajas();
}

async function recargarImagenes(seleccionada) {
  const { imagenes } = await (await fetch("/api/imagenes")).json();
  $("anadir").innerHTML = '<option value="">(elegir imagen…)</option>' +
    imagenes.map((n) => `<option>${n}</option>`).join("");
  if (seleccionada) $("anadir").value = seleccionada;
}

// --- eventos --------------------------------------------------------------

$("curve").onchange = (e) => cambiarForma(e.target.value);
for (const clave of ["min_thickness", "max_thickness", "frame_mm", "samples"]) {
  $(clave).onchange = () => {
    proyecto.shape[clave] = parseFloat($(clave).value);
    refrescar();
  };
}
$("pattern").onchange = () => {
  const patron = $("pattern").value;
  proyecto.background = patron ? { pattern: patron } : { gray: parseInt($("gray").value, 10) };
  $("fila-gris").hidden = Boolean(patron);
  refrescar();
};
$("gray").onchange = () => {
  proyecto.background = { gray: parseInt($("gray").value, 10) };
  refrescar();
};

$("anadir").onchange = (e) => { if (e.target.value) { anadirCapa(e.target.value); e.target.value = ""; } };
$("subir").onchange = async (ev) => {
  const fichero = ev.target.files[0];
  if (!fichero) return;
  $("estado").textContent = "subiendo…";
  const r = await fetch("/api/subir", {
    method: "POST", headers: { "X-Nombre-Fichero": fichero.name }, body: fichero,
  });
  const datos = await r.json();
  if (!r.ok) { $("estado").textContent = "error: " + datos.error; return; }
  await recargarImagenes(datos.path);
  anadirCapa(datos.path);
  ev.target.value = "";
};

$("capa-scale").oninput = () => {
  proyecto.layers[seleccion].scale = parseFloat($("capa-scale").value);
  pintarCajas();
  pedirRefresco();
};
$("capa-gamma").oninput = () => {
  proyecto.layers[seleccion].gamma = parseFloat($("capa-gamma").value);
  pedirRefresco();
};
$("capa-mask").onchange = () => {
  proyecto.layers[seleccion].mask = $("capa-mask").value;
  pintarCajas();
  refrescar();
};
$("capa-ring").onchange = () => {
  proyecto.layers[seleccion].ring = $("capa-ring").checked;
  refrescar();
};
$("capa-borrar").onclick = borrarCapa;
$("capa-subir").onclick = () => moverCapa(-1);
$("capa-bajar").onclick = () => moverCapa(1);

$("btn-guardar").onclick = guardarProyecto;
$("btn-cargar").onclick = () => $("fichero-proyecto").click();
$("fichero-proyecto").onchange = (ev) => ev.target.files[0] && cargarProyecto(ev.target.files[0]);
$("btn-exportar").onclick = exportar;

document.querySelectorAll(".pestanas button").forEach((boton) => {
  boton.onclick = () => {
    vista = boton.dataset.vista;
    document.querySelectorAll(".pestanas button").forEach((otro) =>
      otro.setAttribute("aria-selected", String(otro === boton)));
    const es3d = vista === "modelo";
    $("envoltorio-banda").hidden = es3d;
    $("visor").hidden = !es3d;
    refrescar();
  };
});

$("vista").addEventListener("load", pintarCajas);

inicio();
