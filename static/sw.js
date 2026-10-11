// Hue-App Service Worker (2026-10-11). Liegt per Flask-Route unter /sw.js
// NEBEN der Seite -> Scope = App-Wurzel.
//  * Seite + App-Dateien: network-first, Cache nur als Offline-Rueckfall
//    (so kommt jedes Deploy sofort an; die ?v=-Dateien sind ohnehin versioniert)
//  * /api und der Event-Stream: nie anfassen
const CACHE = 'hue-v1';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k !== CACHE) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.includes('/api/')) return;
  e.respondWith((async () => {
    try {
      // cache: 'no-cache' — sonst liefert der HTTP-Cache alte Bytes in den SW-Cache
      const res = await fetch(req, { cache: 'no-cache' });
      if (res.ok) (await caches.open(CACHE)).put(req, res.clone());
      return res;
    } catch (err) {
      const hit = await caches.match(req);
      if (hit) return hit;
      throw err;
    }
  })());
});
