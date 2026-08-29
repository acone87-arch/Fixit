// Background Sync companion for the shared Fixit offline queue.
importScripts('/static/offline/engine.js?v=20260829-2');
self.addEventListener('sync', (event) => {
  if (event.tag === 'fixit-sync-repairs') event.waitUntil(self.FixitOffline.sync({ token: null }));
});
