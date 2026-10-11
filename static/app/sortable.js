// Karten per Drag-and-drop anordnen — ueberall in der App gleich.
//
// Gefuehl wie die Pipeline in ops / das Board in cue (dort dnd-kit; das braucht
// React, diese App ist bewusst ohne Build — SortableJS ist das Vanilla-Pendant):
//   * frei mitlaufende Vorschau der Karte (forceFallback = eigener Klon)
//   * die anderen Karten machen animiert Platz
//   * Maus startet nach 6 px, Touch nach kurzem Halten (180 ms, 6 px Toleranz) —
//     so bleibt normales Scrollen am Handy moeglich
//   * Auto-Scroll am Rand, Tastatur: Alt + Pfeiltasten
// Schalter, Regler und Eingabefelder bleiben bedienbar (sie starten keinen Zug).
// Die Reihenfolge gilt je Geraet (localStorage), wie im Dashboard.
import Sortable from '../vendor/sortable.esm.js';

const PREFIX = 'hue-order:';

export function loadOrder(key) {
  try { const v = JSON.parse(localStorage.getItem(PREFIX + key)); return Array.isArray(v) ? v : []; } catch (e) { return []; }
}
export function saveOrder(key, ids) {
  try { localStorage.setItem(PREFIX + key, JSON.stringify(ids)); } catch (e) { /* privat */ }
}

/** Gespeicherte Folge zuerst, Neues hinten in Ursprungsfolge, Entferntes faellt
 *  raus, Doppelte nur einmal. Pur. */
export function orderBy(items, saved, idOf = (x) => x.id) {
  const byId = new Map(items.map((x) => [String(idOf(x)), x]));
  const out = [], seen = new Set();
  for (const id of saved || []) {
    const k = String(id);
    if (byId.has(k) && !seen.has(k)) { seen.add(k); out.push(byId.get(k)); }
  }
  for (const x of items) if (!seen.has(String(idOf(x)))) out.push(x);
  return out;
}

/** Stellt die Kinder eines Containers in die gespeicherte Reihenfolge (DOM). */
export function applyOrder(container, key, selector) {
  const kids = [...container.querySelectorAll(':scope > ' + selector)];
  const sorted = orderBy(kids, loadOrder(key), (el) => el.dataset.sortId);
  if (sorted.some((el, i) => el !== kids[i])) container.append(...sorted);
}

const NO_DRAG = 'input, select, textarea, label, a, .sh-switch, .sh-slider, .wheel, .no-drag';
const active = new Set();

/** Ist irgendwo gerade ein Zug? (Neuaufbauten sollen dann warten.) */
export const isDragging = () => active.size > 0;

export function makeSortable(container, { key, draggable, onEnd }) {
  if (container._sortable) return container._sortable;
  let justDropped = false;
  const save = () => {
    const ids = [...container.querySelectorAll(':scope > ' + draggable)].map((el) => el.dataset.sortId).filter(Boolean);
    saveOrder(key, ids);
    onEnd && onEnd(ids);
  };
  const s = Sortable.create(container, {
    draggable,
    animation: 220,
    easing: 'cubic-bezier(0.2, 0, 0, 1)',
    filter: NO_DRAG,
    preventOnFilter: false,           // gefilterte Elemente bleiben voll bedienbar
    forceFallback: true,              // frei schwebende Vorschau statt HTML5-Ghost
    fallbackOnBody: false,            // Klon im Container: erbt Theme und Breite
    fallbackTolerance: 6,             // Maus: erst nach 6 px ein Zug, sonst Klick
    delay: 180, delayOnTouchOnly: true, touchStartThreshold: 6,
    scroll: true, bubbleScroll: true, scrollSensitivity: 80, scrollSpeed: 14,
    ghostClass: 'sort-ghost', chosenClass: 'sort-chosen', dragClass: 'sort-drag', fallbackClass: 'sort-fallback',
    onStart: () => { active.add(container); document.body.classList.add('sorting'); },
    onEnd: (e) => {
      active.delete(container);
      document.body.classList.toggle('sorting', active.size > 0);
      if (e.oldIndex !== e.newIndex) { justDropped = true; setTimeout(() => { justDropped = false; }, 60); save(); }
    },
  });
  // Nach dem Ablegen kein versehentlicher Klick auf die Karte (oeffnete sonst den Raum).
  container.addEventListener('click', (e) => { if (justDropped) { e.preventDefault(); e.stopPropagation(); } }, true);
  // Tastatur: Alt + Pfeil verschiebt die fokussierte Karte.
  container.addEventListener('keydown', (e) => {
    if (!e.altKey || !/^Arrow(Up|Down|Left|Right)$/.test(e.key)) return;
    const item = e.target.closest(draggable);
    if (!item || item.parentElement !== container) return;
    const back = e.key === 'ArrowUp' || e.key === 'ArrowLeft';
    const sib = back ? item.previousElementSibling : item.nextElementSibling;
    if (!sib || !sib.matches(draggable)) return;
    e.preventDefault();
    if (back) container.insertBefore(item, sib); else container.insertBefore(sib, item);
    e.target.focus();
    save();
  });
  container._sortable = s;
  return s;
}
