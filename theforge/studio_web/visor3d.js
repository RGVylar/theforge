// Visor de STL binario en WebGL, sin librerias.
//
// Se escribio a mano en vez de traer three.js por dos razones: un visor de STL
// necesita muy poco (parsear, una camara y un shader difuso) y traer 600 KB de
// terceros para eso no sale a cuenta en un repo que no depende de nada.
//
// El STL ya trae normal por triangulo, asi que no hay que calcularla: se
// replica a los tres vertices y sale el sombreado facetado, que para revisar
// una pieza es mejor que el suavizado (se ven las facetas del muestreo).

const VS = `
attribute vec3 posicion;
attribute vec3 normal;
uniform mat4 mvp;
uniform mat4 modelo;
varying vec3 vNormal;
void main() {
  vNormal = mat3(modelo) * normal;
  gl_Position = mvp * vec4(posicion, 1.0);
}`;

const FS = `
precision mediump float;
varying vec3 vNormal;
uniform vec3 color;
void main() {
  vec3 n = normalize(vNormal);
  // Dos luces: una principal alta y un relleno frontal flojo, para que las
  // caras en sombra no queden negras del todo.
  float principal = max(dot(n, normalize(vec3(-0.35, 0.55, 0.75))), 0.0);
  float relleno  = max(dot(n, normalize(vec3(0.5, -0.3, 0.4))), 0.0);
  float luz = 0.18 + 0.75 * principal + 0.22 * relleno;
  gl_FragColor = vec4(color * luz, 1.0);
}`;

// --- algebra minima -------------------------------------------------------

function multiplicar(a, b) {
  const r = new Float32Array(16);
  for (let i = 0; i < 4; i++)
    for (let j = 0; j < 4; j++)
      r[i * 4 + j] =
        a[i * 4] * b[j] + a[i * 4 + 1] * b[4 + j] +
        a[i * 4 + 2] * b[8 + j] + a[i * 4 + 3] * b[12 + j];
  return r;
}

function perspectiva(fov, aspecto, cerca, lejos) {
  const f = 1 / Math.tan(fov / 2);
  return new Float32Array([
    f / aspecto, 0, 0, 0,
    0, f, 0, 0,
    0, 0, (lejos + cerca) / (cerca - lejos), -1,
    0, 0, (2 * lejos * cerca) / (cerca - lejos), 0,
  ]);
}

function mirarDesde(ojo, centro, arriba) {
  const resta = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const cruz = (a, b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
  const norm = (v) => { const l = Math.hypot(...v) || 1; return v.map((c) => c / l); };
  const z = norm(resta(ojo, centro));
  const x = norm(cruz(arriba, z));
  const y = cruz(z, x);
  const punto = (a, b) => a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
  return new Float32Array([
    x[0], y[0], z[0], 0,
    x[1], y[1], z[1], 0,
    x[2], y[2], z[2], 0,
    -punto(x, ojo), -punto(y, ojo), -punto(z, ojo), 1,
  ]);
}

function traslacion(t) {
  return new Float32Array([1,0,0,0, 0,1,0,0, 0,0,1,0, t[0],t[1],t[2],1]);
}

// --- STL ------------------------------------------------------------------

export function parsearSTL(buffer) {
  const dv = new DataView(buffer);
  if (buffer.byteLength < 84) throw new Error("STL demasiado corto");
  const cuantos = dv.getUint32(80, true);
  if (buffer.byteLength !== 84 + cuantos * 50) {
    throw new Error(`STL con tamano incoherente: ${buffer.byteLength} bytes para ${cuantos} triangulos`);
  }

  const posiciones = new Float32Array(cuantos * 9);
  const normales = new Float32Array(cuantos * 9);
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];

  for (let t = 0; t < cuantos; t++) {
    const base = 84 + t * 50;
    const nx = dv.getFloat32(base, true);
    const ny = dv.getFloat32(base + 4, true);
    const nz = dv.getFloat32(base + 8, true);
    for (let v = 0; v < 3; v++) {
      const o = base + 12 + v * 12;
      const x = dv.getFloat32(o, true);
      const y = dv.getFloat32(o + 4, true);
      const z = dv.getFloat32(o + 8, true);
      const i = t * 9 + v * 3;
      posiciones[i] = x; posiciones[i + 1] = y; posiciones[i + 2] = z;
      normales[i] = nx; normales[i + 1] = ny; normales[i + 2] = nz;
      if (x < min[0]) min[0] = x; if (x > max[0]) max[0] = x;
      if (y < min[1]) min[1] = y; if (y > max[1]) max[1] = y;
      if (z < min[2]) min[2] = z; if (z > max[2]) max[2] = z;
    }
  }
  const centro = [0, 1, 2].map((i) => (min[i] + max[i]) / 2);
  const radio = Math.hypot(...[0, 1, 2].map((i) => (max[i] - min[i]) / 2)) || 1;
  return { posiciones, normales, triangulos: cuantos, centro, radio, min, max };
}

