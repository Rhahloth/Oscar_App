const CACHE_NAME = "rob-cache-v1";

// Only cache essentials for offline functionality
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
  "/static/offline.html"
];

// Install: cache necessary files
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      console.log("✅ Caching offline essentials...");
      return cache.addAll(urlsToCache);
    })
  );
});

// Activate: clean up old caches
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.map(key => {
          if (key !== CACHE_NAME) {
            console.log("🗑️ Deleting outdated cache:", key);
            return caches.delete(key);
          }
        })
      )
    )
  );
});

// Fetch: cache-first, fallback to offline page
self.addEventListener("fetch", event => {
  event.respondWith(
    caches.match(event.request).then(response => {
      return response || fetch(event.request);
    }).catch(() => {
      // Show offline page for navigation requests (HTML pages)
      if (event.request.mode === 'navigate') {
        return caches.match("/static/offline.html");
      }
    })
  );
});
