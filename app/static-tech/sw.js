// ============================================================
// Service worker PWA техника.
// Две задачи: (1) кэш app shell, чтобы приложение открывалось без сети,
// (2) Background Sync — отправка накопленных офлайн-ремонтов в фоне,
// даже если вкладка/приложение закрыты (см. п.3.2 ТЗ: "отложенная отправка").
// ============================================================

const CACHE_NAME = 'fixit-tech-shell-v10';
const SHELL_FILES = [
  '/tech/',
  '/tech/index.html',
  '/tech/styles.css',
  '/tech/app.js?v=20260829-2',
  '/tech/db.js?v=20260828-8',
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

  try {
    if (pending.length) {
      let deviceId = await self.TechDB.kvGet('deviceId');
      if (!deviceId) { deviceId = createUuid(); await self.TechDB.kvSet('deviceId', deviceId); }
      const res = await fetch('/api/v1/sync/repairs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ device_id: deviceId, repairs: pending.map(({ _equipmentName, ...rest }) => rest) }),
      });
      if (!res.ok) return; // оба набора остаются в очереди, попробуем позже
      const data = await res.json();
      for (const r of data.results) {
        if (r.resolved_as !== 'failed') {
          const attachments = await self.TechDB.getAll('pendingAttachments');
          for (const attachment of attachments.filter((item) => item.local_uuid === r.local_uuid)) {
            attachment.repair_id = r.server_id;
            await self.TechDB.put('pendingAttachments', attachment);
          }
          await self.TechDB.delete('pendingRepairs', r.local_uuid);
        }
      }
    }
    await syncPendingAttachmentsFromSW(token);
  } catch (_) {
    // Нет сети прямо сейчас — Background Sync API сам повторит попытку позже.
  }
}

async function syncPendingAttachmentsFromSW(token) {
  const attachments = await self.TechDB.getAll('pendingAttachments');
  for (const attachment of attachments) {
    if (!attachment.repair_id) continue;
    try {
      let blob = attachment.file instanceof Blob ? attachment.file : null;
      if (!blob && attachment.data_url) {
        const source = await fetch(attachment.data_url);
        if (!source.ok) throw new Error('attachment data is unavailable');
        blob = await source.blob();
      }
      if (!(blob instanceof Blob) || !blob.size) throw new Error('attachment is empty');
      const form = new FormData();
      form.append('kind', attachment.kind || 'after');
      form.append('file', blob, attachment.file_name || `${attachment.kind || 'attachment'}.jpg`);
      const response = await fetch(`/api/repairs/${attachment.repair_id}/attachments`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: form,
      });
      if (!response.ok) throw new Error('upload failed');
      await self.TechDB.delete('pendingAttachments', attachment.id);
    } catch (_) {
      // Delete only a confirmed upload. The next Background Sync will retry this item.
    }
  }
}
