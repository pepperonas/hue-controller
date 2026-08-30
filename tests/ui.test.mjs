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

/* ⚠️ Fuer Aussagen der Art "Regel X ist weg" oder "X steht VOR Y" immer den
   kommentarfreien Quelltext nehmen: die Kommentare hier ZITIEREN entfernte oder
   benachbarte Regeln woertlich ("Hier stand ein @media (prefers-color-scheme)
   …"), ein nackter Textvergleich meldet sie sonst als noch vorhanden. Genau
   daran sind zwei dieser Tests beim Schreiben zuerst gescheitert. */
const CSS_PUR = CSS.replace(/\/\*[\s\S]*?\*\//g, '');
/* Dasselbe fuers Skript. Die Falle ist dort GEMEINER, weil sie leise ist: der
   Erklaerkommentar an einer Korrektur nennt zwangslaeufig den richtigen Weg
   ("ueber window.switchTab wiederherstellen"), also findet ihn ein Textprueftest
   auch dann noch, wenn der Code laengst wieder den falschen geht. Genau das
   ist beim Mutationstest hier aufgefallen: der Test blieb gruen, obwohl der
   Fehler wieder eingebaut war. */
const JS_PUR = JS.replace(/\/\*[\s\S]*?\*\//g, '');

/** Einen Block ab einem Kopf-Ausdruck schneiden (Klammer-Zaehlung). */
function schneideBlock(src, kopf, was = kopf) {
  const start = src.indexOf(kopf);
  assert.notEqual(start, -1, `${was} nicht gefunden`);
  let i = src.indexOf('{', start), tiefe = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') tiefe++;
    else if (src[j] === '}') { tiefe--; if (tiefe === 0) return src.slice(start, j + 1); }
  }
  throw new Error(`${was} nicht geschlossen`);
}

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

/** Wie schneideFunktion, aber fuer eine Methode der Klasse (`name(args) {`). */
function schneideMethode(src, name) {
  const start = src.search(new RegExp(`^\\s+${name}\\s*\\([^)]*\\)\\s*\\{`, 'm'));
  assert.notEqual(start, -1, `Methode ${name} nicht gefunden`);
  let i = src.indexOf('{', start), tiefe = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') tiefe++;
    else if (src[j] === '}') { tiefe--; if (tiefe === 0) return src.slice(start, j + 1).trim(); }
  }
  throw new Error(`Methode ${name} nicht geschlossen`);
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

/* ---- Neuaufbau-Sperre (das gemeldete Flackern, 2026-08-20) -------------- */

/** `unveraendert` als aufrufbare Methode auf einem frischen Objekt.
 *  Die Methode fragt window.hueZieht ab (Zug-Sperre) — im Browser immer da,
 *  hier gestellt, damit der Zustand steuerbar bleibt. */
function ladeUnveraendert(zieht = false) {
  const f = new Function('window', `return { ${schneideMethode(JS_PUR, 'unveraendert')} };`);
  return f({ hueZieht: zieht });
}
const voll = () => ({ children: { length: 3 } });

test('unveraendert: der erste Aufruf baut immer', () => {
  assert.equal(ladeUnveraendert().unveraendert('lampen', { a: 1 }, voll()), false);
});

test('unveraendert: gleiche Daten ⇒ kein Neuaufbau', () => {
  /* Der Kern des Flacker-Fixes: das Live-Update ruft die Render-Funktionen im
     Sekundentakt, obwohl sich fast nie etwas aendert. */
  const o = ladeUnveraendert(), c = voll();
  o.unveraendert('lampen', { a: 1, s: { on: true, bri: 200 } }, c);
  assert.equal(o.unveraendert('lampen', { a: 1, s: { on: true, bri: 200 } }, c), true);
});

test('unveraendert: geaenderte Daten ⇒ Neuaufbau', () => {
  const o = ladeUnveraendert(), c = voll();
  o.unveraendert('lampen', { s: { on: true, bri: 200 } }, c);
  assert.equal(o.unveraendert('lampen', { s: { on: true, bri: 201 } }, c), false,
    'eine geaenderte Helligkeit muss sichtbar werden');
  assert.equal(o.unveraendert('lampen', { s: { on: false, bri: 201 } }, c), false,
    'ein geschaltetes Licht muss sichtbar werden');
});

test('unveraendert: ein LEERER Container wird immer neu gebaut', () => {
  /* Sonst bliebe die Liste nach einem Reiterwechsel, der den Container
     ausraeumt, fuer immer leer — der Fingerabdruck passte ja noch. */
  const o = ladeUnveraendert(), leer = { children: { length: 0 } };
  o.unveraendert('lampen', { a: 1 }, leer);
  assert.equal(o.unveraendert('lampen', { a: 1 }, leer), false);
});

test('⚠️ waehrend eines Zugs wird NIE neu gebaut', () => {
  /* Der Sekundentakt wuerde die gezogene Karte sonst unter dem Finger
     vernichten — die Sperre gilt selbst bei frischen Daten. */
  const o = ladeUnveraendert(true), c = voll();
  assert.equal(o.unveraendert('lampen', { a: 1 }, c), true, 'erster Aufruf trotzdem gebaut');
  assert.equal(o.unveraendert('lampen', { a: 2 }, c), true, 'geaenderte Daten brachen den Zug ab');
});

test('unveraendert: die Schluessel der Listen mischen sich nicht', () => {
  const o = ladeUnveraendert(), c = voll();
  o.unveraendert('lampen', { a: 1 }, c);
  assert.equal(o.unveraendert('gruppen', { a: 1 }, c), false,
    'Gruppen erbten den Fingerabdruck der Lampen');
});

test('⚠️ jede im Sekundentakt gerufene Render-Funktion nutzt die Sperre', () => {
  /* refreshCurrentTab ruft loadLights/loadGroups/loadScenes jede Sekunde.
     Wer die Sperre vergisst, bringt das Flackern zurueck. */
  for (const [methode, schluessel] of [
    ['renderLights', 'lampen'], ['renderGroups', 'gruppen'], ['renderScenes', 'szenen'],
  ]) {
    const fn = schneideMethode(JS_PUR, methode);
    assert.match(fn, new RegExp(`if \\(this\\.unveraendert\\('${schluessel}'`),
      `${methode} baut bedingungslos neu`);
    assert.ok(fn.indexOf('unveraendert') < fn.indexOf('innerHTML'),
      `${methode} raeumt den Container aus, bevor es die Sperre fragt`);
  }
});

test('hueCollapsedSet: kaputter Inhalt wirft nicht, sondern liefert leer', () => {
  // Sonst risse ein einziges verungluecktes localStorage-Feld die ganze
  // Oberflaeche ab, weil die Einrichtung frueh laeuft.
  for (const muell of ['{kaputt', 'null', '"kein array"', '']) {
    assert.doesNotThrow(() => ladeCollapsedSet(muell)());
  }
});

/* --- Gemeinsame Zeitachse der Lampen-Analyse ------------------------------
   Der Anzeigefehler vom 2026-08-16: die Achse kannte nur die Zeitpunkte der
   ERSTEN Lampe, jede Reihe brachte aber ihre eigenen mit. Punkte, deren x in
   der Beschriftungsliste fehlt, kann Chart.js nicht verorten — die zweite
   Lampe lag als Gewirr aus Waagerechten und Diagonalen ueber dem Diagramm. */
const { zeitSchluessel, vereinigeLampenreihen } = (() => {
  const src = schneideFunktion(JS, 'zeitSchluessel') + '\n' +
              schneideFunktion(JS, 'vereinigeLampenreihen') +
              '\n; return { zeitSchluessel, vereinigeLampenreihen };';
  return new Function(src)();
})();

test('zeitSchluessel ordnet die Stunde ohne fuehrende Null richtig ein', () => {
  /* Genau hier versagt ein Textvergleich: das Backend baut
     CONCAT(DATE, ' ', HOUR, ':00'), also "2026-08-10 8:00" — als Zeichenkette
     laege das HINTER "2026-08-10 16:00". */
  assert.ok(zeitSchluessel('2026-08-10 8:00') < zeitSchluessel('2026-08-10 16:00'));
  assert.ok('2026-08-10 8:00' > '2026-08-10 16:00', 'Annahme: der Textvergleich irrt hier');
  assert.ok(zeitSchluessel('9:05') < zeitSchluessel('10:00'), 'Tagesform ebenso');
  assert.ok(zeitSchluessel('2026-08-09') < zeitSchluessel('2026-08-10'), 'Monatsform');
  assert.ok(zeitSchluessel('2026-08-31 23:00') < zeitSchluessel('2026-09-01 0:00'), 'Monatswechsel');
});

test('zeitSchluessel meldet unbekannte Formen als NaN', () => {
  for (const s of ['', 'gestern', '2026/08/10', null, undefined]) {
    assert.ok(Number.isNaN(zeitSchluessel(s)), `${s} sollte NaN ergeben`);
  }
});

test('zwei Lampen teilen sich EINE chronologische Achse', () => {
  const { zeiten, reihen } = vereinigeLampenreihen([
    { punkte: [{ time: '8:00', wert: 5 }, { time: '10:00', wert: 6 }] },
    { punkte: [{ time: '9:00', wert: 3 }, { time: '10:00', wert: 4 }] },
  ]);
  assert.deepEqual(zeiten, ['8:00', '9:00', '10:00'], 'Zeitpunkte beider Lampen, chronologisch');
  assert.deepEqual(reihen[0], [5, null, 6]);
  assert.deepEqual(reihen[1], [null, 3, 4]);
});

test('jede Reihe ist so lang wie die Achse', () => {
  // Sonst verrutschen die Werte gegen die Beschriftungen — der Fehler selbst.
  const { zeiten, reihen } = vereinigeLampenreihen([
    { punkte: [{ time: '2026-08-09 16:00', wert: 1 }] },
    { punkte: [{ time: '2026-08-09 8:00', wert: 2 }, { time: '2026-08-10 9:00', wert: 3 }] },
  ]);
  assert.equal(zeiten.length, 3);
  for (const r of reihen) assert.equal(r.length, zeiten.length);
  assert.deepEqual(zeiten, ['2026-08-09 8:00', '2026-08-09 16:00', '2026-08-10 9:00']);
  assert.deepEqual(reihen[0], [null, 1, null]);
});

test('ein Wert landet unter SEINEM Zeitpunkt, nicht unter dem Nachbarn', () => {
  // Die eigentliche Zusicherung: Beschriftung und Wert gehoeren zusammen.
  const lampen = [
    { punkte: [{ time: '0:10', wert: 11 }, { time: '0:30', wert: 33 }] },
    { punkte: [{ time: '0:20', wert: 22 }] },
  ];
  const { zeiten, reihen } = vereinigeLampenreihen(lampen);
  for (const [i, l] of lampen.entries()) {
    for (const p of l.punkte) {
      assert.equal(reihen[i][zeiten.indexOf(p.time)], p.wert,
        `${p.time} steht nicht an seiner Stelle`);
    }
  }
});

test('unbekannte Zeitform laesst die Reihenfolge des Servers stehen', () => {
  // Lieber die (bereits chronologische) Server-Reihenfolge behalten als nach
  // einem Schluessel sortieren, den es nicht gibt.
  const { zeiten } = vereinigeLampenreihen([
    { punkte: [{ time: 'spaet', wert: 1 }, { time: 'frueh', wert: 2 }] },
  ]);
  assert.deepEqual(zeiten, ['spaet', 'frueh']);
});

test('eine Lampe ohne Messwerte kippt die Achse nicht', () => {
  const { zeiten, reihen } = vereinigeLampenreihen([
    { punkte: [] },
    { punkte: [{ time: '1:00', wert: 7 }] },
  ]);
  assert.deepEqual(zeiten, ['1:00']);
  assert.deepEqual(reihen[0], [null]);
  assert.deepEqual(reihen[1], [7]);
});

test('doppelte Zeitpunkte tauchen nur einmal auf der Achse auf', () => {
  const { zeiten, reihen } = vereinigeLampenreihen([
    { punkte: [{ time: '1:00', wert: 1 }, { time: '1:00', wert: 9 }] },
  ]);
  assert.deepEqual(zeiten, ['1:00']);
  assert.deepEqual(reihen[0], [9], 'der letzte Wert gewinnt');
});

test('die Reihen haengen nicht mehr an den Zeitpunkten der ERSTEN Lampe', () => {
  // Vertrags-Pin gegen den Rueckfall: kein {x: item.time} mehr, und die
  // Beschriftungen kommen nicht aus validLamps[0].
  const r = schneideBlock(JS_PUR, 'renderIndividualLampChart(lampData, timeframe)', 'Renderer');
  assert.ok(!/x:\s*item\.time/.test(r),
    'die Reihe traegt wieder eigene x-Werte gegen eine fremde Achse');
  assert.ok(!/validLamps\[0\]\.data\.detailed_data\.map/.test(r),
    'die Achse kommt wieder nur von der ersten Lampe');
  assert.match(r, /vereinigeLampenreihen/, 'die gemeinsame Achse wird nicht gebildet');
});

test('Luecken werden nicht ueberbrueckt', () => {
  /* Hausregel: bei Datenausfall bricht die Linie, statt Messwerte zu erfinden
     (so halten es dB-Verlauf und Klima-Sparklines). Eine Lampe, die drei Tage
     keinen Eintrag hatte, bekam sonst eine schnurgerade Linie darueber —
     gemessen 19 fehlende Stunden am Stueck. Ein allein stehender Wert braucht
     dafuer einen sichtbaren Punkt, sonst faellt er ganz weg. */
  const r = schneideBlock(JS_PUR, 'renderIndividualLampChart(lampData, timeframe)', 'Renderer');
  assert.match(r, /spanGaps:\s*false/, 'Luecken werden wieder ueberbrueckt');
  assert.match(r, /pointRadius:\s*\(c\)/, 'einzelne Werte zwischen Luecken waeren unsichtbar');
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
  const fn = schneideFunktion(JS_PUR, 'initHueCollapse');
  assert.match(fn, /card-collapse'\)\)\s*return/,
    'kein Schutz gegen doppelte Chevrons');
});

test('Zuklappen: jede gepruefte Kopfzeile wird markiert, auch die ohne Titel', () => {
  /* Die Marke traegt zugleich den Vorabtest in planeHueCollapse. Bekaeme eine
     titellose Kopfzeile sie NICHT, meldete der Vorabtest ewig Arbeit, die es
     nicht gibt — der Beobachter liefe dann bei jeder Mutation voll durch. */
  const fn = schneideFunktion(JS_PUR, 'initHueCollapse');
  const markiert = fn.indexOf('dataset.hueCollapse');
  const abbruch = fn.indexOf('if (!key) return');
  assert.ok(markiert > -1, 'keine Marke gesetzt');
  assert.ok(abbruch > -1, 'kein Abbruch bei titelloser Kopfzeile');
  assert.ok(markiert < abbruch,
    'die Marke wird erst NACH dem Abbruch gesetzt — titellose Koepfe bleiben ungemarkt');
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

test('der Titel klebt nicht an der Verbrauchszeile', () => {
  /* Beide Raender auf 0 zu setzen war zu viel des Guten: Titel und
     Verbrauchszeile standen ohne jeden Zwischenraum aufeinander (gemessen 0 px,
     Nutzerbefund 2026-08-16). Der Kopf traegt den Abstand nach AUSSEN, der
     Titel den nach INNEN — beides muss gesetzt sein. */
  const h1 = CSS.match(/\n\s*\.header h1\s*\{[^}]*\}/)?.[0] || '';
  assert.match(h1, /margin-bottom:\s*var\(--sh-gap-lg\)/,
    'der Titel bringt keinen Abstand zur Verbrauchszeile mit');
});

test('die Mobil-Bloecke erfinden keine eigene Kopf-Rhythmik', () => {
  /* Frueher: Kopf-Polster 16/12, Titelrand 4, Verbrauchszeile 8 — drei
     verschiedene Rhythmen auf drei Schirmbreiten. Die Media-Bloecke duerfen nur
     noch Schriftgroessen anfassen. */
  for (const block of CSS.match(/@media[^{]*\{[\s\S]*?\n        \}/g) || []) {
    const kopf = block.match(/\.header\s*\{([^}]*)\}/);
    if (kopf) assert.ok(!/padding|margin/.test(kopf[1]),
      `ein Media-Block setzt wieder Kopf-Abstaende: ${kopf[1].trim()}`);
    const titel = block.match(/\.header h1\s*\{([^}]*)\}/);
    if (titel) assert.ok(!/margin/.test(titel[1]),
      `ein Media-Block setzt wieder einen Titelrand: ${titel[1].trim()}`);
  }
});

test('die Reiterleiste haelt den Haus-Abstand zum Inhalt', () => {
  // Gemessen 2026-08-16: 24 px, waehrend alles andere auf 16 stand.
  const tabs = CSS.match(/\n\s*\.tabs\s*\{[^}]*display:\s*flex[^}]*\}/)?.[0] || '';
  assert.match(tabs, /margin-bottom:\s*var\(--sh-gap-lg\)/,
    'die Reiterleiste weicht wieder vom Haus-Abstand ab');
});

