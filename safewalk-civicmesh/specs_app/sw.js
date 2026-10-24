/* Offline shell only. Never cache camera frames, API data, tokens, or incident clips. */
const VERSION = 'safewalk-shell-v1.0.0';
const SHELL = ['/specs/', '/specs/index.html', '/specs/js/specs_core.js', '/specs/js/audio_spatializer.js',
  '/specs/js/gesture_engine.js', '/specs/manifest.webmanifest', '/specs/icon.svg', '/specs/icon-192.png', '/specs/icon-512.png'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(VERSION).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('safewalk-shell-') && key !== VERSION)
    .map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin || !SHELL.includes(url.pathname)) return;
  event.respondWith(fetch(request).then(response => {
    if (response.ok) { const copy = response.clone(); caches.open(VERSION).then(cache => cache.put(url.pathname, copy)); }
    return response;
  }).catch(() => caches.match(url.pathname).then(cached => cached || (request.mode === 'navigate' ? caches.match('/specs/') : Response.error()))));
});
