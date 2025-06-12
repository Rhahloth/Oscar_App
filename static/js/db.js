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
    console.log("IndexedDB ready");
    if (navigator.onLine) {
      uploadPendingSales();
      uploadPendingExpenses();
      uploadPendingRepayments();
    }
  };

  request.onerror = function (event) {
    console.error("IndexedDB error:", event.target.errorCode);
  };
}

// Save functions
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

// Upload functions
function uploadPendingSales() {
  const tx = db.transaction("unsynced_sales", "readonly");
  tx.objectStore("unsynced_sales").getAll().onsuccess = function (event) {
    const data = event.target.result;
    if (data.length > 0) {
      fetch("/upload_offline_sales", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      }).then(res => {
        if (res.ok) {
          const tx = db.transaction("unsynced_sales", "readwrite");
          tx.objectStore("unsynced_sales").clear();
        }
      });
    }
  };
}

function uploadPendingExpenses() {
  const tx = db.transaction("unsynced_expenses", "readonly");
  tx.objectStore("unsynced_expenses").getAll().onsuccess = function (event) {
    const data = event.target.result;
    if (data.length > 0) {
      fetch("/upload_offline_expenses", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      }).then(res => {
        if (res.ok) {
          const tx = db.transaction("unsynced_expenses", "readwrite");
          tx.objectStore("unsynced_expenses").clear();
        }
      });
    }
  };
}

function uploadPendingRepayments() {
  const tx = db.transaction("unsynced_repayments", "readonly");
  tx.objectStore("unsynced_repayments").getAll().onsuccess = function (event) {
    const data = event.target.result;
    if (data.length > 0) {
      fetch("/upload_offline_repayments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      }).then(res => {
        if (res.ok) {
          const tx = db.transaction("unsynced_repayments", "readwrite");
          tx.objectStore("unsynced_repayments").clear();
        }
      });
    }
  };
}

window.addEventListener("online", () => {
  uploadPendingSales();
  uploadPendingExpenses();
  uploadPendingRepayments();
});
