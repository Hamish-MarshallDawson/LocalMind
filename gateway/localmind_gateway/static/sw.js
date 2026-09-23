// Keeps the page itself available when this device can't reach the gateway (off the tailnet, on
// a plane): it opens from cache and shows the chats and PC status saved on the device. The API is
// never cached, so nothing live is ever stale.
const SHELL = 'lm-gateway-shell-v2';
const FILES = ['./', 'app.css', 'app.js', 'icon.svg', 'manifest.webmanifest'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(SHELL).then((cache) => cache.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== SHELL).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  // Network first, so updates arrive straight away; the cache is only the fallback.
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(SHELL).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request, { ignoreSearch: true }).then((hit) => hit || caches.match('./'))),
  );
});
