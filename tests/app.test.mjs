// Tests der neuen App-Module (DOM-frei). node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import { rgbToXy, xyToRgb, clampToGamut, inGamut, hsvToRgb, rgbToHsv, mirekToKelvin, kelvinToMirek, onColor } from '../static/app/color.js';
import { createStore, throttle, RELEASE_MS } from '../static/app/store.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = join(HERE, '..', 'static', 'app');
const GAMUT_C = { red: { x: 0.6915, y: 0.3083 }, green: { x: 0.17, y: 0.7 }, blue: { x: 0.1532, y: 0.0475 } };

// ------------------------------------------------------------ Farbe

test('rgb -> xy -> rgb landet beim selben Farbton', () => {
  for (const rgb of [[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 128, 0]]) {
    const back = xyToRgb(...Object.values(rgbToXy(...rgb)));
    const h1 = rgbToHsv(...rgb).h, h2 = rgbToHsv(...back).h;
    const d = Math.min(Math.abs(h1 - h2), 360 - Math.abs(h1 - h2));
    assert.ok(d < 8, `${rgb} -> ${back} (Farbton ${h1} vs ${h2})`);
  }
});

test('Gamut-Klemmung: drinnen bleibt, draussen landet auf dem Rand', () => {
  const inside = { x: 0.4, y: 0.4 };
  assert.deepEqual(clampToGamut(inside, GAMUT_C), inside);
  const out = clampToGamut({ x: 0.1, y: 0.85 }, GAMUT_C);   // gruener als die Lampe kann
  assert.ok(inGamut({ x: out.x - 1e-4, y: out.y - 1e-4 }, GAMUT_C) || inGamut(out, GAMUT_C));
  assert.ok(Math.abs(out.x - 0.17) < 0.05 && Math.abs(out.y - 0.7) < 0.05);
  assert.deepEqual(clampToGamut(inside, null), inside);
});

test('HSV-Rad: Rot bei 0°, Schwarz-Weiss-Mitte unbunt', () => {
  assert.deepEqual(hsvToRgb(0, 1, 1), [255, 0, 0]);
  assert.deepEqual(hsvToRgb(120, 0, 1), [255, 255, 255]);
});

test('Kelvin <-> Mirek', () => {
  assert.equal(mirekToKelvin(370), 2700);
  assert.equal(kelvinToMirek(6500), 154);
});

test('Schrift auf farbigem Grund ist lesbar', () => {
  assert.equal(onColor('#ffd9a0'), '#1a1c22');   // helles Warmweiss -> dunkle Schrift
  assert.equal(onColor('#1020a0'), '#ffffff');
});

// ------------------------------------------------------------ Speicher

function snap() {
  return {
    rooms: { R1: { id: 'R1', name: 'Wohnzimmer', group: 'G1', on: true, brightness: 60, lights: ['L1'], on_count: 1 } },
    lights: { L1: { id: 'L1', name: 'Decke', on: true, brightness: 60 } },
    scenes: { S1: { id: 'S1', name: 'Neon', room: 'R1', colors: [] } },
    moods: { hell: 'Hell' },
  };
}

test('Snapshot und Delta', () => {
  const st = createStore();
  const seen = [];
  st.subscribe((c) => seen.push(c));
  st.applySnapshot(snap());
  assert.equal(st.get('rooms', 'R1').brightness, 60);
  st.applyDelta({ rooms: { R1: { ...snap().rooms.R1, brightness: 20 } } });
  assert.equal(st.get('rooms', 'R1').brightness, 20);
  assert.ok(seen[1].rooms.has('R1'));
  st.applyDelta({ removed: { scenes: ['S1'] } });
  assert.equal(st.get('scenes', 'S1'), null);
});

test('optimistischer Wert gilt bis zur Frist, danach wieder der Server', () => {
  let now = 0;
  const st = createStore(() => now);
  st.applySnapshot(snap());
  st.optimistic('rooms', 'R1', { on: false });
  assert.equal(st.get('rooms', 'R1').on, false);
  now = 3000;
  assert.equal(st.get('rooms', 'R1').on, true);
});

