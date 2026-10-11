// Raum-Blatt: alles fuer einen Raum an einem Ort — Stimmungen und Szenen,
// Farbe/Weiss, Effekte, Strobo, die einzelnen Lampen.
import { h, icon, shSwitch, shSlider, sheet, toast, confirmSheet, askText } from '../dom.js';
import { api } from '../api.js';
import { throttle } from '../store.js';
import { colorWheel, whiteSlider } from '../colorpick.js';
import { clampToGamut } from '../color.js';

const SCENE_NAME = /^[\p{L}\p{N} .,!?:+()/-]{1,32}$/u;
let strobeConfirmed = false;   // Lichtblitz-Warnung einmal je Sitzung

function section(title, ...kids) {
  return h('section', { class: 'sec' }, h('h3', { class: 'sec-title', text: title }), ...kids);
}

function chip(label, { colors, active, onclick, title }) {
  const dots = (colors || []).slice(0, 4).map((c) => h('span', { class: 'chip-dot', style: { background: c } }));
  return h('button', { class: 'sh-pill chip' + (active ? ' on' : ''), type: 'button', title, onclick },
    dots.length ? h('span', { class: 'chip-dots', 'aria-hidden': 'true' }, dots) : null, label);
}

async function run(promise, what) {
  const r = await promise;
  if (!r.ok) toast(what + ': ' + r.error, 'err');
  return r;
}

