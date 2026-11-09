// Specular glass edge: a WebGL light that runs around a rounded box's edge, follows the cursor when it is near,
// and flashes on demand. Plain-JS port of the SpecularButton component from React Bits (reactbits.dev),
// Copyright (c) 2026 David Haz, MIT + Commons Clause (see LICENSE-react-bits.md), reduced to what these pages
// use. Elements with [data-specular] get it automatically; window.specular.flash(el) makes one flash. Rendering is on demand: it only draws while the light is moving or fading, and stops while
// the page is busy (body.busy: recording/uploading), off screen, or in a hidden tab. Without WebGL2 the element
// keeps its plain CSS border.
(() => {
  const PAD = 24;
  const VERTEX = `#version 300 es
in vec2 aPosition;
void main() { gl_Position = vec4(aPosition, 0.0, 1.0); }`;
  const FRAGMENT = `#version 300 es
precision highp float;
uniform vec2 uCenter; uniform vec2 uHalf; uniform float uRadius; uniform float uPx; uniform float uSpot;
uniform vec2 uEntry; uniform vec3 uLineColor; uniform vec3 uBaseColor; uniform float uIntensity;
uniform vec2 uWindow; uniform float uThickness; uniform float uGlow;
out vec4 outColor;
float roundedBox(vec2 p, vec2 b, float r) { vec2 q = abs(p) - b + r; return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r; }
float loopPosition(vec2 p, vec2 b, float r) {
  vec2 inner = b - r; float arc = 1.5707963 * r; float quarter = inner.x + inner.y + arc;
  vec2 a = abs(p); vec2 q = a - inner;
  float s = q.x > 0.0 && q.y > 0.0 ? inner.y + atan(q.y, q.x) * r
    : (q.x > q.y ? min(a.y, inner.y) : inner.y + arc + inner.x - min(a.x, inner.x));
  if (p.x < 0.0) s = p.y >= 0.0 ? 2.0 * quarter - s : 2.0 * quarter + s; else if (p.y < 0.0) s = 4.0 * quarter - s;
  return s / max(4.0 * quarter, 0.0001);
}
float lobe(float position, float center) { float gap = abs(fract(position - center + 0.5) - 0.5); return 1.0 - smoothstep(uWindow.x, uWindow.x + uWindow.y, gap); }
void main() {
  vec2 p = gl_FragCoord.xy - uCenter;
  float d = roundedBox(p, uHalf, uRadius);
  float position = loopPosition(p, uHalf, uRadius);
  float key = lobe(position, uSpot); float back = lobe(position, uSpot + 0.5);
  float streak = key + back * 0.45;
  float width = max(uThickness * uPx * mix(1.0, max(key, back), 0.6), 0.35);
  float band = smoothstep(-width - 0.6, -width + 0.6, d) * (1.0 - smoothstep(-0.6, 0.6, d));
  float hair = smoothstep(-uPx - 0.6, -uPx + 0.6, d) * (1.0 - smoothstep(-0.6, 0.6, d));
  float inside = 1.0 - smoothstep(-0.6, 0.6, d);
  vec2 pool = (p - uEntry) / (uHalf.y * vec2(1.6, 1.1));
  float glow = streak * 0.2 * exp(-abs(d + width * 0.5) / (5.0 * uPx)) + inside * 0.08 * exp(-dot(pool, pool));
  float light = clamp((band * streak + glow * uGlow) * uIntensity, 0.0, 1.0);
  vec4 base = vec4(uBaseColor, 1.0) * hair * 0.6;
  outColor = vec4(uLineColor, 1.0) * light + base * (1.0 - light);
}`;
  const OPTS = { radius: 999, lineColor: [1, 1, 1], baseColor: [0.32, 0.32, 0.32], intensity: 1, idle: 0.35,
                 shineSize: 10, shineFade: 34, thickness: 1.2, glow: 1, proximity: 250 };
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const wrap = v => v - Math.floor(v);
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const pointer = { x: 0, y: 0, known: false };
  const all = [];
  const paused = () => document.body.classList.contains('busy') || document.hidden;

  function loopPos(x, y, hx, hy, r) {
    const ix = hx - r, iy = hy - r, arc = (Math.PI / 2) * r, quarter = ix + iy + arc;
    const ax = Math.abs(x), ay = Math.abs(y), qx = ax - ix, qy = ay - iy;
    let s;
    if (qx > 0 && qy > 0) s = iy + Math.atan2(qy, qx) * r;
    else if (qx > qy) s = Math.min(ay, iy);
    else s = iy + arc + ix - Math.min(ax, ix);
    if (x < 0) s = y >= 0 ? 2 * quarter - s : 2 * quarter + s; else if (y < 0) s = 4 * quarter - s;
    return wrap(s / Math.max(4 * quarter, 0.0001));
  }
  function rimPoint(pos, hx, hy, r) {
    const ix = hx - r, iy = hy - r, arc = (Math.PI / 2) * r, quarter = ix + iy + arc;
    let s = wrap(pos) * 4 * quarter, sx = 1, sy = 1;
    if (s > 3 * quarter) { s = 4 * quarter - s; sy = -1; }
    else if (s > 2 * quarter) { s -= 2 * quarter; sx = -1; sy = -1; }
    else if (s > quarter) { s = 2 * quarter - s; sx = -1; }
    let x = ix - (s - iy - arc), y = hy;
    if (s <= iy) { x = hx; y = s; }
    else if (s <= iy + arc) { const a = (s - iy) / Math.max(r, 0.0001); x = ix + Math.cos(a) * r; y = iy + Math.sin(a) * r; }
    return [x * sx, y * sy];
  }
  function program(gl) {
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null; };
    const v = sh(gl.VERTEX_SHADER, VERTEX), f = sh(gl.FRAGMENT_SHADER, FRAGMENT);
    if (!v || !f) return null;
    const p = gl.createProgram();
    gl.attachShader(p, v); gl.attachShader(p, f); gl.bindAttribLocation(p, 0, 'aPosition'); gl.linkProgram(p);
    return gl.getProgramParameter(p, gl.LINK_STATUS) ? p : null;
  }

  function attach(el) {
    const canvas = document.createElement('canvas');
    canvas.className = 'spec-light';
    canvas.setAttribute('aria-hidden', 'true');
    const gl = canvas.getContext('webgl2', { alpha: true, premultipliedAlpha: true, antialias: false, depth: false, stencil: false });
    const prog = gl && program(gl);
    if (!prog) return null;                                   // no WebGL2: keep the CSS border
    const u = {};
    ['uCenter', 'uHalf', 'uRadius', 'uPx', 'uSpot', 'uEntry', 'uLineColor', 'uBaseColor', 'uIntensity', 'uWindow', 'uThickness', 'uGlow']
      .forEach(n => { u[n] = gl.getUniformLocation(prog, n); });
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    el.prepend(canvas);
    el.classList.add('spec-on');

    const o = OPTS, view = { w: 1, h: 1, ratio: 1 }, st = { spot: 0, level: o.idle, press: 0 };
    let raf = 0, last = 0, visible = true;
    const rad = () => Math.min(o.radius, view.w / 2, view.h / 2);
    const rest = () => { const r = rad(), i = r * (1 - Math.SQRT1_2); return loopPos(i - view.w / 2, view.h / 2 - i, view.w / 2, view.h / 2, r); };
    st.spot = rest();

    function aim() {
      if (!pointer.known) return null;
      const b = el.getBoundingClientRect(), hx = view.w / 2, hy = view.h / 2;
      const x = pointer.x - b.left - b.width / 2, y = b.top + b.height / 2 - pointer.y;
      const dist = Math.hypot(Math.max(Math.abs(x) - hx, 0), Math.max(Math.abs(y) - hy, 0));
      const t = clamp(1 - dist / o.proximity, 0, 1);
      return { spot: loopPos(x, y, hx, hy, rad()), near: t * t * (3 - 2 * t) };
    }
    function draw() {
      const sx = canvas.width / (view.w + PAD * 2), sy = canvas.height / (view.h + PAD * 2), r = rad();
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
      gl.useProgram(prog);
      gl.uniform2f(u.uCenter, (PAD + view.w / 2) * sx, (PAD + view.h / 2) * sy);
      gl.uniform2f(u.uHalf, (view.w / 2) * sx, (view.h / 2) * sy);
      gl.uniform1f(u.uRadius, r * sx);
      gl.uniform1f(u.uPx, view.ratio);
      const [rx, ry] = rimPoint(st.spot, view.w / 2, view.h / 2, r), len = Math.max(Math.hypot(rx, ry), 0.0001);
      const pull = 1 - Math.min(0.35 * (view.h / 2), len) / len;
      gl.uniform1f(u.uSpot, st.spot);
      gl.uniform2f(u.uEntry, rx * pull * sx, ry * pull * sy);
      gl.uniform3fv(u.uLineColor, o.lineColor);
      gl.uniform3fv(u.uBaseColor, o.baseColor);
      gl.uniform1f(u.uIntensity, o.intensity * (st.level + st.press * 0.8));
      gl.uniform2f(u.uWindow, o.shineSize / 360 + st.press * 0.06, o.shineFade / 360 + 0.0001);
      gl.uniform1f(u.uThickness, o.thickness);
      gl.uniform1f(u.uGlow, o.glow);
      gl.bindVertexArray(vao);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
    function frame(now) {
      raf = 0;
      if (!visible) return;
      const dt = last ? Math.min(0.05, (now - last) / 1000) : 1 / 60;
      last = now;
      const t = aim(), steering = !!t && t.near > 0;
      let diff = (steering ? t.spot : rest()) - st.spot;
      diff -= Math.round(diff);
      st.spot = wrap(st.spot + diff * (1 - Math.exp(-dt * 8)));
      const level = o.idle + (1 - o.idle) * (t ? t.near : 0);
      st.level += (level - st.level) * (1 - Math.exp(-dt * 7));
      st.press *= Math.exp(-dt * 5);
      draw();
      if (Math.abs(diff) > 0.0002 || Math.abs(level - st.level) > 0.001 || st.press > 0.002) raf = requestAnimationFrame(frame);
      else last = 0;
    }
    const wake = () => { if (!raf && visible && !paused()) raf = requestAnimationFrame(frame); };
    function measure() {
      view.w = Math.max(1, el.offsetWidth); view.h = Math.max(1, el.offsetHeight);
      view.ratio = Math.min(devicePixelRatio || 1, 2);
      canvas.width = Math.round((view.w + PAD * 2) * view.ratio);
      canvas.height = Math.round((view.h + PAD * 2) * view.ratio);
      draw(); wake();
    }
    new ResizeObserver(measure).observe(el);
    new IntersectionObserver(es => { visible = es.some(e => e.isIntersecting); if (visible) { last = 0; wake(); } }).observe(el);
    measure();
    const api = { el, wake, flash() { if (reduce || paused() || !visible) return; st.press = 1; wake(); } };
    all.push(api);
    return api;
  }

  addEventListener('pointermove', e => { pointer.x = e.clientX; pointer.y = e.clientY; pointer.known = true; all.forEach(a => a.wake()); }, { passive: true });
  document.documentElement.addEventListener('pointerleave', () => { pointer.known = false; all.forEach(a => a.wake()); });
  document.addEventListener('visibilitychange', () => all.forEach(a => a.wake()));
  new MutationObserver(() => all.forEach(a => a.wake())).observe(document.body, { attributes: true, attributeFilter: ['class'] });

  document.querySelectorAll('[data-specular]').forEach(attach);
  window.specular = { flash: el => all.find(a => a.el === el)?.flash() };
})();