test('⚠️ der gespeicherte Reiter wird ueber den GLOBALEN Einstieg wiederhergestellt', () => {
  /* Der Kern des Fehlers "ich kann keine Lampen auswaehlen" (2026-08-16):
     switchTab existiert ZWEIMAL — als Klassenmethode (schaltet nur sichtbar)
     und als globaler Aufsatz (laedt zusaetzlich die Lampenliste, die Debug- und
     Tastendaten). init() stellte den Reiter aus dem Speicher ueber die METHODE
     wieder her und umging damit alle Nebenwirkungen: wer die App zuletzt im
     Verbrauchs-Reiter verlassen hatte, sah beim naechsten Laden eine dauerhaft
     leere Lampenauswahl. */
  const init = schneideBlock(JS_PUR, 'async init()', 'Methode init');
  assert.match(init, /hue-active-tab/, 'die Wiederherstellung fehlt ganz');
  assert.match(init, /window\.switchTab/,
    'der gespeicherte Reiter laeuft wieder an den Reiter-Nebenwirkungen vorbei');
  assert.ok(!/this\.switchTab\(savedTab\)/.test(init),
    'die Wiederherstellung ruft wieder direkt die Klassenmethode und umgeht die Nebenwirkungen');
});

test('der Verbrauchs-Reiter fuellt die Lampenliste auch nachtraeglich', () => {
  // Zweite Verteidigungslinie: ein leerer Kasten muss beim naechsten Aufruf
  // neu gefuellt werden, nicht nur beim allerersten.
  /* ⚠️ Erst den globalen Aufsatz ausschneiden: `if (tabName === 'power')`
     kommt ZWEIMAL vor — auch in der Klassenmethode, die nur die Diagramme
     anstoesst. Ein Anker, den es mehrfach gibt, trifft sonst den falschen
     Block (derselbe Fehlgriff wie beim Massstab). */
  const aufsatz = schneideBlock(JS, 'window.switchTab = function(tabName)', 'globales switchTab');
  const g = schneideBlock(aufsatz, "if (tabName === 'power') {", 'power-Zweig');
  assert.match(g, /querySelector\('\.lamp-checkbox'\)/,
    'es wird nur der Merker geprueft, nicht der tatsaechliche Inhalt');
  assert.match(g, /loadLampSelection\(\)/, 'die Liste wird gar nicht geladen');
});

