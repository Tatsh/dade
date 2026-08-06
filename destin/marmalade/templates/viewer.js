// WebGL render loop for the standalone model viewer.
// POS (flat xyz array) and IDX (triangle indices) are defined by the inline
// <script> that marmalade.viewer.obj_to_html emits just before this file.

const VERTEX_SHADER = `
  attribute vec3 p;
  attribute vec3 n;
  uniform mat4 mvp, mv;
  varying vec3 vn, vp;
  void main() {
    vn = mat3(mv) * n;
    vp = (mv * vec4(p, 1.0)).xyz;
    gl_Position = mvp * vec4(p, 1.0);
  }
`;
const FRAGMENT_SHADER = `
  precision mediump float;
  varying vec3 vn, vp;
  void main() {
    vec3 N = normalize(vn);
    vec3 V = normalize(-vp);
    vec3 L = normalize(vec3(0.4, 0.7, 0.8));
    if (!gl_FrontFacing) {
      N = -N;
    }
    float diffuse = max(dot(N, L), 0.0);
    float ambient = 0.35 + 0.25 * N.y;
    float rim = pow(1.0 - max(dot(N, V), 0.0), 3.0) * 0.4;
    vec3 col = vec3(0.55, 0.68, 0.85) * (ambient + 0.75 * diffuse) + vec3(rim);
    gl_FragColor = vec4(pow(col, vec3(0.85)), 1.0);
  }
`;

// Per-vertex normals, accumulated from face normals and normalised.
const NRM = new Float32Array(POS.length);
for (let f = 0; f < IDX.length; f += 3) {
  const a = IDX[f] * 3,
    b = IDX[f + 1] * 3,
    c = IDX[f + 2] * 3;
  const ux = POS[b] - POS[a],
    uy = POS[b + 1] - POS[a + 1],
    uz = POS[b + 2] - POS[a + 2];
  const vx = POS[c] - POS[a],
    vy = POS[c + 1] - POS[a + 1],
    vz = POS[c + 2] - POS[a + 2];
  const nx = uy * vz - uz * vy,
    ny = uz * vx - ux * vz,
    nz = ux * vy - uy * vx;
  for (const o of [a, b, c]) {
    NRM[o] += nx;
    NRM[o + 1] += ny;
    NRM[o + 2] += nz;
  }
}
for (let i = 0; i < NRM.length; i += 3) {
  const l = Math.hypot(NRM[i], NRM[i + 1], NRM[i + 2]) || 1;
  NRM[i] /= l;
  NRM[i + 1] /= l;
  NRM[i + 2] /= l;
}

const cv = document.getElementById('c');
const gl = cv.getContext('webgl');

function resize() {
  cv.width = cv.clientWidth * devicePixelRatio;
  cv.height = cv.clientHeight * devicePixelRatio;
  gl.viewport(0, 0, cv.width, cv.height);
}
addEventListener('resize', resize);
resize();

function compile(type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  return shader;
}

const program = gl.createProgram();
gl.attachShader(program, compile(gl.VERTEX_SHADER, VERTEX_SHADER));
gl.attachShader(program, compile(gl.FRAGMENT_SHADER, FRAGMENT_SHADER));
gl.linkProgram(program);
gl.useProgram(program);

function bindAttrib(data, name, size) {
  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(program, name);
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0);
}
bindAttrib(POS, 'p', 3);
bindAttrib(NRM, 'n', 3);

const indexBuffer = gl.createBuffer();
gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBuffer);
gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(IDX), gl.STATIC_DRAW);
gl.enable(gl.DEPTH_TEST);
gl.clearColor(0.055, 0.063, 0.08, 1);

function perspective(fov, aspect, near, far) {
  const t = 1 / Math.tan(fov / 2);
  return [
    t / aspect,
    0,
    0,
    0,
    0,
    t,
    0,
    0,
    0,
    0,
    (far + near) / (near - far),
    -1,
    0,
    0,
    (2 * far * near) / (near - far),
    0,
  ];
}

function multiply(a, b) {
  const out = [];
  for (let i = 0; i < 4; i++) {
    for (let j = 0; j < 4; j++) {
      let s = 0;
      for (let k = 0; k < 4; k++) {
        s += a[k * 4 + j] * b[i * 4 + k];
      }
      out[i * 4 + j] = s;
    }
  }
  return out;
}

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];
const normalize = (a) => {
  const l = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0] / l, a[1] / l, a[2] / l];
};

function lookAt(eye, center, up) {
  const z = normalize(sub(eye, center));
  const x = normalize(cross(up, z));
  const y = cross(z, x);
  return [
    x[0],
    y[0],
    z[0],
    0,
    x[1],
    y[1],
    z[1],
    0,
    x[2],
    y[2],
    z[2],
    0,
    -dot(x, eye),
    -dot(y, eye),
    -dot(z, eye),
    1,
  ];
}

let yaw = 0.6,
  pitch = 0.5,
  dist = 3.2,
  auto = true;

cv.addEventListener('mousedown', (e) => {
  auto = false;
  let px = e.clientX,
    py = e.clientY;
  const move = (v) => {
    yaw += (v.clientX - px) * 0.01;
    pitch = Math.max(-1.5, Math.min(1.5, pitch + (v.clientY - py) * 0.01));
    px = v.clientX;
    py = v.clientY;
  };
  const up = () => {
    removeEventListener('mousemove', move);
    removeEventListener('mouseup', up);
  };
  addEventListener('mousemove', move);
  addEventListener('mouseup', up);
});

cv.addEventListener(
  'wheel',
  (e) => {
    e.preventDefault();
    dist = Math.max(1.4, Math.min(12, dist * Math.exp(e.deltaY * 0.001)));
  },
  { passive: false },
);

cv.addEventListener('dblclick', () => {
  yaw = 0.6;
  pitch = 0.5;
  dist = 3.2;
  auto = true;
});

function frame() {
  if (auto) {
    yaw += 0.004;
  }
  const eye = [
    dist * Math.cos(pitch) * Math.sin(yaw),
    dist * Math.sin(pitch),
    dist * Math.cos(pitch) * Math.cos(yaw),
  ];
  const mv = lookAt(eye, [0, 0, 0], [0, 1, 0]);
  const mvp = multiply(perspective(1.05, cv.width / cv.height, 0.1, 100), mv);
  gl.uniformMatrix4fv(gl.getUniformLocation(program, 'mvp'), false, mvp);
  gl.uniformMatrix4fv(gl.getUniformLocation(program, 'mv'), false, mv);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  gl.drawElements(gl.TRIANGLES, IDX.length, gl.UNSIGNED_SHORT, 0);
  requestAnimationFrame(frame);
}
frame();
