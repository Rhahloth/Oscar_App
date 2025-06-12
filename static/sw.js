const CACHE_NAME = "rob-cache-v2";
const OFFLINE_URL = "/static/offline.html";
const OFFLINE_SALES_FORM_URL = "/static/offline_sales_form.html";

const urlsToCache = [
  "/",
  "/record_sale",
  "/static/styles.css",
  "/static/logo.png",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/js/db.js",
  OFFLINE_SALES_FORM_URL,
  OFFLINE_URL,
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
        keys
          .filter(key => key !== CACHE_NAME)
          .map(key => {
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
    console.log("📡 Navigating:", request.url);

    // ✅ Explicitly serve the offline sales form from cache if it's requested
    if (request.url.endsWith("/static/offline_sales_form.html")) {
      event.respondWith(
        caches.match(OFFLINE_SALES_FORM_URL).then(res => {
          return res || fetch(request).catch(() => caches.match(OFFLINE_URL));
        })
      );
      return;
    }

    // ✅ Default fallback to offline.html
    event.respondWith(
      fetch(request).catch(() => {
        console.warn("⚠️ Offline fallback triggered for:", request.url);
        return caches.match(OFFLINE_URL);
      })
    );
  } else {
    // For static assets
    event.respondWith(
      caches.match(request).then(cachedResponse => {
        if (cachedResponse) {
          console.log("📁 Serving from cache:", request.url);
        }
        return cachedResponse || fetch(request);
      })
    );
  }
});
