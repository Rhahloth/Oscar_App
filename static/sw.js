const CACHE_NAME = "rob-cache-v1";

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

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      console.log("✅ Caching essential offline pages");
      return cache.addAll(urlsToCache);
    })
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(cacheNames =>
      Promise.all(
        cacheNames.map(name => {
          if (name !== CACHE_NAME) {
            console.log("🗑️ Removing old cache:", name);
            return caches.delete(name);
          }
        })
      )
    )
  );
});

self.addEventListener("fetch", event => {
  event.respondWith(
    caches.match(event.request).then(cachedResponse => {
      if (cachedResponse) return cachedResponse;
      return fetch(event.request).catch(() =>
        caches.match("/static/offline.html")
      );
    })
  );
});
