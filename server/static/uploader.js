// Browser port of client/uploader.py: same protocol, same rules.
//  - sequential chunks addressed by byte offset, each with its own SHA-256 (X-Chunk-SHA256)
//  - transient failures (network error, timeout = stall, 5xx, 429, 422) -> retry with
//    exponential backoff + full jitter, halve the chunk, then ask the server where to continue
//  - adaptive chunk size: aim for ~2 s per chunk, grow at most 2x per step
//  - resume: the upload id is remembered per file SHA-256 (localStorage), and the server's
//    received_bytes says where to continue
//  - COMPLETE only when the server's full-file hash matches ours

export async function sha256Hex(data) {
  const buf = data instanceof Blob ? await data.arrayBuffer() : data;
  const h = await crypto.subtle.digest('SHA-256', buf);
  return [...new Uint8Array(h)].map(b => b.toString(16).padStart(2, '0')).join('');
}

class GiveUp extends Error {}

export class Uploader {
  constructor({ base = '', initialChunk = 256 * 1024, minChunk = 64 * 1024, maxChunk = 8 * 1024 * 1024,
                targetChunkSeconds = 2, stallTimeoutMs = 20000, maxConsecutiveFailures = 15,
                backoffBaseMs = 500, backoffCapMs = 30000, onEvent = () => {} } = {}) {
    Object.assign(this, { base, chunk: initialChunk, minChunk, maxChunk, targetChunkSeconds, stallTimeoutMs,
                          maxConsecutiveFailures, backoffBaseMs, backoffCapMs, onEvent });
    this.failures = 0; this.retries = 0; this.bytesSent = 0; this.events = [];
  }

  log(event, fields = {}) {
    const e = { t: Date.now() / 1000, event, ...fields };
    this.events.push(e);
    this.onEvent(e);
  }

  async failed(what, err) {
    this.failures++; this.retries++;
    if (this.failures > this.maxConsecutiveFailures) {
      this.log('give_up', { what, error: String(err) });
      throw new GiveUp(`${what}: ${this.failures - 1} consecutive failures, last: ${err}`);
    }
    const delay = Math.random() * Math.min(this.backoffCapMs, this.backoffBaseMs * 2 ** (this.failures - 1));
    this.chunk = Math.max(this.minChunk, Math.floor(this.chunk / 2));
    this.log('retry', { what, error: String(err), attempt: this.failures, delay_s: +(delay / 1000).toFixed(3),
                        next_chunk: this.chunk });
    await new Promise(r => setTimeout(r, delay));
  }

