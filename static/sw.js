// Minimal service worker — required for the site to be installable as an app.
// Passes all requests straight through to the network (no offline caching),
// so the app always shows live, current data.
self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request));
});