export function openRoom(store, roomId) {
  const room = store.get('rooms', roomId);
  if (!room) return;
  let unsub = null;

  sheet(room.name, (body, head) => {
    const put = (b) => run(api.put('/v2/room/' + roomId, b), room.name);
    const sendBri = throttle((v) => api.put('/v2/room/' + roomId, { brightness: v }), 100);

    const sw = shSwitch('Licht ' + room.name, room.on, (on) => {
      store.optimistic('rooms', roomId, { on });
      put({ on });
    });
    head.insertBefore(sw, head.lastChild);

    const bri = shSlider('Helligkeit', room.brightness ?? 1, {
      onStart: () => store.hold('rooms', roomId),
      onInput: (v) => { store.hold('rooms', roomId, { brightness: v, on: true }); sendBri(v); },
      onDone: (v) => { put({ brightness: v }); store.release('rooms', roomId); },
    });
    const briVal = h('span', { class: 'val' });
    body.append(h('div', { class: 'line' }, icon('brightness'), bri, briVal));

    // --- Stimmungen + Szenen
    const moodRow = h('div', { class: 'chips' });
    const sceneRow = h('div', { class: 'chips' });
    const saveBtn = h('button', { class: 'sh-btn tonal small', type: 'button', onclick: async () => {
      const name = await askText('Szene speichern', 'Name der Szene', { pattern: SCENE_NAME });
      if (!name) return;
      const r = await run(api.post('/v2/room/' + roomId + '/scene', { name }), 'Szene');
      if (r.ok) toast('Szene „' + name + '“ gespeichert', 'ok');
    } }, icon('save'), 'Aktuellen Zustand als Szene speichern');
    function renderScenes() {
      moodRow.replaceChildren(...Object.entries(store.raw.moods || {}).map(([k, label]) =>
        chip(label, { onclick: () => run(api.post('/v2/room/' + roomId + '/mood', { mood: k }), label) })));
      const scenes = store.scenesOf(roomId).sort((a, b) => a.name.localeCompare(b.name, 'de'));
      sceneRow.replaceChildren(...scenes.map((s) =>
        chip(s.name, { colors: s.colors, active: s.active,
          onclick: () => run(api.post('/v2/scene/' + s.id + '/recall', {}), s.name) })));
      if (!scenes.length) sceneRow.append(h('p', { class: 'muted small', text: 'Noch keine eigenen Szenen für diesen Raum.' }));
    }
    body.append(section('Stimmung', moodRow), section('Szenen', sceneRow, saveBtn));

    // --- Farbe / Weiss
    let wheel = null, white = null;
    const tabs = h('div', { class: 'sh-tabs', role: 'tablist' });
    const colorPane = h('div', { class: 'pane' });
    if (room.color || room.ct) {
      const lights = store.lightsOf(roomId);
      const firstColor = lights.find((l) => l.color && l.mode === 'xy');
      const firstCt = lights.find((l) => l.ct && l.mirek);
      if (room.color) {
        wheel = colorWheel({
          xy: firstColor && firstColor.xy,
          onStart: () => store.hold('rooms', roomId),
          onPick: (xy) => api.put('/v2/room/' + roomId, { xy }),
          onEnd: () => store.release('rooms', roomId),
        });
      }
      if (room.ct) {
        white = whiteSlider({
          mirek: firstCt && firstCt.mirek,
          onPick: (mirek) => api.put('/v2/room/' + roomId, { mirek }),
        });
      }
      const show = (which) => {
        colorPane.replaceChildren(which === 'color' ? wheel : white);
        for (const b of tabs.children) {
          const on = b.dataset.p === which;
          b.classList.toggle('on', on);
          b.setAttribute('aria-selected', String(on));
        }
      };
      if (wheel) tabs.append(h('button', { class: 'sh-pill', role: 'tab', type: 'button', 'data-p': 'color', onclick: () => show('color') }, 'Farbe'));
      if (white) tabs.append(h('button', { class: 'sh-pill', role: 'tab', type: 'button', 'data-p': 'white', onclick: () => show('white') }, 'Weiß'));
      show(firstColor && wheel ? 'color' : white ? 'white' : 'color');
      body.append(section('Licht', tabs, colorPane));
    }

    // --- Effekte + Strobo
    const effectNames = store.raw.effects || {};
    const available = new Set(store.lightsOf(roomId).flatMap((l) => l.effects || []));
    const effRow = h('div', { class: 'chips' });
    function renderEffects() {
      const running = new Set(store.lightsOf(roomId).map((l) => l.effect).filter((e) => e && e !== 'no_effect'));
      // replaceChildren schreibt null als TEXT "null" — Leeres vorher rausfiltern
      effRow.replaceChildren(...[
        ...Object.entries(effectNames).filter(([k]) => available.has(k)).map(([k, label]) =>
          chip(label, { active: running.has(k), onclick: () => run(api.post('/v2/room/' + roomId + '/effect', { effect: k }), label) })),
        running.size ? chip('Effekt aus', { onclick: () => run(api.post('/v2/room/' + roomId + '/effect', { effect: 'none' }), 'Effekt') }) : null,
      ].filter(Boolean));
    }
    const strobe = h('div', { class: 'chips' },
      ...[5, 15, 30].map((s) => chip(`Strobo ${s} s`, { onclick: async () => {
        if (!strobeConfirmed) {
          const ok = await confirmSheet('Lichtblitze',
            'Strobo erzeugt schnelle Lichtblitze. Das kann bei Menschen mit lichtempfindlicher Epilepsie Anfälle auslösen. Fortfahren?',
            'Ja, starten', true);
          if (!ok) return;
          strobeConfirmed = true;
        }
        run(api.post('/v2/room/' + roomId + '/signal', { duration_ms: s * 1000 }), 'Strobo');
      } })),
      chip('Stopp', { onclick: () => run(api.post('/v2/room/' + roomId + '/signal', { duration_ms: 0 }), 'Strobo') }));
    if (available.size) body.append(section('Effekte', effRow));
    body.append(section('Strobo', strobe, h('p', { class: 'muted small', text: 'Blinkt in den Lampen selbst und endet von allein.' })));

    // --- Lampen
    const lampList = h('div', { class: 'lamps', role: 'list' });
    const rows = new Map();
    function lampRow(l) {
      const send = throttle((v) => api.put('/v2/light/' + l.id, { brightness: v }), 100);
      const dot = h('button', { class: 'lamp-dot', type: 'button', 'aria-label': 'Farbe von ' + l.name,
        onclick: () => openLight(store, l.id) });
      const name = h('span', { class: 'lamp-name' });
      const lsw = shSwitch(l.name, l.on, (on) => {
        store.optimistic('lights', l.id, { on });
        run(api.put('/v2/light/' + l.id, { on }), l.name);
      });
      const ls = shSlider('Helligkeit ' + l.name, l.brightness ?? 1, {
        onStart: () => store.hold('lights', l.id),
        onInput: (v) => { store.hold('lights', l.id, { brightness: v, on: true }); send(v); },
        onDone: (v) => { api.put('/v2/light/' + l.id, { brightness: v }); store.release('lights', l.id); },
      });
      const el = h('div', { class: 'lamp', role: 'listitem' }, h('div', { class: 'lamp-top' }, dot, name, lsw), ls);
      el.update = (x) => {
        name.textContent = x.name.replace(/\s*(Color|Light|Lightstrip|White)\b.*$/i, '').trim() || x.name;
        name.title = x.reachable ? x.name : x.name + ' (nicht erreichbar)';
        dot.style.background = x.on ? x.hex : 'transparent';
        dot.classList.toggle('off', !x.on);
        lsw.set(x.on);
        ls.set(x.brightness ?? 1);
        el.classList.toggle('dead', !x.reachable);
        dot.disabled = !(x.color || x.ct);
      };
      return el;
    }
    function renderLamps() {
      for (const l of store.lightsOf(roomId)) {
        let el = rows.get(l.id);
        if (!el) { el = lampRow(l); rows.set(l.id, el); lampList.append(el); }
        el.update(l);
      }
    }
    body.append(section('Lampen', lampList));

    function update() {
      const r = store.get('rooms', roomId);
      if (!r) return;
      sw.set(r.on && r.on_count > 0);
      bri.set(r.brightness ?? 1);
      briVal.textContent = r.on && r.brightness != null ? Math.round(r.brightness) + ' %' : 'aus';
      renderLamps();
      renderEffects();
      const lights = store.lightsOf(roomId);
      const c = lights.find((l) => l.on && l.mode === 'xy');
      const t = lights.find((l) => l.on && l.mode === 'ct');
      if (wheel && c) wheel.set(c.xy);
      if (white && t) white.set(t.mirek);
    }
    renderScenes();
    update();
    unsub = store.subscribe((c) => {
      if (c.all || c.scenes) renderScenes();
      if (c.all || (c.rooms && c.rooms.has(roomId)) || [...(c.lights || [])].some((id) => room.lights.includes(id))) update();
    });
  }, () => unsub && unsub());
}

