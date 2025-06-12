const CACHE_NAME = "rob-cache-v1";
const OFFLINE_URL = "/static/offline.html";

// ✅ List all assets you want to cache during install
const urlsToCache = [
  "/",
  "/record_sale",
  "/record_expense",
  "/repayments",
  "/static/styles.css",
  "/static/logo.png",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/js/db.js",
  OFFLINE_URL
];

// ✅ On install: cache app shell and offline page
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      console.log("✅ Caching essential assets...");
      return cache.addAll(urlsToCache);
    })
  );
  self.skipWaiting();
});

// ✅ On activate: delete any old cache versions
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(key => key !== CACHE_NAME).map(key => {
          console.log("🗑️ Removing old cache:", key);
          return caches.delete(key);
        })
      )
    )
  );
  self.clients.claim();
});

// ✅ On fetch: serve from cache, fall back to network, then offline.html
self.addEventListener("fetch", event => {
  if (event.request.mode === 'navigate') {
    // Handle navigation requests (HTML pages)
    event.respondWith(
      fetch(event.request).catch(() => {
        console.warn("⚠️ Offline fallback triggered");
        return caches.match(OFFLINE_URL);
      })
    );
  } else {
    // Handle static assets (CSS, JS, images)
    event.respondWith(
      caches.match(event.request).then(response => {
        return response || fetch(event.request);
      })
    );
  }
});
