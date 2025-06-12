const CACHE_NAME = "rob-cache-v1";
const OFFLINE_URL = "/static/offline.html";
const OFFLINE_SALES_FORM = "/static/offline_sales_form.html";

const urlsToCache = [
  "/", // Main route
  "/static/styles.css",
  "/static/logo.png",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/js/db.js",
  OFFLINE_URL,
  OFFLINE_SALES_FORM,  // ✅ Offline sales form only
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      console.log("✅ Caching sales-related assets...");
      return cache.addAll(urlsToCache);
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(() => {
        return caches.match(OFFLINE_URL);
      })
    );
  } else {
    event.respondWith(
      caches.match(event.request).then(res => res || fetch(event.request))
    );
  }
});