test('die Lampen-Analyse teilt sich in Liste und Bedienspalte', () => {
  /* Geerbt war `auto-fill minmax(300px, 1fr)`: bei 1160 px entstanden DREI
     Spuren fuer zwei Kinder — die Liste auf 371 px gequetscht, rechts eine
     leere Spalte (gemessen 2026-08-16). */
  assert.match(HTML, /class="controls-grid lamp-analysis-grid"/,
    'die Karte nutzt wieder das geerbte Raster');
  const regel = CSS.match(/\.lamp-analysis-grid\s*\{[^}]*\}/)?.[0] || '';
  assert.match(regel, /grid-template-columns:\s*minmax\(0,\s*1fr\)/,
    'die Liste bekommt nicht den freien Platz');
});

test('⚠️ das Raster der Lampen-Analyse steht VOR den Mobil-Regeln', () => {
  /* Gleiche Spezifitaet, spaetere Quelle gewinnt: stuende die Klasse hinter
     `.controls-grid { grid-template-columns: 1fr }`, bliebe die Karte auf dem
     Telefon zweispaltig. Als style-Attribut waere sie ohnehin unschlagbar —
     deshalb ist es bewusst eine Klasse. */
  // Kommentarfrei pruefen — der Kommentar an der Regel zitiert die Mobil-Regel
  // woertlich und wurde sonst selbst als Treffer gezaehlt.
  const eigen = CSS_PUR.indexOf('.lamp-analysis-grid');
  assert.notEqual(eigen, -1, '.lamp-analysis-grid fehlt');
  const mobil = [...CSS_PUR.matchAll(/\.controls-grid\s*\{\s*grid-template-columns:\s*1fr/g)]
    .map(m => m.index);
  assert.ok(mobil.length >= 1, 'keine Mobil-Regel fuer .controls-grid gefunden');
  for (const idx of mobil) {
    assert.ok(eigen < idx,
      'die Klasse steht hinter einer Mobil-Regel und macht die Karte dort zweispaltig');
  }
  const karte = HTML.match(/<div class="controls-grid lamp-analysis-grid"([^>]*)>/);
  assert.ok(!/grid-template-columns/.test(karte[1]),
    'das Raster steht wieder inline und schlaegt damit jede Media-Query');
});

test('Bedienelemente sind in BEIDEN Themes sichtbar', () => {
  /* Fest verdrahtetes Weiss: im hellen Theme stand ein weisser Rahmen auf
     heller Flaeche — das Kaestchen war unsichtbar, und genau das war als
     "ich kann keine Lampen auswaehlen" gemeldet. */
  const cb = CSS.match(/\.lamp-checkbox, \.form-checkbox, input\[type="checkbox"\]\s*\{[^}]*\}/)?.[0] || '';
  assert.ok(!/rgba\(255,\s*255,\s*255/.test(cb), 'das Kaestchen ist wieder fest weiss umrandet');
  assert.match(cb, /color-mix\(in srgb, var\(--text-primary\)/, 'die Kontur folgt nicht der Schriftfarbe');

  const sel = CSS.match(/\.form-select, select\s*\{[^}]*\}/)?.[0] || '';
  assert.ok(!/rgba\(255,\s*255,\s*255/.test(sel), 'das Auswahlfeld ist wieder fest weiss');
  assert.match(sel, /currentColor/, 'der Pfeil folgt nicht der Schriftfarbe');
});

test('das Kaestchen ist eckig — ein Kreis verspraeche Entweder-oder', () => {
  // var(--radius) sind 28 px und machten aus 18 px einen Kreis: das liest sich
  // als Radio-Knopf, obwohl mehrere Lampen erlaubt sind.
  const cb = CSS.match(/\.lamp-checkbox, \.form-checkbox, input\[type="checkbox"\]\s*\{[^}]*\}/)?.[0] || '';
  const r = cb.match(/border-radius:\s*([^;]+);/);
  assert.ok(r, 'keine Rundung gesetzt');
  assert.ok(!/var\(--radius\)/.test(r[1]), 'die 28-px-Rundung macht wieder einen Kreis daraus');
});

test('das Haekchen ist wirklich gezeichnet', () => {
  // content: '' faerbte nur das Kaestchen — ein Haken war nie zu sehen.
  const after = CSS.match(/input\[type="checkbox"\]:checked::after\s*\{[^}]*\}/)?.[0] || '';
  assert.match(after, /border-width:/, 'der Haken wird nicht gezeichnet');
  assert.match(after, /rotate\(45deg\)/, 'ohne Drehung ist es kein Haken');
});

