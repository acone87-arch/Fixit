// Durable repair queue for Fixit Pulse. It deliberately preserves the existing
// IndexedDB database/stores so pending entries from retired /tech clients can
// still be synchronized rather than lost.
(function (root) {
  const DB_NAME = 'fixit-tech-db';
  const DB_VERSION = 2;
  let dbPromise;
  let configured = false;

  function uuid() {
    if (root.crypto?.randomUUID) return root.crypto.randomUUID();
    const bytes = new Uint8Array(16);
    root.crypto?.getRandomValues?.(bytes);
    for (let index = 0; index < bytes.length; index += 1) if (!bytes[index]) bytes[index] = Math.floor(Math.random() * 256);
    bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
    const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }

  function open() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains('kv')) db.createObjectStore('kv');
        if (!db.objectStoreNames.contains('tasks')) db.createObjectStore('tasks', { keyPath: 'id' });
        if (!db.objectStoreNames.contains('equipment')) db.createObjectStore('equipment', { keyPath: 'id' });
        if (!db.objectStoreNames.contains('stock')) db.createObjectStore('stock', { keyPath: 'part_id' });
        if (!db.objectStoreNames.contains('pendingRepairs')) db.createObjectStore('pendingRepairs', { keyPath: 'local_uuid' });
        if (!db.objectStoreNames.contains('pendingAttachments')) db.createObjectStore('pendingAttachments', { keyPath: 'id' });
      };
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    return dbPromise;
  }
  async function store(name, mode) { return (await open()).transaction(name, mode).objectStore(name); }
  function wrap(request) { return new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); }); }
  const db = {
    getAll: async (name) => wrap((await store(name, 'readonly')).getAll()),
    put: async (name, item) => wrap((await store(name, 'readwrite')).put(item)),
    delete: async (name, key) => wrap((await store(name, 'readwrite')).delete(key)),
    kvGet: async (key) => wrap((await store('kv', 'readonly')).get(key)),
    kvSet: async (key, value) => wrap((await store('kv', 'readwrite')).put(value, key)),
    kvDelete: async (key) => wrap((await store('kv', 'readwrite')).delete(key)),
  };

  async function uploadAttachment(token, attachment) {
    const blob = attachment.file instanceof Blob ? attachment.file : null;
    if (!(blob instanceof Blob) || !blob.size) throw new Error('Сохранённое фото повреждено');
    const form = new FormData();
    form.append('kind', attachment.kind || 'after');
    form.append('file', blob, attachment.file_name || `${attachment.kind || 'photo'}.jpg`);
    // This survives a timeout after the server has accepted the file: retrying
    // the same durable queue item must not create a second RepairAttachment.
    form.append('client_id', attachment.id);
    const response = await fetch(`/api/repairs/${attachment.repair_id}/attachments`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: form });
    if (!response.ok) {
      let detail = '';
      try {
        const body = await response.json();
        detail = typeof body?.detail === 'string' ? body.detail : JSON.stringify(body?.detail || '');
      } catch (_) { /* A proxy or old server may return a non-JSON error page. */ }
      const message = `${response.status || 'Ошибка'}: ${detail || 'Не удалось загрузить фото'}`;
      console.error('[FixitOffline] attachment upload failed', {
        repairId: attachment.repair_id, attachmentId: attachment.id, status: response.status, detail,
      });
      throw new Error(message);
    }
  }

  async function queueStatus(filter = null) {
    const localUuid = typeof filter === 'string' ? filter : filter?.localUuid || null;
    const serviceRequestId = typeof filter === 'object' ? filter?.serviceRequestId || null : null;
    const [repairs, attachments] = await Promise.all([db.getAll('pendingRepairs'), db.getAll('pendingAttachments')]);
    const matches = (item) => !localUuid && !serviceRequestId || (localUuid && item.local_uuid === localUuid) || (serviceRequestId && item.service_request_id === serviceRequestId);
    const pendingRepairs = repairs.filter(matches);
    const pendingAttachments = attachments.filter(matches);
    return {
      repairPending: pendingRepairs.length > 0,
      attachmentsPending: pendingAttachments.length,
      fullySynced: pendingRepairs.length === 0 && pendingAttachments.length === 0,
      repairId: pendingAttachments.find((item) => item.repair_id)?.repair_id || null,
      localUuid: pendingRepairs[0]?.local_uuid || pendingAttachments[0]?.local_uuid || null,
    };
  }

  function announce(summary) {
    if (typeof window !== 'undefined' && typeof window.CustomEvent === 'function') {
      window.dispatchEvent(new CustomEvent('fixit-offline-sync', { detail: summary }));
    }
  }

  async function sync({ token, deviceId = 'fixit-pulse', onError } = {}) {
    token ||= await db.kvGet('token');
    const results = new Map();
    if (!token || (typeof navigator !== 'undefined' && !navigator.onLine)) {
      return { results, status: await queueStatus() };
    }
    try {
      const repairs = await db.getAll('pendingRepairs');
      if (repairs.length) {
        const response = await fetch('/api/v1/sync/repairs', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ device_id: deviceId, repairs }) });
        if (!response.ok) throw new Error('Не удалось синхронизировать ремонт');
        const body = await response.json();
        for (const result of body.results || []) {
          results.set(result.local_uuid, result);
          if (result.resolved_as === 'failed') continue;
          const attachments = await db.getAll('pendingAttachments');
          for (const attachment of attachments.filter((item) => item.local_uuid === result.local_uuid)) {
            attachment.repair_id = result.server_id;
            await db.put('pendingAttachments', attachment);
          }
          await db.delete('pendingRepairs', result.local_uuid);
        }
      }
      const attachments = await db.getAll('pendingAttachments');
      for (const attachment of attachments) {
        if (!attachment.repair_id) continue;
        try { await uploadAttachment(token, attachment); await db.delete('pendingAttachments', attachment.id); }
        catch (error) { onError?.(error, attachment); }
      }
      if ((await db.getAll('pendingRepairs')).length || (await db.getAll('pendingAttachments')).length) registerBackgroundSync();
    } catch (error) { onError?.(error); }
    const summary = { results, status: await queueStatus() };
    announce(summary);
    return summary;
  }

  async function enqueueRepair(repair, photos = []) {
    const local_uuid = repair.local_uuid || uuid();
    await db.put('pendingRepairs', { ...repair, local_uuid });
    for (const [index, photo] of photos.entries()) {
      if (!(photo?.file instanceof Blob) || !photo.file.size) continue;
      await db.put('pendingAttachments', { id: `${local_uuid}:${index}:${uuid()}`, local_uuid, service_request_id: repair.service_request_id || null, repair_id: null, kind: photo.kind || 'after', file: photo.file, file_name: photo.file.name || `photo-${index + 1}.jpg` });
    }
    await registerBackgroundSync();
    return local_uuid;
  }

  async function registerBackgroundSync() {
    if (typeof navigator === 'undefined' || !navigator.serviceWorker) return;
    try {
      const registration = await navigator.serviceWorker.register('/sw.js?v=20260904-4', { scope: '/' });
      if ('sync' in registration) await registration.sync.register('fixit-sync-repairs');
    } catch (_) { /* online retry remains available */ }
  }
  function configure({ token } = {}) {
    // Never replace a usable background-sync credential with an empty value.
    if (typeof token === 'string' && token) db.kvSet('token', token);
    if (!configured && typeof window !== 'undefined') {
      configured = true;
      window.addEventListener('online', () => sync({ token: null }));
    }
  }

  root.FixitOffline = { db, uuid, configure, enqueueRepair, sync, queueStatus, registerBackgroundSync };
})(typeof self !== 'undefined' ? self : window);
