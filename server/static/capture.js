// M5 browser client: record 30 s, log per-frame timing with requestVideoFrameCallback,
// upload video + log with the same resumable protocol, then show the integrity report.
import { Uploader, sha256Hex } from './uploader.js';

const RECORD_MS = 30000;
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ---------------- IndexedDB: keep the finished recording until the upload is COMPLETE ----------------
// so closing/reloading the page or a crash does not lose it (resume after restart).
function idb() {
  return new Promise((res, rej) => {
    const r = indexedDB.open('vi-capture', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('pending');
    r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
  });
}
async function idbDo(mode, fn) {
  try {
    const db = await idb();
    return await new Promise((res, rej) => {
      const tx = db.transaction('pending', mode); const req = fn(tx.objectStore('pending'));
      tx.oncomplete = () => res(req?.result); tx.onerror = () => rej(tx.error);
    });
  } catch (e) { log('ui', `browser storage unavailable (${e}); resume after reload will not work`); return null; }
}
const savePending = rec => idbDo('readwrite', s => s.put(rec, 'current'));
const loadPending = () => idbDo('readonly', s => s.get('current'));
const clearPending = () => idbDo('readwrite', s => s.delete('current'));

// ---------------- UI log ----------------
function log(kind, text) {
  const row = document.createElement('tr');
  row.innerHTML = `<td>${new Date().toLocaleTimeString()}</td><td>${esc(kind)}</td><td>${esc(text)}</td>`;
  $('events').prepend(row);
}
function setState(text, cls = '') { $('state').textContent = text; $('state').className = 'state ' + cls; }

// ---------------- sources ----------------
async function cameraSource() {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } }, audio: false });
  return { stream, stop: () => stream.getTracks().forEach(t => t.stop()), faults: [] };
}

// Synthetic source for testing without a camera: paints a numbered frame every 1/30 s and hands it
// to the track with requestFrame(), so the cadence does not depend on the display's refresh rate.
// Optional fault: no frames for 500 ms at 10 s - a known capture-side gap for checking the analysis.
function testPatternSource(simulateStall) {
  const c = document.createElement('canvas'); c.width = 1280; c.height = 720;
  const g = c.getContext('2d');
  const faults = simulateStall ? [{ type: 'source_stall', after_start_ms: 10000, duration_ms: 500 }] : [];
  const stream = c.captureStream(0);           // 0 = capture only when requestFrame() is called
  const track = stream.getVideoTracks()[0];
  let n = 0, recStart = null;
  const timer = setInterval(() => {
    const since = recStart === null ? -1 : performance.now() - recStart;
    if (faults.some(f => since >= f.after_start_ms && since < f.after_start_ms + f.duration_ms)) return;
    g.fillStyle = '#202020'; g.fillRect(0, 0, 1280, 720);
    g.fillStyle = `hsl(${(n * 3) % 360} 70% 55%)`; g.fillRect((n * 12) % 1280, 0, 80, 720);
    g.fillStyle = '#fff'; g.font = '64px monospace';
    g.fillText(`frame ${n}`, 60, 120); g.fillText(`${(since / 1000).toFixed(3)} s`, 60, 210);
    n++;
    track.requestFrame();
  }, 1000 / 30);
  return { stream, stop: () => { clearInterval(timer); stream.getTracks().forEach(t => t.stop()); }, faults,
           markStart: t => { recStart = t; } };
}

