const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('app/static-guest/upload.js', 'utf8');
const context = { window: {}, globalThis: {}, FormData, console };
vm.runInNewContext(source, context);
const { uploadPending } = context.window.FixitGuestPhotoUpload;
const photo = (id) => ({ id, file: new Blob(['image']), name: `${id}.jpg`, status: 'pending' });
const response = (status, detail = null) => ({ ok: status >= 200 && status < 300, status, json: async () => detail ? { detail } : {} });

(async () => {
  const calls = [];
  const all = [photo('one'), photo('two'), photo('three')];
  await uploadPending(all, { qrToken: 'token', requestId: 'request', send: async (_url, options) => {
    calls.push(options.body.get('client_id')); return response(201);
  }});
  assert.deepEqual(calls, ['one', 'two', 'three'], 'three photos are uploaded exactly once');
  assert.deepEqual(all.map((item) => item.status), ['success', 'success', 'success']);

  const partialCalls = [];
  const partial = [photo('ok-1'), photo('retry'), photo('ok-2')];
  const firstAttempt = [201, 503, 201];
  await uploadPending(partial, { qrToken: 'token', requestId: 'one-request', send: async (_url, options) => {
    partialCalls.push(options.body.get('client_id')); return response(firstAttempt.shift(), 'Сервис временно недоступен');
  }});
  assert.deepEqual(partial.map((item) => item.status), ['success', 'failed', 'success']);
  assert.equal(partial[1].retryable, true, 'temporary error remains retryable');
  assert.deepEqual(partialCalls, ['ok-1', 'retry', 'ok-2']);

  await uploadPending(partial, { qrToken: 'token', requestId: 'one-request', send: async (_url, options) => {
    partialCalls.push(options.body.get('client_id')); return response(201);
  }});
  assert.deepEqual(partialCalls, ['ok-1', 'retry', 'ok-2', 'retry'], 'retry sends only the failed photo');
  assert.deepEqual(partial.map((item) => item.status), ['success', 'success', 'success']);

  const repeated = [photo('repeated')];
  let repeatedCalls = 0;
  await uploadPending(repeated, { qrToken: 'token', requestId: 'one-request', send: async () => { repeatedCalls += 1; return response(503, 'Временно недоступно'); }});
  await uploadPending(repeated, { qrToken: 'token', requestId: 'one-request', send: async () => { repeatedCalls += 1; return response(503, 'Временно недоступно'); }});
  assert.equal(repeatedCalls, 2);
  assert.equal(repeated[0].status, 'failed');
  assert.equal(repeated[0].retryable, true, 'a second temporary failure stays visible and retryable');

  const invalid = [photo('invalid')];
  let invalidCalls = 0;
  await uploadPending(invalid, { qrToken: 'token', requestId: 'one-request', send: async () => { invalidCalls += 1; return response(422, 'Нужна фотография до 6 МБ'); }});
  await uploadPending(invalid, { qrToken: 'token', requestId: 'one-request', send: async () => { invalidCalls += 1; return response(201); }});
  assert.equal(invalidCalls, 1, 'validation failures are not retried automatically');
  assert.equal(invalid[0].retryable, false);

  const app = fs.readFileSync('app/static-guest/app.js', 'utf8');
  assert.match(app, /if \(state\.submitting \|\| state\.createdRequest\) return;/, 'double submit cannot create another request');
  assert.match(app, /state\.createdRequest = body;/, 'request id remains in the page session for retries');
  assert.match(app, /uploadPending\(state\.photos/, 'retries use photo state, not ticket creation');
  console.log('guest photo upload runtime: ok');
})().catch((error) => { console.error(error); process.exitCode = 1; });
