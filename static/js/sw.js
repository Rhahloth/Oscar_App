const CACHE_NAME = "rob-cache-v1";

const urlsToCache = [
  "/",                         // Home
  "/dashboard",               // Dashboard (owner/salesperson)
  "/transactions",            // Transaction history
  "/products",                // Manage products
  "/users",                   // Manage branches
  "/report",                  // Sales report
  "/add_customer",           // Customer management
  "/record_sale",            // POS entry
  "/my_inventory",           // Salesperson's inventory
  "/request_stock",          // Stock request
  "/review_requests",        // Stock review
  "/repayments",             // Credit repayments
  "/record_expense",         // Record expenses
  "/view_expenses",          // Expense listing
  "/static/styles.css",
  "/static/logo.png",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/js/db.js"
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(urlsToCache);
    })
  );
});

self.addEventListener("fetch", event => {
  event.respondWith(
    caches.match(event.request).then(response => {
      return response || fetch(event.request);
    })
  );
});
