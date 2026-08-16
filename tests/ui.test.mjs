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
