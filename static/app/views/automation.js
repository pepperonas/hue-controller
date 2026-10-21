// Automation: Abwesenheit, Bewegungsmelder, Zeitplaene und Lichtwecker.
import { h, icon, shSwitch, sheet, toast, confirmSheet } from '../dom.js';
import { api } from '../api.js';
import { orderRooms } from './home.js';
import { makeSortable, applyOrder, isDragging, orderBy, loadOrder } from '../sortable.js';

const DAY_NAMES = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
const ACTIONS = { on: 'Einschalten', off: 'Ausschalten', brightness: 'Helligkeit', mood: 'Stimmung', scene: 'Szene' };
const RULE_NAME = /^[\p{L}\p{N} .,!?:+()/-]{1,40}$/u;

export function daysText(days) {
  const d = [...days].sort();
  const key = d.join(',');
  if (key === '0,1,2,3,4,5,6') return 'täglich';
  if (key === '0,1,2,3,4') return 'Mo–Fr';
  if (key === '5,6') return 'Sa–So';
  return d.map((i) => DAY_NAMES[i]).join(', ');
}

export function ruleText(r, moods = {}, scenes = {}) {
  const c = r.config;
  if (r.kind === 'wakeup') return `${daysText(c.days)} · wach um ${c.time} · ${c.duration_min} min sanft heller`;
  if (r.kind === 'motion') return `${c.window === 'dark' ? 'nur bei Dunkelheit' : 'immer'} · ${c.brightness} % · ${c.duration_min} min`;
  const at = c.at.type === 'time' ? c.at.time
    : (c.at.type === 'sunrise' ? 'Sonnenaufgang' : 'Sonnenuntergang') + (c.at.offset ? ` ${c.at.offset > 0 ? '+' : '−'}${Math.abs(c.at.offset)} min` : '');
  const a = c.action;
  const what = a.type === 'brightness' ? `${a.brightness} %` : a.type === 'mood' ? (moods[a.mood] || a.mood)
    : a.type === 'scene' ? (scenes[a.scene] ? scenes[a.scene].name : 'Szene') : ACTIONS[a.type];
  return `${daysText(c.days)} · ${at} · ${what}${a.transition_min ? ` (über ${a.transition_min} min)` : ''}`;
}

export const OFF_AFTER_MIN = [1, 2, 3, 5, 10, 15, 30];

const hm = (iso) => new Date(iso).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });

export function pirState(p, rule) {
  if (!p.available) return 'Sensor nicht verfügbar';
  if (p.active_until) return 'Licht an bis ' + hm(p.active_until);
  if (rule && rule.last_fired) {
    const t = new Date(rule.last_fired);
    const day = t.toDateString() === new Date().toDateString() ? 'heute' : t.toLocaleDateString('de-DE', { weekday: 'short', day: '2-digit', month: '2-digit' });
    return `bereit · zuletzt ausgelöst ${day} ${hm(rule.last_fired)}`;
  }
  return 'bereit · noch nie ausgelöst';
}

function nextText(iso) {
  if (!iso) return 'aus';
  const t = new Date(iso), now = new Date();
  const sameDay = t.toDateString() === now.toDateString();
  const tomorrow = new Date(now.getTime() + 864e5).toDateString() === t.toDateString();
  const hm = t.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
  return 'nächstes Mal ' + (sameDay ? 'heute' : tomorrow ? 'morgen' : t.toLocaleDateString('de-DE', { weekday: 'long' })) + ' ' + hm;
}

