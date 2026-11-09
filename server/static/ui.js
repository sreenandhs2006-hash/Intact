// Page motion and section behaviour. Purely presentational: it only *reads* the elements capture.js writes
// (#state text, #bar width, #report content) and never changes app state, endpoints or IDs.
//  - scroll reveal for .reveal elements
//  - the step tracker (#steps) follows the #state capsule
//  - the big percentage (#pct) follows the #bar width
//  - body.busy while recording/uploading: decorative loops pause, like the ambient canvas, so nothing competes
//    with the frames whose timing is being measured
(() => {
  const $ = id => document.getElementById(id);
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // scroll reveal
  const els = document.querySelectorAll('.reveal');
  if (still || !('IntersectionObserver' in window)) els.forEach(e => e.classList.add('in'));
  else {
    const io = new IntersectionObserver(es => es.forEach(e => {
      if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
    }), { rootMargin: '0px 0px -8% 0px' });
    els.forEach(e => io.observe(e));
  }

  // stop the hero loops when the hero is off screen
  const hero = $('hero');
  if (hero && 'IntersectionObserver' in window)
    new IntersectionObserver(([e]) => hero.classList.toggle('idle', !e.isIntersecting)).observe(hero);

  // pipeline: flash each specular node as a travelling piece reaches it. Pieces take 4 s end to end and two run
  // 2 s apart, so node i (at fraction i/3 of the track) is reached every 2 s at phase (i/3 * 4000) mod 2000 ms.
  // The phase is read from the CSS animation itself, so the flashes stay in step with what is on screen.
  const pk = document.querySelector('.pipe .pk');
  const nodes = [...document.querySelectorAll('.pipe .dot')];
  if (pk && nodes.length && window.specular && !still) {
    const anim = () => pk.getAnimations?.()[0];
    nodes.forEach((dot, i) => {
      const at = (i / (nodes.length - 1)) * 4000 % 2000;
      const next = () => {
        const a = anim();
        if (!a || a.playState !== 'running') return setTimeout(next, 500);   // paused (busy / off screen)
        const t = (a.currentTime ?? 0) % 2000;
        setTimeout(() => { window.specular.flash(dot); setTimeout(next, 100); }, ((at - t + 2000) % 2000) || 2000);
      };
      next();
    });
  }

  // step tracker follows the state capsule
  const state = $('state'), steps = $('steps'), report = $('report');
  const STEP = { STARTING: 0, RECORDING: 0, UPLOADING: 1, RECONNECTING: 1, VERIFYING: 2, COMPLETE: 3 };
  const BUSY = new Set(['STARTING', 'RECORDING', 'UPLOADING', 'RECONNECTING', 'VERIFYING']);
  let last = -1;
  function track() {
    const s = state.textContent.trim();
    document.body.classList.toggle('busy', BUSY.has(s));
    if (!steps) return;
    const items = [...steps.children];
    const failed = state.classList.contains('bad');
    const reported = !!report?.querySelector('.verdict');
    let now = s in STEP ? STEP[s] : (failed ? Math.max(last, 0) : -1);
    if (!failed && s in STEP) last = now;
    items.forEach((li, i) => {
      const done = reported ? true : i < now;
      li.className = done ? 'done' : i === now ? (failed ? 'fail' : 'now') : '';
    });
    const fill = reported ? 1 : Math.max(now, 0) / (items.length - 1);
    steps.style.setProperty('--fill', fill.toFixed(3));
  }
  if (state) {
    new MutationObserver(track).observe(state, { childList: true, characterData: true, subtree: true, attributes: true });
    if (report) new MutationObserver(() => {
      track();
      if (report.querySelector('.verdict')) $('result')?.scrollIntoView({ behavior: still ? 'auto' : 'smooth', block: 'start' });
    }).observe(report, { childList: true });
    track();
  }

  // big percentage follows the progress bar; counts up smoothly between updates
  const bar = $('bar'), pct = $('pct');
  if (bar && pct) {
    let shown = 0, target = 0, raf = 0;
    const paint = () => { pct.innerHTML = `${Math.round(shown)}<small>%</small>`; };
    const step = () => {
      shown += (target - shown) * 0.2;
      if (Math.abs(target - shown) < 0.5) shown = target;
      paint();
      raf = shown === target ? 0 : requestAnimationFrame(step);
    };
    new MutationObserver(() => {
      target = parseFloat(bar.style.width) || 0;
      if (still) { shown = target; paint(); } else if (!raf) raf = requestAnimationFrame(step);
    }).observe(bar, { attributes: true, attributeFilter: ['style'] });
  }
})();
