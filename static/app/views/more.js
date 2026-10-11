// Mehr: Energie, Status, Anleitung.
import { h } from '../dom.js';
import { api } from '../api.js';
import { areaChart, barChart } from '../chart.js';
import { makeSortable, applyOrder } from '../sortable.js';

const DAYS = { Monday: 'Mo', Tuesday: 'Di', Wednesday: 'Mi', Thursday: 'Do', Friday: 'Fr', Saturday: 'Sa', Sunday: 'So' };
const DAY_ORDER = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const n = (v) => Number(v) || 0;
const fmt = (v, d = 1) => n(v).toLocaleString('de-DE', { maximumFractionDigits: d, minimumFractionDigits: d });

function energy() {
  const now = h('div', { class: 'kpis' });
  const chartBox = h('div', { class: 'chart-box' });
  const top = h('ol', { class: 'top-list' });
  const weekdays = h('div', { class: 'chart-box' });
  const months = h('div', { class: 'chart-box' });
  let range = 'today';
  const pills = h('div', { class: 'sh-tabs', role: 'tablist' },
    ...[['today', 'Heute'], ['week', 'Woche'], ['month', 'Monat']].map(([k, label]) =>
      h('button', { class: 'sh-pill' + (k === range ? ' on' : ''), type: 'button', role: 'tab', 'data-r': k,
        'aria-selected': String(k === range),
        onclick: () => { range = k; for (const b of pills.children) { b.classList.toggle('on', b.dataset.r === k); b.setAttribute('aria-selected', String(b.dataset.r === k)); } loadDetail(); } }, label)));

  async function loadNow() {
    const r = await api.get('/power/current', 10000);
    if (!r.ok) { now.replaceChildren(h('p', { class: 'muted', text: 'Verbrauch nicht verfügbar: ' + r.error })); return; }
    const d = r.data;
    now.replaceChildren(
      kpi(fmt(d.total_watts) + ' W', 'jetzt'),
      kpi(String(d.active_lights), 'Lampen an'),
      kpi(fmt(d.estimated_monthly_kwh) + ' kWh', 'pro Monat (geschätzt)'),
      kpi(fmt(d.estimated_monthly_cost_eur, 2) + ' €', 'pro Monat (0,30 €/kWh)'));
  }
  async function loadDetail() {
    chartBox.replaceChildren(h('div', { class: 'chart-empty', text: 'Lädt …' }));
    const r = await api.get('/power/detailed/' + range, 30000);
    if (!r.ok) { chartBox.replaceChildren(h('div', { class: 'chart-empty', text: 'Nicht verfügbar: ' + r.error })); return; }
    const pts = (r.data.detailed_data || []).map((p) => ({ label: shortTime(p.time, range), value: n(p.avg_watts) }));
    chartBox.replaceChildren(areaChart(pts, { unit: 'W', label: 'Leistung', width: chartBox.clientWidth }));
    top.replaceChildren(...(r.data.top_lights || []).slice(0, 6).map((l) =>
      h('li', null, h('span', { text: l.light_name }), h('span', { class: 'muted', text: fmt(l.total_kwh, 2) + ' kWh · ' + Math.round(n(l.on_percentage)) + ' % an' }))));
  }
  async function loadWeekly() {
    const r = await api.get('/power/weekly', 30000);
    if (!r.ok) return weekdays.replaceChildren(h('div', { class: 'chart-empty', text: 'Nicht verfügbar' }));
    const by = Object.fromEntries((r.data.weekday_summary || []).map((d) => [d.weekday, d]));
    weekdays.replaceChildren(barChart(DAY_ORDER.filter((d) => by[d]).map((d) => ({
      label: DAYS[d], value: n(by[d].total_kwh) / Math.max(1, n(by[d].days_counted)),
      title: `${DAYS[d]}: ⌀ ${fmt(n(by[d].total_kwh) / Math.max(1, n(by[d].days_counted)), 2)} kWh je Tag`,
    })), { unit: 'kWh/Tag', label: 'Verbrauch je Wochentag', width: weekdays.clientWidth }));
  }
  async function loadMonthly() {
    const r = await api.get('/power/monthly', 30000);
    if (!r.ok) return months.replaceChildren(h('div', { class: 'chart-empty', text: 'Nicht verfügbar' }));
    const rows = (r.data.monthly_summary || []).slice().reverse();
    months.replaceChildren(barChart(rows.map((m) => ({
      label: m.month.slice(5) + '/' + m.month.slice(2, 4), value: n(m.total_kwh),
      title: `${m.month}: ${fmt(m.total_kwh, 2)} kWh · ${fmt(m.cost_eur, 2)} €`,
    })), { unit: 'kWh', label: 'Verbrauch je Monat', width: months.clientWidth }));
  }

  const el = h('div', { class: 'stack' },
    h('section', { class: 'card sortable-card', 'data-sort-id': 'now' }, h('h2', { class: 'card-title', text: 'Jetzt' }), now,
      h('p', { class: 'muted small', text: 'Schätzung aus Helligkeit × 9 W je Lampe — kein Messgerät.' })),
    h('section', { class: 'card sortable-card', 'data-sort-id': 'power' }, h('div', { class: 'card-head' }, h('h2', { class: 'card-title', text: 'Leistung' }), pills), chartBox,
      h('h3', { class: 'sec-title', text: 'Größte Verbraucher' }), top),
    h('section', { class: 'card sortable-card', 'data-sort-id': 'weekdays' }, h('h2', { class: 'card-title', text: 'Je Wochentag' }), weekdays),
    h('section', { class: 'card sortable-card', 'data-sort-id': 'months' }, h('h2', { class: 'card-title', text: 'Je Monat' }), months));
  applyOrder(el, 'energy-cards', '.sortable-card');
  makeSortable(el, { key: 'energy-cards', draggable: '.sortable-card' });
  el.load = () => { loadNow(); loadDetail(); loadWeekly(); loadMonthly(); };
  return el;
}

