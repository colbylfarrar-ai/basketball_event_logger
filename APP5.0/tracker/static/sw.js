/* sw.js — cache-first app shell; /api/* is network only */
const CACHE = 'tracker-v3';
const ASSETS = [
  '/',
  '/static/app.js',
  '/static/court.js',
  '/static/style.css',
  '/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/icon-180.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE)
      // add each asset individually so a missing icon can't brick the install
      .then((cache) => Promise.all(ASSETS.map((url) => cache.add(url).catch(() => {}))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;        // passthrough cross-origin
  if (url.pathname.startsWith('/api/')) return;      // network only, never cached
  if (e.request.method !== 'GET') return;
  e.respondWith(
    caches.match(e.request).then((hit) =>
      hit ||
      fetch(e.request).then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return res;
      })
    )
  );
});
