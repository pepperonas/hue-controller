// Szenen: alle Raeume mit ihren Stimmungen und Szenen auf einen Blick.
import { h, toast } from '../dom.js';
import { api } from '../api.js';
import { orderRooms, roomOrder } from './home.js';
import { makeSortable, isDragging } from '../sortable.js';

const FAV_KEY = 'hue-scene-favs';
const favs = () => { try { return new Set(JSON.parse(localStorage.getItem(FAV_KEY)) || []); } catch (e) { return new Set(); } };
const saveFavs = (s) => { try { localStorage.setItem(FAV_KEY, JSON.stringify([...s])); } catch (e) { /* privat */ } };

export function scenesView(store) {
  const list = h('div', { class: 'stack' });

  async function act(p, b, label) {
    const r = await api.post(p, b);
    toast(r.ok ? label + ' ✓' : label + ': ' + r.error, r.ok ? 'ok' : 'err');
  }

  function render() {
    if (isDragging()) return;
    const f = favs();
    // dieselbe Raumfolge wie auf "Zuhause" — ein Raum steht ueberall an seinem Platz
    const rooms = orderRooms(store.list('rooms').filter((r) => r.lights.length && r.kind === 'room'), roomOrder());
    const favScenes = store.list('scenes').filter((s) => f.has(s.id));
    const blocks = [];
    if (favScenes.length) {
      blocks.push(h('section', { class: 'card' }, h('h2', { class: 'card-title', text: 'Favoriten' }),
        h('div', { class: 'chips' }, favScenes.map((s) => sceneChip(s, f)))));
    }
    for (const r of rooms) {
      const scenes = store.scenesOf(r.id).sort((a, b) => a.name.localeCompare(b.name, 'de'));
      blocks.push(h('section', { class: 'card sortable-card', 'data-sort-id': r.id },
        h('h2', { class: 'card-title', text: r.name }),
        h('div', { class: 'chips' },
          Object.entries(store.raw.moods || {}).map(([k, label]) =>
            h('button', { class: 'sh-pill chip', type: 'button',
              onclick: () => act('/v2/room/' + r.id + '/mood', { mood: k }, r.name + ': ' + label) }, label)),
          scenes.map((s) => sceneChip(s, f)))));
    }
    list.replaceChildren(...blocks);
  }

  function sceneChip(s, f) {
    const star = h('button', { class: 'star', type: 'button', 'aria-pressed': String(f.has(s.id)),
      'aria-label': (f.has(s.id) ? 'Favorit entfernen: ' : 'Als Favorit: ') + s.name,
      onclick: (e) => { e.stopPropagation(); const n = favs(); n.has(s.id) ? n.delete(s.id) : n.add(s.id); saveFavs(n); render(); } },
      f.has(s.id) ? '★' : '☆');
    const dots = s.colors.slice(0, 4).map((c) => h('span', { class: 'chip-dot', style: { background: c } }));
    return h('span', { class: 'chip-wrap' },
      h('button', { class: 'sh-pill chip' + (s.active ? ' on' : ''), type: 'button',
        onclick: () => act('/v2/scene/' + s.id + '/recall', {}, s.name) },
        dots.length ? h('span', { class: 'chip-dots', 'aria-hidden': 'true' }, dots) : null, s.name), star);
  }

  makeSortable(list, { key: 'rooms', draggable: '.sortable-card' });
  store.subscribe((c) => { if (c.all || c.scenes) render(); });
  const sec = h('section', { class: 'view', id: 'view-szenen', 'aria-labelledby': 'h-szenen' },
    h('h1', { id: 'h-szenen', class: 'view-title', text: 'Szenen' }),
    h('p', { class: 'muted', text: 'Stimmungen gibt es für jeden Raum. Eigene Szenen speicherst du im Raum über „Aktuellen Zustand als Szene speichern“.' }),
    list);
  sec.render = render;
  return sec;
}
