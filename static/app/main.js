// Einstieg der Hue-App: vier Ziele, ein Speicher, eine Live-Verbindung.
import { h, icon, toast } from './dom.js';
import { connect } from './api.js';
import { createStore } from './store.js';
import { homeView } from './views/home.js';
import { scenesView } from './views/scenes.js';
import { automationView } from './views/automation.js';
import { moreView } from './views/more.js';

const store = createStore();
const views = {
  home: { label: 'Zuhause', icon: 'home', el: homeView(store) },
  szenen: { label: 'Szenen', icon: 'palette', el: scenesView(store) },
  automation: { label: 'Automation', icon: 'clock', el: automationView(store) },
  mehr: { label: 'Mehr', icon: 'sliders', el: moreView(store) },
};

const main = document.getElementById('main');
const nav = document.getElementById('nav');
const link = document.getElementById('link');
main.replaceChildren(...Object.values(views).map((v) => v.el));

for (const [k, v] of Object.entries(views)) {
  nav.append(h('a', { href: '#' + k, class: 'nav-item', 'data-v': k },
    icon(v.icon, 'nav-ic'), h('span', { class: 'nav-label', text: v.label })));
}

function show() {
  const k = views[location.hash.slice(1)] ? location.hash.slice(1) : 'home';
  for (const [key, v] of Object.entries(views)) {
    const on = key === k;
    v.el.hidden = !on;
    const a = nav.querySelector(`[data-v="${key}"]`);
    a.classList.toggle('on', on);
    if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  }
  views[k].el.render && store.ready && views[k].el.render();
}
window.addEventListener('hashchange', show);

const LINK = {
  live: ['live', 'Live'],
  poll: ['poll', 'Live-Verbindung getrennt – aktualisiere alle 10 s'],
  off: ['off', 'Server nicht erreichbar'],
  'bridge-off': ['off', 'Bridge nicht erreichbar – verbinde neu'],
};
function setLink(state) {
  const [cls, text] = LINK[state] || LINK.off;
  link.className = 'link ' + cls;
  link.lastChild.textContent = text;
}

store.subscribe((c) => { if (c.all) show(); });
connect(store, setLink, (d) => toast('Die Bridge hat einen Befehl abgelehnt: ' + d.msg, 'err'));
show();

if ('serviceWorker' in navigator) {
  // sw.js liegt neben der Seite -> Scope = App-Wurzel (die alte Registrierung
  // unter static/ hatte den Scope /static/ und steuerte die Seite nie).
  navigator.serviceWorker.register('sw.js').catch(() => {});
}