function kpi(value, label) {
  return h('div', { class: 'kpi' }, h('span', { class: 'kpi-v', text: value }), h('span', { class: 'kpi-l', text: label }));
}

function shortTime(t, range) {
  if (!t) return '';
  if (range === 'today') return t;
  const m = /^(\d{4})-(\d{2})-(\d{2})(?: (\d+):\d+)?/.exec(t);
  return m ? `${m[3]}.${m[2]}.` + (range === 'week' && m[4] ? ` ${m[4]}h` : '') : t;
}

function status(store) {
  const box = h('dl', { class: 'facts' });
  const q = h('dl', { class: 'facts' });
  async function load() {
    const r = await api.get('/v2/status', 5000);
    const s = r.ok ? r.data : store.raw.status || {};
    const age = s.last_event ? Math.round(Date.now() / 1000 - s.last_event) : null;
    box.replaceChildren(
      dt('Bridge-Verbindung'), dd(s.connected ? 'verbunden (Event-Stream)' : 'getrennt — verbinde neu'),
      dt('Letztes Ereignis'), dd(age == null ? '–' : age < 60 ? `vor ${age} s` : `vor ${Math.round(age / 60)} min`),
      dt('Live-Verbindungen'), dd(String(s.subscribers ?? '–')),
      dt('Räume / Lampen'), dd(`${Object.keys(store.raw.rooms).length} / ${Object.keys(store.raw.lights).length}`));
    const qs = s.queue || {};
    q.replaceChildren(
      dt('Gesendet'), dd(String(qs.sent ?? '–')),
      dt('Zusammengefasst'), dd(String(qs.coalesced ?? '–') + ' (Zwischenwerte beim Ziehen)'),
      dt('Fehlgeschlagen'), dd(String(qs.failed ?? '–')),
      dt('Wartend'), dd(String(qs.pending ?? '–')));
    errs.replaceChildren(...(s.errors || []).slice().reverse().map((e) =>
      h('li', null, h('span', { class: 'muted', text: new Date(e.at * 1000).toLocaleTimeString('de-DE') + ' · ' + e.where + ' · ' }), e.msg)));
    if (!(s.errors || []).length) errs.append(h('li', { class: 'muted', text: 'Keine Fehler.' }));
  }
  const errs = h('ul', { class: 'errs' });
  const el = h('div', { class: 'stack' },
    h('section', { class: 'card sortable-card', 'data-sort-id': 'link' }, h('h2', { class: 'card-title', text: 'Verbindung' }), box),
    h('section', { class: 'card sortable-card', 'data-sort-id': 'queue' }, h('h2', { class: 'card-title', text: 'Befehls-Warteschlange' }), q,
      h('p', { class: 'muted small', text: 'Die Bridge verträgt etwa 10 Befehle pro Sekunde. Beim Ziehen eines Reglers wird nur der jeweils letzte Wert gesendet.' })),
    h('section', { class: 'card sortable-card', 'data-sort-id': 'errors' }, h('h2', { class: 'card-title', text: 'Letzte Fehler' }), errs));
  applyOrder(el, 'status-cards', '.sortable-card');
  makeSortable(el, { key: 'status-cards', draggable: '.sortable-card' });
  el.load = load;
  return el;
}
const dt = (t) => h('dt', { text: t });
const dd = (t) => h('dd', { text: t });

function guide() {
  const p = (t) => h('p', { text: t });
  return h('div', { class: 'stack' }, h('section', { class: 'card prose' },
    h('h2', { class: 'card-title', text: 'So funktioniert’s' }),
    p('Zuhause zeigt jeden Raum als Kachel: Schalter zum An- und Ausschalten, der Regler dimmt live. Die Farbe der Kachel ist die echte Lichtfarbe im Raum.'),
    p('Ein Tipp auf den Raumnamen öffnet den Raum: Stimmungen, eigene Szenen, Farbe und Weißton, Effekte, Strobo und jede einzelne Lampe.'),
    p('Änderungen aus der Philips-App, von Schaltern oder Automationen erscheinen sofort — die App hört der Bridge zu, statt nachzufragen.'),
    p('Eigene Szenen: Raum einstellen, dann „Aktuellen Zustand als Szene speichern“. Sie erscheinen auch in der Philips-App.'),
    p('Effekte laufen in den Lampen selbst. Welche ein Raum anbietet, hängt von seinen Lampen ab.')));
}

export function moreView(store) {
  const panes = { energie: energy(), status: status(store), hilfe: guide() };
  let cur = 'energie';
  const host = h('div');
  const tabs = h('div', { class: 'sh-tabs', role: 'tablist' },
    ...[['energie', 'Energie'], ['status', 'Status'], ['hilfe', 'Anleitung']].map(([k, label]) =>
      h('button', { class: 'sh-pill', type: 'button', role: 'tab', 'data-k': k, onclick: () => show(k) }, label)));
  function show(k) {
    cur = k;
    for (const b of tabs.children) { b.classList.toggle('on', b.dataset.k === k); b.setAttribute('aria-selected', String(b.dataset.k === k)); }
    host.replaceChildren(panes[k]);
    panes[k].load && panes[k].load();
  }
  const sec = h('section', { class: 'view', id: 'view-mehr', 'aria-labelledby': 'h-mehr' },
    h('h1', { id: 'h-mehr', class: 'view-title', text: 'Mehr' }), tabs, host);
  sec.render = () => show(cur);
  return sec;
}
