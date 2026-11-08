// Ambient background: a faint dot grid that drifts slowly and brightens a little near the cursor.
// Cheap by construction: the grid is drawn once into a 28x28 tile and the screen is filled with that tile
// at an offset (one fill per frame); only the ~100 dots near the cursor are drawn individually. The drift
// is 3 px/s, so it updates at 15 fps; a cursor move redraws at once. Drawing stops in hidden tabs, is
// static under prefers-reduced-motion, and window.ambient.pause() / resume() let the capture page stop it
// while recording and uploading, so it never competes with the frames whose timing is being measured.
(() => {
  const c = document.getElementById('ambient-canvas');
  if (!c) return;
  const g = c.getContext('2d');
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const GAP = 28, BASE = 0.07, PEAK = 0.24, RADIUS = 140, FPS = 15;
  let w = 0, h = 0, pattern = null, mx = -1e4, my = -1e4, timer = 0, queued = 0, paused = false;
  const t0 = performance.now();

  function size() {
    const dpr = Math.min(devicePixelRatio || 1, 1.5);
    w = innerWidth; h = innerHeight;
    c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const tile = document.createElement('canvas');
    tile.width = tile.height = GAP;
    const tg = tile.getContext('2d');
    tg.fillStyle = `rgba(255,255,255,${BASE})`;
    tg.fillRect(0, 0, 1.1, 1.1);
    pattern = g.createPattern(tile, 'repeat');
  }

  function draw() {
    queued = 0;
    const t = still ? 0 : (performance.now() - t0) / 1000;
    const ox = (t * 3) % GAP, oy = (t * 1.5) % GAP;          // slow diagonal drift
    g.clearRect(0, 0, w, h);
    g.save(); g.translate(ox, oy); g.fillStyle = pattern; g.fillRect(-GAP, -GAP, w + 2 * GAP, h + 2 * GAP); g.restore();
    if (mx < -1e3) return;
    // brighter dots near the cursor, on the same drifting grid
    const x0 = Math.floor((mx - RADIUS - ox) / GAP) * GAP + ox, y0 = Math.floor((my - RADIUS - oy) / GAP) * GAP + oy;
    for (let y = y0; y <= my + RADIUS; y += GAP) {
      for (let x = x0; x <= mx + RADIUS; x += GAP) {
        const d = Math.hypot(x - mx, y - my);
        if (d >= RADIUS) continue;
        const k = (1 - d / RADIUS) ** 2;
        g.fillStyle = `rgba(255,255,255,${(BASE + (PEAK - BASE) * k).toFixed(3)})`;
        g.fillRect(x - 0.3 * k, y - 0.3 * k, 1.1 + 0.6 * k, 1.1 + 0.6 * k);
      }
    }
  }
  const redraw = () => { if (!queued) queued = requestAnimationFrame(draw); };

  function start() {
    if (still || paused || timer) return;
    timer = setInterval(() => { if (!document.hidden) redraw(); }, 1000 / FPS);
  }
  function stop() { clearInterval(timer); timer = 0; cancelAnimationFrame(queued); queued = 0; }

  addEventListener('resize', () => { size(); draw(); });
  addEventListener('pointermove', e => { mx = e.clientX; my = e.clientY; if (!paused) redraw(); }, { passive: true });
  document.addEventListener('pointerleave', () => { mx = my = -1e4; if (!paused) redraw(); });

  window.ambient = {
    pause() { paused = true; stop(); },
    resume() { paused = false; start(); },
  };
  size(); draw(); start();
})();
