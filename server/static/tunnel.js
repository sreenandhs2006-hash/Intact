// Light tunnel behind the opening section: fibres running into the distance with light pulses travelling along
// them; the far end leans toward the cursor and a click sends a ring of light down the tunnel. Plain-JS port of
// the LightTunnel component from React Bits (reactbits.dev; check its licence, MIT + Commons Clause at the time
// of writing), with the settings fixed to the ones these pages use.
// Cost control: it draws only while its container is on screen, the tab is visible and the page is not busy
// (body.busy = recording or uploading, so it never competes with the frames being measured). Without WebGL2,
// or under prefers-reduced-motion, it draws a single still frame or nothing.
(() => {
  const box = document.querySelector('[data-tunnel]');
  if (!box) return;
  const S = {
    cable: [1, 1, 1], pulse: [1, 1, 1], tunnel: [1, 1, 1], tunnelOpacity: 0, speed: 0.1, flow: -1 /* inward */,
    pulseSpeed: 2, pulseLength: 0.28, pulseBlend: 0.6, pulseWidth: 1, pulseDensity: 0.5, cableCount: 56,
    thickness: 0.35, rimWidth: 0.15, waviness: 0.3, sway: 0.5, bend: 0.4, size: 1, centerX: 0, centerY: 0,
    glow: 1, fadeNear: 0.5, fadeFar: 2, brightness: 1, colorVariance: true, opacity: 0.55,
    mouseStrength: 0.1, maxDpr: 1.5, introSeconds: 1.8,
  };
  const VERTEX = `#version 300 es
in vec2 aPosition;
void main() { gl_Position = vec4(aPosition, 0.0, 1.0); }`;
  const FRAGMENT = `#version 300 es
precision highp float;
uniform vec2 uResolution; uniform vec2 uCenter; uniform float uScale; uniform float uRatio; uniform float uTime;
uniform float uDrift; uniform vec2 uSteer; uniform float uBend; uniform float uCount; uniform float uSwing;
uniform float uWave; uniform float uWidth; uniform float uPulseWidth; uniform float uHead; uniform float uTail;
uniform float uChance; uniform float uSpacing; uniform float uPulseSpeed; uniform float uFlow; uniform float uHalo;
uniform float uGlow; uniform float uBrightness; uniform float uVariance; uniform float uBody; uniform float uFadeNear;
uniform float uFadeFar; uniform vec3 uCable; uniform vec3 uPulse; uniform vec3 uTunnel; uniform vec3 uSurge;
uniform float uReveal; uniform float uOpacity;
out vec4 outColor;
const float TAU = 6.2831853;
float hash(float n) { return fract(sin(n * 127.1) * 43758.5453); }
vec2 bendAt(float depth) {
  float reach = 1.0 - exp(-max(depth, 0.0) * 0.55);
  vec2 wobble = vec2(sin(uDrift * 0.37 + depth * 0.31), cos(uDrift * 0.29 + depth * 0.23)) * uBend;
  return (wobble + uSteer) * reach;
}
void main() {
  vec2 p = (gl_FragCoord.xy - 0.5 * uResolution - uCenter) / uScale;
  float depth = -log(max(length(p), 1e-5));
  vec2 q = p;
  for (int i = 0; i < 4; i++) { q = p - bendAt(depth); depth = -log(max(length(q), 1e-5)); }
  float r = length(q);
  float px = r * uScale;
  float turn = atan(q.y, q.x) / TAU;
  float s = turn - uSwing - uWave * sin(depth * 1.2 + uDrift * 0.5);
  float cell = floor(s * uCount);
  float spacing = TAU * px / uCount;
  float near = smoothstep(0.55, 1.25, r);
  float width = uWidth * (1.0 + near * 1.2);
  float soft = uRatio * (0.55 + near * 0.9);
  float tight = uRatio * uHalo * (1.0 + near);
  float wide = tight * 4.5;
  float lines = 0.0, body = 0.0, strokes = 0.0;
  vec3 glow = vec3(0.0);
  for (int k = -3; k <= 3; k++) {
    float i = cell + float(k);
    float id = mod(i, uCount);
    float h1 = hash(id), h2 = hash(id + 17.0), h3 = hash(id + 41.0), h4 = hash(id + 73.0);
    float center = (i + 0.5 + (h1 - 0.5) * 0.55) / uCount;
    center += 0.12 * sin(depth * (0.8 + h2 * 0.9) + uDrift * (0.4 + h3 * 0.5) + h4 * TAU) / uCount;
    float d = abs(s - center) * TAU * px;
    float shade = 1.0 + uVariance * (h3 - 0.5) * 0.9;
    float reach = smoothstep(spacing * 2.4, spacing * 1.4, d);
    lines += smoothstep(width + soft, width - soft, d) * shade;
    body += exp(-d / max(spacing * 0.22, 0.001)) * shade * reach;
    float x = depth * uSpacing + uTime * uPulseSpeed * (0.55 + h2 * 0.6) * uFlow + h4 * 7.0;
    float lead = (fract(x) - 0.5) / uSpacing * uFlow;
    float lit = step(hash(id * 3.7 + floor(x) * 13.1), uChance);
    float limit = 0.5 / uSpacing;
    float head = exp(-pow(max(-lead, 0.0) / uHead, 2.0)) * smoothstep(-limit, -limit * 0.8, lead);
    float tail = exp(-max(lead, 0.0) / uTail) * smoothstep(limit, limit * 0.55, lead);
    float pulse = (lead < 0.0 ? head : tail) * lit;
    float ring = uSurge.y * exp(-pow((depth - uSurge.x) / uSurge.z, 2.0));
    pulse = max(pulse, ring);
    float hot = pulse * (lead < 0.0 ? 1.0 : exp(-max(lead, 0.0) / (uTail * 0.35)));
    float core = uPulseWidth * width + 0.35 * uRatio;
    float stroke = smoothstep(core + soft, core - soft, d);
    float bloom = (exp(-d / tight) * 0.7 + exp(-d / wide) * 0.18) * uGlow * reach;
    vec3 tint = mix(uPulse, vec3(1.0), hot * 0.55);
    glow += tint * pulse * (stroke * 1.5 + bloom) * shade;
    strokes += pulse * stroke * shade;
  }
  float lod = smoothstep(4.0, 1.2, spacing);
  float average = min(2.0 * uWidth / max(spacing, 0.001), 1.0);
  lines = mix(lines, average, lod);
  glow = mix(glow, uPulse * average * 0.6 * uChance, lod);
  body = mix(body, 1.0, lod) * uBody;
  float rr = r * 0.25;
  float fade = smoothstep(0.0, uFadeNear, rr) * smoothstep(uFadeFar, uFadeFar * 0.55, rr);
  fade *= smoothstep(uReveal - 0.6, uReveal, depth);
  vec3 light = (uCable * lines * 0.12 + uTunnel * body * 0.35 + glow) * uBrightness * fade;
  vec3 mapped = (1.0 - exp(-light * 1.4)) * uOpacity;
  outColor = vec4(mapped, max(mapped.r, max(mapped.g, mapped.b)));
}`;

  const canvas = document.createElement('canvas');
  canvas.className = 'tunnel-canvas';
  canvas.setAttribute('aria-hidden', 'true');
  const gl = canvas.getContext('webgl2', { alpha: true, premultipliedAlpha: true, antialias: false, depth: false, stencil: false });
  if (!gl) return;
  const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null; };
  const v = sh(gl.VERTEX_SHADER, VERTEX), f = sh(gl.FRAGMENT_SHADER, FRAGMENT);
  if (!v || !f) return;
  const prog = gl.createProgram();
  gl.attachShader(prog, v); gl.attachShader(prog, f); gl.bindAttribLocation(prog, 0, 'aPosition'); gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return;
  const u = {};
  for (let i = 0, n = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS); i < n; i++) {
    const info = gl.getActiveUniform(prog, i);
    u[info.name] = gl.getUniformLocation(prog, info.name);
  }
  const vao = gl.createVertexArray();
  gl.bindVertexArray(vao);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
  box.append(canvas);

  const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const pointer = { x: 0, y: 0, inside: false }, steer = { x: 0, y: 0 }, surge = { age: 10 };
  let time = 0, drift = 0, reveal = reduce ? 1 : 0, raf = 0, last = 0, visible = true;
  const busy = () => document.body.classList.contains('busy');

  function render() {
    const w = canvas.width, h = canvas.height, ratio = w / Math.max(1, box.clientWidth), minSide = Math.min(w, h);
    const travel = surge.age * 2.6, surgeDepth = S.flow > 0 ? 3.4 - travel : -0.6 + travel;
    const surgeLevel = surge.age < 2.4 ? Math.min(1, surge.age / 0.12) * Math.exp(-surge.age * 1.1) : 0;
    const eased = reveal * reveal * (3 - 2 * reveal), len = S.pulseLength * 1.2;
    gl.viewport(0, 0, w, h);
    gl.useProgram(prog);
    gl.bindVertexArray(vao);
    gl.uniform2f(u.uResolution, w, h);
    gl.uniform2f(u.uCenter, S.centerX * minSide, S.centerY * minSide);
    gl.uniform1f(u.uScale, minSide * 0.5 * S.size);
    gl.uniform1f(u.uRatio, ratio);
    gl.uniform1f(u.uTime, time);
    gl.uniform1f(u.uDrift, drift);
    gl.uniform2f(u.uSteer, steer.x, steer.y);
    gl.uniform1f(u.uBend, S.bend * 0.45);
    gl.uniform1f(u.uCount, S.cableCount);
    gl.uniform1f(u.uSwing, (Math.sin(drift * 0.9) * S.sway * 0.5) / (Math.PI * 2));
    gl.uniform1f(u.uWave, S.waviness * 0.15);
    gl.uniform1f(u.uWidth, (0.25 + S.thickness * 1.5) * ratio);
    gl.uniform1f(u.uPulseWidth, 0.6 + S.pulseWidth * 0.9);
    gl.uniform1f(u.uHead, len * (0.08 + S.pulseBlend * 0.22));
    gl.uniform1f(u.uTail, len * (0.5 + S.pulseBlend * 0.7));
    gl.uniform1f(u.uChance, S.pulseDensity);
    gl.uniform1f(u.uSpacing, 0.4);
    gl.uniform1f(u.uPulseSpeed, S.pulseSpeed * 4);
    gl.uniform1f(u.uFlow, S.flow);
    gl.uniform1f(u.uHalo, 1.2 + S.rimWidth * 8);
    gl.uniform1f(u.uGlow, S.glow);
    gl.uniform1f(u.uBrightness, S.brightness);
    gl.uniform1f(u.uVariance, S.colorVariance ? 1 : 0);
    gl.uniform1f(u.uBody, S.tunnelOpacity);
    gl.uniform1f(u.uFadeNear, S.fadeNear);
    gl.uniform1f(u.uFadeFar, S.fadeFar);
    gl.uniform3fv(u.uCable, S.cable);
    gl.uniform3fv(u.uPulse, S.pulse);
    gl.uniform3fv(u.uTunnel, S.tunnel);
    gl.uniform3f(u.uSurge, surgeDepth, surgeLevel, 0.22);
    gl.uniform1f(u.uReveal, 1.7 - eased * 3.6);
    gl.uniform1f(u.uOpacity, S.opacity);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  function frame(now) {
    raf = 0;
    if (!visible || document.hidden || busy()) { last = 0; return; }
    const dt = last ? clamp((now - last) / 1000, 0.0005, 0.05) : 1 / 60;
    last = now;
    const motion = reduce ? 0 : 1;
    time += dt * S.speed * motion;
    drift += dt * (S.speed + 0.2) * motion;
    surge.age += dt;
    if (reveal < 1) reveal = Math.min(1, reveal + dt / S.introSeconds);
    const reach = S.mouseStrength * 2.5;
    const tx = pointer.inside && !reduce ? pointer.x * reach : 0, ty = pointer.inside && !reduce ? pointer.y * reach : 0;
    const follow = 1 - Math.exp(-dt / 0.6);
    steer.x += (tx - steer.x) * follow;
    steer.y += (ty - steer.y) * follow;
    render();
    const settled = Math.abs(tx - steer.x) < 0.0005 && Math.abs(ty - steer.y) < 0.0005;
    if (motion > 0 || !settled || surge.age < 2.4) raf = requestAnimationFrame(frame);
    else last = 0;
  }
  const wake = () => { if (!raf && visible && !document.hidden && !busy()) raf = requestAnimationFrame(frame); };

  function resize() {
    const w = Math.max(1, box.clientWidth), h = Math.max(1, box.clientHeight), d = Math.min(devicePixelRatio || 1, S.maxDpr);
    canvas.width = Math.round(w * d); canvas.height = Math.round(h * d);
    render(); wake();
  }
  function locate(e) {
    const b = box.getBoundingClientRect(), x = e.clientX - b.left, y = e.clientY - b.top;
    pointer.inside = x >= 0 && y >= 0 && x <= b.width && y <= b.height;
    const sc = Math.max(1, Math.min(b.width, b.height) * 0.5);
    pointer.x = (x - b.width / 2) / sc; pointer.y = (b.height / 2 - y) / sc;
  }
  addEventListener('pointermove', e => { locate(e); wake(); }, { passive: true });
  addEventListener('pointerdown', e => { locate(e); if (pointer.inside && !reduce) { surge.age = 0; wake(); } }, { passive: true });
  document.documentElement.addEventListener('pointerleave', () => { pointer.inside = false; });
  document.addEventListener('visibilitychange', () => { last = 0; wake(); });
  new MutationObserver(wake).observe(document.body, { attributes: true, attributeFilter: ['class'] });
  new ResizeObserver(resize).observe(box);
  new IntersectionObserver(es => { visible = es.some(e => e.isIntersecting); if (visible) { last = 0; wake(); } }).observe(box);
  resize();
})();
