/* Tests der Hue-Oberflaeche.  Ausfuehren: node --test tests/
 *
 * Zwei Sorten:
 *   1. ECHTE Unit-Tests — die Funktionen werden aus dem ausgelieferten
 *      public/index.html herausgeschnitten und mit Stubs ausgefuehrt. So kann
 *      keine Kopie danebenlaufen.
 *   2. Vertrags-Pins — Zusicherungen, die sich nicht am Ergebnis ablesen
 *      lassen, sondern beschreiben, WIE etwas gebaut sein muss. Jede haengt an
 *      einem Fehler, der hier tatsaechlich aufgetreten ist.
 *
 * Abhaengigkeitsfrei: handgerollte Stubs statt jsdom.
 *
 * Hinweis zu `new Function(...)`: hier wird ausschliesslich der eigene, unter
 * Versionskontrolle stehende Quelltext aus public/index.html ausgefuehrt —
 * genau das ist der Zweck (die AUSGELIEFERTE Funktion pruefen, keine Kopie).
 * Es fliesst nichts Fremdes ein, und die Suite laeuft nur lokal bzw. in CI.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const HTML = readFileSync(join(HERE, '..', 'public', 'index.html'), 'utf8');

const styleBloecke = [...HTML.matchAll(/<style>([\s\S]*?)<\/style>/g)].map(m => m[1]);
const scriptBloecke = [...HTML.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const CSS = styleBloecke.join('\n');
const JS = scriptBloecke.join('\n');

/** Eine Funktion per Namen aus der Quelle schneiden (Klammer-Zaehlung). */
function schneideFunktion(src, name) {
  const start = src.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `Funktion ${name} nicht gefunden`);
  let i = src.indexOf('{', start), tiefe = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') tiefe++;
    else if (src[j] === '}') { tiefe--; if (tiefe === 0) return src.slice(start, j + 1); }
  }
  throw new Error(`Funktion ${name} nicht geschlossen`);
}

/* ============================ 1. Echte Unit-Tests ======================== */

/** themeColor mit einem DOM-Stub laden; `farbe` ist, was getComputedStyle liefert. */
function ladeThemeColor(farbe) {
  const angelegt = [];
  const entfernt = [];
  const documentStub = {
    createElement: () => {
      const el = { style: { cssText: '' }, remove() { entfernt.push(this); } };
      angelegt.push(el);
      return el;
    },
    body: { appendChild: () => {} },
  };
  const fn = new Function('document', 'getComputedStyle',
    schneideFunktion(JS, 'themeColor') + '; return themeColor;'
  )(documentStub, () => ({ color: farbe }));
  return { themeColor: fn, angelegt, entfernt };
}

test('themeColor: ohne Alpha kommt die Farbe unveraendert zurueck', () => {
  const { themeColor } = ladeThemeColor('rgb(179, 197, 255)');
  assert.equal(themeColor('var(--accent-blue)'), 'rgb(179, 197, 255)');
  assert.equal(themeColor('var(--accent-blue)', 1), 'rgb(179, 197, 255)');
});

test('themeColor: mit Alpha entsteht ein gueltiges rgba()', () => {
  const { themeColor } = ladeThemeColor('rgb(255, 138, 128)');
  assert.equal(themeColor('var(--accent-red)', 0.1), 'rgba(255, 138, 128, 0.1)');
  assert.equal(themeColor('var(--accent-red)', 0.5), 'rgba(255, 138, 128, 0.5)');
});

test('themeColor: Alpha ueber 1 wird nicht ausgegeben', () => {
  // Ein rgba(...,2) waere ungueltig — und ungueltig heisst auf dem Canvas
  // still Schwarz, genau der Fehler, den diese Funktion behebt.
  const { themeColor } = ladeThemeColor('rgb(10, 20, 30)');
  assert.equal(themeColor('x', 2), 'rgb(10, 20, 30)');
});

test('themeColor: leere Rueckgabe faellt auf ein sichtbares Grau zurueck', () => {
  // Lieber ein erkennbar falsches Grau als unsichtbares Schwarz.
  const { themeColor } = ladeThemeColor('');
  assert.match(themeColor('var(--gibt-es-nicht)'), /rgb/);
});

test('themeColor: nicht zerlegbare Farbe wird unveraendert durchgereicht', () => {
  const { themeColor } = ladeThemeColor('color(display-p3 1 0 0)');
  assert.equal(themeColor('x', 0.3), 'color(display-p3 1 0 0)');
});

test('themeColor: raeumt sein Messelement wieder ab', () => {
  // Die Funktion laeuft pro Chart dutzendfach — ein Leck waere teuer.
  const { themeColor, angelegt, entfernt } = ladeThemeColor('rgb(1, 2, 3)');
  for (let i = 0; i < 5; i++) themeColor('x', 0.2);
  assert.equal(angelegt.length, 5);
  assert.equal(entfernt.length, 5, 'nicht jedes Messelement wurde entfernt');
});

