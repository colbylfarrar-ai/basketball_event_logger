/* sw.js — reliability over cleverness:
   - install auto-activates (skipWaiting) so a new version never gets stuck
     "waiting" behind an open tab (iOS especially never reliably activated it);
   - activate purges old caches + claims clients;
   - app shell (navigations, app.js, court.js, style.css, manifest) is NETWORK-FIRST
     so an open of the app always pulls the latest when online, with a cache
     fallback so courtside offline still works;
   - icons are cache-first; /api/* and /sw.js are never cached.
   The page reloads once when a NEW worker takes over (see index.html), so a reopen
   lands on the latest — no banner, no kill-and-reopen, no reinstall. */
const CACHE = 'tracker-v32';
const ASSETS = [
  '/',
  '/static/app.js',
  '/static/court.js',
  '/static/wb.js',
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
      .then(() => self.skipWaiting())          // activate immediately, never wait
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Shell assets we always want fresh when online.
function isShell(url, request) {
  return request.mode === 'navigate' ||
    url.pathname === '/' ||
    url.pathname === '/manifest.json' ||
    /\/static\/(app|court)\.js$/.test(url.pathname) ||
    /\/static\/style\.css$/.test(url.pathname);
}

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;        // passthrough cross-origin
  if (url.pathname.startsWith('/api/')) return;      // network only, never cached
  if (url.pathname === '/sw.js') return;             // never cache the SW script
  if (e.request.method !== 'GET') return;

  if (isShell(url, e.request)) {
    // network-first: freshest shell when online, cache fallback when offline.
    e.respondWith(
      fetch(e.request).then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return res;
      }).catch(() => caches.match(e.request))
    );
    return;
  }

  // icons + other static: cache-first
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
