const CACHE_NAME = "rob-cache-v1";

const urlsToCache = [
  "/", "/dashboard", "/transactions", "/products", "/users",
  "/report", "/add_customer", "/record_sale", "/my_inventory",
  "/request_stock", "/review_requests", "/repayments",
  "/record_expense", "/view_expenses",
  "/static/styles.css", "/static/logo.png",
  "/static/icons/icon-192.png", "/static/icons/icon-512.png",
  "/static/js/db.js"
];

// Install event
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(urlsToCache))
  );
});

// Activate event – clear old caches
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(cacheNames =>
      Promise.all(
        cacheNames.map(name => {
          if (name !== CACHE_NAME) return caches.delete(name);
        })
      )
    )
  );
});

// Fetch event – try cache first, fallback to network
self.addEventListener("fetch", event => {
  event.respondWith(
    caches.match(event.request).then(response =>
      response || fetch(event.request)
    ).catch(() => caches.match("/dashboard")) // Optional offline fallback
  );
});
