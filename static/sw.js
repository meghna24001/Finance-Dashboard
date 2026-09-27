/* Service worker — kept only so the app can be installed (PWA).
 * Offline caching and page saving have been removed; the app requires an internet connection.
 */
const VERSION = "v5";
const STATIC = `finance-static-${VERSION}`;

const PRECACHE = [
  "/static/css/style.css",
  "/static/js/forms.js",
  "/static/js/dashboard.js",
  "/static/js/pwa.js",
  "/static/js/vendor/chart.umd.min.js",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/icon-maskable-512.png",
  "/static/icons/apple-touch-icon.png",
  "/static/icons/favicon-32.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(STATIC)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  // Remove caches left behind by older versions.
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          names
            .filter((n) => n.startsWith("finance-") && n !== STATIC)
            .map((n) => caches.delete(n))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Static assets: serve from network, fall back to cache when offline.
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            caches.open(STATIC).then((cache) => cache.put(request, response.clone()));
          }
          return response;
        })
        .catch(() => caches.match(request).then((saved) => saved || Response.error()))
    );
  }
  // All other requests (pages, API calls) go straight to the network — no offline fallback.
});