test('⚠️ Zustandsregeln der Auswahlfelder setzen das Pfeilbild nicht zurueck', () => {
  /* `background: <farbe>` ist die KURZFORM und loescht background-image mit —
     der Pfeil verschwand beim Ueberfahren. Nur background-color darf hier. */
  for (const zustand of [':hover', ':focus']) {
    const r = CSS.match(new RegExp(`\\.form-select${zustand}, select${zustand}\\s*\\{[^}]*\\}`))?.[0] || '';
    assert.ok(r, `Regel fuer ${zustand} fehlt`);
    assert.ok(!/\n\s*background:\s/.test(r),
      `${zustand} nutzt die Kurzform und loescht damit den Pfeil`);
  }
});

test('es gibt genau EINEN Pfeil je Auswahlfeld', () => {
  // Das select zeichnet seinen eigenen; die Huelle setzte zusaetzlich ein ▼.
  assert.ok(!/\.select-wrapper::after\s*\{[^}]*content:\s*'▼'/.test(CSS),
    'die Huelle zeichnet wieder einen zweiten Pfeil');
});

test('⚠️ kein OS-Theme-Block ueberschreibt die Bedienelemente', () => {
  /* Ein `@media (prefers-color-scheme: dark)` hing an der Einstellung des
     BETRIEBSSYSTEMS und wusste nichts vom Theme-Schalter der Seite: System
     dunkel + App hell ergab weisse Flaechen auf hellem Grund. */
  assert.ok(!/@media \(prefers-color-scheme/.test(CSS_PUR),
    'wieder ein OS-Theme-Block — er kann den data-theme-Schalter nicht sehen');
});

test('⚠️ die Karten ueberleben einen Neuaufbau durch das Live-Update', () => {
  /* Die Karten der Lampen, Gruppen, Szenen und Sensoren werden vom
     Live-Update staendig NEU GEBAUT. Mit dem alten Stand fielen Chevron UND
     Zuklapp-Zustand dabei jedes Mal weg (gemessen 2026-08-17: nach dem
     Einrichten 11 Chevrons, nach EINEM loadLights wieder 0). Ein Beobachter
     richtet nach jeder Aenderung neu ein — einzelne Render-Funktionen
     nachzuruesten hiesse, jede kuenftige zu vergessen. */
  assert.match(JS_PUR, /new MutationObserver\(planeHueCollapse\)/,
    'kein Beobachter — die Karten verlieren ihren Chevron beim naechsten Neuaufbau');
  assert.match(JS_PUR, /observe\(document\.body,\s*\{\s*childList:\s*true,\s*subtree:\s*true/,
    'der Beobachter sieht die neu gebauten Karten nicht');
});

test('⚠️ der Beobachter richtet SYNCHRON ein — weder Zeitgeber noch rAF', () => {
  /* Der Rueckruf eines MutationObservers laeuft am Mikrotask-Punkt, also noch
     vor dem naechsten Zeichnen. Nur so bekommt eine neu gebaute Karte ihren
     Zuklapp-Zustand zurueck, ohne dass der Browser sie je offen malt.
     Hier stand ein setTimeout(50) — damit sprang eine zugeklappte Karte nach
     jedem Neuaufbau sichtbar auf und wieder zu: das gemeldete Flackern auf dem
     Handy (gemessen 2026-08-20, im Sekundentakt reproduziert).
     rAF waere ebenso falsch: es ruht in einem Tab, der nicht gezeichnet wird
     (beim Messen real passiert: 0 statt 8 Chevrons). */
  const plan = schneideFunktion(JS_PUR, 'planeHueCollapse');
  assert.ok(!/requestAnimationFrame/.test(plan), 'wieder an rAF gehaengt');
  assert.ok(!/setTimeout/.test(plan),
    'wieder aufgeschoben — die Karte springt dann sichtbar auf, bevor sie zuklappt');
  assert.match(plan, /initHueCollapse\(\)/, 'es wird gar nicht nachgeruestet');
  assert.match(plan, /hueCollapseLaeuft/,
    'ohne Wiedereintritts-Sperre loesen die eigenen Chevrons den Beobachter erneut aus');
  assert.match(plan, /:not\(\[data-hue-collapse\]\)/,
    'ohne Vorabtest laeuft bei JEDER Mutation ein voller Durchlauf');
});

test('⚠️ der aktive Reiter wird am NAMEN markiert, nicht am Klick-Ereignis', () => {
  /* Vorher haftete die Markierung an `event.target`. Beim Wiederherstellen des
     gespeicherten Reiters, beim Klick in der unteren Leiste und bei jedem
     Aufruf aus dem Code gibt es kein Ereignis — dann war KEINE Pille markiert,
     die Leiste sah tot aus und die Gruppen waren nicht wiederzufinden. */
  const st = schneideBlock(JS_PUR, 'switchTab(tabName) {', 'Klassenmethode switchTab');
  assert.ok(!/event\.target\.classList\.contains\('tab'\)/.test(st),
    'die Markierung haengt wieder am Klick-Ereignis');
  assert.match(st, /dataset\.tab === tabName/, 'der Reiter wird nicht am Namen erkannt');
});

test('jeder Reiter der Hauptleiste traegt seinen Namen als data-tab', () => {
  const leiste = HTML.slice(HTML.indexOf('<div class="tabs">'));
  const ende = leiste.indexOf('</div>');
  const zeile = leiste.slice(0, ende);
  const pillen = [...zeile.matchAll(/<button class="tab[^"]*"([^>]*)>([^<]+)</g)];
  assert.equal(pillen.length, 9, 'die Hauptleiste hat nicht mehr neun Reiter');
  for (const [, attrs, label] of pillen) {
    assert.match(attrs, /data-tab="[a-z]+"/, `Reiter ohne data-tab: ${label.trim()}`);
  }
  assert.match(zeile, /data-tab="groups"[^>]*>Gruppen</, 'der Gruppen-Reiter fehlt');
});

test('⚠️ die Zeitraum-Pillen des Verbrauchs-Reiters bleiben unangetastet', () => {
  // Sie tragen dieselbe Klasse `.tab`; ein pauschales Zuruecksetzen ueber
  // `.tab` nahm ihnen ihre Markierung.
  const st = schneideBlock(JS_PUR, 'switchTab(tabName) {', 'Klassenmethode switchTab');
  assert.match(st, /\.tabs > \.tab\[data-tab\]/,
    'die Auswahl trifft auch die Zeitraum-Pillen');
});

test('geteilte Leiste und Icons stehen auf der Hausversion', () => {
  assert.match(HTML, /nav\.js\?v=25/, 'nav.js-Version weicht ab');
  assert.match(HTML, /icons\.js\?v=9/, 'icons.js-Version weicht ab');
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

/* ---- Sortierbare Listen (2026-08-21) ------------------------------------ */

function ladeSortierLogik() {
  const src = schneideFunktion(JS, 'ordneSchluessel')
            + schneideFunktion(JS, 'naechsteKachel')
            + '; return { ordneSchluessel, naechsteKachel };';
  return new Function(src)();
}
const box = (left, top, width = 100, height = 40) => ({ left, top, width, height });

test('ordneSchluessel: die gespeicherte Reihenfolge gewinnt', () => {
  const { ordneSchluessel } = ladeSortierLogik();
  assert.deepEqual(ordneSchluessel(['a', 'b', 'c'], ['c', 'a', 'b']), ['c', 'a', 'b']);
});

test('⚠️ ordneSchluessel: eine NEUE Lampe verschwindet nicht, sie haengt hinten an', () => {
  /* Die Bridge lernt Lampen dazu. Wer nur die gespeicherte Liste rendert,
     blendet alles Neue unsichtbar aus — der haeufigste Fehler bei so etwas. */
  const { ordneSchluessel } = ladeSortierLogik();
  assert.deepEqual(ordneSchluessel(['a', 'b', 'neu'], ['b', 'a']), ['b', 'a', 'neu']);
});

test('ordneSchluessel: mehrere Neue behalten ihre Ursprungsfolge', () => {
  const { ordneSchluessel } = ladeSortierLogik();
  assert.deepEqual(ordneSchluessel(['x', 'y', 'a'], ['a']), ['a', 'x', 'y']);
});

test('ordneSchluessel: entfernte Lampen fallen still raus', () => {
  // Eine abgemeldete Lampe steht noch gespeichert — sie darf nichts kaputtmachen.
  const { ordneSchluessel } = ladeSortierLogik();
  assert.deepEqual(ordneSchluessel(['a', 'b'], ['weg', 'b', 'a']), ['b', 'a']);
});

test('ordneSchluessel: ohne gespeicherte Reihenfolge bleibt alles, wie es kam', () => {
  const { ordneSchluessel } = ladeSortierLogik();
  assert.deepEqual(ordneSchluessel(['a', 'b', 'c'], []), ['a', 'b', 'c']);
});

test('ordneSchluessel: jeder Schluessel kommt genau einmal vor', () => {
  // Ein Duplikat wuerde beim Anwenden eine Kachel verschlucken (Map-Zugriff).
  const { ordneSchluessel } = ladeSortierLogik();
  const r = ordneSchluessel(['a', 'b', 'c'], ['b', 'b', 'a']);
  assert.equal(new Set(r).size, r.length);
  assert.equal(r.length, 3);
});

test('naechsteKachel: findet die Kachel unter dem Zeiger', () => {
  const { naechsteKachel } = ladeSortierLogik();
  const boxen = [box(0, 0), box(200, 0), box(0, 100)];
  assert.equal(naechsteKachel(50, 20, boxen), 0);
  assert.equal(naechsteKachel(250, 20, boxen), 1);
  assert.equal(naechsteKachel(50, 120, boxen), 2);
});

test('⚠️ naechsteKachel misst zur MITTE, nicht nach Zeile oder Spalte', () => {
  /* Die Liste ist ein Grid und bricht in zwei Richtungen um; eine Regel
     "welche Zeile" waere dort blind fuer die Bewegung zur Seite. */
  const { naechsteKachel } = ladeSortierLogik();
  const boxen = [box(0, 0), box(200, 0)];
  assert.equal(naechsteKachel(149, 20, boxen), 0, 'knapp links der Grenze');
  assert.equal(naechsteKachel(151, 20, boxen), 1, 'knapp rechts der Grenze');
});

test('naechsteKachel: leere Liste liefert -1 statt zu werfen', () => {
  const { naechsteKachel } = ladeSortierLogik();
  assert.equal(naechsteKachel(10, 10, []), -1);
});

test('⚠️ die Reihenfolge wird nur angefasst, wenn sie falsch ist', () => {
  /* Ein bedingungsloses appendChild erzeugt Mutationen — und der Beobachter
     haengt an Mutationen. Ohne diesen Fruehausstieg dreht sich das endlos. */
  const fn = schneideFunktion(JS_PUR, 'wendeReihenfolgeAn');
  assert.match(fn, /if \(soll\.every\(\(k, i\) => k === keys\[i\]\)\) return;/,
    'kein Fruehausstieg bei bereits richtiger Reihenfolge');
});

test('⚠️ gezogen wird per Zeigerereignis, nicht per HTML5-Drag-and-Drop', () => {
  // HTML5-DnD kennt kein Touch — die App wird auf dem Handy bedient.
  const fn = schneideFunktion(JS_PUR, 'beginneZug');
  assert.match(fn, /setPointerCapture/, 'ohne Pointer-Capture reisst der Zug ab');
  assert.ok(!/dragstart|dataTransfer|draggable/.test(JS_PUR),
    'HTML5-Drag-and-Drop eingebaut — funktioniert auf dem Handy nicht');
  assert.match(CSS_PUR, /\.hue-griff\s*\{[^}]*touch-action:\s*none/,
    'ohne touch-action scrollt das Handy statt zu ziehen');
});

test('⚠️ der Zug haelt den Neuaufbau an', () => {
  const fn = schneideMethode(JS_PUR, 'unveraendert');
  assert.match(fn, /window\.hueZieht/, 'der Poll wuerde die gezogene Karte vernichten');
  assert.match(schneideFunktion(JS_PUR, 'beginneZug'), /window\.hueZieht = true/);
});

test('⚠️ zugeklappte Karten strecken sich nicht auf die Zeilenhoehe', () => {
  /* Grid-Kinder strecken per Default: die zugeklappte Karte blieb so hoch wie
     die hoechste der Zeile und stand leer da (Nutzerbefund 2026-08-21). */
  assert.match(schneideBlock(CSS_PUR, '.controls-grid {'), /align-items:\s*start/);
});

test('der Titeltext bekommt den freien Raum, sonst rutscht er in die Mitte', () => {
  // Mit Griff UND Chevron hat die Titelzeile drei Kinder — genau die Falle,
  // vor der der Kommentar an .card-title--collapsible warnt.
  assert.match(CSS_PUR, /\.card-title-text\s*\{[^}]*flex:\s*1/);
  assert.match(schneideFunktion(JS_PUR, 'initGriffe'), /huelleTitelText/);
});

test('der Griff hat auf Touch eine groessere Trefferflaeche als er aussieht', () => {
  /* Sichtbar 30 px wie der Chevron daneben, Trefferflaeche 44 px. Live nicht
     pruefbar: der Kopfbrowser meldet auch bei 390 px Breite einen FEINEN
     Zeiger, `pointer: coarse` greift dort nie. */
  assert.match(CSS_PUR, /@media \(pointer: coarse\)[\s\S]{0,200}\.hue-griff::before[\s\S]{0,160}width:\s*44px/);
  assert.match(CSS_PUR, /\.hue-griff\s*\{[^}]*width:\s*30px/);
});

/* ---- Farben & Effekte aufklappbar (2026-08-24) -------------------------- */

test('Toggle und Helligkeit stehen VOR dem Aufklapper, der Rest dahinter', () => {
  /* Der Alltag (schalten, dimmen) bleibt sofort sichtbar; die zwoelf
     Farbknoepfe + Strobo machten jede Karte ~560 px hoch. */
  const fn = schneideMethode(JS_PUR, 'createLightCard');
  const toggle = fn.indexOf('hue.toggle(');
  const slider = fn.indexOf('debouncedSetBrightness');
  const klappe = fn.indexOf('class="card-details');
  const farben = fn.indexOf('Beliebte Farben');
  const strobo = fn.indexOf('toggleStrobe');
  assert.ok(toggle > -1 && slider > -1 && klappe > -1);
  assert.ok(toggle < klappe && slider < klappe, 'Alltag hinter der Klappe versteckt');
  assert.ok(farben > klappe && strobo > klappe, 'Farben/Strobo nicht in der Klappe');
});

test('der Aufklapper startet ZU', () => {
  assert.match(CSS_PUR, /\.card-details\s*\{\s*display:\s*none/);
  assert.match(CSS_PUR, /\.card-details\.open\s*\{\s*display:\s*block/);
});

test('⚠️ der Offen-Zustand ueberlebt den Fingerprint-Rebuild', () => {
  /* Farbe setzen aendert die Lampendaten -> die Liste wird neu gebaut.
     Ohne das Set klappte der Aufklapper MITTEN im Faerben zu. Die Karte
     muss den Zustand beim Neuaufbau aus dem Set LESEN. */
  const fn = schneideMethode(JS_PUR, 'createLightCard');
  /* ⚠️ Der Pin muss an der KLASSE haengen, nicht irgendwo: die erste Fassung
     matchte jedes _openDetails.has() — auch das aria-Attribut — und blieb
     gruen, als die Klasse (die das Zeigen/Verstecken traegt) den Zustand
     nicht mehr las (eigene Mutationsprobe). */
  assert.match(fn, /class="card-details\$\{this\._openDetails\.has\(`\$\{type\}_\$\{id\}`\) \? ' open' : ''\}"/,
    'die card-details-KLASSE liest den Offen-Zustand nicht');
  assert.match(fn, /aria-expanded="\$\{this\._openDetails\.has\(`\$\{type\}_\$\{id\}`\)\}"/,
    'aria-expanded liest den Offen-Zustand nicht');
  const tg = schneideMethode(JS_PUR, 'toggleDetails');
  assert.match(tg, /_openDetails\.add\(key\)/);
  assert.match(tg, /_openDetails\.delete\(key\)/);
});

test('toggleDetails schaltet Klasse, Set und aria gemeinsam', () => {
  // Echter Verhaltens-Test mit Stubs statt Text-Pin.
  const mk = () => {
    const box = { classList: { c: new Set(), add(x){this.c.add(x);}, remove(x){this.c.delete(x);} } };
    const btn = { nextElementSibling: box, attrs: {}, setAttribute(k,v){this.attrs[k]=v;} };
    return { box, btn };
  };
  const obj = { _openDetails: new Set() };
  const fn = new Function('return function ' + schneideMethode(JS_PUR, 'toggleDetails'))();
  const { box, btn } = mk();
  fn.call(obj, 'light', '7', btn);
  assert.ok(obj._openDetails.has('light_7'));
  assert.ok(box.classList.c.has('open'));
  assert.equal(btn.attrs['aria-expanded'], 'true');
  fn.call(obj, 'light', '7', btn);
  assert.ok(!obj._openDetails.has('light_7'));
  assert.ok(!box.classList.c.has('open'));
  assert.equal(btn.attrs['aria-expanded'], 'false');
});

/* ---- Phase-3-Adoption: Suite-Dialekt (2026-08-30) ------------------------- */

const CSSP = CSS.replace(/\/\*[\s\S]*?\*\//g, '');

test('alle Buttons tragen sh-btn (Alt-Klassen bleiben als JS-Vertraege)', () => {
  const btns = [...HTML.matchAll(/<button[^>]*class="btn[ "$][^>]*/g)];
  assert.equal(btns.length, 26, 'Buttons gefunden: ' + btns.length);
  for (const b of btns) assert.match(b[0], /sh-btn/, b[0].slice(0, 90));
  // .btn.warning wird per querySelectorAll selektiert — die Klasse MUSS bleiben:
  assert.match(HTML, /querySelectorAll\('\.btn\.warning'\)/);
  assert.ok([...HTML.matchAll(/class="btn warning sh-btn warn"/g)].length === 3);
});

test('Lampen-Knopf: Zustaende kommen aus dem Dialekt (on/tonal)', () => {
  assert.match(HTML, /class="btn sh-btn \$\{this\.getButtonClass\(isOn, isReachable\)\}"/);
  const fn = HTML.match(/getButtonClass\(isOn, isReachable\) \{[\s\S]{0,400}?\}/)[0];
  assert.match(fn, /'on'/); assert.match(fn, /'tonal'/);
  assert.ok(!/btn-on/.test(fn), 'alte Zustandsklasse lebt noch in getButtonClass');
  // Die Lampen-AN-Glut ist App-Identitaet auf dem Dialekt:
  assert.match(CSSP, /\.sh-btn\.on\s*\{[^}]*box-shadow/);
});

test('die 2 Toggles sind sh-switch (Vertrag A), das alte Skinning ist tot', () => {
  const sw = [...HTML.matchAll(/<label class="toggle-switch sh-switch">/g)];
  assert.equal(sw.length, 2);
  assert.ok([...HTML.matchAll(/sh-switch-track/g)].length >= 2);
  assert.ok(!/\.toggle-slider\s*\{/.test(CSSP), 'toggle-slider-Skin lebt noch');
});

test('die 6 Slider sind sh-slider mit Fuellungs-Verdrahtung', () => {
  const sliders = [...HTML.matchAll(/<input type="range"[^>]*>/g)];
  assert.equal(sliders.length, 6);
  for (const m of sliders) assert.match(m[0], /sh-slider/, m[0].slice(0, 90));
  // Lampen-Slider wird bei jedem Rebuild NEU gebaut — die Fuellung muss im
  // Template GEBACKEN sein, sonst blitzt sie nach jedem Fingerprint-Rebuild weg:
  assert.match(HTML, /--sh-slider-fill:\$\{/);
  // Statische Slider: delegierter input-Listener + programmatischer Faenger:
  assert.match(HTML, /fuelleShSlider/);
  assert.ok(!/\.slider::-webkit-slider-thumb/.test(CSSP), 'eigener Thumb-Skin lebt noch');
});

test('Reiter-Pillen sprechen sh-pill, der Skin ist tot', () => {
  const tabs = [...HTML.matchAll(/<button class="tab[ "][^>]*/g)];
  assert.equal(tabs.length, 15);
  for (const t of tabs) assert.match(t[0], /sh-pill/, t[0].slice(0, 90));
  assert.ok(!/\.tab\.active\s*\{[^}]*background/.test(CSSP), 'eigener Aktiv-Skin lebt noch');
});

test('btn-active (Strobo) ist tokenisiert und sitzt AUF dem Dialekt', () => {
  assert.ok(!CSSP.includes('#FF6B6B'), 'Hardcode-Rot lebt noch');
  assert.match(CSSP, /\.sh-btn\.btn-active\s*\{[^}]*var\(--sh-loud\)/);
  assert.ok(!/\.sh-btn\.btn-active\s*\{[^}]*!important/.test(CSSP),
    'important war nur gegen den eigenen Alt-Skin noetig');
});

test('die toten Skins sind wirklich tot', () => {
  for (const tot of ['.btn-primary', '.btn-secondary', '.btn.accent', '.btn.premium', '.btn-on', '.btn-off', '.btn-disabled']) {
    assert.ok(!new RegExp(tot.replace(/\./g, '\\.') + '\\s*\\{').test(CSSP), tot + ' lebt noch');
  }
});

/* ---- Chart-Motion (2026-08-30) -------------------------------------------- */

test('Chart.js zeichnet bei jedem expliziten Aufbau ein (reduced-motion-bewusst)', () => {
  // Die Charts entstehen NUR bei expliziten Wechseln (destroy+new; kein Poll
  // fasst sie an) — animation:false hatte das Einzeichnen ueberall abgeschaltet.
  const JSP = HTML.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/[^\n]*$/gm, '');
  assert.ok(!/animation: false,/.test(JSP), 'ein Chart ist noch stumm');
  assert.equal([...JSP.matchAll(/animation: this\.chartAnim\(\),/g)].length, 7);
  assert.match(JSP, /prefers-reduced-motion[\s\S]{0,80}\? false/);
});
