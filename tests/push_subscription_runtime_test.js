const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('app/static/app.js', 'utf8');
const lifecycle = source.slice(source.indexOf('async function enablePush()'), source.indexOf('async function removePushSubscription('));

function fixture(rotating = true, failUnsubscribe = false) {
  const calls = [];
  const oldEndpoint = 'https://fcm.googleapis.com/fcm/send/old-synthetic';
  const newEndpoint = 'https://fcm.googleapis.com/fcm/send/new-synthetic';
  const active = new Set([oldEndpoint, ...Array.from({length: 9}, (_, i) => `synthetic-${i}`)]);
  let current = {endpoint: oldEndpoint, options: {applicationServerKey: new Uint8Array([rotating ? 1 : 2])},
    toJSON() { return {endpoint: this.endpoint, keys: {}}; },
    async unsubscribe() { calls.push('browser-unsubscribe'); current = null; return true; }};
  const manager = {async getSubscription() { return current; }, async subscribe() {
    calls.push('browser-subscribe');
    current = {endpoint: newEndpoint, toJSON() { return {endpoint: this.endpoint, keys: {}}; }};
    return current;
  }};
  const registration = {pushManager: manager};
  const context = {Uint8Array, JSON, Notification: {permission: 'granted', requestPermission: async () => 'granted'},
    pushSupported: () => true, urlBase64ToUint8Array: () => new Uint8Array([2]),
    registerPulseWorker: async () => registration, navigator: {serviceWorker: {getRegistration: async () => registration}},
    toast() {}, renderNav() {}, async api(path, options) {
      calls.push(path);
      if (path === '/push/public-key') return {public_key: 'synthetic'};
      const endpoint = JSON.parse(options.body).endpoint;
      if (path === '/push/unsubscribe') {
        if (failUnsubscribe) throw new Error('synthetic unavailable API');
        active.delete(endpoint);
      } else if (path === '/push/subscribe') {
        if (!active.has(endpoint) && active.size >= 10) throw new Error('synthetic capacity 429');
        active.add(endpoint);
      }
    }};
  vm.runInNewContext(lifecycle, context);
  return {context, calls, active, current: () => current, oldEndpoint, newEndpoint};
}

(async () => {
  const rotated = fixture();
  assert.equal(await rotated.context.enablePush(), 'enabled', 'VAPID rotation must succeed at capacity');
  assert.deepEqual(rotated.calls, ['/push/public-key', '/push/unsubscribe', 'browser-unsubscribe', 'browser-subscribe', '/push/subscribe']);
  assert.equal(rotated.active.size, 10);
  assert(!rotated.active.has(rotated.oldEndpoint));
  assert(rotated.active.has(rotated.newEndpoint));

  const renewed = fixture(false);
  assert.equal(await renewed.context.enablePush(), 'enabled');
  assert.deepEqual(renewed.calls, ['/push/public-key', '/push/subscribe']);
  assert.equal(await renewed.context.disablePush(), 'disabled');
  assert.equal(renewed.current(), null);
  assert.equal(renewed.active.size, 9);

  const unavailable = fixture(true, true);
  assert.equal(await unavailable.context.enablePush(), 'error');
  assert.equal(unavailable.current().endpoint, unavailable.oldEndpoint);
  assert(!unavailable.calls.includes('browser-unsubscribe'));
  console.log('PASS Web Push lifecycle: rotation at capacity, renewal, disable, unavailable API (4 scenarios)');
})().catch(error => { console.error(error); process.exitCode = 1; });
