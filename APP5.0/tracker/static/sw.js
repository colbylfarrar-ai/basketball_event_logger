/* sw.js — app shell is stale-while-revalidate (instant load + background refresh
   so a new deploy reaches installed phones on the next open); icons are
   cache-first; /api/* is network only (never cached — the offline queue is the
   source of truth). Bump CACHE on every release to purge the old shell. */
const CACHE = 'tracker-v9';
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
  // No skipWaiting() here — a new SW WAITS until the app tells it to activate
  // (the user taps "Refresh" on the update banner), so we never swap code out
  // from under a coach mid-possession.
  e.waitUntil(
    caches.open(CACHE)
      // add each asset individually so a missing icon can't brick the install
      .then((cache) => Promise.all(ASSETS.map((url) => cache.add(url).catch(() => {}))))
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// The page posts this when the user taps "Refresh" on the update banner — that's
// the only thing that activates a waiting new version.
self.addEventListener('message', (e) => {
  if (e.data && e.data.type === 'SKIP_WAITING') self.skipWaiting();
});

// App-shell assets get fresh code on every open: navigations ('/'), the JS, and
// the CSS. Icons + everything else stay cache-first (they rarely change).
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
  if (url.pathname === '/sw.js') return;             // never cache the SW script itself
  if (e.request.method !== 'GET') return;

  if (isShell(url, e.request)) {
    // stale-while-revalidate: serve cache instantly, refresh in the background,
    // fall back to cache when offline so courtside use never breaks.
    e.respondWith(
      caches.open(CACHE).then((cache) =>
        cache.match(e.request).then((hit) => {
          const fetching = fetch(e.request).then((res) => {
            if (res.ok) cache.put(e.request, res.clone());
            return res;
          }).catch(() => hit);
          return hit || fetching;
        })
      )
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
