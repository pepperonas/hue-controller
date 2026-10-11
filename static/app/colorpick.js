// Farbrad (Canvas) + Weiss-Regler. Liefert waehrend des Ziehens gedrosselt
// xy bzw. Mirek; die Queue im Backend koalesziert ohnehin auf den letzten Wert.
import { h } from './dom.js';
import { hsvToRgb, rgbToXy, xyToRgb, rgbToHsv, mirekToKelvin, kelvinToMirek, mirekToRgb, toHex } from './color.js';
import { throttle } from './store.js';

const SIZE = 240;

export function colorWheel({ xy, onPick, onStart, onEnd, label = 'Farbe wählen' }) {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const canvas = h('canvas', {
    width: SIZE * dpr, height: SIZE * dpr, class: 'wheel',
    role: 'slider', tabindex: 0, 'aria-label': label,
    'aria-valuemin': 0, 'aria-valuemax': 359,
  });
  const knob = h('div', { class: 'wheel-knob', 'aria-hidden': 'true' });
  const wrap = h('div', { class: 'wheel-wrap' }, canvas, knob);
  const ctx = canvas.getContext('2d');

  // Rad einmal malen: Farbton im Kreis, Saettigung nach aussen
  const img = ctx.createImageData(SIZE * dpr, SIZE * dpr);
  const R = (SIZE * dpr) / 2;
  for (let py = 0; py < SIZE * dpr; py++) {
    for (let px = 0; px < SIZE * dpr; px++) {
      const dx = px - R, dy = py - R, d = Math.hypot(dx, dy);
      const i = (py * SIZE * dpr + px) * 4;
      if (d > R) { img.data[i + 3] = 0; continue; }
      const hue = (Math.atan2(dy, dx) * 180) / Math.PI + 180;
      const [r, g, b] = hsvToRgb(hue, Math.min(1, d / R), 1);
      img.data[i] = r; img.data[i + 1] = g; img.data[i + 2] = b;
      img.data[i + 3] = d > R - 1 ? Math.round(255 * (R - d)) : 255;  // weiche Kante
    }
  }
  ctx.putImageData(img, 0, 0);

  let hue = 0, sat = 0;
  function place() {
    const rad = ((hue - 180) * Math.PI) / 180;
    const r = (SIZE / 2) * sat;
    knob.style.transform = `translate(${SIZE / 2 + Math.cos(rad) * r}px, ${SIZE / 2 + Math.sin(rad) * r}px)`;
    const rgb = hsvToRgb(hue, sat, 1);
    knob.style.background = toHex(rgb);
    canvas.setAttribute('aria-valuenow', Math.round(hue));
    canvas.setAttribute('aria-valuetext', `Farbton ${Math.round(hue)}°, Sättigung ${Math.round(sat * 100)} %`);
  }
  function setFromXy(p) {
    if (!p) return;
    const { h: hh, s } = rgbToHsv(...xyToRgb(p.x, p.y));
    hue = hh; sat = s;
    place();
  }
  const send = throttle(() => onPick(rgbToXy(...hsvToRgb(hue, sat, 1))), 120);

  function fromPointer(e) {
    const r = canvas.getBoundingClientRect();
    const dx = e.clientX - r.left - r.width / 2, dy = e.clientY - r.top - r.height / 2;
    hue = (Math.atan2(dy, dx) * 180) / Math.PI + 180;
    sat = Math.min(1, Math.hypot(dx, dy) / (r.width / 2));
    place();
    send();
  }
  let dragging = false;
  canvas.addEventListener('pointerdown', (e) => {
    dragging = true;
    canvas.setPointerCapture(e.pointerId);
    onStart && onStart();
    fromPointer(e);
  });
  canvas.addEventListener('pointermove', (e) => { if (dragging) fromPointer(e); });
  const end = () => {
    if (!dragging) return;
    dragging = false;
    onPick(rgbToXy(...hsvToRgb(hue, sat, 1)));
    onEnd && onEnd();
  };
  canvas.addEventListener('pointerup', end);
  canvas.addEventListener('pointercancel', end);
  canvas.addEventListener('keydown', (e) => {
    const step = e.shiftKey ? 15 : 5;
    if (e.key === 'ArrowRight') hue = (hue + step) % 360;
    else if (e.key === 'ArrowLeft') hue = (hue - step + 360) % 360;
    else if (e.key === 'ArrowUp') sat = Math.min(1, sat + 0.05);
    else if (e.key === 'ArrowDown') sat = Math.max(0, sat - 0.05);
    else return;
    e.preventDefault();
    place();
    send();
  });

  setFromXy(xy);
  wrap.set = (p) => { if (!dragging) setFromXy(p); };
  return wrap;
}

/** Weiss-Regler in Kelvin (intern Mirek), Verlauf warm -> kalt. */
export function whiteSlider({ mirek, min = 153, max = 500, onPick, onStart, onEnd }) {
  const kMin = mirekToKelvin(max), kMax = mirekToKelvin(min);
  const out = h('span', { class: 'val' });
  const el = h('input', {
    type: 'range', class: 'sh-slider white', min: kMin, max: kMax, step: 50,
    'aria-label': 'Farbtemperatur in Kelvin',
  });
  el.style.background = `linear-gradient(90deg, ${toHex(mirekToRgb(max))}, ${toHex(mirekToRgb(Math.round((min + max) / 2)))}, ${toHex(mirekToRgb(min))})`;
  const show = () => { out.textContent = el.value + ' K'; };
  el.value = mirek ? mirekToKelvin(mirek) : 2700;
  show();
  const send = throttle(() => onPick(clampM(kelvinToMirek(+el.value))), 120);
  const clampM = (m) => Math.max(min, Math.min(max, m));
  let dragging = false;
  el.addEventListener('pointerdown', () => { dragging = true; onStart && onStart(); });
  el.addEventListener('input', () => { show(); send(); });
  el.addEventListener('change', () => { dragging = false; onPick(clampM(kelvinToMirek(+el.value))); onEnd && onEnd(); });
  const row = h('div', { class: 'line' }, h('span', { class: 'lbl', text: 'Weiß' }), el, out);
  row.set = (m) => { if (!dragging && m) { el.value = mirekToKelvin(m); show(); } };
  return row;
}
