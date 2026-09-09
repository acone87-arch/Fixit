// Shared by Pulse, legacy /tech and service workers. Keep v2 stores/payloads.
// Ownership/error fields are additive; unowned history is never auto-claimed.
(function (root) {
  const DB_NAME = 'fixit-tech-db', DB_VERSION = 2, LOCK = 'fixit-repair-queue';
  let dbPromise, configured = false, pageToken;
  function uuid() {
    if (root.crypto?.randomUUID) return root.crypto.randomUUID();
    const bytes = root.crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
    const hex = [...bytes].map(byte => byte.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  function open() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const database = request.result;
        for (const [name, keyPath] of [['kv', null], ['tasks', 'id'], ['equipment', 'id'], ['stock', 'part_id'], ['pendingRepairs', 'local_uuid'], ['pendingAttachments', 'id']]) {
          if (!database.objectStoreNames.contains(name)) database.createObjectStore(name, keyPath ? { keyPath } : undefined);
        }
      };
      request.onsuccess = () => {
        request.result.onversionchange = () => { request.result.close(); dbPromise = null; };
        resolve(request.result);
      };
      request.onerror = () => { dbPromise = null; reject(request.error); };
      request.onblocked = () => { dbPromise = null; reject(new Error('Закройте старые вкладки Fixit и повторите сохранение')); };
    });
    return dbPromise;
  }
  // Schedule requests synchronously or in IDB callbacks. A successful request
  // is not durability: resolve only after the complete transaction commits.
  async function transaction(names, mode, action) {
    const database = await open();
    return new Promise((resolve, reject) => {
      const tx = database.transaction(names, mode);
      let result, failure;
      tx.oncomplete = () => resolve(result?.result);
      tx.onabort = () => reject(failure || tx.error || new Error('Сохранение отменено; данные не записаны'));
      tx.onerror = () => { failure ||= tx.error; };
      try { result = action(tx); } catch (error) { failure = error; tx.abort(); }
    });
  }
  const one = (name, mode, action) => transaction(name, mode, tx => action(tx.objectStore(name)));
  const db = {
    getAll: name => one(name, 'readonly', s => s.getAll()),
    get: (name, key) => one(name, 'readonly', s => s.get(key)),
    put: (name, item) => one(name, 'readwrite', s => s.put(item)),
    putAll: (name, items) => one(name, 'readwrite', s => { for (const item of items) s.put(item); }),
    delete: (name, key) => one(name, 'readwrite', s => s.delete(key)),
    clear: name => one(name, 'readwrite', s => s.clear()),
    kvGet: key => one('kv', 'readonly', s => s.get(key)),
    kvSet: (key, value) => one('kv', 'readwrite', s => s.put(value, key)),
    kvDelete: key => one('kv', 'readwrite', s => s.delete(key)),
  };
  function identity(token) {
    try {
      const encoded = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      const value = JSON.parse(atob(encoded));
      return value.sub && value.org ? { user: value.sub, org: value.org, exp: value.exp } : null;
    } catch (_) { return null; }
  }
  const owns = (item, owner) => Boolean(owner && item.queue_owner?.user === owner.user && item.queue_owner?.org === owner.org);
  async function exclusive(action) {
    // Released by the browser on tab death/worker termination. Never substitute
    // a per-tab boolean or an expiring lease while a network request is alive.
    if (!root.navigator?.locks) throw new Error('Для безопасной отправки обновите браузер и откройте Fixit по HTTPS. Очередь сохранена.');
    return root.navigator.locks.request(LOCK, action);
  }
  async function activeToken(explicit) {
    if (pageToken === null) throw new Error('Выполнен выход. Войдите владельцем очереди.');
    const saved = await db.kvGet('token');
    const expected = explicit || pageToken;
    if (!saved || (expected && expected !== saved)) throw new Error('Аккаунт изменился или выполнен выход. Войдите владельцем очереди.');
    if (!identity(saved)) throw new Error('Не удалось определить владельца. Войдите заново.');
    return saved;
  }
  async function snapshot() {
    let repairs, attachments;
    await transaction(['pendingRepairs', 'pendingAttachments'], 'readonly', tx => {
      tx.objectStore('pendingRepairs').getAll().onsuccess = e => { repairs = e.target.result; };
      tx.objectStore('pendingAttachments').getAll().onsuccess = e => { attachments = e.target.result; };
    });
    return { repairs, attachments };
  }
  async function queueStatus(filter = null) {
    const owner = identity(pageToken === undefined ? await db.kvGet('token') : pageToken);
    const localUuid = typeof filter === 'string' ? filter : filter?.localUuid;
    const serviceRequestId = typeof filter === 'object' ? filter?.serviceRequestId : null;
    const all = await snapshot();
    const matches = item => owns(item, owner) && ((!localUuid && !serviceRequestId) || (localUuid && item.local_uuid === localUuid) || (serviceRequestId && item.service_request_id === serviceRequestId));
    const repairs = all.repairs.filter(matches), attachments = all.attachments.filter(matches);
    return {
      repairPending: repairs.length > 0, attachmentsPending: attachments.length,
      fullySynced: repairs.length === 0 && attachments.length === 0,
      repairId: attachments.find(item => item.repair_id)?.repair_id || null,
      localUuid: repairs[0]?.local_uuid || attachments[0]?.local_uuid || null,
      errors: [...new Set([...repairs, ...attachments].map(item => item.queue_error).filter(Boolean))],
      unownedCount: [...all.repairs, ...all.attachments].filter(item => !item.queue_owner).length,
    };
  }
  async function photoBlob(photo) {
    if (photo.file instanceof Blob && photo.file.size) return photo.file;
    // Decode locally; legacy data_url must never become an arbitrary network URL.
    if (typeof photo.data_url === 'string' && /^data:[^,]*;base64,/.test(photo.data_url)) {
      const [header, data] = photo.data_url.split(',');
      const blob = new Blob([Uint8Array.from(atob(data), c => c.charCodeAt(0))], { type: header.slice(5).split(';')[0] });
      if (blob.size) return blob;
    }
    throw new Error('Сохранённое фото повреждено. Исходная запись оставлена на устройстве.');
  }
  async function responseError(response, fallback) {
    let detail;
    try { const body = await response.json(); detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail); } catch (_) {}
    return new Error(`${response.status || 'Ошибка'}: ${detail || fallback}${response.status === 401 ? ' Войдите заново тем же аккаунтом.' : ''}`);
  }
  async function request(url, options) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);
    try { return await fetch(url, { ...options, signal: controller.signal }); }
    finally { clearTimeout(timeout); }
  }
  async function uploadAttachment(token, attachment) {
    const blob = await photoBlob(attachment);
    const form = new FormData();
    form.append('kind', attachment.kind || 'after');
    form.append('file', blob, attachment.file_name || 'photo.jpg');
    form.append('client_id', attachment.id);
    const response = await request(`/api/repairs/${attachment.repair_id}/attachments`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: form });
    if (!response.ok) {
      const error = await responseError(response, 'Не удалось загрузить фото');
      console.error('[FixitOffline] attachment upload failed', { repairId: attachment.repair_id, attachmentId: attachment.id, status: response.status, detail: error.message });
      throw error;
    }
  }
  const receiptKey = id => `queue-receipt:${id}`;
  async function acknowledge(repair, result) {
    await transaction(['kv', 'pendingRepairs', 'pendingAttachments'], 'readwrite', tx => {
      const attachments = tx.objectStore('pendingAttachments');
      attachments.getAll().onsuccess = e => {
        for (const item of e.target.result) {
          if (item.local_uuid === repair.local_uuid && owns(item, repair.queue_owner)) attachments.put({ ...item, repair_id: result.server_id, queue_error: null });
        }
        tx.objectStore('kv').put({ ...result, queue_owner: repair.queue_owner }, receiptKey(repair.local_uuid));
        tx.objectStore('pendingRepairs').delete(repair.local_uuid);
      };
    });
  }
  async function sync({ token, deviceId = 'fixit-pulse', onError } = {}) {
    const results = new Map();
    let syncError;
    try {
      await exclusive(async () => {
        token = await activeToken(token);
        const owner = identity(token);
        if (root.navigator?.onLine === false) return;
        const expired = owner.exp && owner.exp * 1000 <= Date.now();
        const repairs = (await db.getAll('pendingRepairs')).filter(item => owns(item, owner));
        for (const repair of repairs) {
          try {
            if (expired) throw new Error('Сессия истекла. Войдите заново тем же аккаунтом.');
            const { queue_owner, queue_error, _equipmentName, ...payload } = repair;
            const response = await request('/api/v1/sync/repairs', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ device_id: deviceId, repairs: [payload] }) });
            if (!response.ok) throw await responseError(response, 'Не удалось отправить ремонт');
            const body = await response.json();
            const result = body.results?.find(item => item.local_uuid === repair.local_uuid);
            if (result) results.set(repair.local_uuid, result);
            if (!result?.server_id || !['applied', 'already_synced', 'applied_with_conflict'].includes(result.resolved_as)) throw new Error(result?.error || 'Сервер не подтвердил сохранение ремонта');
            await acknowledge(repair, result);
          } catch (error) {
            await db.put('pendingRepairs', { ...repair, queue_error: error.message });
            onError?.(error, repair);
          }
        }
        const attachments = (await db.getAll('pendingAttachments')).filter(item => owns(item, owner));
        for (const attachment of attachments) {
          if (!attachment.repair_id) continue;
          try {
            if (expired) throw new Error('Сессия истекла. Войдите заново тем же аккаунтом.');
            await uploadAttachment(token, attachment);
            await db.delete('pendingAttachments', attachment.id);
          } catch (error) {
            await db.put('pendingAttachments', { ...attachment, queue_error: error.message });
            onError?.(error, attachment);
          }
        }
      });
    } catch (error) { syncError = error.message; onError?.(error); }
    const summary = { results, status: await queueStatus() };
    if (syncError) summary.status.errors.push(syncError);
    if (typeof window !== 'undefined' && typeof window.CustomEvent === 'function') window.dispatchEvent(new CustomEvent('fixit-offline-sync', { detail: summary }));
    return summary;
  }
  async function enqueueRepair(repair, photos = []) {
    const local_uuid = repair.local_uuid || uuid();
    for (const photo of photos) await photoBlob(photo);
    await exclusive(async () => {
      const token = await activeToken();
      const { user, org } = identity(token), queue_owner = { user, org };
      const existing = await db.get('pendingRepairs', local_uuid) || await db.kvGet(receiptKey(local_uuid));
      if (existing) {
        if (!owns(existing, queue_owner)) throw new Error('Этот ремонт принадлежит другой или неизвестной учётной записи');
        return; // Immutable retry, including retry after acknowledgement.
      }
      await transaction(['pendingRepairs', 'pendingAttachments'], 'readwrite', tx => {
        tx.objectStore('pendingRepairs').put({ ...repair, local_uuid, queue_owner, queue_error: null });
        photos.forEach((photo, index) => tx.objectStore('pendingAttachments').put({
          ...photo, id: photo.id || `${local_uuid}:${index}:${uuid()}`, local_uuid,
          service_request_id: repair.service_request_id || null, repair_id: null,
          kind: photo.kind || 'after', file_name: photo.file_name || photo.file?.name || `photo-${index + 1}.jpg`, queue_owner, queue_error: null,
        }));
      });
    });
    await registerBackgroundSync();
    return local_uuid;
  }
  async function registerBackgroundSync() {
    if (!root.navigator?.serviceWorker) return;
    try {
      const registration = await root.navigator.serviceWorker.register('/sw.js?v=20260909-5', { scope: '/' });
      if ('sync' in registration) await registration.sync.register('fixit-sync-repairs');
    } catch (_) { /* Foreground recovery works without Background Sync. */ }
  }
  async function configure({ token } = {}) {
    if (!identity(token)) throw new Error('Войдите заново для сохранения очереди');
    await exclusive(() => db.kvSet('token', token));
    pageToken = token;
    if (!configured && typeof window !== 'undefined') {
      configured = true;
      window.addEventListener('online', () => sync());
      window.addEventListener('focus', () => sync());
      document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') sync(); });
    }
  }
  async function logout() {
    const expected = pageToken;
    pageToken = null;
    await exclusive(async () => { if (!expected || await db.kvGet('token') === expected) await db.kvDelete('token'); });
  }
  // Unowned history has no reliable provenance. Export for assisted recovery
  // without silently attributing it to whichever account logs in next.
  async function exportUnowned() {
    const all = await snapshot();
    const repairs = all.repairs.filter(item => !item.queue_owner), attachments = [];
    for (const item of all.attachments.filter(item => !item.queue_owner)) {
      const copy = { ...item };
      if (copy.file instanceof Blob) {
        const bytes = new Uint8Array(await copy.file.arrayBuffer());
        let binary = ''; for (const byte of bytes) binary += String.fromCharCode(byte);
        copy.data_url = `data:${copy.file.type || 'application/octet-stream'};base64,${btoa(binary)}`;
        delete copy.file;
      }
      attachments.push(copy);
    }
    return new Blob([JSON.stringify({ format: 'fixit-unowned-queue-v1', repairs, attachments })], { type: 'application/json' });
  }
  root.FixitOffline = { db, uuid, configure, logout, enqueueRepair, sync, queueStatus, registerBackgroundSync, exportUnowned };
})(typeof self !== 'undefined' ? self : window);
