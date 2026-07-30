// ============================================================
// IndexedDB-слой PWA техника.
// Подключается и через <script> на странице, и через importScripts()
// в service worker — поэтому без ES-модулей, всё в один глобальный объект TechDB.
// ============================================================

const TechDB = (() => {
  const DB_NAME = 'fixit-tech-db';
  const DB_VERSION = 1;
  let dbPromise = null;

  function open() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains('kv')) db.createObjectStore('kv');
        if (!db.objectStoreNames.contains('tasks')) db.createObjectStore('tasks', { keyPath: 'id' });
        if (!db.objectStoreNames.contains('equipment')) db.createObjectStore('equipment', { keyPath: 'id' });
        if (!db.objectStoreNames.contains('stock')) db.createObjectStore('stock', { keyPath: 'part_id' });
        if (!db.objectStoreNames.contains('pendingRepairs')) db.createObjectStore('pendingRepairs', { keyPath: 'local_uuid' });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    return dbPromise;
  }

  async function tx(storeName, mode) {
    const db = await open();
    return db.transaction(storeName, mode).objectStore(storeName);
  }

  function wrap(request) {
    return new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  return {
    // --- kv (одиночные значения: токен, профиль техника) ---
    async kvGet(key) { return wrap((await tx('kv', 'readonly')).get(key)); },
    async kvSet(key, value) { const s = await tx('kv', 'readwrite'); return wrap(s.put(value, key)); },
    async kvDelete(key) { const s = await tx('kv', 'readwrite'); return wrap(s.delete(key)); },

    // --- generic collection helpers (tasks / equipment / stock) ---
    async putAll(storeName, items) {
      const s = await tx(storeName, 'readwrite');
      await Promise.all(items.map((item) => wrap(s.put(item))));
    },
    async put(storeName, item) {
      const s = await tx(storeName, 'readwrite');
      return wrap(s.put(item));
    },
    async getAll(storeName) {
      return wrap((await tx(storeName, 'readonly')).getAll());
    },
    async get(storeName, key) {
      return wrap((await tx(storeName, 'readonly')).get(key));
    },
    async clear(storeName) {
      const s = await tx(storeName, 'readwrite');
      return wrap(s.clear());
    },
    async delete(storeName, key) {
      const s = await tx(storeName, 'readwrite');
      return wrap(s.delete(key));
    },
  };
})();

// В service worker `self` есть, `window` нет — экспортируем в глобальную область в обоих случаях.
if (typeof self !== 'undefined') self.TechDB = TechDB;
