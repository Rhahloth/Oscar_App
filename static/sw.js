const CACHE_NAME = "rob-cache-v3";
const OFFLINE_URL = "/offline"; // Use Flask route, not static path
const OFFLINE_SALES_FORM_URL = "/offline_sales_form"; // Also use route

const urlsToCache = [
  "/",                     // Main entry
  "/record_sale",          // Sales form
  "/offline",              // Offline fallback route (Flask-served)
  "/offline_sales_form",   // Offline POS form (Flask-served)
  "/static/styles.css",
  "/static/logo.png",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/js/db.js"
];

self.addEventListener("install", event => {
  console.log("📦 Installing service worker...");
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      console.log("✅ Caching assets...");
      return cache.addAll(urlsToCache);
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  console.log("⚙️ Activating new service worker...");
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(key => key !== CACHE_NAME).map(key => {
          console.log("🗑️ Deleting old cache:", key);
          return caches.delete(key);
        })
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  const { request } = event;

  if (request.mode === "navigate") {
    const url = new URL(request.url);

    if (url.pathname === OFFLINE_SALES_FORM_URL) {
      console.log("🛒 Navigating to offline sales form");
      event.respondWith(
        caches.match(OFFLINE_SALES_FORM_URL).then(res => {
          return res || fetch(request).catch(() => caches.match(OFFLINE_URL));
        })
      );
    } else {
      console.log("📡 Navigating to:", request.url);
      event.respondWith(
        fetch(request).catch(() => {
          console.warn("⚠️ Fallback to offline page");
          return caches.match(OFFLINE_URL);
        })
      );
    }
  } else {
    // Static or API requests
    event.respondWith(
      caches.match(request).then(cachedResponse => {
        if (cachedResponse) {
          console.log("📁 Serving cached:", request.url);
        }
        return cachedResponse || fetch(request);
      })
    );
  }
});