function pickMime() {
  for (const t of ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm', 'video/mp4'])
    if (MediaRecorder.isTypeSupported(t)) return t;
  return '';
}

// ---------------- record ----------------
async function record() {
  $('record').disabled = true;
  const kind = $('source').value;
  let src;
  try { src = kind === 'camera' ? await cameraSource() : testPatternSource($('stall').checked); }
  catch (e) { setState('NO CAMERA', 'bad'); log('error', `${e.name}: ${e.message}`); $('record').disabled = false; return; }

  const video = $('preview');
  video.srcObject = src.stream; await video.play();
  const track = src.stream.getVideoTracks()[0];
  const mime = pickMime();
  const capLog = {
    log_version: 1, clock: 'performance.now() milliseconds (page monotonic clock)',
    source: kind === 'camera' ? 'camera' : 'test_pattern', user_agent: navigator.userAgent, mime_type: mime,
    requested: { width: 1280, height: 720, frame_rate: 30 }, track_settings: track.getSettings(),
    rvfc_supported: 'requestVideoFrameCallback' in HTMLVideoElement.prototype,
    recorder: {}, visibility: [{ t_ms: performance.now(), state: document.visibilityState }],
    frames: [], simulated_faults: src.faults,
  };
  const onVis = () => capLog.visibility.push({ t_ms: performance.now(), state: document.visibilityState });
  document.addEventListener('visibilitychange', onVis);

  let recording = false, stopped = false;
  if (capLog.rvfc_supported) {
    const onFrame = (now, m) => {
      if (recording) capLog.frames.push({
        now, presented_frames: m.presentedFrames, capture_time: m.captureTime ?? null,
        presentation_time: m.presentationTime, expected_display_time: m.expectedDisplayTime,
        media_time: m.mediaTime, width: m.width, height: m.height, processing_duration: m.processingDuration ?? null });
      if (!stopped) video.requestVideoFrameCallback(onFrame);
    };
    video.requestVideoFrameCallback(onFrame);
  } else {
    log('warn', 'requestVideoFrameCallback not supported: no per-frame capture evidence');
  }

  const parts = [];
  const rec = new MediaRecorder(src.stream, mime ? { mimeType: mime, videoBitsPerSecond: 2_500_000 } : {});
  capLog.recorder.timeslice_ms = 1000;
  rec.ondataavailable = e => { if (e.data.size) parts.push(e.data); };
  const done = new Promise(res => { rec.onstop = res; });
  rec.onstart = () => { capLog.recorder.started_ms = performance.now(); };
  recording = true;
  capLog.recorder.start_called_ms = performance.now();
  src.markStart?.(capLog.recorder.start_called_ms);
  rec.start(capLog.recorder.timeslice_ms);
  // 30 s from start(): the recording covers frames from start() on, even while the encoder starts up
  setTimeout(() => { capLog.recorder.stop_called_ms = performance.now(); recording = false; rec.stop(); }, RECORD_MS);
  setState('RECORDING', 'info');
  const tick = setInterval(() => {
    const s = (performance.now() - capLog.recorder.start_called_ms) / 1000;
    $('timer').textContent = `${Math.min(s, 30).toFixed(1)} / 30 s · ${capLog.frames.length} frames logged`;
  }, 200);

  await done;
  stopped = true;
  capLog.recorder.stopped_ms = performance.now();
  clearInterval(tick);
  document.removeEventListener('visibilitychange', onVis);
  src.stop();
  video.srcObject = null;

  const blob = new Blob(parts, { type: rec.mimeType || mime });
  const ext = (rec.mimeType || mime).includes('mp4') ? 'mp4' : 'webm';
  const filename = `capture-${new Date().toISOString().replace(/[:.]/g, '-')}.${ext}`;
  const sha = await sha256Hex(blob);
  capLog.video_sha256 = sha;
  capLog.video_bytes = blob.size;
  log('recorded', `${filename}: ${(blob.size / 1048576).toFixed(2)} MB, ${capLog.frames.length} frame records, sha256 ${sha.slice(0, 16)}…`);
  const pending = { blob, filename, sha, logText: JSON.stringify(capLog) };
  await savePending(pending);
  offerDownloads(pending);
  await upload(pending);
}

function offerDownloads(p) {
  $('downloads').innerHTML = '';
  for (const [name, data, type] of [[p.filename, p.blob], [p.filename.replace(/\.\w+$/, '.capture-log.json'), p.logText, 'application/json']]) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(data instanceof Blob ? data : new Blob([data], { type }));
    a.download = name; a.textContent = `Save ${name}`;
    $('downloads').append(a, ' ');
  }
}

