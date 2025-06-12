const CACHE_NAME = "rob-cache-v1";

const urlsToCache = [
  "/", "/dashboard", "/transactions", "/products", "/users",
  "/report", "/add_customer", "/record_sale", "/my_inventory",
  "/request_stock", "/review_requests", "/repayments",
  "/record_expense", "/view_expenses", "/offline.html",
  "/static/styles.css", "/static/logo.png",
  "/static/icons/icon-192.png", "/static/icons/icon-512.png",
  "/static/js/db.js"
];

// Install event – cache app shell
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      console.log("✅ Caching static assets");
      return cache.addAll(urlsToCache);
    })
  );
});

// Activate event – clean up old caches
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(cacheNames =>
      Promise.all(
        cacheNames.map(name => {
          if (name !== CACHE_NAME) {
            console.log("🗑️ Deleting old cache:", name);
            return caches.delete(name);
          }
        })
      )
    )
  );
});

// Fetch event – cache first, fallback to network or offline.html
self.addEventListener("fetch", event => {
  event.respondWith(
    caches.match(event.request).then(response => {
      // Return cached response if available
      return response || fetch(event.request);
    }).catch(() => {
      // If both cache and network fail, fallback to offline page
      return caches.match("/static/offline.html");
    })
  );
});