/** hueCollapsedSet mit localStorage-Stub laden. */
function ladeCollapsedSet(gespeichert) {
  const store = { 'hue-collapsed': gespeichert };

  // HUE_COLLAPSE_KEY steht ausserhalb der Funktion und muss mitgereicht
  // werden — sonst greift der try/catch der Funktion und jeder Fall saehe
  // wie "leer" aus, der Test waere gruen-blind.
  const KEY = /HUE_COLLAPSE_KEY\s*=\s*'([^']+)'/.exec(JS)[1];
  const fn = new Function('localStorage', 'HUE_COLLAPSE_KEY',
    schneideFunktion(JS, 'hueCollapsedSet') + '; return hueCollapsedSet;'
  )({ getItem: k => (k in store ? store[k] : null) }, KEY);
  return fn;
}

test('hueCollapsedSet: ohne Eintrag ist die Menge leer', () => {
  assert.equal(ladeCollapsedSet(null)().size, 0);
});

test('hueCollapsedSet: liest gespeicherte Titel', () => {
  const s = ladeCollapsedSet('["Stimmungsszenen","Top Verbraucher"]')();
  assert.equal(s.size, 2);
  assert.ok(s.has('Stimmungsszenen'));
});

test('hueCollapsedSet: kaputter Inhalt wirft nicht, sondern liefert leer', () => {
  // Sonst risse ein einziges verungluecktes localStorage-Feld die ganze
  // Oberflaeche ab, weil die Einrichtung frueh laeuft.
  for (const muell of ['{kaputt', 'null', '"kein array"', '']) {
    assert.doesNotThrow(() => ladeCollapsedSet(muell)());
  }
});

/* ============================ 2. Vertrags-Pins =========================== */

const chartJS = JS.slice(JS.indexOf('powerCharts'));

test('Chart-Farben: kein color-mix() in den Konfigurationen', () => {
  // Chart.js malt auf ein CANVAS. Dort gibt es weder CSS-Variablen noch
  // color-mix() — ein ungueltiger Farbstring laesst den 2D-Kontext auf seinem
  // vorherigen Wert stehen, praktisch auf Schwarz. Alle drei Datenreihen und
  // die Legenden-Kacheln waren dadurch unsichtbar.
  assert.ok(!/'color-mix\(/.test(chartJS),
    'color-mix() in einer Chart-Konfiguration — auf dem Canvas ergibt das Schwarz');
});

test('Chart-Farben: kein fest verdrahtetes Weiss', () => {
  // rgba(255,255,255,…) fuer Achsen und Legende funktioniert nur im dunklen
  // Theme; im hellen stuende die Beschriftung weiss auf weiss.
  const treffer = [...chartJS.matchAll(/'rgba\(255,\s*255,\s*255[^']*'/g)].map(m => m[0]);
  assert.deepEqual(treffer, [], 'Achsen/Legende sind auf Dunkel festgenagelt');
});

test('Chart-Farben: themeColor ist definiert, bevor es benutzt wird', () => {
  const def = HTML.indexOf('function themeColor(');
  const ersteNutzung = HTML.indexOf('themeColor(', def === -1 ? 0 : def + 30);
  assert.notEqual(def, -1, 'themeColor fehlt');
  assert.ok(def < ersteNutzung, 'themeColor wird vor seiner Definition benutzt');
});

test('Chart-Farben: die Datenreihen holen ihre Farbe ueber themeColor', () => {
  for (const token of ['--accent-blue', '--accent-red', '--accent-green']) {
    assert.match(chartJS, new RegExp(`themeColor\\('var\\(${token}\\)'`),
      `${token} wird nicht ueber themeColor aufgeloest`);
  }
});

test('Reiter-Leiste traegt kein Karten-Chrome', () => {
  // Sie war als Kartenkopf gestaltet (oben gerundet, 2-px-Unterlinie), ohne
  // dass darunter eine Karte haengt: rechts neben den Pillen lief eine
  // 437-px-Wanne aus (Container 1200, Inhalt bis 763).
  const regel = CSS.match(/\.tabs\s*\{[^}]*\}/g)?.join('\n') || '';
  assert.ok(!/border-bottom:\s*2px/.test(regel), '.tabs hat wieder eine Unterlinie');
  assert.ok(!/background:\s*var\(--card-background\)/.test(regel), '.tabs hat wieder eine Flaeche');
  assert.ok(!/border-radius:\s*var\(--radius\)\s+var\(--radius\)/.test(regel),
    '.tabs hat wieder oben gerundete Ecken');
});

test('keine Karte enthaelt ausschliesslich eine Reiterreihe', () => {
  // Dieselbe leere Wanne, nur eine Ebene hoeher.
  assert.ok(!/<div class="card"[^>]*>\s*<div class="tabs"/.test(HTML),
    'eine .card umschliesst direkt eine .tabs-Reihe');
});

