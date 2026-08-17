// ============================================================
// Service worker PWA техника.
// Две задачи: (1) кэш app shell, чтобы приложение открывалось без сети,
// (2) Background Sync — отправка накопленных офлайн-ремонтов в фоне,
// даже если вкладка/приложение закрыты (см. п.3.2 ТЗ: "отложенная отправка").
// ============================================================

const CACHE_NAME = 'fixit-tech-shell-v3';
const SHELL_FILES = [
  '/tech/',
  '/tech/index.html',
  '/tech/styles.css',
  '/tech/app.js?v=20260817-3',
  '/tech/db.js?v=20260817-3',
  '/tech/manifest.json',
  '/tech/icon-192.png',
  '/tech/icon-512.png',
];

self.importScripts('/tech/db.js');

function createUuid() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Сеть сначала для файлов оболочки приложения: иначе кэш может удерживать старую
// версию после выпуска. При отсутствии связи берём последнюю сохранённую копию.
// Запросы к /api/* всегда идут в сеть напрямую — офлайн-данные для них
// обслуживает IndexedDB на уровне app.js, а не service worker.
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || !url.pathname.startsWith('/tech/')) return;
  if (url.pathname.startsWith('/api/')) return;

  event.respondWith(
    fetch(event.request).then((res) => {
      const copy = res.clone();
      caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
      return res;
    }).catch(() => caches.match(event.request))
  );
});

// ---------- Background Sync ----------

self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-repairs') {
    event.waitUntil(syncPendingRepairsFromSW());
  }
});

async function syncPendingRepairsFromSW() {
  const token = await self.TechDB.kvGet('token');
  if (!token) return;
  const pending = await self.TechDB.getAll('pendingRepairs');
  if (!pending.length) return;

  let deviceId = await self.TechDB.kvGet('deviceId');
  if (!deviceId) { deviceId = createUuid(); await self.TechDB.kvSet('deviceId', deviceId); }

  try {
    const res = await fetch('/api/v1/sync/repairs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ device_id: deviceId, repairs: pending.map(({ _equipmentName, ...rest }) => rest) }),
    });
    if (!res.ok) return; // остаётся в очереди, попробуем на следующий sync-триггер
    const data = await res.json();
    for (const r of data.results) {
      if (r.resolved_as !== 'failed') await self.TechDB.delete('pendingRepairs', r.local_uuid);
    }
  } catch (_) {
    // Нет сети прямо сейчас — Background Sync API сам повторит попытку позже.
  }
}
