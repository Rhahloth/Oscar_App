const CACHE_NAME = "rob-cache-v1";
const OFFLINE_URL = "/static/offline.html";

// ✅ List all essential static assets and fallback pages
const urlsToCache = [
  "/", // Home redirect
  "/static/styles.css",
  "/static/logo.png",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/js/db.js",
  "/static/offline.html",
  "/static/offline_sales_form.html",  // ✅ Offline fallback sales
];

// ✅ On install: pre-cache everything
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      console.log("✅ Caching essential assets...");
      return cache.addAll(urlsToCache);
    })
  );
  self.skipWaiting();
});

// ✅ On activate: clean old caches
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

// ✅ On fetch: fallback strategy for pages + static assets
self.addEventListener("fetch", event => {
  if (event.request.mode === "navigate") {
    // Page requests (like /record_sale)
    event.respondWith(
      fetch(event.request).catch(() => {
        console.warn("⚠️ Offline page served:", event.request.url);
        return caches.match(OFFLINE_URL);
      })
    );
  } else {
    // Static asset requests (CSS, JS, icons)
    event.respondWith(
      caches.match(event.request).then(response => {
        return response || fetch(event.request);
      })
    );
  }
});