// --- visor ----------------------------------------------------------------

export function crearVisor(canvas) {
  const gl = canvas.getContext("webgl", { antialias: true });
  if (!gl) throw new Error("este navegador no trae WebGL");

  const compilar = (tipo, fuente) => {
    const s = gl.createShader(tipo);
    gl.shaderSource(s, fuente);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      throw new Error("shader: " + gl.getShaderInfoLog(s));
    }
    return s;
  };
  const programa = gl.createProgram();
  gl.attachShader(programa, compilar(gl.VERTEX_SHADER, VS));
  gl.attachShader(programa, compilar(gl.FRAGMENT_SHADER, FS));
  gl.linkProgram(programa);
  gl.useProgram(programa);

  const bufPos = gl.createBuffer();
  const bufNor = gl.createBuffer();
  const aPos = gl.getAttribLocation(programa, "posicion");
  const aNor = gl.getAttribLocation(programa, "normal");
  const uMvp = gl.getUniformLocation(programa, "mvp");
  const uModelo = gl.getUniformLocation(programa, "modelo");
  const uColor = gl.getUniformLocation(programa, "color");
  gl.enable(gl.DEPTH_TEST);
  gl.clearColor(0.06, 0.07, 0.09, 1);

  let malla = null;
  // La pieza se imprime de pie: se mira desde un poco por encima del ecuador.
  const camara = { azimut: -0.6, elevacion: 0.35, distancia: 3.0 };

  function dibujar() {
    const ancho = canvas.clientWidth || 1;
    const alto = canvas.clientHeight || 1;
    const escala = window.devicePixelRatio || 1;
    if (canvas.width !== ancho * escala || canvas.height !== alto * escala) {
      canvas.width = ancho * escala;
      canvas.height = alto * escala;
    }
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!malla) return;

    const d = camara.distancia * malla.radio;
    const ce = Math.cos(camara.elevacion);
    const ojo = [
      d * ce * Math.sin(camara.azimut),
      d * ce * -Math.cos(camara.azimut),
      d * Math.sin(camara.elevacion),
    ];
    // El modelo se lleva al origen para poder orbitar alrededor de su centro.
    const modelo = traslacion(malla.centro.map((c) => -c));
    const vista = mirarDesde(ojo, [0, 0, 0], [0, 0, 1]);
    const proy = perspectiva(0.9, ancho / alto, malla.radio * 0.05, malla.radio * 40);

    gl.uniformMatrix4fv(uMvp, false, multiplicar(multiplicar(modelo, vista), proy));
    gl.uniformMatrix4fv(uModelo, false, modelo);
    gl.uniform3f(uColor, 0.55, 0.72, 0.95);
    gl.drawArrays(gl.TRIANGLES, 0, malla.triangulos * 3);
  }

  function cargar(buffer) {
    malla = parsearSTL(buffer);
    gl.bindBuffer(gl.ARRAY_BUFFER, bufPos);
    gl.bufferData(gl.ARRAY_BUFFER, malla.posiciones, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, bufNor);
    gl.bufferData(gl.ARRAY_BUFFER, malla.normales, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(aNor);
    gl.vertexAttribPointer(aNor, 3, gl.FLOAT, false, 0, 0);
    dibujar();
    return malla;
  }

  // Orbita: arrastrar gira, rueda acerca. La elevacion se topa antes de los
  // polos para que la vista no se de la vuelta.
  let arrastrando = null;
  canvas.addEventListener("pointerdown", (e) => {
    arrastrando = { x: e.clientX, y: e.clientY };
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!arrastrando) return;
    camara.azimut += (e.clientX - arrastrando.x) * 0.01;
    camara.elevacion = Math.max(-1.45, Math.min(1.45,
      camara.elevacion + (e.clientY - arrastrando.y) * 0.01));
    arrastrando = { x: e.clientX, y: e.clientY };
    dibujar();
  });
  const soltar = () => { arrastrando = null; };
  canvas.addEventListener("pointerup", soltar);
  canvas.addEventListener("pointercancel", soltar);
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    camara.distancia = Math.max(1.2, Math.min(8, camara.distancia * (1 + e.deltaY * 0.001)));
    dibujar();
  }, { passive: false });
  window.addEventListener("resize", dibujar);

  return { cargar, dibujar };
}
