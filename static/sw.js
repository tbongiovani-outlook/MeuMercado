/*
 * Service worker do Meu Mercado (PWA).
 * Estratégia:
 *   - Estáticos (/static/): cache-first (rápido e disponível offline).
 *   - Navegações (páginas): network-first com fallback ao cache.
 * Dados sensíveis nunca são cacheados: apenas GET de mesma origem.
 */
var CACHE = "meu-mercado-v1";
var ATIVOS = [
    "/static/style.css",
    "/static/app.js",
    "/static/favicon.svg",
    "/static/manifest.webmanifest"
];

self.addEventListener("install", function (event) {
    event.waitUntil(
        caches.open(CACHE).then(function (cache) {
            return cache.addAll(ATIVOS);
        }).then(function () {
            return self.skipWaiting();
        })
    );
});

self.addEventListener("activate", function (event) {
    event.waitUntil(
        caches.keys().then(function (chaves) {
            return Promise.all(
                chaves.filter(function (c) { return c !== CACHE; })
                    .map(function (c) { return caches.delete(c); })
            );
        }).then(function () {
            return self.clients.claim();
        })
    );
});

self.addEventListener("fetch", function (event) {
    var req = event.request;
    if (req.method !== "GET") return;

    var url = new URL(req.url);
    if (url.origin !== self.location.origin) return;

    // Estáticos: cache-first.
    if (url.pathname.startsWith("/static/")) {
        event.respondWith(
            caches.match(req).then(function (hit) {
                return hit || fetch(req).then(function (resp) {
                    var copia = resp.clone();
                    caches.open(CACHE).then(function (cache) { cache.put(req, copia); });
                    return resp;
                });
            })
        );
        return;
    }

    // Navegações (páginas): network-first, cai para o cache offline.
    if (req.mode === "navigate") {
        event.respondWith(
            fetch(req).then(function (resp) {
                var copia = resp.clone();
                caches.open(CACHE).then(function (cache) { cache.put(req, copia); });
                return resp;
            }).catch(function () {
                return caches.match(req).then(function (hit) {
                    return hit || caches.match("/");
                });
            })
        );
    }
});
