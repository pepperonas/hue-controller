// Farbumrechnung fuer die Hue-App (rein, ohne DOM — auch unter node:test).
// Hue spricht CIE xy (Farbe) und Mirek (Weiss). Angezeigt wird sRGB.

const clamp01 = (v) => Math.max(0, Math.min(1, v));

function gammaToLinear(c) {
  return c > 0.04045 ? Math.pow((c + 0.055) / 1.055, 2.4) : c / 12.92;
}
function linearToGamma(c) {
  c = Math.max(0, c);
  return c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
}

/** sRGB 0..255 -> CIE xy (Wide-Gamut-D65, wie von Philips dokumentiert). */
export function rgbToXy(r, g, b) {
  const R = gammaToLinear(r / 255), G = gammaToLinear(g / 255), B = gammaToLinear(b / 255);
  const X = R * 0.664511 + G * 0.154324 + B * 0.162028;
  const Y = R * 0.283881 + G * 0.668433 + B * 0.047685;
  const Z = R * 0.000088 + G * 0.07231 + B * 0.986039;
  const s = X + Y + Z;
  if (s === 0) return { x: 0.3127, y: 0.329 };   // Schwarz -> Weisspunkt
  return { x: round4(X / s), y: round4(Y / s) };
}

/** CIE xy -> sRGB 0..255, auf volle Leuchtkraft normiert (Anzeige). */
export function xyToRgb(x, y) {
  if (!(y > 0)) return [255, 255, 255];
  const Y = 1, X = (Y / y) * x, Z = (Y / y) * (1 - x - y);
  let r = X * 1.656492 - Y * 0.354851 - Z * 0.255038;
  let g = -X * 0.707196 + Y * 1.655397 + Z * 0.036152;
  let b = X * 0.051713 - Y * 0.121364 + Z * 1.01153;
  const m = Math.max(r, g, b, 1e-9);
  return [r, g, b].map((v) => Math.round(clamp01(linearToGamma(v / m)) * 255));
}

function closestOnSegment(p, a, b) {
  const ap = { x: p.x - a.x, y: p.y - a.y }, ab = { x: b.x - a.x, y: b.y - a.y };
  const t = clamp01((ap.x * ab.x + ap.y * ab.y) / (ab.x * ab.x + ab.y * ab.y || 1));
  return { x: a.x + ab.x * t, y: a.y + ab.y * t };
}
const cross = (a, b) => a.x * b.y - a.y * b.x;

/** Liegt xy im Farbraum-Dreieck der Lampe? */
export function inGamut(p, g) {
  if (!g) return true;
  const v1 = { x: g.green.x - g.red.x, y: g.green.y - g.red.y };
  const v2 = { x: g.blue.x - g.red.x, y: g.blue.y - g.red.y };
  const q = { x: p.x - g.red.x, y: p.y - g.red.y };
  const d = cross(v1, v2);
  const s = cross(q, v2) / d, t = cross(v1, q) / d;
  return s >= 0 && t >= 0 && s + t <= 1;
}

/** xy ausserhalb des Lampen-Farbraums -> naechster Punkt auf dessen Rand.
 *  Sonst klemmt die Lampe selbst, und die Anzeige luegt. */
export function clampToGamut(p, g) {
  if (!g || inGamut(p, g)) return { x: round4(p.x), y: round4(p.y) };
  const cands = [
    closestOnSegment(p, g.red, g.green),
    closestOnSegment(p, g.green, g.blue),
    closestOnSegment(p, g.blue, g.red),
  ];
  let best = cands[0], bd = Infinity;
  for (const c of cands) {
    const d = (c.x - p.x) ** 2 + (c.y - p.y) ** 2;
    if (d < bd) { bd = d; best = c; }
  }
  return { x: round4(best.x), y: round4(best.y) };
}

/** HSV (h 0..360, s/v 0..1) -> sRGB 0..255 */
export function hsvToRgb(h, s, v) {
  h = ((h % 360) + 360) % 360;
  const c = v * s, x = c * (1 - Math.abs(((h / 60) % 2) - 1)), m = v - c;
  const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x]
    : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return [r, g, b].map((u) => Math.round((u + m) * 255));
}

/** sRGB -> HSV (fuer das Setzen des Rad-Markers aus einer Lampenfarbe) */
export function rgbToHsv(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  let h = 0;
  if (d) {
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
    if (h < 0) h += 360;
  }
  return { h, s: max ? d / max : 0, v: max };
}

export const mirekToKelvin = (m) => Math.round(1e6 / m / 50) * 50;
export const kelvinToMirek = (k) => Math.round(1e6 / k);

/** Farbtemperatur -> sRGB (Tanner-Helland), fuer die Anzeige. */
export function mirekToRgb(m) {
  const k = 1e6 / Math.max(1, m) / 100;
  let r, g, b;
  if (k <= 66) {
    r = 255;
    g = 99.4708025861 * Math.log(k) - 161.1195681661;
    b = k <= 19 ? 0 : 138.5177312231 * Math.log(k - 10) - 305.0447927307;
  } else {
    r = 329.698727446 * Math.pow(k - 60, -0.1332047592);
    g = 288.1221695283 * Math.pow(k - 60, -0.0755148492);
    b = 255;
  }
  return [r, g, b].map((v) => Math.round(Math.max(0, Math.min(255, v))));
}

export const toHex = ([r, g, b]) =>
  '#' + [r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('');

export function hexToRgb(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Lesbare Schriftfarbe auf einem farbigen Grund (WCAG-Luminanz). */
export function onColor(hex) {
  const rgb = hexToRgb(hex);
  if (!rgb) return '#000000';
  const L = rgb.map((c) => gammaToLinear(c / 255));
  const lum = 0.2126 * L[0] + 0.7152 * L[1] + 0.0722 * L[2];
  return lum > 0.4 ? '#1a1c22' : '#ffffff';
}

function round4(v) { return Math.round(v * 10000) / 10000; }
