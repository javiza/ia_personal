// Service worker: deja la app instalable y abre rápido. NUNCA guarda respuestas de /api (conversaciones privadas).
const VERSION = "jarvis-v2";
const BASE = ["/", "/static/estilo.css", "/static/app.js", "/static/img/avatar_reposo.gif", "/static/img/avatar_escuchando.gif",
              "/static/img/avatar_pensando.gif", "/static/img/avatar_hablando.gif", "/static/img/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(BASE)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== VERSION).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // red primero (siempre la versión nueva); si no hay internet, lo guardado
  e.respondWith(fetch(e.request).then((r) => {
    if (r.ok) { const copia = r.clone(); caches.open(VERSION).then((c) => c.put(e.request, copia)); }
    return r;
  }).catch(() => caches.match(e.request).then((r) => r || caches.match("/"))));
});