test('die FAB-Knoepfe sind entfernt — Markup wie CSS', () => {
  assert.ok(!HTML.includes('floating-controls'), 'floating-controls noch vorhanden');
  assert.ok(!HTML.includes('floating-btn'), 'floating-btn noch vorhanden');
});

test('kein style-Attribut ohne schliessendes Anfuehrungszeichen', () => {
  // Beim roten FAB fehlte genau das — der Parser verschluckte daraufhin das
  // nachfolgende Markup und sein Icon erschien nie.
  for (const m of HTML.matchAll(/style="([^"]*)"/g)) {
    assert.ok(!m[1].includes('<'),
      `style-Attribut verschluckt Markup: ${m[0].slice(0, 70)}`);
  }
});

test('Lampen-Auswahl: der Merker allein entscheidet nicht', () => {
  // lampSelectionLoaded blieb gesetzt, auch wenn der Container zwischendurch
  // leer geraeumt wurde — dann fuellte ihn niemand mehr nach und die Liste
  // blieb bis zum Neuladen leer.
  // ⚠️ NICHT an "tabName === 'power'" verankern — den String gibt es zweimal
  // (Klassen-Methode und globale Funktion), und der erste Treffer ist der
  // falsche. Der Waechter selbst ist der eindeutige Anker.
  const i = JS.indexOf('lampSelectionLoaded');
  assert.notEqual(i, -1, 'der Waechter fehlt ganz');
  const stelle = JS.slice(Math.max(0, i - 700), i + 400);
  assert.match(stelle, /lamp-selection/, 'der Container wird nicht geprueft');
  assert.match(stelle, /lamp-checkbox/, 'es wird nicht auf tatsaechlichen Inhalt geprueft');
  assert.match(stelle, /!hue\.lampSelectionLoaded\s*\|\|/, 'die Leer-Pruefung haengt nicht am Merker vorbei');
});

test('Zuklappen: Zustand liegt unter einem eigenen Schluessel', () => {
  assert.match(JS, /HUE_COLLAPSE_KEY\s*=\s*'hue-collapsed'/);
  assert.match(JS, /localStorage\.setItem\(HUE_COLLAPSE_KEY/);
});

test('Zuklappen: die Einrichtung laeuft mehrfach ohne Schaden', () => {
  // switchTab ruft sie nach jedem Reiterwechsel erneut auf; ohne Wiedereintritts-
  // Schutz bekaeme jede Karte bei jedem Wechsel einen weiteren Chevron.
  const fn = schneideFunktion(JS, 'initHueCollapse');
  assert.match(fn, /querySelector\('\.card-collapse'\)\)\s*return/,
    'kein Schutz gegen doppelte Chevrons');
});

test('Zuklappen: der Reiterwechsel richtet neue Karten mit ein', () => {
  const fn = schneideFunktion(JS, 'switchTab');
  assert.match(fn, /initHueCollapse/, 'nachgeladene Karten bekaemen keinen Chevron');
});

test('Zuklappen: eingeklappt bleibt nur die Titelzeile stehen', () => {
  assert.match(CSS, /\.card\.collapsed\s*>\s*\*:not\(\.card-title\)\s*\{[^}]*display:\s*none/);
});

test('Kopfabstand entspricht der Haus-Norm', () => {
  // 16 px zwischen Kopf und Inhalt, gemessen ueber alle Apps. Hier stapelten
  // sich drei Abstaende unter der Statuszeile zu 48.
  const pd = CSS.match(/\.power-display\s*\{[^}]*\}/)?.[0] || '';
  assert.match(pd, /margin-bottom:\s*0/, '.power-display bringt wieder einen eigenen Unterrand mit');
  const hd = CSS.match(/\n\s*\.header\s*\{[^}]*\}/)?.[0] || '';
  assert.match(hd, /margin-bottom:\s*var\(--sh-gap-lg\)/, '.header setzt den Abstand nicht ueber den Token');
});

test('geteilte Leiste und Icons stehen auf der Hausversion', () => {
  assert.match(HTML, /nav\.js\?v=20/, 'nav.js-Version weicht ab');
  assert.match(HTML, /icons\.js\?v=8/, 'icons.js-Version weicht ab');
});

test('CSS-Klammern sind ausgeglichen', () => {
  for (const [i, b] of styleBloecke.entries()) {
    const auf = (b.match(/\{/g) || []).length, zu = (b.match(/\}/g) || []).length;
    assert.equal(auf, zu, `Style-Block ${i + 1}: ${auf} auf, ${zu} zu`);
  }
});

test('jeder Skriptblock ist syntaktisch gueltig', () => {
  for (const [i, b] of scriptBloecke.entries()) {
    assert.doesNotThrow(() => new Function(b), `Skriptblock ${i + 1} parst nicht`);
  }
});
