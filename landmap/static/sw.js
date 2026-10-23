/* Service worker: cache the app shell and map tiles so the map works on the property without signal. */
const SHELL_CACHE = "landmap-shell-v5";
const TILE_CACHE = "landmap-tiles";
const SHELL = [
  "/", "/static/app.js", "/static/style.css", "/static/manifest.webmanifest", "/static/icon.svg",
  "/static/vendor/leaflet/leaflet.css", "/static/vendor/leaflet/leaflet.js",
];
const TILE_HOSTS = ["server.arcgisonline.com"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((k) => k.startsWith("landmap-shell-") && k !== SHELL_CACHE).map((k) => caches.delete(k))
    )).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET") return;

  if (url.pathname.startsWith("/api/")) {
    // Network first; fall back to the last good copy so the boundary and pins still show offline.
    event.respondWith(
      fetch(event.request).then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(SHELL_CACHE).then((c) => c.put(event.request, copy));
        }
        return res;
      }).catch(() => caches.match(event.request))
    );
    return;
  }

  if (TILE_HOSTS.includes(url.hostname)) {
    event.respondWith(
      caches.open(TILE_CACHE).then((c) => c.match(event.request).then((hit) => hit ||
        fetch(event.request).then((res) => { if (res.ok) c.put(event.request, res.clone()); return res; })))
    );
    return;
  }

  // App shell: network first so a connected browser always gets the current version;
  // the cached copy is the fallback for use on the property without signal.
  event.respondWith(
    fetch(event.request).then((res) => {
      if (res.ok && url.origin === self.location.origin) {
        const copy = res.clone();
        caches.open(SHELL_CACHE).then((c) => c.put(event.request, copy));
      }
      return res;
    }).catch(() => caches.match(event.request))
  );
});
