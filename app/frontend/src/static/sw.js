// CL-66 service worker: precache every file of the static build on
// install, then serve same-origin GETs cache-first. After the first
// visit the page, the Pyodide runtime, the library bundle and the
// examples all load with no network at all.
const PREFIX = "covertlens-static-";

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const response = await fetch("precache.json", { cache: "no-store" });
      const manifest = await response.json();
      const cache = await caches.open(PREFIX + manifest.revision);
      await cache.addAll(manifest.files.map((f) => new Request(f, { cache: "reload" })));
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const response = await caches.match("precache.json");
      const keep = response ? PREFIX + (await response.clone().json()).revision : null;
      for (const key of await caches.keys()) {
        if (key.startsWith(PREFIX) && key !== keep) await caches.delete(key);
      }
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET" || new URL(request.url).origin !== self.location.origin) {
    return;
  }
  event.respondWith(
    (async () => {
      const cached = await caches.match(request, { ignoreSearch: true });
      if (cached) return cached;
      const url = new URL(request.url);
      if (url.pathname.endsWith("/")) {
        const index = await caches.match(new URL("index.html", url).href);
        if (index) return index;
      }
      return fetch(request);
    })(),
  );
});
