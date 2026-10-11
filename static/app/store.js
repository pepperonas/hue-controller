// Zustandsspeicher der Hue-App (rein, ohne DOM — auch unter node:test).
//
// Quelle der Wahrheit ist der Server (SSE: snapshot + delta). Darueber liegt
// eine UEBERLAGERUNG fuer zwei Faelle:
//   * optimistisch: ein Tipp zeigt sofort den neuen Zustand, bis die Bridge ihn
//     bestaetigt (oder die Frist ablaeuft -> dann gilt wieder der Server);
//   * Zugschutz: waehrend ein Slider gezogen wird, wuerden eintreffende Deltas
//     den Daumen unter dem Finger wegziehen — die Ueberlagerung haelt ihn fest,
//     bis 600 ms nach dem Loslassen.
// Ein Fehler-Event der Queue nimmt die Ueberlagerung des Ziels sofort zurueck.

export const OPTIMISTIC_MS = 2500;
export const RELEASE_MS = 600;

export function createStore(clock = () => Date.now()) {
  const base = { rooms: {}, lights: {}, scenes: {}, moods: {}, effects: {}, home: {}, status: {} };
  const overlay = new Map();          // "rooms:ID" -> { patch, until }
  const listeners = new Set();
  let ready = false;

  const key = (kind, id) => kind + ':' + id;

  function emit(change) {
    for (const fn of listeners) {
      try { fn(change); } catch (e) { /* ein kaputter Abnehmer stoppt die anderen nicht */ }
    }
  }

  function get(kind, id) {
    const b = base[kind][id];
    if (!b) return null;
    const o = overlay.get(key(kind, id));
    if (!o) return b;
    if (o.until !== Infinity && o.until <= clock()) {
      overlay.delete(key(kind, id));
      return b;
    }
    return { ...b, ...o.patch };
  }

  function list(kind) {
    return Object.keys(base[kind]).map((id) => get(kind, id));
  }

  function applySnapshot(data) {
    for (const k of ['rooms', 'lights', 'scenes']) base[k] = { ...(data[k] || {}) };
    for (const k of ['moods', 'effects', 'home', 'status']) if (data[k]) base[k] = data[k];
    ready = true;
    emit({ all: true });
  }

  function applyDelta(d) {
    const change = { rooms: new Set(), lights: new Set(), scenes: false, all: false };
    for (const k of ['rooms', 'lights', 'scenes']) {
      for (const [id, v] of Object.entries(d[k] || {})) {
        base[k][id] = v;
        if (k === 'scenes') change.scenes = true; else change[k].add(id);
      }
      for (const id of (d.removed && d.removed[k]) || []) {
        delete base[k][id];
        overlay.delete(key(k, id));
        if (k === 'scenes') change.scenes = true; else change.all = true;
      }
    }
    if (d.home) base.home = d.home;
    emit(change);
  }

  function setStatus(s) { base.status = s; emit({ status: true }); }

  /** Optimistischer Zustand fuer ``ms`` Millisekunden. */
  function optimistic(kind, id, patch, ms = OPTIMISTIC_MS) {
    const prev = overlay.get(key(kind, id));
    const until = prev && prev.until === Infinity ? Infinity : clock() + ms;
    overlay.set(key(kind, id), { patch: { ...(prev ? prev.patch : {}), ...patch }, until });
    emit(changeFor(kind, id));
  }

  /** Zugschutz an (Slider gedrueckt). */
  function hold(kind, id, patch = {}) {
    const prev = overlay.get(key(kind, id));
    overlay.set(key(kind, id), { patch: { ...(prev ? prev.patch : {}), ...patch }, until: Infinity });
  }

  /** Zugschutz aus — der gezogene Wert bleibt noch ``ms`` stehen. */
  function release(kind, id, ms = RELEASE_MS) {
    const o = overlay.get(key(kind, id));
    if (o) o.until = clock() + ms;
  }

  /** Fehler-Event der Queue: Ueberlagerung des Ziels sofort verwerfen. */
  function rollback(rtype, rid) {
    let kind = null, id = null;
    if (rtype === 'light') { kind = 'lights'; id = rid; }
    else if (rtype === 'grouped_light') {
      const room = Object.values(base.rooms).find((r) => r.group === rid);
      if (room) { kind = 'rooms'; id = room.id; }
    }
    if (!kind || !overlay.delete(key(kind, id))) return false;
    emit(changeFor(kind, id));
    return true;
  }

  function changeFor(kind, id) {
    const c = { rooms: new Set(), lights: new Set(), scenes: false, all: false };
    if (c[kind]) c[kind].add(id);
    return c;
  }

  return {
    get, list, applySnapshot, applyDelta, setStatus, optimistic, hold, release, rollback,
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    get ready() { return ready; },
    get raw() { return base; },
    scenesOf(roomId) { return list('scenes').filter((s) => s.room === roomId); },
    lightsOf(roomId) { const r = get('rooms', roomId); return r ? r.lights.map((id) => get('lights', id)).filter(Boolean) : []; },
  };
}

/** Sendet hoechstens alle ``ms`` und garantiert, dass der LETZTE Wert ankommt. */
export function throttle(fn, ms, clock = () => Date.now(), timer = setTimeout) {
  let last = -Infinity, pending = null, scheduled = false;
  return function (...args) {
    pending = args;
    const now = clock();
    if (now - last >= ms) {
      last = now;
      const a = pending; pending = null;
      fn(...a);
    } else if (!scheduled) {
      scheduled = true;
      timer(() => {
        scheduled = false;
        if (pending) { last = clock(); const a = pending; pending = null; fn(...a); }
      }, ms - (now - last));
    }
  };
}
