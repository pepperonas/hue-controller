// DOM-Helfer. Regel: Text (Namen von der Bridge!) NUR per textContent —
// die alte App setzte Lampen- und Szenennamen per innerHTML (XSS).

export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'text') el.textContent = v;
    else if (k in el && k !== 'list' && k !== 'form') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

/** Icon aus dem geteilten Set (statische, vertrauenswuerdige SVG-Strings). */
export function icon(name, cls = 'ic') {
  const span = h('span', { class: cls, 'aria-hidden': 'true' });
  if (window.SHIcons && window.SHIcons.ICONS[name]) span.innerHTML = window.SHIcons.html(name);
  return span;
}

/** sh-switch, Vertrag A (label + checkbox) — mit Namen fuer Screenreader. */
export function shSwitch(label, checked, onChange) {
  const input = h('input', { type: 'checkbox', 'aria-label': label });
  input.checked = !!checked;
  input.addEventListener('change', () => onChange(input.checked));
  const sw = h('label', { class: 'sh-switch' }, input,
    h('span', { class: 'sh-switch-track' }, h('span', { class: 'sh-switch-thumb' })));
  sw.set = (v) => { input.checked = !!v; };
  sw.input = input;
  return sw;
}

/** sh-slider mit Fuellstand; ``onInput`` beim Ziehen, ``onDone`` beim Loslassen. */
export function shSlider(label, value, { min = 1, max = 100, step = 1, onStart, onInput, onDone } = {}) {
  const el = h('input', { type: 'range', class: 'sh-slider', min, max, step, 'aria-label': label });
  const paint = () => el.style.setProperty('--sh-slider-fill', ((el.value - min) / (max - min)) * 100 + '%');
  el.value = value ?? min;
  paint();
  let dragging = false;
  const start = () => { if (!dragging) { dragging = true; onStart && onStart(); } };
  el.addEventListener('pointerdown', start);
  el.addEventListener('keydown', start);
  el.addEventListener('input', () => { start(); paint(); onInput && onInput(+el.value); });
  el.addEventListener('change', () => { dragging = false; paint(); onDone && onDone(+el.value); });
  el.set = (v) => { if (!dragging && v != null) { el.value = v; paint(); } };
  el.isDragging = () => dragging;
  return el;
}

let toastTimer = 0;
export function toast(text, kind = '') {
  let t = document.getElementById('toast');
  if (!t) {
    t = h('div', { id: 'toast', role: 'status', 'aria-live': 'polite' });
    document.body.append(t);
  }
  t.textContent = text;
  t.className = 'show ' + kind;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = ''; }, 3500);
}

/** Bottom-Sheet auf <dialog>. Liefert {dialog, body, close}. */
export function sheet(title, build, onClose) {
  const body = h('div', { class: 'sheet-body' });
  const closeBtn = h('button', { class: 'sh-icon-btn sheet-x', type: 'button', 'aria-label': 'Schließen' }, icon('close'));
  const head = h('div', { class: 'sheet-head' }, h('h2', { class: 'sheet-title', text: title }), closeBtn);
  const dlg = h('dialog', { class: 'sheet', 'aria-label': title }, h('div', { class: 'sheet-grip', 'aria-hidden': 'true' }), head, body);
  document.body.append(dlg);
  const close = () => dlg.close();
  closeBtn.addEventListener('click', close);
  dlg.addEventListener('click', (e) => { if (e.target === dlg) close(); });
  dlg.addEventListener('close', () => { onClose && onClose(); dlg.remove(); });
  build(body, head);
  dlg.showModal();
  // Fokus auf Schliessen statt aufs erste Bedienelement (meist der Raum-Schalter):
  // ein versehentliches Enter soll kein Licht schalten.
  closeBtn.focus();
  return { dialog: dlg, body, head, close };
}

export function confirmSheet(title, text, okLabel, danger = false) {
  return new Promise((resolve) => {
    let answer = false;
    sheet(title, (body) => {
      body.append(
        h('p', { class: 'muted', text }),
        h('div', { class: 'row end' },
          h('button', { class: 'sh-btn tonal', type: 'button', onclick: (e) => e.target.closest('dialog').close() }, 'Abbrechen'),
          h('button', {
            class: 'sh-btn' + (danger ? ' danger' : ''), type: 'button',
            onclick: (e) => { answer = true; e.target.closest('dialog').close(); },
          }, okLabel)));
    }, () => resolve(answer));
  });
}

/** Kleiner Texteingabe-Dialog (statt prompt()). */
export function askText(title, label, { maxLength = 32, pattern } = {}) {
  return new Promise((resolve) => {
    let value = null;
    sheet(title, (body) => {
      const input = h('input', { class: 'field', type: 'text', maxLength, 'aria-label': label, placeholder: label });
      const form = h('form', {
        class: 'stack',
        onsubmit: (e) => {
          e.preventDefault();
          const v = input.value.trim();
          if (!v || (pattern && !pattern.test(v))) { input.setAttribute('aria-invalid', 'true'); input.focus(); return; }
          value = v;
          form.closest('dialog').close();
        },
      }, input, h('div', { class: 'row end' }, h('button', { class: 'sh-btn', type: 'submit' }, 'Speichern')));
      body.append(form);
      setTimeout(() => input.focus(), 50);
    }, () => resolve(value));
  });
}
