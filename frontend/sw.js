// Bump CACHE_NAME whenever frontend behaviour changes meaningfully, or a
// browser can keep serving the old JS/HTML from cache indefinitely.
const CACHE_NAME = "xau-guess-v7";
const SHELL_FILES = [
  "./",
  "./index.html",
  "./style.css",
  "./app.js",
  "./config.js",
  "./manifest.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // Only same-origin shell assets. API calls (Supabase, Yahoo) go straight to
  // the network -- caching a price would be worse than showing nothing.
  if (url.origin !== self.location.origin || event.request.method !== "GET") return;
  // Network-first: always prefer the freshly deployed file, fall back to
  // cache only when actually offline.
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
