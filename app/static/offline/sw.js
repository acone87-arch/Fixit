// Background Sync companion for the shared Fixit offline queue.
importScripts('/static/offline/engine.js?v=20260909-5');
self.addEventListener('install', (event) => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('sync', (event) => {
  if (event.tag === 'fixit-sync-repairs' || event.tag === 'sync-repairs') {
    event.waitUntil(self.FixitOffline.sync({ token: null }));
  }
});
