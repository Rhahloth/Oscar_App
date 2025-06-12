const CACHE_NAME = "rob-cache-v2";
const OFFLINE_URL = "/static/offline.html";

const urlsToCache = [
  "/",
  "/record_sale",
  "/static/styles.css",
  "/static/logo.png",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/js/db.js",
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
  if (event.request.mode === "navigate") {
    console.log("📡 Fetching (HTML):", event.request.url);
    event.respondWith(
      fetch(event.request).catch(() => {
        console.warn("⚠️ Offline fallback triggered for:", event.request.url);
        return caches.match(OFFLINE_URL);
      })
    );
  } else {
    event.respondWith(
      caches.match(event.request).then(res => {
        if (res) {
          console.log("📁 Serving from cache:", event.request.url);
        }
        return res || fetch(event.request);
      })
    );
  }
});