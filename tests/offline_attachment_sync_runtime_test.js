const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('app/static-tech/app.js', 'utf8');
const between = (start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
const uploadSource = between('async function uploadAttachment', 'async function syncPendingAttachments');
const attachmentSyncSource = between('async function syncPendingAttachments', 'async function getDeviceId');
const repairSyncSource = between('async function syncPendingRepairs', 'async function registerBackgroundSync');

async function runSync(attachments, failingIds = []) {
  const data = new Map(attachments.map((item) => [item.id, item]));
  const uploaded = [];
  const notices = [];
  const errors = [];
  const context = {
    Blob, FormData, Promise, Map, console: { error: (...args) => errors.push(args) },
    navigator: { onLine: true },
    state: { token: 'token', syncing: false },
    toast: (message) => notices.push(message), renderConnStrip: () => {}, registerBackgroundSync: async () => {},
    getDeviceId: async () => 'device-1', apiFetch: async () => ({ results: [] }),
    TechDB: {
      getAll: async (store) => store === 'pendingRepairs' ? [] : [...data.values()],
      put: async (_store, item) => data.set(item.id, item),
      delete: async (_store, id) => data.delete(id),
    },
    fetch: async (url, options = {}) => {
      if (String(url).startsWith('data:')) return { ok: true, blob: async () => new Blob(['photo'], { type: 'image/jpeg' }) };
      const id = String(url).match(/repairs\/([^/]+)/)?.[1];
      uploaded.push({ id, file: options.body?.get('file'), clientId: options.body?.get('client_id') });
      return failingIds.includes(id) ? { ok: false, status: 403, json: async () => ({ detail: 'Оборудование не назначено вам для обслуживания' }) } : { ok: true, status: 201, json: async () => ({ id: 'uploaded' }) };
    },
  };
  vm.runInNewContext(`${uploadSource}\n${attachmentSyncSource}\n${repairSyncSource}\nthis.run = syncPendingRepairs;`, context);
  await context.run();
  return { data, uploaded, notices, errors };
}

(async () => {
  const success = await runSync([{ id: 'ok', repair_id: 'repair-ok', kind: 'after', data_url: 'data:image/jpeg;base64,cGhvdG8=' }]);
  assert.equal(success.data.size, 0, 'successfully uploaded attachment must be removed');
  assert.equal(success.uploaded[0].file instanceof Blob, true, 'FormData receives a Blob/File, never undefined');
  assert.equal(success.uploaded[0].clientId, 'ok', 'durable queue id is reused for idempotent retries');

  const failed = await runSync([{ id: 'retry', repair_id: 'repair-retry', kind: 'after', data_url: 'data:image/jpeg;base64,cGhvdG8=' }], ['repair-retry']);
  assert.equal(failed.data.size, 1, 'failed upload remains queued for retry');
  assert.match(failed.notices[0], /403: Оборудование не назначено вам для обслуживания/, 'UI receives backend detail');
  assert.equal(failed.errors.length, 1, 'failed upload is diagnosable in console');
  console.log('offline attachment sync runtime: ok');
})().catch((error) => { console.error(error); process.exitCode = 1; });
