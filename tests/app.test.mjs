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
