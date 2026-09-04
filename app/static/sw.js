// Root-scoped Fixit Pulse worker: preserves the durable offline repair engine.
importScripts('/static/offline/engine.js?v=20260902-1');
const SHELL_CACHE = 'fixit-pulse-shell-v4';
const SHELL = ['/', '/static/styles.css?v=20260902-2', '/static/app.js?v=20260904-3', '/static/offline/engine.js?v=20260902-1'];
self.addEventListener('install', (event) => event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('sync', (event) => {
  if (event.tag === 'fixit-sync-repairs') event.waitUntil(self.FixitOffline.sync({ token: null }));
});
self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET' || new URL(event.request.url).origin !== self.location.origin) return;
  if (event.request.mode === 'navigate') event.respondWith(fetch(event.request).catch(() => caches.match('/')));
  else if (new URL(event.request.url).pathname.startsWith('/static/')) {
    event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request)));
  }
});
self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data?.json() || {}; } catch (_) {}
  const title = String(data.title || 'Fixit Pulse').slice(0, 120);
  const body = String(data.body || 'Есть обновление по заявке').slice(0, 240);
  const url = typeof data.url === 'string' && data.url.startsWith('/#requests/') ? data.url : '/#requests';
  event.waitUntil(self.registration.showNotification(title, { body, icon: '/static/icons/fixit-192.svg', badge: '/static/icons/fixit-192.svg', data: { url }, tag: `fixit:${url}`, renotify: true }));
});
self.addEventListener('notificationclick', (event) => event.waitUntil((async () => {
  event.notification.close(); const target = new URL(event.notification.data?.url || '/#requests', self.location.origin).href;
  const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  if (windows.length) { await windows[0].focus(); await windows[0].navigate(target); return; }
  await self.clients.openWindow(target);
})()));
