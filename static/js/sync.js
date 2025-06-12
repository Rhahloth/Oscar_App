// sync.js — Automatically upload offline sales when back online

window.addEventListener("load", () => {
    if (navigator.onLine) {
      trySyncOfflineSales();
    }
  });
  
  window.addEventListener("online", () => {
    console.log("📶 Back online. Trying to sync offline sales...");
    trySyncOfflineSales();
  });
  
  function trySyncOfflineSales() {
    const offlineSales = localStorage.getItem("offline_sales");
    if (!offlineSales) {
      console.log("✅ No offline sales to sync.");
      return;
    }
  
    const parsedSales = JSON.parse(offlineSales);
    if (!Array.isArray(parsedSales) || !parsedSales.length) return;
  
    fetch("/upload_offline_sales", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(parsedSales)
    })
      .then(res => {
        if (!res.ok) throw new Error("Server rejected sync.");
        return res.json();
      })
      .then(data => {
        console.log("✅ Offline sales synced:", data);
        alert("✅ Your offline sales have been synced.");
        localStorage.removeItem("offline_sales");
      })
      .catch(err => {
        console.warn("❌ Sync failed:", err);
      });
  }
  