/** Farbe und Weiss einer einzelnen Lampe — mit Klemmung auf ihren Farbraum. */
export function openLight(store, lightId) {
  const l = store.get('lights', lightId);
  if (!l) return;
  let unsub = null;
  sheet(l.name, (body) => {
    const put = (b) => api.put('/v2/light/' + lightId, b);
    let wheel = null, white = null;
    if (l.color) {
      wheel = colorWheel({
        xy: l.xy,
        onStart: () => store.hold('lights', lightId),
        onPick: (xy) => put({ xy: clampToGamut(xy, l.gamut) }),
        onEnd: () => store.release('lights', lightId),
        label: 'Farbe von ' + l.name,
      });
      body.append(section('Farbe', wheel));
    }
    if (l.ct) {
      white = whiteSlider({ mirek: l.mirek, min: l.mirek_min || 153, max: l.mirek_max || 500, onPick: (mirek) => put({ mirek }) });
      body.append(section('Weiß', white));
    }
    if (!l.color && !l.ct) body.append(h('p', { class: 'muted', text: 'Diese Lampe ist nur dimmbar.' }));
    unsub = store.subscribe((c) => {
      if (!(c.all || (c.lights && c.lights.has(lightId)))) return;
      const x = store.get('lights', lightId);
      if (wheel && x.mode === 'xy') wheel.set(x.xy);
      if (white && x.mode === 'ct') white.set(x.mirek);
    });
  }, () => unsub && unsub());
}
