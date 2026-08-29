const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');

function memoryIndexedDb() {
  const stores = new Map();
  const request = (value) => {
    const result = {};
    queueMicrotask(() => { result.result = value; result.onsuccess?.(); });
    return result;
  };
  const database = {
    objectStoreNames: { contains: (name) => stores.has(name) },
    createObjectStore(name, options = {}) { stores.set(name, { keyPath: options.keyPath, values: new Map() }); },
    transaction(name) {
      const store = stores.get(name);
      return { objectStore: () => ({
        getAll: () => request([...store.values.values()]),
        get: (key) => request(store.values.get(key)),
        put: (value, key) => { store.values.set(store.keyPath ? value[store.keyPath] : key, value); return request(key); },
        delete: (key) => { store.values.delete(key); return request(undefined); },
      }) };
    },
  };
  return { open: () => {
    const result = {};
    queueMicrotask(() => { result.result = database; result.onupgradeneeded?.(); result.onsuccess?.(); });
    return result;
  } };
}

async function loadEngine(fetch) {
  const context = { Blob, FormData, Promise, Map, Uint8Array, crypto: webcrypto, indexedDB: memoryIndexedDb(), navigator: { onLine: true }, fetch, self: null };
  context.self = context;
  vm.runInNewContext(fs.readFileSync('app/static/offline/engine.js', 'utf8'), context);
  await context.FixitOffline.configure({ token: 'test-token' });
  return context.FixitOffline;
}

(async () => {
  let repairCalls = 0;
  let attachmentCalls = 0;
  let failAttachment = true;
  const offline = await loadEngine(async (url, options = {}) => {
    if (url === '/api/v1/sync/repairs') {
      repairCalls += 1;
      const body = JSON.parse(options.body);
      return { ok: true, json: async () => ({ results: body.repairs.map((repair) => ({ local_uuid: repair.local_uuid, server_id: 'server-repair', resolved_as: 'applied' })) }) };
    }
    attachmentCalls += 1;
    assert.equal(options.body.get('file') instanceof Blob, true, 'FormData never receives undefined');
    assert.equal(Boolean(options.body.get('client_id')), true, 'attachment retry has a stable client id');
    return failAttachment ? { ok: false } : { ok: true };
  });
  const localUuid = await offline.enqueueRepair({ local_uuid: 'local-repair', service_request_id: 'request-1', equipment_id: 'equipment', description: 'work' }, [
    { file: new Blob(['one'], { type: 'image/jpeg' }), kind: 'after' },
    { file: new Blob(['two'], { type: 'image/jpeg' }), kind: 'after' },
  ]);
  assert.equal(localUuid, 'local-repair');
  const partial = await offline.sync();
  assert.equal(partial.status.repairPending, false, 'Repair is not requeued after server acknowledgement');
  assert.equal(partial.status.attachmentsPending, 2, 'failed photos remain durable');
  assert.equal((await offline.queueStatus({ serviceRequestId: 'request-1' })).attachmentsPending, 2, 'request reopens with its pending-photo state');
  assert.equal(repairCalls, 1);

  failAttachment = false;
  const complete = await offline.sync();
  assert.equal(complete.status.fullySynced, true, 'only successful uploads leave the queue');
  assert.equal(repairCalls, 1, 'retry uploads photos without duplicating Repair');
  assert.equal(attachmentCalls, 4);
  assert.equal(await offline.db.kvGet('token'), 'test-token', 'background sync can read its token from IndexedDB');
  await offline.db.kvDelete('token');
  assert.equal(await offline.db.kvGet('token'), undefined, 'logout clears durable offline credential');
  console.log('pulse offline engine runtime: ok');
})().catch((error) => { console.error(error); process.exitCode = 1; });