export function automationView(store) {
  const awayBox = h('div');
  const pirBox = h('div');
  const list = h('div', { class: 'stack' });
  const logList = h('ul', { class: 'errs' });
  let data = null, timer = 0;

  async function load() {
    const r = await api.get('/v2/automations', 8000);
    if (!r.ok) { list.replaceChildren(h('p', { class: 'muted', text: 'Automationen nicht erreichbar: ' + r.error })); return; }
    data = r.data;
    render();
  }

  function rooms() { return orderRooms(store.list('rooms').filter((r) => r.kind === 'room' && r.lights.length), []); }

  function render() {
    if (isDragging()) return;
    // Abwesenheit
    const aw = data.away || {};
    const sim = h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: !!aw.simulate, onchange: (e) => setAway(!!aw.on, e.target.checked) }),
      ' Abends bewohnt wirken (zufällig 1 Raum für 20–60 min)');
    awayBox.replaceChildren(
      h('div', { class: 'line' }, h('span', { class: 'lbl grow', text: aw.on ? 'Abwesend – alles aus' : 'Zuhause' }),
        shSwitch('Abwesend', aw.on, (on) => setAway(on, !!aw.simulate))),
      sim,
      h('p', { class: 'muted small', text: `Heute: Sonnenaufgang ${data.sun.sunrise}, Sonnenuntergang ${data.sun.sunset}. Während Abwesenheit laufen Zeitpläne nicht (Ausschalten schon).` }));

    // Bewegungsmelder
    const pir = data.rules.find((r) => r.kind === 'motion');
    pirBox.replaceChildren(
      h('p', { class: 'muted small', text: 'Sensor an GPIO 26: ' + pirState(data.pir, pir) }),
      ...(pir ? [ruleRow(pir), offAfter(pir)]
        : [h('button', { class: 'sh-btn tonal', type: 'button', onclick: () => edit('motion') }, icon('plus'), 'Einrichten')]));

    // Regeln
    const rules = orderBy(data.rules.filter((r) => r.kind !== 'motion'), loadOrder('rules'), (r) => String(r.id));
    list.replaceChildren(...(rules.length ? rules.map(ruleRow)
      : [h('p', { class: 'muted', text: 'Noch keine Zeitpläne oder Lichtwecker.' })]));
    logList.replaceChildren(...(data.log.length ? data.log.slice(0, 15).map((l) => h('li', null,
      h('span', { class: 'muted', text: new Date(l.at * 1000).toLocaleString('de-DE', { weekday: 'short', hour: '2-digit', minute: '2-digit' }) + ' · ' }), l.msg))
      : [h('li', { class: 'muted', text: 'Noch nichts passiert.' })]));
  }

  function ruleRow(r) {
    const kindIcon = r.kind === 'wakeup' ? 'sunrise' : r.kind === 'motion' ? 'target' : 'clock';
    return h('div', { class: 'rule' + (r.enabled ? '' : ' off'), 'data-sort-id': String(r.id) },
      h('span', { class: 'rule-ic' }, icon(kindIcon)),
      h('div', { class: 'rule-text' },
        h('span', { class: 'rule-name', text: r.name + ' · ' + r.room_name }),
        h('span', { class: 'rule-sub', text: ruleText(r, store.raw.moods, store.raw.scenes) }),
        r.kind !== 'motion' ? h('span', { class: 'rule-next', text: nextText(r.next) }) : null),
      h('button', { class: 'sh-icon-btn', type: 'button', 'aria-label': r.name + ' bearbeiten', onclick: () => edit(r.kind, r) }, icon('edit')),
      shSwitch(r.name + ' aktiv', r.enabled, async (on) => {
        const res = await api.put('/v2/automations/' + r.id, { enabled: on });
        if (!res.ok) toast(res.error, 'err');
        load();
      }));
  }

  // Abschaltzeit direkt in der Karte: ein Tipp speichert, ohne den Dialog
  function offAfter(pir) {
    const cur = pir.config.duration_min;
    const opts = OFF_AFTER_MIN.includes(cur) ? OFF_AFTER_MIN : [...OFF_AFTER_MIN, cur].sort((a, b) => a - b);
    return h('div', { class: 'stack' },
      h('span', { class: 'lbl', text: 'Automatisch aus nach' }),
      h('div', { class: 'chips', role: 'group', 'aria-label': 'Automatisch aus nach' },
        ...opts.map((m) => h('button', {
          class: 'sh-pill' + (m === cur ? ' on' : ''), type: 'button', 'aria-pressed': String(m === cur),
          onclick: () => setOffAfter(pir, m),
        }, m + ' min'))),
      h('p', { class: 'muted small', text: 'Jede neue Bewegung startet die Zeit von vorn. Andere Werte (1–60 min) über „bearbeiten“.' }));
  }

  async function setOffAfter(pir, minutes) {
    if (minutes === pir.config.duration_min) return;
    const r = await api.put('/v2/automations/' + pir.id, { config: { ...pir.config, duration_min: minutes } });
    toast(r.ok ? `Gartenlicht geht nach ${minutes} min aus` : r.error, r.ok ? 'ok' : 'err');
    load();
  }

  async function setAway(on, simulate) {
    const r = await api.post('/v2/away', { on, simulate });
    toast(r.ok ? (on ? 'Abwesend – alles aus' : 'Willkommen zurück') : r.error, r.ok ? 'ok' : 'err');
    load();
  }

  function edit(kind, rule) {
    const c = rule ? rule.config : {};
    if (!rule) {
      // sinnvoller Vorschlag statt "erster Raum im Alphabet"
      const want = { wakeup: 'bedroom', motion: 'garden' }[kind];
      const hit = want && rooms().find((r) => r.archetype === want);
      if (hit) c.room = hit.id;
    }
    const title = { schedule: 'Zeitplan', wakeup: 'Lichtwecker', motion: 'Bewegungsmelder' }[kind];
    sheet((rule ? '' : 'Neu: ') + title, (body) => {
      const name = h('input', { class: 'field', type: 'text', maxLength: 40, value: rule ? rule.name : title, 'aria-label': 'Name' });
      const room = h('select', { class: 'field', 'aria-label': 'Raum' },
        ...rooms().map((r) => h('option', { value: r.id, selected: r.id === c.room, text: r.name })));
      const days = new Set(c.days || [0, 1, 2, 3, 4]);
      const dayChips = h('div', { class: 'chips' }, ...DAY_NAMES.map((d, i) => {
        const b = h('button', { class: 'sh-pill' + (days.has(i) ? ' on' : ''), type: 'button', 'aria-pressed': String(days.has(i)),
          onclick: () => { days.has(i) ? days.delete(i) : days.add(i); b.classList.toggle('on'); b.setAttribute('aria-pressed', String(days.has(i))); } }, d);
        return b;
      }));
      const fields = [field('Name', name), field('Raum', room)];
      let collect;
      if (kind === 'wakeup') {
        const time = h('input', { class: 'field', type: 'time', value: c.time || '06:30', 'aria-label': 'Weckzeit' });
        const dur = h('select', { class: 'field', 'aria-label': 'Dauer' },
          ...[15, 20, 30, 45, 60].map((m) => h('option', { value: m, selected: m === (c.duration_min || 30), text: m + ' min' })));
        fields.push(field('Tage', dayChips), field('Hell um', time), field('Sanft heller über', dur));
        collect = () => ({ room: room.value, days: [...days], time: time.value, duration_min: +dur.value });
      } else if (kind === 'motion') {
        const dur = h('input', { class: 'field', type: 'number', min: 1, max: 60, value: c.duration_min || 3, 'aria-label': 'Minuten' });
        const bri = h('input', { class: 'field', type: 'number', min: 1, max: 100, value: c.brightness || 60, 'aria-label': 'Helligkeit' });
        const win = h('select', { class: 'field', 'aria-label': 'Wann' },
          h('option', { value: 'dark', selected: c.window !== 'always', text: 'nur bei Dunkelheit' }),
          h('option', { value: 'always', selected: c.window === 'always', text: 'immer' }));
        fields.push(field('Automatisch aus nach (min)', dur), field('Helligkeit (%)', bri), field('Wann', win),
          h('p', { class: 'muted small', text: 'War das Licht schon an oder hat es jemand verändert, schaltet der Melder es nicht aus.' }));
        collect = () => ({ room: room.value, duration_min: +dur.value, brightness: +bri.value, mirek: c.mirek || 370, window: win.value });
      } else {
        const atType = h('select', { class: 'field', 'aria-label': 'Wann' },
          ...[['time', 'Uhrzeit'], ['sunrise', 'Sonnenaufgang'], ['sunset', 'Sonnenuntergang']].map(([v, t]) =>
            h('option', { value: v, selected: v === ((c.at && c.at.type) || 'time'), text: t })));
        const time = h('input', { class: 'field', type: 'time', value: (c.at && c.at.time) || '07:00', 'aria-label': 'Uhrzeit' });
        const off = h('input', { class: 'field', type: 'number', min: -180, max: 180, step: 5, value: (c.at && c.at.offset) || 0, 'aria-label': 'Minuten Versatz' });
        const timeF = field('Uhrzeit', time), offF = field('Versatz in Minuten (− davor, + danach)', off);
        const syncAt = () => { timeF.hidden = atType.value !== 'time'; offF.hidden = atType.value === 'time'; };
        atType.addEventListener('change', syncAt);
        const a = c.action || { type: 'on' };
        const act = h('select', { class: 'field', 'aria-label': 'Aktion' },
          ...Object.entries(ACTIONS).map(([v, t]) => h('option', { value: v, selected: v === a.type, text: t })));
        const bri = h('input', { class: 'field', type: 'number', min: 1, max: 100, value: a.brightness || 50, 'aria-label': 'Helligkeit' });
        const mood = h('select', { class: 'field', 'aria-label': 'Stimmung' },
          ...Object.entries(store.raw.moods || {}).map(([v, t]) => h('option', { value: v, selected: v === a.mood, text: t })));
        const scene = h('select', { class: 'field', 'aria-label': 'Szene' });
        const fillScenes = () => scene.replaceChildren(...store.scenesOf(room.value).map((s) => h('option', { value: s.id, selected: s.id === a.scene, text: s.name })));
        room.addEventListener('change', fillScenes);
        fillScenes();
        const trans = h('input', { class: 'field', type: 'number', min: 0, max: 60, value: a.transition_min || 0, 'aria-label': 'Übergang in Minuten' });
        const briF = field('Helligkeit (%)', bri), moodF = field('Stimmung', mood), sceneF = field('Szene', scene);
        const syncAct = () => { briF.hidden = act.value !== 'brightness'; moodF.hidden = act.value !== 'mood'; sceneF.hidden = act.value !== 'scene'; };
        act.addEventListener('change', syncAct);
        fields.push(field('Tage', dayChips), field('Wann', atType), timeF, offF, field('Aktion', act), briF, moodF, sceneF, field('Übergang (min)', trans));
        syncAt(); syncAct();
        collect = () => {
          const at = atType.value === 'time' ? { type: 'time', time: time.value } : { type: atType.value, offset: +off.value };
          const action = { type: act.value, transition_min: +trans.value };
          if (act.value === 'brightness') action.brightness = +bri.value;
          if (act.value === 'mood') action.mood = mood.value;
          if (act.value === 'scene') action.scene = scene.value;
          return { room: room.value, days: [...days], at, action };
        };
      }
      const save = h('button', { class: 'sh-btn', type: 'submit' }, 'Speichern');
      const del = rule ? h('button', { class: 'sh-btn tonal danger-text', type: 'button', onclick: async () => {
        if (!(await confirmSheet('Löschen?', `„${rule.name}“ wird gelöscht.`, 'Löschen', true))) return;
        const r = await api.del('/v2/automations/' + rule.id);
        toast(r.ok ? 'Gelöscht' : r.error, r.ok ? 'ok' : 'err');
        body.closest('dialog').close();
        load();
      } }, 'Löschen') : null;
      const form = h('form', { class: 'stack', onsubmit: async (e) => {
        e.preventDefault();
        if (!RULE_NAME.test(name.value.trim())) { name.setAttribute('aria-invalid', 'true'); name.focus(); return; }
        if (kind !== 'motion' && !days.size) { toast('Mindestens einen Tag wählen', 'err'); return; }
        const payload = { name: name.value.trim(), config: collect() };
        const r = rule ? await api.put('/v2/automations/' + rule.id, payload)
          : await api.post('/v2/automations', { kind, ...payload });
        if (!r.ok) { toast(r.error, 'err'); return; }
        toast('Gespeichert', 'ok');
        body.closest('dialog').close();
        load();
      } }, ...fields, h('div', { class: 'row end' }, del, save));
      body.append(form);
    });
  }

  const cards = h('div', { class: 'stack' },
    h('section', { class: 'card sortable-card', 'data-sort-id': 'away' }, h('h2', { class: 'card-title', text: 'Abwesenheit' }), awayBox),
    h('section', { class: 'card sortable-card', 'data-sort-id': 'rules' },
      h('div', { class: 'card-head' }, h('h2', { class: 'card-title', text: 'Zeitpläne & Lichtwecker' }),
        h('div', { class: 'row' },
          h('button', { class: 'sh-btn tonal small', type: 'button', onclick: () => edit('schedule') }, icon('clock'), 'Zeitplan'),
          h('button', { class: 'sh-btn tonal small', type: 'button', onclick: () => edit('wakeup') }, icon('sunrise'), 'Lichtwecker'))),
      list),
    h('section', { class: 'card sortable-card', 'data-sort-id': 'motion' }, h('h2', { class: 'card-title', text: 'Bewegungsmelder' }), pirBox),
    h('section', { class: 'card sortable-card', 'data-sort-id': 'log' }, h('h2', { class: 'card-title', text: 'Verlauf' }), logList));
  applyOrder(cards, 'auto-cards', '.sortable-card');
  makeSortable(cards, { key: 'auto-cards', draggable: '.sortable-card' });
  makeSortable(list, { key: 'rules', draggable: '.rule' });
  const sec = h('section', { class: 'view', id: 'view-automation', 'aria-labelledby': 'h-auto' },
    h('h1', { id: 'h-auto', class: 'view-title', text: 'Automation' }), cards);
  sec.render = () => {
    load();
    clearInterval(timer);
    timer = setInterval(() => { if (!sec.hidden && !document.hidden) load(); }, 60000);
  };
  return sec;
}

function field(label, control) {
  // <label> nur um echte Formularfelder: um die Tages-Chips gelegt, schaltete
  // ein Klick auf den Beschriftungstext den ersten Chip (Montag) mit um.
  const formy = /^(INPUT|SELECT|TEXTAREA)$/.test(control.tagName);
  return h(formy ? 'label' : 'div', { class: 'fld' }, h('span', { class: 'fld-l', text: label }), control);
}
