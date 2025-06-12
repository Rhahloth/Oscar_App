let db;

function initIndexedDB() {
  const request = indexedDB.open("rob_sales_db", 2);

  request.onupgradeneeded = function (event) {
    db = event.target.result;

    if (!db.objectStoreNames.contains("unsynced_sales")) {
      db.createObjectStore("unsynced_sales", { autoIncrement: true });
    }
    if (!db.objectStoreNames.contains("unsynced_expenses")) {
      db.createObjectStore("unsynced_expenses", { autoIncrement: true });
    }
    if (!db.objectStoreNames.contains("unsynced_repayments")) {
      db.createObjectStore("unsynced_repayments", { autoIncrement: true });
    }
  };

  request.onsuccess = function (event) {
    db = event.target.result;
    console.log("✅ IndexedDB initialized");

    if (navigator.onLine) {
      uploadPendingSales();
      uploadPendingExpenses();
      uploadPendingRepayments();
    }
  };

  request.onerror = function (event) {
    console.error("❌ IndexedDB error:", event.target.errorCode);
  };
}

// ======== SAVE FUNCTIONS ========

function saveSaleOffline(data) {
  const tx = db.transaction("unsynced_sales", "readwrite");
  tx.objectStore("unsynced_sales").add(data);
}

function saveExpenseOffline(data) {
  const tx = db.transaction("unsynced_expenses", "readwrite");
  tx.objectStore("unsynced_expenses").add(data);
}

function saveRepaymentOffline(data) {
  const tx = db.transaction("unsynced_repayments", "readwrite");
  tx.objectStore("unsynced_repayments").add(data);
}

// ======== UPLOAD FUNCTIONS ========

function uploadPendingSales() {
  const tx = db.transaction("unsynced_sales", "readonly");
  const store = tx.objectStore("unsynced_sales");

  store.getAll().onsuccess = function (event) {
    const data = event.target.result;

    if (data.length > 0) {
      console.log(`🔄 Uploading ${data.length} offline sales...`);

      fetch("/upload_offline_sales", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      })
        .then(res => {
          if (res.ok) {
            const txClear = db.transaction("unsynced_sales", "readwrite");
            txClear.objectStore("unsynced_sales").clear();
            console.log("✅ Offline sales uploaded and cleared.");
          } else {
            console.error("❌ Server rejected offline sales.");
          }
        })
        .catch(err => {
          console.error("⚠️ Failed to upload offline sales:", err);
        });
    }
  };
}

function uploadPendingExpenses() {
  const tx = db.transaction("unsynced_expenses", "readonly");
  const store = tx.objectStore("unsynced_expenses");

  store.getAll().onsuccess = function (event) {
    const data = event.target.result;

    if (data.length > 0) {
      console.log(`🔄 Uploading ${data.length} offline expenses...`);

      fetch("/upload_offline_expenses", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      })
        .then(res => {
          if (res.ok) {
            const txClear = db.transaction("unsynced_expenses", "readwrite");
            txClear.objectStore("unsynced_expenses").clear();
            console.log("✅ Offline expenses uploaded and cleared.");
          } else {
            console.error("❌ Server rejected offline expenses.");
          }
        })
        .catch(err => {
          console.error("⚠️ Failed to upload offline expenses:", err);
        });
    }
  };
}

function uploadPendingRepayments() {
  const tx = db.transaction("unsynced_repayments", "readonly");
  const store = tx.objectStore("unsynced_repayments");

  store.getAll().onsuccess = function (event) {
    const data = event.target.result;

    if (data.length > 0) {
      console.log(`🔄 Uploading ${data.length} offline repayments...`);

      fetch("/upload_offline_repayments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      })
        .then(res => {
          if (res.ok) {
            const txClear = db.transaction("unsynced_repayments", "readwrite");
            txClear.objectStore("unsynced_repayments").clear();
            console.log("✅ Offline repayments uploaded and cleared.");
          } else {
            console.error("❌ Server rejected offline repayments.");
          }
        })
        .catch(err => {
          console.error("⚠️ Failed to upload offline repayments:", err);
        });
    }
  };
}

// Automatically sync when back online
window.addEventListener("online", () => {
  console.log("📶 Back online — syncing offline data...");
  uploadPendingSales();
  uploadPendingExpenses();
  uploadPendingRepayments();
});
