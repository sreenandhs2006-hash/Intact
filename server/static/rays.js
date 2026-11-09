// Light rays behind the opening section: soft shafts of light from above that turn a little toward the cursor;
// the cursor casts a faint shadow down the rays and a click sends a wave of light along them. Plain-JS port of
// the LightRays component from React Bits (reactbits.dev; check its licence, MIT + Commons Clause at the time
// of writing), with the settings fixed to the ones these pages use.
// Cost control: it draws only while its container is on screen, the tab is visible and the page is not busy
// (body.busy = recording or uploading, so it never competes with the frames being measured). The canvas stays
// within a pixel budget. Without WebGL2 the section simply has no backdrop.
(() => {
  const box = document.querySelector('[data-rays]');
  if (!box) return;
  const PIXEL_BUDGET = 2.4e6, MAX_PULSES = 4;
  const S = {
    anchor: [0.5, -0.2], dir: [0, 1],                 // top-center
    color: [1, 1, 1], speed: 1, spread: 0.5, length: 3, density: 1, tilt: 0, sharpness: 0.35, glow: 0.6,
    haze: 0.25, atmosphere: 1, intensity: 1, pulsating: false, fade: 1, saturation: 1, follow: true, influence: 0.1,
    cursorShadow: true, clickPulse: true, noise: 0, distortion: 0, intro: true, opacity: 1, maxRatio: 2,
  };
  const VERTEX = `#version 300 es
const vec2 corners[3] = vec2[3](vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0));
void main() { gl_Position = vec4(corners[gl_VertexID], 0.0, 1.0); }`;
  const FRAGMENT = `#version 300 es
precision highp float;
uniform vec2 uResolution; uniform float uScale; uniform float uTime; uniform vec2 uSource; uniform vec2 uAim;
uniform float uReach; uniform vec3 uColor; uniform float uSpread; uniform float uLength; uniform float uFade;
uniform float uSaturation; uniform float uPulsating; uniform float uNoise; uniform float uDistortion; uniform float uDensity;
uniform float uSharpness; uniform float uGlow; uniform float uHaze; uniform float uAtmosphere; uniform float uIntensity;
uniform vec4 uShadow; uniform vec4 uPulses[${MAX_PULSES}]; uniform vec2 uIntro; uniform float uOpacity;
out vec4 fragColor;
float hash(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float valueNoise(vec2 p) {
  vec2 i = floor(p); vec2 f = p - i; vec2 w = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), w.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), w.x), w.y);
}
float shape(float strength, float width) {
  float edge = max(mix(0.5, 0.08, uSharpness), width);
  return mix(strength, smoothstep(0.62 - edge, 0.62 + edge, strength), uSharpness);
}
void main() {
  vec2 coord = vec2(gl_FragCoord.x, uResolution.y - gl_FragCoord.y) / uScale;
  vec2 delta = coord - uSource;
  float distance = length(delta);
  vec2 dir = delta / max(distance, 1e-4);
  float cosAngle = dot(dir, uAim);
  float angle = cosAngle + uDistortion * sin(uTime * 2.0 + distance * 0.02) * 0.2;
  float slope = fwidth(angle);
  float depth = distance / uReach;
  float source = exp(-depth * depth * 9.0) * 0.9 + exp(-depth * 3.2) * 0.25;
  float glowLight = uGlow * source * smoothstep(-0.2, 0.6, cosAngle);
  float spread = pow(max(angle, 0.0), 1.0 / uSpread);
  float lengthFalloff = clamp(1.0 - distance / (uReach * uLength), 0.0, 1.0);
  float fadeFalloff = clamp(1.0 - distance / (uReach * uFade), 0.5, 1.0);
  float envelope = spread * lengthFalloff * fadeFalloff;
  float reveal = uIntensity * uIntro.y * (1.0 - smoothstep(uIntro.x - 0.35, uIntro.x, depth));
  if ((envelope * 1.6 + glowLight) * reveal < 0.0015) { fragColor = vec4(0.0); return; }
  float phaseA = angle * 36.2214 * uDensity + uTime * 1.5;
  float phaseB = -angle * 21.11349 * uDensity + uTime * 1.5;
  float phaseC = angle * 22.3991 * uDensity + uTime * 1.1;
  float phaseD = -angle * 18.0234 * uDensity + uTime * 1.1;
  float strengthA = clamp(0.75 + 0.15 * sin(phaseA) + 0.2 * cos(phaseB), 0.0, 1.0);
  float strengthB = clamp(0.75 + 0.15 * sin(phaseC) + 0.2 * cos(phaseD), 0.0, 1.0);
  float widthA = abs(0.15 * 36.2214 * cos(phaseA) + 0.2 * 21.11349 * sin(phaseB)) * uDensity * slope;
  float widthB = abs(0.15 * 22.3991 * cos(phaseC) + 0.2 * 18.0234 * sin(phaseD)) * uDensity * slope;
  float pulseA = uPulsating > 0.5 ? 0.8 + 0.2 * sin(uTime * 4.5) : 1.0;
  float pulseB = uPulsating > 0.5 ? 0.8 + 0.2 * sin(uTime * 3.3) : 1.0;
  float rayLight = envelope * (0.5 * shape(strengthA, widthA) * pulseA + 0.4 * shape(strengthB, widthB) * pulseB);
  if (uHaze > 0.0) {
    float around = atan(uAim.x * dir.y - uAim.y * dir.x, cosAngle);
    vec2 drift = vec2(around * 2.2 + uTime * 0.035, depth * 2.6 - uTime * 0.11);
    float fog = 0.65 * valueNoise(drift * vec2(3.0, 1.0)) + 0.35 * valueNoise(drift * vec2(7.0, 2.3) + 4.1);
    rayLight *= mix(1.0, 0.25 + 1.2 * fog, uHaze);
  }
  if (uShadow.z > 0.0) {
    vec2 toCursor = uShadow.xy - uSource;
    float cursorDistance = length(toCursor);
    float along = dot(delta, toCursor) / max(cursorDistance * cursorDistance, 1e-4);
    float side = abs(delta.x * toCursor.y - delta.y * toCursor.x) / max(cursorDistance, 1e-4);
    float trail = max(along - 1.0, 0.0);
    float width = uShadow.w * along + 0.22 * trail * cursorDistance;
    float behind = smoothstep(0.97, 1.25, along) * exp(-trail * 1.1);
    float shade = (1.0 - smoothstep(width * 0.3, width * 1.6, side)) * behind;
    rayLight *= 1.0 - uShadow.z * 0.62 * shade;
  }
  float boost = 0.0;
  for (int i = 0; i < ${MAX_PULSES}; i++) {
    vec4 wave = uPulses[i];
    if (wave.z <= 0.0) continue;
    float x = (depth - wave.x) / wave.y;
    boost += wave.z * exp(-x * x);
  }
  float light = (rayLight * (1.0 + boost) + glowLight) * reveal;
  if (uNoise > 0.0) {
    float n = fract(sin(dot(coord * 0.02 + uTime * 0.1, vec2(12.9898, 78.233))) * 43758.5453123);
    light *= 1.0 - uNoise + uNoise * n;
  }
  float near = clamp(1.2 - distance / (uResolution.y / uScale), 0.0, 1.0);
  vec3 tint = mix(vec3(0.9), vec3(0.1, 0.3, 0.5) + near * vec3(0.8, 0.6, 0.5), uAtmosphere);
  float gray = dot(tint, vec3(0.299, 0.587, 0.114));
  vec3 hue = max(mix(vec3(gray), tint, uSaturation), 0.0) * uColor;
  float grain = (fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715)))) - 0.5) / 255.0;
  float level = light < 0.75 ? light : 0.75 + 0.25 * (1.0 - exp(-(light - 0.75) / 0.25));
  float top = max(hue.r, max(hue.g, hue.b));
  hue = mix(hue, vec3(top), smoothstep(0.8, 1.0, level) * 0.45);
  vec3 shown = clamp(hue * level, 0.0, 1.0) * level;
  fragColor = vec4(clamp(shown + grain, 0.0, level) * uOpacity, level * uOpacity);
}`;

  const canvas = document.createElement('canvas');
  canvas.className = 'rays-canvas';
  canvas.setAttribute('aria-hidden', 'true');
  const gl = canvas.getContext('webgl2', { alpha: true, premultipliedAlpha: true, antialias: false, depth: false, stencil: false });
  if (!gl) return;
  const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null; };
  const v = sh(gl.VERTEX_SHADER, VERTEX), f = sh(gl.FRAGMENT_SHADER, FRAGMENT);
  if (!v || !f) return;
  const prog = gl.createProgram();
  gl.attachShader(prog, v); gl.attachShader(prog, f); gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return;
  const u = {};
  for (let i = 0, n = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS); i < n; i++) {
    const info = gl.getActiveUniform(prog, i);
    u[info.name.replace(/\[0\]$/, '')] = gl.getUniformLocation(prog, info.name);
  }
  const vao = gl.createVertexArray();
  box.append(canvas);

  const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
  const smoother = t => { const x = clamp(t, 0, 1); return x * x * x * (x * (x * 6 - 15) + 10); };
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const size = { width: 1, height: 1, ratio: 1 };
  const pointer = { x: 0.5, y: 0.5, inside: false, seen: false }, aim = { x: 0.5, y: 0.5 }, shade = { x: 0.5, y: 0.5, presence: 0 };
  const pulses = [], pulseData = new Float32Array(MAX_PULSES * 4);
  let time = 0, opening = S.intro && !reduced ? 0 : 1, raf = 0, last = 0, visible = true, resizePending = true;
  const busy = () => document.body.classList.contains('busy');

  function applyResize() {
    const r = box.getBoundingClientRect(), w = Math.max(1, r.width), h = Math.max(1, r.height);
    const detail = S.density * (0.35 + 0.65 * S.sharpness);
    const sampling = Math.max(clamp(0.35 + 0.3 * detail, 0.5, 2), S.noise > 0 ? 1 : 0);
    const ratio = Math.min(devicePixelRatio || 1, S.maxRatio, sampling, Math.sqrt(PIXEL_BUDGET / (w * h)));
    const cw = Math.max(1, Math.round(w * ratio)), ch = Math.max(1, Math.round(h * ratio));
    if (canvas.width !== cw || canvas.height !== ch) { canvas.width = cw; canvas.height = ch; }
    size.width = w; size.height = h; size.ratio = cw / w;
  }

  function frame(now) {
    raf = 0;
    if (!visible || document.hidden || busy()) return;
    if (resizePending) { resizePending = false; applyResize(); }
    const dt = clamp((now - last) / 1000 || 0, 0, 0.05);
    last = Math.max(last, now);
    time += dt * S.speed * (reduced ? 0.35 : 1);
    if (opening < 1) opening = Math.min(1, opening + dt / 1.8);
    const steer = 1 - Math.exp(-dt / 0.2);
    const aimX = S.follow && pointer.seen ? pointer.x : 0.5, aimY = S.follow && pointer.seen ? pointer.y : 0.5;
    aim.x += (aimX - aim.x) * steer; aim.y += (aimY - aim.y) * steer;
    const glide = 1 - Math.exp(-dt / 0.08);
    shade.x += (pointer.x - shade.x) * glide; shade.y += (pointer.y - shade.y) * glide;
    const shading = pointer.inside && S.cursorShadow && !reduced;
    shade.presence += ((shading ? 1 : 0) - shade.presence) * (1 - Math.exp(-dt / (shading ? 0.25 : 0.5)));
    for (let i = pulses.length - 1; i >= 0; i--) { pulses[i].age += dt; if (pulses[i].age >= 2) pulses.splice(i, 1); }
    pulseData.fill(0);
    pulses.forEach((p, i) => {
      pulseData[i * 4] = 0.05 + p.age * 1.05;
      pulseData[i * 4 + 1] = 0.14 + p.age * 0.14;
      pulseData[i * 4 + 2] = 0.9 * smoother(p.age / 0.15) * (1 - smoother(p.age / 2));
    });
    const w = size.width, h = size.height, sx = S.anchor[0] * w, sy = S.anchor[1] * h;
    const cos = Math.cos(S.tilt), sin = Math.sin(S.tilt);
    let dx = S.dir[0] * cos - S.dir[1] * sin, dy = S.dir[0] * sin + S.dir[1] * cos;
    if (S.follow && S.influence > 0) {
      const mx = aim.x * w - sx, my = aim.y * h - sy, ml = Math.hypot(mx, my) || 1;
      const bx = dx + (mx / ml - dx) * S.influence, by = dy + (my / ml - dy) * S.influence, bl = Math.hypot(bx, by) || 1;
      dx = bx / bl; dy = by / bl;
    }
    const eased = 1 - Math.pow(1 - opening, 3);
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(prog); gl.bindVertexArray(vao);
    gl.uniform2f(u.uResolution, canvas.width, canvas.height);
    gl.uniform1f(u.uScale, size.ratio);
    gl.uniform1f(u.uTime, time);
    gl.uniform2f(u.uSource, sx, sy);
    gl.uniform2f(u.uAim, dx, dy);
    gl.uniform1f(u.uReach, Math.max(w, h));
    gl.uniform3f(u.uColor, S.color[0], S.color[1], S.color[2]);
    gl.uniform1f(u.uSpread, S.spread);
    gl.uniform1f(u.uLength, S.length);
    gl.uniform1f(u.uFade, S.fade);
    gl.uniform1f(u.uSaturation, S.saturation);
    gl.uniform1f(u.uPulsating, S.pulsating ? 1 : 0);
    gl.uniform1f(u.uNoise, S.noise);
    gl.uniform1f(u.uDistortion, S.distortion);
    gl.uniform1f(u.uDensity, S.density);
    gl.uniform1f(u.uSharpness, S.sharpness);
    gl.uniform1f(u.uGlow, S.glow);
    gl.uniform1f(u.uHaze, S.haze);
    gl.uniform1f(u.uAtmosphere, S.atmosphere);
    gl.uniform1f(u.uIntensity, S.intensity);
    gl.uniform4f(u.uShadow, shade.x * w, shade.y * h, shade.presence, 16);
    gl.uniform4fv(u.uPulses, pulseData);
    gl.uniform2f(u.uIntro, eased * 2.6, smoother(opening / 0.5));
    gl.uniform1f(u.uOpacity, S.opacity);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    const settling = Math.abs(aim.x - aimX) > 1e-4 || Math.abs(aim.y - aimY) > 1e-4 ||
      (shade.presence > 1e-3 && Math.abs(shade.x - pointer.x) + Math.abs(shade.y - pointer.y) > 1e-4) ||
      Math.abs((shading ? 1 : 0) - shade.presence) > 1e-3 || pulses.length > 0;
    if (S.speed > 0 || opening < 1 || settling) raf = requestAnimationFrame(frame);
  }
  const wake = () => {
    if (raf || !visible || document.hidden || busy()) return;
    last = performance.now();
    raf = requestAnimationFrame(frame);
  };

  function locate(e) {
    const r = box.getBoundingClientRect();
    return { x: (e.clientX - r.left) / Math.max(1, r.width), y: (e.clientY - r.top) / Math.max(1, r.height),
             inside: e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom };
  }
  addEventListener('pointermove', e => {
    const p = locate(e);
    if (!pointer.inside && p.inside) { shade.x = p.x; shade.y = p.y; }
    Object.assign(pointer, p, { seen: true });
    wake();
  }, { passive: true });
  addEventListener('pointerdown', e => {
    const p = locate(e);
    if (!p.inside || !S.clickPulse || reduced) return;
    pulses.push({ age: 0 }); if (pulses.length > MAX_PULSES) pulses.shift();
    wake();
  }, { passive: true });
  document.documentElement.addEventListener('pointerleave', () => { pointer.inside = false; wake(); });
  document.addEventListener('visibilitychange', wake);
  new MutationObserver(wake).observe(document.body, { attributes: true, attributeFilter: ['class'] });
  new ResizeObserver(() => { resizePending = true; wake(); }).observe(box);
  new IntersectionObserver(es => { visible = es.some(e => e.isIntersecting); wake(); }).observe(box);
  wake();
})();
