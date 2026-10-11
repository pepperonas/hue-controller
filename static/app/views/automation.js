// Automation — wird in Phase 4 ausgebaut (Zeitplaene, Lichtwecker,
// Bewegungsmelder, Abwesenheit). Bis dahin ehrlicher Platzhalter.
import { h } from '../dom.js';

export function automationView() {
  const sec = h('section', { class: 'view', id: 'view-automation', 'aria-labelledby': 'h-auto' },
    h('h1', { id: 'h-auto', class: 'view-title', text: 'Automation' }),
    h('section', { class: 'card' }, h('p', { class: 'muted', text: 'Zeitpläne, Lichtwecker, Bewegungsmelder und Abwesenheit folgen hier.' })));
  sec.render = () => {};
  return sec;
}
