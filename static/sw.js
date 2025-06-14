const CACHE_NAME = "rob-cache-v3";
const OFFLINE_URL = "/offline";
const OFFLINE_SALES_FORM_URL = "/offline_sales_form";

// Pages or routes to exclude from caching (especially auth-sensitive)
const EXCLUDE_FROM_CACHE = ["/logout", "/login", "/register_owner"];

// Core assets to cache
const urlsToCache = [
  "/", // Entry point
  "/record_sale",
  "/offline",
  "/offline_sales_form",
  "/static/styles.css",
  "/static/logo.png",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png"
];

// Install event - pre-cache essential files
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

// Activate event - clean up old caches
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

// Fetch handler with exclusion logic
self.addEventListener("fetch", event => {
  const { request } = event;
  const url = new URL(request.url);

  // Do not cache or intercept auth-sensitive requests
  if (EXCLUDE_FROM_CACHE.includes(url.pathname)) {
    console.log("🚫 Skipping cache for:", url.pathname);
    return;
  }

  // Handle navigation requests (HTML pages)
  if (request.mode === "navigate") {
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
    // Static asset or API request
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