test('Zugschutz: Deltas bewegen den gezogenen Regler nicht', () => {
  let now = 0;
  const st = createStore(() => now);
  st.applySnapshot(snap());
  st.hold('rooms', 'R1', { brightness: 90 });
  st.applyDelta({ rooms: { R1: { ...snap().rooms.R1, brightness: 30 } } });
  now = 60_000;                                   // gehalten = unbegrenzt
  assert.equal(st.get('rooms', 'R1').brightness, 90);
  st.release('rooms', 'R1');
  assert.equal(st.get('rooms', 'R1').brightness, 90);   // noch im Nachlauf
  now += RELEASE_MS + 1;
  assert.equal(st.get('rooms', 'R1').brightness, 30);   // jetzt gilt der Server
});

test('Fehler der Bridge nimmt den optimistischen Raumwert ueber die Gruppe zurueck', () => {
  const st = createStore(() => 0);
  st.applySnapshot(snap());
  st.optimistic('rooms', 'R1', { on: false });
  assert.equal(st.rollback('grouped_light', 'G1'), true);
  assert.equal(st.get('rooms', 'R1').on, true);
  assert.equal(st.rollback('grouped_light', 'unbekannt'), false);
});

test('throttle: hoechstens einer je Fenster, der letzte Wert kommt an', () => {
  let now = 0;
  const sent = [], timers = [];
  const f = throttle((v) => sent.push(v), 100, () => now, (fn) => timers.push(fn));
  f(1); f(2); f(3);
  assert.deepEqual(sent, [1]);
  now = 100; timers.shift()();
  assert.deepEqual(sent, [1, 3]);
});

// ------------------------------------------------------------ Ansicht

test('Raumreihenfolge: gespeichert zuerst, Neues hinten, Zonen nach Raeumen', async () => {
  const { orderRooms, roomSummary } = await import('../static/app/views/home.js');
  const rooms = [
    { id: 'Z', name: 'Abends', kind: 'zone' }, { id: 'B', name: 'Bad', kind: 'room' },
    { id: 'K', name: 'Küche', kind: 'room' }, { id: 'W', name: 'Wohnzimmer', kind: 'room' },
  ];
  assert.deepEqual(orderRooms(rooms, ['W', 'weg']).map((r) => r.id), ['W', 'B', 'K', 'Z']);
  assert.equal(roomSummary({ on: true, on_count: 2, lights: [1, 2, 3], brightness: 59.6 }), '2 von 3 an · 60 %');
  assert.equal(roomSummary({ on: true, on_count: 0, lights: [1] }), 'aus');
});

// ------------------------------------------------------------ Vertraege im Quelltext

