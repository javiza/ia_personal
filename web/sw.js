// Service worker: deja la app instalable y abre rápido, incluso sin conexión (muestra la app o una página de aviso).
// NUNCA guarda respuestas de /api (conversaciones, archivos y papelera son privados).
const VERSION = "jarvis-v6";
const BASE = ["/", "/instalar", "/static/offline.html", "/static/estilo.css", "/static/app.js", "/static/img/avatar_reposo.gif",
              "/static/img/avatar_escuchando.gif", "/static/img/avatar_pensando.gif", "/static/img/avatar_hablando.gif",
              "/static/img/icon-192.png"];

self.addEventListener("install", (e) => {
  // addAll falla entero si UNA ruta falla: se guardan una por una para que un fallo suelto no impida instalar
  e.waitUntil(caches.open(VERSION).then((c) => Promise.all(BASE.map((u) => c.add(u).catch(() => {})))).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== VERSION).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // red primero (siempre la versión nueva); si no hay conexión, lo guardado; si tampoco, la página de aviso
  e.respondWith(fetch(e.request).then((r) => {
    if (r.ok) { const copia = r.clone(); caches.open(VERSION).then((c) => c.put(e.request, copia)); }
    return r;
  }).catch(async () => {
    const guardado = await caches.match(e.request, { ignoreSearch: true });
    if (guardado) return guardado;
    if (e.request.mode === "navigate") return (await caches.match("/", { ignoreSearch: true })) || caches.match("/static/offline.html");
    return Response.error();
  }));
});
