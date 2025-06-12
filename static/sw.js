const CACHE_NAME = "rob-cache-v1";
const OFFLINE_URL = "/static/offline.html";
const OFFLINE_SALES_FORM = "/static/offline_sales_form.html";

// ✅ Cache only sales-related assets
const urlsToCache = [
  "/", // Home route
  "/record_sale", // This will be replaced by offline form if offline
  "/static/styles.css",
  "/static/logo.png",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/js/db.js",
  OFFLINE_URL,
  OFFLINE_SALES_FORM
];

// ✅ Cache assets on install
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      console.log("✅ Caching core sales assets...");
      return cache.addAll(urlsToCache);
    })
  );
  self.skipWaiting();
});

// ✅ Remove old cache on activate
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(key => key !== CACHE_NAME).map(key => {
          console.log("🧹 Clearing old cache:", key);
          return caches.delete(key);
        })
      )
    )
  );
  self.clients.claim();
});

// ✅ Handle fetch: fallback to offline form for /record_sale
self.addEventListener("fetch", event => {
  if (event.request.mode === "navigate") {
    const requestURL = new URL(event.request.url);

    // If it's /record_sale and offline, serve offline sales form
    if (requestURL.pathname === "/record_sale") {
      event.respondWith(
        fetch(event.request).catch(() => {
          console.warn("📉 Offline fallback: /record_sale → offline_sales_form.html");
          return caches.match(OFFLINE_SALES_FORM);
        })
      );
    } else {
      // Generic offline fallback
      event.respondWith(
        fetch(event.request).catch(() => {
          console.warn("⚠️ Offline fallback: general navigation");
          return caches.match(OFFLINE_URL);
        })
      );
    }
  } else {
    // Static assets
    event.respondWith(
      caches.match(event.request).then(response => response || fetch(event.request))
    );
  }
});
