// Netzwerk der Hue-App: Live-Zustand per SSE, Befehle per JSON.
// Unter /app/hue/ (nginx) laufen Aufrufe ueber /proxy/hue/api — nur dort hat
// der Event-Stream eine ungepufferte Location; sonst kaemen Events Sekunden spaet.

export const BASE = typeof location !== 'undefined' && location.pathname.startsWith('/app/hue')
  ? '/proxy/hue/api' : '/api';
const FALLBACK_POLL_MS = 10000;

async function call(method, path, body, timeoutMs = 6000) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(BASE + path, {
      method,
      cache: 'no-store',
      signal: ctl.signal,
      // JSON ist Pflicht: der Server lehnt alles andere ab (CSRF-Riegel)
      headers: { 'Content-Type': 'application/json' },
      body: method === 'GET' ? undefined : JSON.stringify(body || {}),
    });
    let data = null;
    try { data = await r.json(); } catch (e) { /* leer */ }
    if (!r.ok) return { ok: false, status: r.status, error: (data && (data.error || data.message)) || 'HTTP ' + r.status, data };
    return { ok: true, status: r.status, data };
  } catch (e) {
    return { ok: false, status: 0, error: e.name === 'AbortError' ? 'Zeitüberschreitung' : 'nicht erreichbar' };
  } finally {
    clearTimeout(t);
  }
}

export const api = {
  get: (p, t) => call('GET', p, null, t),
  put: (p, b) => call('PUT', p, b),
  post: (p, b) => call('POST', p, b),
  del: (p) => call('DELETE', p, {}),
};

/**
 * Haelt den Speicher aktuell: SSE, bei Ausfall 10-s-Polling mit sichtbarem
 * Hinweis, Pause im Hintergrund-Tab. ``onLink(state)`` meldet 'live' | 'poll' | 'off'.
 */
export function connect(store, onLink, onError) {
  let es = null, pollTimer = null, stopped = false, retry = 1000;

  function startPoll() {
    if (pollTimer || stopped) return;
    const tick = async () => {
      const r = await api.get('/v2/state', 8000);
      if (r.ok) { store.applySnapshot(r.data); onLink('poll'); } else onLink('off');
    };
    tick();
    pollTimer = setInterval(tick, FALLBACK_POLL_MS);
  }
  function stopPoll() { clearInterval(pollTimer); pollTimer = null; }

  function open() {
    if (stopped || document.hidden) return;
    if (!('EventSource' in window)) { startPoll(); return; }
    es = new EventSource(BASE + '/v2/events');
    es.addEventListener('snapshot', (e) => {
      store.applySnapshot(JSON.parse(e.data));
      retry = 1000;
      stopPoll();
      onLink('live');
    });
    es.addEventListener('delta', (e) => store.applyDelta(JSON.parse(e.data)));
    es.addEventListener('status', (e) => {
      const s = JSON.parse(e.data);
      store.setStatus(s);
      if (!s.connected) onLink('bridge-off');
    });
    es.addEventListener('fail', (e) => {
      // die Bridge hat einen Befehl abgelehnt: optimistischen Wert zuruecknehmen
      const d = JSON.parse(e.data);
      store.rollback(d.rtype, d.rid);
      onError && onError(d);
    });
    es.addEventListener('error', () => {
      // Verbindungsabbruch: Polling als Rueckfall, Wiederverbinden mit Backoff
      es.close();
      es = null;
      startPoll();
      setTimeout(open, retry);
      retry = Math.min(30000, retry * 2);
    });
  }

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      if (es) { es.close(); es = null; }
      stopPoll();
    } else if (!es) {
      open();
    }
  });

  open();
  return { stop() { stopped = true; if (es) es.close(); stopPoll(); } };
}