  // fetch with a timeout: a request that makes no progress for stallTimeoutMs is a stall
  async fetchT(url, opts = {}) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(new Error('stall timeout')), this.stallTimeoutMs);
    try { return await fetch(this.base + url, { ...opts, signal: ctl.signal, cache: 'no-store' }); }
    finally { clearTimeout(timer); }
  }

  // send until we get a response that is not a transient error
  async request(what, url, opts) {
    for (;;) {
      let r;
      try { r = await this.fetchT(url, opts); }
      catch (err) { await this.failed(what, err); continue; }
      if (r.status >= 500 || r.status === 429) { await this.failed(what, new Error(`HTTP ${r.status}`)); continue; }
      return r;
    }
  }

  async status(id) {
    const r = await this.request('status', `/uploads/${id}`);
    if (!r.ok) throw new GiveUp(`status HTTP ${r.status}`);
    return r.json();
  }

  async resumeOrCreate(filename, size, sha) {
    const key = `vi-upload:${sha}`;
    const saved = safeGet(key);
    if (saved) {
      const r = await this.request('status', `/uploads/${saved}`);
      if (r.ok) {
        const info = await r.json();
        if (['UPLOADING', 'STALLED', 'COMPLETE'].includes(info.state) && info.sha256 === sha) {
          this.log('resume', { upload_id: info.upload_id, received_bytes: info.received_bytes, state: info.state });
          return { info, resumed: info.received_bytes };
        }
      }
    }
    const r = await this.request('create', '/uploads', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename, size, sha256: sha }) });
    if (!r.ok) throw new GiveUp(`create HTTP ${r.status}: ${await r.text()}`);
    const info = await r.json();
    safeSet(key, info.upload_id);
    this.log('created', { upload_id: info.upload_id, size, sha256: sha });
    return { info, resumed: 0 };
  }

  // beforeFinalize(uploadId): optional hook, e.g. attach the capture log
  async upload(blob, filename, { sha = null, beforeFinalize = null } = {}) {
    const t0 = performance.now();
    const size = blob.size;
    sha = sha || await sha256Hex(blob);
    this.log('start', { filename, size, sha256: sha });
    let state = 'FAILED', detail = null, uploadId = null, resumed = 0, serverSha = null;
    try {
      const { info, resumed: rb } = await this.resumeOrCreate(filename, size, sha);
      uploadId = info.upload_id; resumed = rb; state = info.state; serverSha = info.server_sha256;
      let received = info.received_bytes;
      while (received < size && state !== 'COMPLETE') {
        const data = blob.slice(received, Math.min(size, received + this.chunk));
        const chunkSha = await sha256Hex(data);
        const t = performance.now();
        let r;
        try {
          r = await this.fetchT(`/uploads/${uploadId}/chunks?offset=${received}`, {
            method: 'PUT', body: data,
            headers: { 'X-Chunk-SHA256': chunkSha, 'Content-Type': 'application/octet-stream' } });
        } catch (err) {
          this.bytesSent += data.size;
          await this.failed('chunk', err);
          received = (await this.status(uploadId)).received_bytes;
          continue;
        }
        this.bytesSent += data.size;
        const body = (r.headers.get('content-type') || '').startsWith('application/json') ? await r.json() : {};
        if (r.status === 200) {
          const elapsed = Math.max((performance.now() - t) / 1000, 1e-3);
          this.failures = 0;
          received = body.received_bytes;
          const rate = data.size / elapsed;
          this.chunk = Math.floor(Math.min(this.maxChunk, this.chunk * 2, Math.max(this.minChunk, rate * this.targetChunkSeconds)));
          this.log('chunk_ok', { offset: received - data.size, length: data.size, secs: +elapsed.toFixed(3),
                                 rate_Bps: Math.floor(rate), duplicate: body.duplicate, next_chunk: this.chunk,
                                 received_bytes: received, size });
        } else if (r.status === 409 && 'received_bytes' in body) {
          received = body.received_bytes;  // the server says where to continue
          this.log('resync', { received_bytes: received, reason: body.error });
        } else if (r.status === 409) {
          state = body.state || 'FAILED'; detail = body.message; break;
        } else if (r.status === 422 || r.status >= 500 || r.status === 429) {
          await this.failed('chunk', new Error(`HTTP ${r.status} ${body.error || ''}`));
          received = (await this.status(uploadId)).received_bytes;
        } else {
          throw new GiveUp(`Unexpected HTTP ${r.status}: ${JSON.stringify(body).slice(0, 200)}`);
        }
      }
      if (received >= size && state !== 'COMPLETE') {
        if (beforeFinalize) await beforeFinalize(uploadId, this);
        const r = await this.request('finalize', `/uploads/${uploadId}/finalize`, { method: 'POST' });
        const body = await r.json();
        state = body.state || 'FAILED'; detail = body.detail || body.message; serverSha = body.server_sha256;
      }
    } catch (err) {
      if (!(err instanceof GiveUp)) throw err;
      state = 'FAILED'; detail = err.message;
    }
    if (['COMPLETE', 'REJECTED'].includes(state)) safeRemove(`vi-upload:${sha}`);
    const result = { state, upload_id: uploadId, size, client_sha256: sha, server_sha256: serverSha,
                     hash_match: state === 'COMPLETE' && serverSha === sha,
                     duration_s: +((performance.now() - t0) / 1000).toFixed(3), retries: this.retries,
                     resumed_bytes: resumed, bytes_sent: this.bytesSent, detail };
    this.log('result', result);
    return result;
  }
}

// localStorage can throw (private mode, blocked storage): resume then simply starts over
function safeGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function safeSet(k, v) { try { localStorage.setItem(k, v); } catch {} }
function safeRemove(k) { try { localStorage.removeItem(k); } catch {} }