function appFiles(dir = APP) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? appFiles(join(dir, e.name)) : e.name.endsWith('.js') ? [join(dir, e.name)] : []);
}
const strip = (s) => s.replace(/\/\/[^\n]*/g, '').replace(/\/\*[\s\S]*?\*\//g, '');

test('innerHTML nur fuer die statischen Haus-Icons (Namen gehen per textContent)', () => {
  for (const f of appFiles()) {
    const code = strip(readFileSync(f, 'utf8'));
    const hits = code.match(/\.innerHTML\s*=/g) || [];
    if (f.endsWith('dom.js')) {
      assert.equal(hits.length, 1, 'dom.js: genau die Icon-Stelle');
      assert.match(code, /span\.innerHTML = window\.SHIcons\.html\(name\)/);
    } else {
      assert.equal(hits.length, 0, f + ' setzt innerHTML');
    }
  }
});

test('Befehlsfehler kommen als "fail"-Event, nicht als "error"', () => {
  const code = strip(readFileSync(join(APP, 'api.js'), 'utf8'));
  assert.match(code, /addEventListener\('fail'/);
  assert.match(code, /'Content-Type': 'application\/json'/);
});

test('Live-Verbindung pausiert im Hintergrund', () => {
  const code = strip(readFileSync(join(APP, 'api.js'), 'utf8'));
  assert.match(code, /visibilitychange/);
  assert.match(code, /document\.hidden/);
});

test('Seite: geteilte Hausversionen und Service Worker neben der Seite', () => {
  const html = readFileSync(join(HERE, '..', 'public', 'index.html'), 'utf8');
  assert.match(html, /nav\.js\?v=26/);
  assert.match(html, /icons\.js\?v=10/);
  assert.match(html, /type="module" src="static\/app\/main\.js/);
  const main = readFileSync(join(APP, 'main.js'), 'utf8');
  assert.match(main, /register\('sw\.js'\)/);
});

test('Manifest: Pfade relativ zum Manifest (static/) und Scope = App-Wurzel', () => {
  const m = JSON.parse(readFileSync(join(HERE, '..', 'static', 'manifest.json'), 'utf8'));
  assert.equal(m.start_url, '../');
  assert.equal(m.scope, '../');
  for (const i of m.icons) assert.ok(!i.src.startsWith('/'), 'absoluter Icon-Pfad: ' + i.src);
});

test('Navigation ist kein direktes body-Kind (nav.js setzt dort width:100%)', () => {
  const html = readFileSync(join(HERE, '..', 'public', 'index.html'), 'utf8');
  const body = html.slice(html.indexOf('<body>'));
  const wrapStart = body.indexOf('<div class="wrap">');
  const navAt = body.indexOf('<nav id="nav"');
  const wrapEnd = body.indexOf('</div>', navAt);
  assert.ok(wrapStart > 0 && navAt > wrapStart && wrapEnd > navAt, 'nav muss in .wrap stehen');
});

test('Automation: Texte fuer Tage und Regeln', async () => {
  const { daysText, ruleText } = await import('../static/app/views/automation.js');
  assert.equal(daysText([0, 1, 2, 3, 4]), 'Mo–Fr');
  assert.equal(daysText([6, 5]), 'Sa–So');
  assert.equal(daysText([0, 2]), 'Mo, Mi');
  assert.equal(ruleText({ kind: 'wakeup', config: { days: [0, 1, 2, 3, 4], time: '06:30', duration_min: 30 } }),
    'Mo–Fr · wach um 06:30 · 30 min sanft heller');
  assert.equal(ruleText({ kind: 'schedule', config: { days: [0, 1, 2, 3, 4, 5, 6], at: { type: 'sunset', offset: -15 },
    action: { type: 'mood', mood: 'gemuetlich' } } }, { gemuetlich: 'Gemütlich' }),
  'täglich · Sonnenuntergang −15 min · Gemütlich');
});

test('Dialoge und Toasts haengen NICHT direkt an body (nav.js setzt dort width:100%)', () => {
  const code = strip(readFileSync(join(APP, 'dom.js'), 'utf8'));
  assert.ok(!/document\.body\.append/.test(code), 'Ueberlagerung direkt an body');
  assert.match(code, /overlayHost\(\)\.append\(dlg\)/);
});

test('replaceChildren bekommt nie null (wuerde als Text "null" erscheinen)', () => {
  for (const f of appFiles()) {
    const code = strip(readFileSync(f, 'utf8'));
    for (const m of code.matchAll(/replaceChildren\(([\s\S]*?)\);\n/g)) {
      const arg = m[1];
      if (/: null\s*$|: null\s*,/.test(arg)) {
        assert.match(arg, /\.filter\(Boolean\)/, f + ': null kann in replaceChildren landen');
      }
    }
  }
});

// ------------------------------------------------------------ Drag-and-drop

test('orderBy: gespeichert zuerst, Neues hinten, Entferntes raus, Doppelte einmal', async () => {
  const { orderBy } = await import('../static/app/sortable.js');
  const items = [{ id: 'a' }, { id: 'b' }, { id: 'c' }, { id: 'd' }];
  assert.deepEqual(orderBy(items, ['c', 'x', 'a', 'c']).map((x) => x.id), ['c', 'a', 'b', 'd']);
  assert.deepEqual(orderBy(items, []).map((x) => x.id), ['a', 'b', 'c', 'd']);
  assert.deepEqual(orderBy([{ id: 7 }, { id: 3 }], ['3']).map((x) => x.id), [3, 7]);   // Zahl vs. Text
});

test('Sortieren: Gefuehl wie ops/cue (Vorschau, Schwellen, Touch-Halten, Auto-Scroll)', () => {
  const code = strip(readFileSync(join(APP, 'sortable.js'), 'utf8'));
  for (const opt of ['forceFallback: true', 'fallbackTolerance: 6', 'delay: 180', 'delayOnTouchOnly: true',
                     'touchStartThreshold: 6', 'scroll: true', 'animation: 220', 'preventOnFilter: false']) {
    assert.ok(code.includes(opt), 'fehlt: ' + opt);
  }
  // Schalter und Regler duerfen keinen Zug starten
  assert.match(code, /NO_DRAG = '[^']*\.sh-switch[^']*\.sh-slider/);
  // nach dem Ablegen kein Klick auf die Karte (oeffnete sonst den Raum)
  assert.match(code, /if \(justDropped\) \{ e\.preventDefault\(\); e\.stopPropagation\(\); \}/);
  // Tastatur
  assert.match(code, /e\.altKey/);
});

test('Sortieren ist in ALLEN Ansichten verdrahtet', () => {
  const want = {
    'views/home.js': "key: 'rooms', draggable: '.tile'",
    'views/room.js': "key: 'lamps:' + roomId, draggable: '.lamp'",
    'views/scenes.js': "key: 'rooms', draggable: '.sortable-card'",
    'views/automation.js': "key: 'auto-cards', draggable: '.sortable-card'",
    'views/more.js': "key: 'energy-cards', draggable: '.sortable-card'",
  };
  for (const [f, needle] of Object.entries(want)) {
    assert.ok(readFileSync(join(APP, f), 'utf8').includes(needle), f + ': ' + needle);
  }
  assert.ok(readFileSync(join(APP, 'views/automation.js'), 'utf8').includes("key: 'rules', draggable: '.rule'"));
  assert.ok(readFileSync(join(APP, 'views/more.js'), 'utf8').includes("key: 'status-cards'"));
});

test('waehrend eines Zugs wird nicht neu sortiert/gebaut', () => {
  assert.match(readFileSync(join(APP, 'views/home.js'), 'utf8'), /if \(reorder && !isDragging\(\)\)/);
  for (const f of ['views/scenes.js', 'views/automation.js']) {
    assert.match(readFileSync(join(APP, f), 'utf8'), /if \(isDragging\(\)\) return;/, f);
  }
});

test('Zuhause: die alte Hoch/Runter-Folge wird uebernommen', () => {
  const code = readFileSync(join(APP, 'views/home.js'), 'utf8');
  assert.match(code, /LEGACY_ORDER_KEY = 'hue-room-order'/);
  assert.match(code, /if \(old\.length\) saveOrder\('rooms', old\)/);
  assert.ok(!/editBtn|function move\(/.test(code), 'Hoch/Runter-Modus ist zurueck');
});

test('SortableJS ist lokal und versioniert eingebunden (kein CDN)', () => {
  const v = readFileSync(join(HERE, '..', 'static', 'vendor', 'sortable.esm.js'), 'utf8');
  assert.match(v.slice(0, 200), /Sortable 1\.15\.6/);
  assert.match(readFileSync(join(APP, 'sortable.js'), 'utf8'), /from '\.\.\/vendor\/sortable\.esm\.js'/);
});
