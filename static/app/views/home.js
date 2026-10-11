// Zuhause: Raumkacheln mit echter Farbe, Schalter und Live-Dimmer.
// Kacheln werden EINMAL gebaut und danach nur aktualisiert — kein
// innerHTML-Neuaufbau je Event (das liess frueher Zuege abreissen).
import { h, icon, shSwitch, shSlider, toast } from '../dom.js';
import { api } from '../api.js';
import { throttle } from '../store.js';
import { onColor } from '../color.js';
import { openRoom } from './room.js';

const ORDER_KEY = 'hue-room-order';
const ARCH_ICON = { living_room: 'home', bedroom: 'sleep', kitchen: 'flame', bathroom: 'droplet',
  hallway: 'link', garden: 'leaf', office: 'laptop', dining: 'heart' };

function loadOrder() {
  try { return JSON.parse(localStorage.getItem(ORDER_KEY)) || []; } catch (e) { return []; }
}
function saveOrder(ids) {
  try { localStorage.setItem(ORDER_KEY, JSON.stringify(ids)); } catch (e) { /* privat */ }
}

/** Gespeicherte Folge zuerst, Neues hinten an (Raeume vor Zonen), Entferntes faellt raus. */
export function orderRooms(rooms, saved) {
  const byId = new Map(rooms.map((r) => [r.id, r]));
  const out = [];
  for (const id of saved) if (byId.has(id)) { out.push(byId.get(id)); byId.delete(id); }
  const rest = [...byId.values()].sort((a, b) =>
    (a.kind === b.kind ? 0 : a.kind === 'room' ? -1 : 1) || a.name.localeCompare(b.name, 'de'));
  return out.concat(rest);
}

export function roomSummary(r) {
  if (!r.on || !r.on_count) return 'aus';
  const n = r.lights.length;
  const part = r.on_count === n ? (n === 1 ? 'an' : 'alle an') : `${r.on_count} von ${n} an`;
  return r.brightness != null ? `${part} · ${Math.round(r.brightness)} %` : part;
}

export function homeView(store) {
  const grid = h('div', { class: 'tiles', role: 'list' });
  const tiles = new Map();
  let editing = false;

  const allOff = h('button', { class: 'sh-btn tonal', type: 'button', onclick: async () => {
    const r = await api.post('/v2/all', { on: false });
    if (!r.ok) toast('Alles aus ging nicht: ' + r.error, 'err');
  } }, icon('power'), 'Alles aus');
  const editBtn = h('button', { class: 'sh-btn tonal', type: 'button', 'aria-pressed': 'false', onclick: () => {
    editing = !editing;
    editBtn.setAttribute('aria-pressed', String(editing));
    editBtn.lastChild.textContent = editing ? 'Fertig' : 'Reihenfolge';
    grid.classList.toggle('editing', editing);
  } }, icon('sliders'), h('span', { text: 'Reihenfolge' }));
  const quick = h('div', { class: 'quick' }, allOff, editBtn);

  function move(id, dir) {
    const ids = orderRooms(store.list('rooms'), loadOrder()).map((r) => r.id);
    const i = ids.indexOf(id), j = i + dir;
    if (i < 0 || j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    saveOrder(ids);
    render(true);
  }

  function buildTile(r) {
    const name = h('span', { class: 'tile-name' });
    const sub = h('span', { class: 'tile-sub' });
    const ic = icon(ARCH_ICON[r.archetype] || 'bulb', 'tile-ic');
    const send = throttle((v) => api.put('/v2/room/' + r.id, { brightness: v }), 100);
    const sw = shSwitch('Licht ' + r.name, r.on, async (on) => {
      store.optimistic('rooms', r.id, { on, on_count: on ? Math.max(1, store.get('rooms', r.id).on_count) : 0 });
      const res = await api.put('/v2/room/' + r.id, { on });
      if (!res.ok) { store.rollback('grouped_light', r.group); toast(r.name + ': ' + res.error, 'err'); }
    });
    const slider = shSlider('Helligkeit ' + r.name, r.brightness ?? 1, {
      onStart: () => store.hold('rooms', r.id),
      onInput: (v) => { store.hold('rooms', r.id, { brightness: v, on: true }); send(v); },
      onDone: (v) => { api.put('/v2/room/' + r.id, { brightness: v }); store.release('rooms', r.id); },
    });
    const open = h('button', { class: 'tile-open', type: 'button', 'aria-label': r.name + ' öffnen',
      onclick: () => { if (!editing) openRoom(store, r.id); } }, ic, h('span', { class: 'tile-text' }, name, sub));
    const up = h('button', { class: 'sh-icon-btn mv', type: 'button', 'aria-label': r.name + ' nach vorn', onclick: () => move(r.id, -1) }, '↑');
    const down = h('button', { class: 'sh-icon-btn mv', type: 'button', 'aria-label': r.name + ' nach hinten', onclick: () => move(r.id, 1) }, '↓');
    const el = h('div', { class: 'tile', role: 'listitem' },
      h('div', { class: 'tile-top' }, open, h('span', { class: 'mvs' }, up, down), sw), slider);
    const t = { el, name, sub, sw, slider };
    t.update = (room) => {
      name.textContent = room.name;
      sub.textContent = roomSummary(room);
      sw.set(room.on && room.on_count > 0);
      slider.set(room.brightness ?? 1);
      slider.disabled = !room.lights.length;
      el.classList.toggle('on', !!(room.on && room.on_count));
      el.classList.toggle('zone', room.kind === 'zone');
      const c = room.on && room.hex ? room.hex : null;
      el.style.setProperty('--glow', c || 'transparent');
      el.style.setProperty('--on-glow', c ? onColor(c) : 'inherit');
    };
    return t;
  }

  function render(reorder) {
    const rooms = orderRooms(store.list('rooms').filter((r) => r.lights.length), loadOrder());
    const seen = new Set();
    for (const r of rooms) {
      let t = tiles.get(r.id);
      if (!t) { t = buildTile(r); tiles.set(r.id, t); reorder = true; }
      t.update(r);
      seen.add(r.id);
    }
    for (const [id, t] of tiles) if (!seen.has(id)) { t.el.remove(); tiles.delete(id); }
    if (reorder) grid.replaceChildren(...rooms.map((r) => tiles.get(r.id).el));
  }

  store.subscribe((c) => {
    if (c.all) return render(true);
    for (const id of c.rooms || []) {
      const t = tiles.get(id), r = store.get('rooms', id);
      if (t && r) t.update(r);
    }
  });

  const section = h('section', { class: 'view', id: 'view-home', 'aria-labelledby': 'h-home' },
    h('h1', { id: 'h-home', class: 'view-title', text: 'Zuhause' }), quick, grid);
  section.render = () => render(true);
  return section;
}
