// Hue-Controller SW — app-v7 (2026-08-13, optimistisches Laden).
// Vorher: cache-first fuer die Shell OHNE Activate-Cleanup — Updates
// erreichten installierte PWAs nie (caches.match durchsucht ALLE Caches,
// die alte app-v1-Shell gewann fuer immer). Jetzt das Haus-Muster
// (yamaha-SW-Fix): NETWORK-FIRST fuer Navigationen/Shell mit
// Cache-Fallback (offline), cache-first fuer statische Assets,
// /api/ IMMER am Cache vorbei, und alte Caches werden beim Activate
// geloescht. Bei Shell-Aenderungen: CACHE_NAME bumpen.
const CACHE_NAME = 'app-v7';
const urlsToCache = [
  '/',
  '/index.html'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
    )).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.url.includes('/api/')) {
    return;   // API nie cachen — direkt durch
  }
  const isShell = req.mode === 'navigate'
    || req.url.endsWith('/index.html') || new URL(req.url).pathname === '/';
  if (isShell) {
    // network-first: frische Shell, Cache nur als Offline-Fallback
    event.respondWith(
      fetch(req).then(res => {
        const copy = res.clone();
        caches.open(CACHE_NAME).then(c => c.put(req, copy));
        return res;
      }).catch(() => caches.match(req, { cacheName: CACHE_NAME }))
    );
    return;
  }
  event.respondWith(
    caches.match(req).then(res => res || fetch(req))
  );
});
