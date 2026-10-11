// Schlanke SVG-Diagramme (Linie/Flaeche und Balken) in den Haus-Tokens.
// Ersetzt Chart.js vom CDN (ungepinnt, render-blockierend, ~200 kB).
import { h } from './dom.js';

const NS = 'http://www.w3.org/2000/svg';
const s = (tag, attrs) => {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  return el;
};

const tick = (v) => (Number.isInteger(v) ? String(v) : v.toLocaleString('de-DE', { maximumFractionDigits: 1 }));

function niceMax(v) {
  if (!(v > 0)) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

/** Flaechendiagramm. points: [{label, value}] */
export function areaChart(points, { unit = 'W', height = 170, label = 'Verlauf', width = 600 } = {}) {
  // In der echten Breite zeichnen: ein gestrecktes viewBox liesse die
  // Achsenschrift am Desktop auf das Doppelte wachsen.
  const W = Math.max(280, Math.round(width)), H = height, pad = { l: 38, r: 8, t: 24, b: 22 };
  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: 'chart', role: 'img', 'aria-label': label });
  if (!points.length) {
    const wrap = h('div', { class: 'chart-empty', text: 'Noch keine Daten' });
    return wrap;
  }
  const max = niceMax(Math.max(...points.map((p) => p.value)));
  const x = (i) => pad.l + (i / Math.max(1, points.length - 1)) * (W - pad.l - pad.r);
  const y = (v) => pad.t + (1 - v / max) * (H - pad.t - pad.b);
  for (const f of [0, 0.5, 1]) {
    svg.append(s('line', { x1: pad.l, x2: W - pad.r, y1: y(max * f), y2: y(max * f), class: 'grid' }));
    const t = s('text', { x: pad.l - 6, y: y(max * f) + 4, class: 'axis', 'text-anchor': 'end' });
    t.textContent = tick(max * f);
    svg.append(t);
  }
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join('');
  svg.append(s('path', { d: `${line}L${x(points.length - 1)},${y(0)}L${x(0)},${y(0)}Z`, class: 'area' }));
  svg.append(s('path', { d: line, class: 'line' }));
  const ticks = Math.min(Math.max(2, Math.floor(W / 90)), points.length);
  for (let k = 0; k < ticks; k++) {
    const i = Math.round((k / Math.max(1, ticks - 1)) * (points.length - 1));
    const t = s('text', { x: x(i), y: H - 6, class: 'axis', 'text-anchor': k === 0 ? 'start' : k === ticks - 1 ? 'end' : 'middle' });
    t.textContent = points[i].label;
    svg.append(t);
  }
  const unitT = s('text', { x: 4, y: 12, class: 'axis' });   // ueber der obersten Linie, nicht darauf
  unitT.textContent = unit;
  svg.append(unitT);
  return svg;
}

/** Balkendiagramm. bars: [{label, value, title}] */
export function barChart(bars, { unit = 'kWh', height = 160, label = 'Balken', width = 600 } = {}) {
  const W = Math.max(280, Math.round(width)), H = height, pad = { l: 38, r: 8, t: 24, b: 22 };
  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: 'chart', role: 'img', 'aria-label': label });
  if (!bars.length) return h('div', { class: 'chart-empty', text: 'Noch keine Daten' });
  const max = niceMax(Math.max(...bars.map((b) => b.value)));
  const bw = (W - pad.l - pad.r) / bars.length;
  const y = (v) => pad.t + (1 - v / max) * (H - pad.t - pad.b);
  for (const f of [0, 0.5, 1]) {
    svg.append(s('line', { x1: pad.l, x2: W - pad.r, y1: y(max * f), y2: y(max * f), class: 'grid' }));
    const t = s('text', { x: pad.l - 6, y: y(max * f) + 4, class: 'axis', 'text-anchor': 'end' });
    t.textContent = tick(max * f);
    svg.append(t);
  }
  bars.forEach((b, i) => {
    const r = s('rect', {
      x: pad.l + i * bw + bw * 0.15, width: bw * 0.7, y: y(b.value),
      height: Math.max(0, y(0) - y(b.value)), rx: 4, class: 'bar',
    });
    const tt = s('title');
    tt.textContent = b.title || `${b.label}: ${b.value.toFixed(2)} ${unit}`;
    r.append(tt);
    svg.append(r);
    const t = s('text', { x: pad.l + i * bw + bw / 2, y: H - 6, class: 'axis', 'text-anchor': 'middle' });
    t.textContent = b.label;
    svg.append(t);
  });
  const unitT = s('text', { x: 4, y: 12, class: 'axis' });   // ueber der obersten Linie, nicht darauf
  unitT.textContent = unit;
  svg.append(unitT);
  return svg;
}