// ---------------- upload (same protocol as the Python client) ----------------
async function upload(p) {
  $('record').disabled = true; $('resume').hidden = true; $('discard').hidden = true;
  setState('UPLOADING', 'info');
  const up = new Uploader({ onEvent: e => {
    if (e.event === 'chunk_ok') {
      $('bar').style.width = `${(100 * e.received_bytes / e.size).toFixed(1)}%`;
      $('progress').textContent = `${(e.received_bytes / 1048576).toFixed(2)} / ${(e.size / 1048576).toFixed(2)} MB · next chunk ${(e.next_chunk / 1024).toFixed(0)} KB`;
    } else if (e.event !== 'result') {
      log(e.event, JSON.stringify(Object.fromEntries(Object.entries(e).filter(([k]) => k !== 't' && k !== 'event'))));
      if (e.event === 'retry') setState('RETRYING', 'warn');
    }
  } });
  const attachLog = async (uploadId, u) => {
    const logSha = await sha256Hex(new TextEncoder().encode(p.logText));
    const r = await u.request('capture_log', `/uploads/${uploadId}/capture-log`, {
      method: 'POST', body: p.logText, headers: { 'Content-Type': 'application/json', 'X-Content-SHA256': logSha } });
    const body = await r.json().catch(() => ({}));
    if (r.ok) log('capture_log', `stored (${body.duplicate ? 'already there' : 'new'}), sha256 ${logSha.slice(0, 16)}…`);
    else log('warn', `capture log not stored: HTTP ${r.status} ${body.error || ''} - the report will have no capture evidence`);
  };
  const res = await up.upload(p.blob, p.filename, { sha: p.sha, beforeFinalize: attachLog });
  log('result', JSON.stringify(res));
  if (res.state === 'COMPLETE' && res.hash_match) {
    setState('COMPLETE', 'ok');
    await clearPending();
    await showReport(res.upload_id);
  } else {
    setState(res.state, 'bad');
    if (res.state === 'FAILED') { $('resume').hidden = false; $('discard').hidden = false; }
  }
  $('record').disabled = false;
}

async function showReport(id) {
  $('report').innerHTML = 'Analysing…';
  for (;;) {
    const r = await fetch(`/uploads/${id}/report`, { cache: 'no-store' });
    if (r.status === 200) {
      const rep = await r.json();
      const s = rep.summary, ce = rep.capture_evidence || {};
      $('report').innerHTML = `<p><b>${esc(s.validation)}</b> · transfer ${esc(s.transfer)} · ${s.anomalies_total} anomalies
        ${esc(Object.entries(s.anomaly_counts).map(([k, n]) => `${k}: ${n}`).join(', '))}</p>
        <p>${esc(s.dropped_frames_in_original_recording)}</p>
        <p class="meta">capture log: ${ce.present ? `time base ${esc(ce.time_base)}, coverage ${((ce.coverage || 0) * 100).toFixed(1)}%, ${esc(ce.records_in_recording)} records` : 'none'}</p>
        <p><a href="/uploads/${id}/report.html" target="_blank">Open full report</a> · <a href="/uploads/${id}/report" target="_blank">JSON</a></p>`;
      return;
    }
    if (r.status !== 202 && r.status !== 404) { $('report').textContent = `Analysis failed (HTTP ${r.status})`; return; }
    await new Promise(res => setTimeout(res, 1000));
  }
}

// ---------------- start-up: offer to resume an unfinished upload ----------------
let pendingRec = null;
$('record').onclick = () => record().catch(e => { log('error', String(e)); setState('ERROR', 'bad'); $('record').disabled = false; });
$('resume').onclick = () => upload(pendingRec).catch(e => log('error', String(e)));
$('discard').onclick = async () => { await clearPending(); $('resume').hidden = true; $('discard').hidden = true; log('ui', 'unfinished recording discarded'); };
$('source').onchange = () => { $('stallrow').hidden = $('source').value !== 'test'; };
$('rvfc').textContent = 'requestVideoFrameCallback' in HTMLVideoElement.prototype ? 'supported' : 'NOT supported';
// ?autostart=camera|test[&stall=1] starts a recording on load (used for scripted runs, e.g. headless
// Chrome/Edge with --use-fake-device-for-media-stream)
const q = new URLSearchParams(location.search);
if (q.get('autostart')) {
  $('source').value = q.get('autostart') === 'test' ? 'test' : 'camera';
  $('stall').checked = q.get('stall') === '1';
  $('record').click();
}
loadPending().then(p => {
  if (!p) return;
  pendingRec = p;
  log('ui', `unfinished recording in this browser: ${p.filename} (${(p.blob.size / 1048576).toFixed(2)} MB)`);
  offerDownloads(p);
  $('resume').hidden = false; $('discard').hidden = false;
});
