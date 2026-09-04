// ============================================================
// Сервис и склад — панель администратора
// Vanilla JS SPA: без сборки, отдаётся FastAPI напрямую из app/static.
// ============================================================

const state = {
  token: localStorage.getItem('token') || null,
  me: null,
  equipmentTypes: [],
  clients: [],
  sites: [],
  route: location.hash.replace('#', '') || 'pulse',
};

let adminScanStream = null;
let activeTechnicianWorkspaceCleanup = null;
let activeServiceRequestDetailCleanup = null;
let activeImageLightbox = null;
let activeClientPhotoUrls = [];
let deferredInstallPrompt = null;
let installationCompletedThisSession = false;

const isStandalone = () => window.matchMedia?.('(display-mode: standalone)').matches || window.navigator.standalone === true;
const isIos = () => /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;
const pushSupported = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

window.addEventListener?.('beforeinstallprompt', (event) => {
  event.preventDefault();
  deferredInstallPrompt = event;
  if (state.me) renderNav();
});
window.addEventListener?.('appinstalled', () => {
  deferredInstallPrompt = null;
  installationCompletedThisSession = true;
  localStorage.removeItem('fixit-install-dismissed');
  renderNav();
});

function urlBase64ToUint8Array(value) {
  const base64 = value.replace(/-/g, '+').replace(/_/g, '/');
  const padded = base64 + '='.repeat((4 - base64.length % 4) % 4);
  return Uint8Array.from(atob(padded), (char) => char.charCodeAt(0));
}

async function registerPulseWorker() {
  if (!('serviceWorker' in navigator)) return null;
  const registrations = await navigator.serviceWorker.getRegistrations();
  await Promise.all(registrations.filter((item) => new URL(item.active?.scriptURL || item.waiting?.scriptURL || item.installing?.scriptURL || '', location.origin).pathname === '/static/offline/sw.js').map((item) => item.unregister()));
  return navigator.serviceWorker.register('/sw.js?v=20260904-1', { scope: '/' });
}

async function enablePush() {
  if (!pushSupported()) { toast('В этом браузере уведомления не поддерживаются', 'error'); return 'unsupported'; }
  if (Notification.permission === 'denied') { toast('Уведомления запрещены браузером. Разрешите их в настройках сайта.', 'error'); return 'denied'; }
  try {
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') { renderNav(); return permission === 'denied' ? 'denied' : 'dismissed'; }
    const key = await api('/push/public-key');
    const registration = await registerPulseWorker();
    const subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(key.public_key) });
    await api('/push/subscribe', { method: 'POST', body: JSON.stringify(subscription.toJSON()) });
    toast('Уведомления включены'); renderNav(); return 'enabled';
  } catch (error) { toast(error.message || 'Не удалось включить уведомления', 'error'); return 'error'; }
}

async function removePushSubscription(token) {
  if (!pushSupported()) return;
  try {
    const registration = await navigator.serviceWorker.getRegistration('/');
    const subscription = await registration?.pushManager.getSubscription();
    if (subscription && token) {
      await fetch('/api/push/unsubscribe', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ endpoint: subscription.endpoint }) });
    }
    await subscription?.unsubscribe();
  } catch (_) { /* logout must remain usable offline */ }
}

function pwaControls() {
  const dismissed = localStorage.getItem('fixit-install-dismissed') === '1';
  const install = isStandalone() ? '' : deferredInstallPrompt && !dismissed
    ? '<section class="pwa-card"><strong>Установите Fixit</strong><p>Получайте заявки и уведомления сразу на телефон.</p><button class="btn btn-primary pwa-install-btn">Установить приложение</button><button class="pwa-dismiss-btn">Не сейчас</button></section>'
    : isIos() && !dismissed
      ? '<section class="pwa-card"><strong>Установите Fixit</strong><p>Чтобы установить Fixit: <b>Поделиться → На экран «Домой»</b>.</p><button class="pwa-dismiss-btn">Понятно</button></section>'
      : !dismissed ? '<section class="pwa-card"><strong>Установка недоступна</strong><p>Откройте Fixit в актуальном Chrome или Edge по HTTPS, чтобы установить приложение.</p></section>' : '';
  const notifications = pushSupported()
    ? `<section class="pwa-card pwa-notifications"><strong>${Notification.permission === 'granted' ? 'Уведомления включены' : Notification.permission === 'denied' ? 'Уведомления запрещены браузером' : 'Включить уведомления'}</strong><p>${Notification.permission === 'granted' ? 'Fixit будет сообщать о новых заявках и важных изменениях.' : Notification.permission === 'denied' ? 'Разрешите уведомления в настройках сайта, чтобы получать обновления.' : 'Fixit сообщит о новых заявках и важных изменениях.'}</p>${Notification.permission === 'default' ? '<button class="btn btn-secondary pwa-push-btn">Включить уведомления</button>' : ''}</section>`
    : '<section class="pwa-card pwa-notifications"><strong>Уведомления недоступны</strong><p>Этот браузер или устройство не поддерживает Web Push.</p></section>';
  return install + notifications;
}

function onboardingKey() {
  return `fixit-onboarding-dismissed:${state.me?.organization_id || 'org'}:${state.me?.id || 'user'}`;
}

async function currentPushState() {
  if (!pushSupported()) return { state: 'unsupported' };
  if (Notification.permission === 'denied') return { state: 'denied' };
  if (Notification.permission !== 'granted') return { state: 'available' };
  try {
    const registration = await registerPulseWorker();
    const subscription = await registration?.pushManager.getSubscription();
    if (!subscription) return { state: 'available' };
    const remote = await api(`/push/state?endpoint=${encodeURIComponent(subscription.endpoint)}`);
    return remote.configured && remote.subscribed ? { state: 'enabled' } : { state: 'available' };
  } catch (_) { return { state: 'available' }; }
}

async function requestPwaInstall() {
  if (!deferredInstallPrompt) return 'unsupported';
  deferredInstallPrompt.prompt();
  const result = await deferredInstallPrompt.userChoice;
  deferredInstallPrompt = null;
  if (result.outcome === 'accepted') installationCompletedThisSession = true;
  return result.outcome === 'accepted' ? 'accepted' : 'dismissed';
}

async function openPwaOnboarding() {
  const push = await currentPushState();
  const needsInstallationStep = !isStandalone() && !installationCompletedThisSession;
  const needsNotificationStep = push.state !== 'enabled';
  if (!needsInstallationStep && !needsNotificationStep) {
    localStorage.setItem(onboardingKey(), '1');
    return;
  }
  const installBody = !needsInstallationStep ? '' : isIos()
    ? '<section class="onboarding-step"><span>ШАГ 1</span><h3>Установите Fixit на iPhone</h3><p>Нажмите <b>Поделиться → На экран «Домой»</b>.</p></section>'
    : deferredInstallPrompt
      ? '<section class="onboarding-step"><span>ШАГ 1</span><h3>Установите приложение</h3><p>Получайте новые заявки и важные уведомления сразу на телефон.</p><button class="btn btn-primary" id="onboarding-install">Установить Fixit</button></section>'
      : '<section class="onboarding-step"><span>ШАГ 1</span><h3>Установка недоступна</h3><p>Откройте Fixit в актуальном Chrome или Edge по HTTPS, чтобы установить приложение.</p></section>';
  const notificationBody = !needsNotificationStep ? '' : `<section class="onboarding-step"><span>ШАГ ${needsInstallationStep ? 2 : 1}</span><h3>Включите уведомления</h3><p>Fixit сообщит о новых заявках, согласованиях и важных изменениях.</p>${push.state === 'unsupported' ? '<p class="onboarding-note">Этот браузер не поддерживает уведомления.</p>' : push.state === 'denied' ? '<p class="onboarding-note">Уведомления запрещены браузером. Их можно разрешить позже в настройках сайта.</p>' : '<button class="btn btn-secondary" id="onboarding-push">Включить уведомления</button>'}</section>`;
  const backdrop = openModal('Fixit готов к работе', `<div class="onboarding-intro">Настройте приложение сейчас или продолжите — это всегда можно сделать позже в профиле.</div>${installBody}${notificationBody}`, '<button class="btn btn-primary" id="onboarding-continue">Продолжить в Fixit</button>');
  const refresh = async () => { closeModal(); await openPwaOnboarding(); };
  backdrop.querySelector('#onboarding-install')?.addEventListener('click', async () => {
    const outcome = await requestPwaInstall();
    if (outcome === 'dismissed') toast('Установка отменена — Fixit продолжит работать в браузере.');
    await refresh();
  });
  backdrop.querySelector('#onboarding-push')?.addEventListener('click', async () => {
    const outcome = await enablePush();
    if (outcome === 'error') return;
    await refresh();
  });
  backdrop.querySelector('#onboarding-continue').addEventListener('click', () => {
    localStorage.setItem(onboardingKey(), '1'); closeModal();
  });
}

async function maybeStartPwaOnboarding() {
  if (!state.me || localStorage.getItem(onboardingKey()) === '1') return;
  await openPwaOnboarding();
}

// ---------- API-клиент ----------

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (state.token) headers['Authorization'] = `Bearer ${state.token}`;
  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }
  const res = await fetch('/api' + path, { ...options, headers });
  if (res.status === 401 && path !== '/auth/login') {
    logout();
    throw new Error('Сессия истекла, войдите заново');
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    } catch (_) {}
    throw new Error(detail || 'Ошибка запроса');
  }
  if (res.status === 204) return null;
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

async function apiBlob(path) {
  const headers = state.token ? { Authorization: `Bearer ${state.token}` } : {};
  // API DTOs expose protected media as /api/... URLs, while older callers
  // pass relative API paths. Accept both without producing /api/api/...
  const url = path.startsWith('/api/') ? path : '/api' + path;
  const res = await fetch(url, { headers });
  if (res.status === 401) {
    logout();
    throw new Error('Сессия истекла, войдите заново');
  }
  if (!res.ok) throw new Error('Не удалось загрузить файл');
  return res.blob();
}

// ---------- Утилиты ----------

function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' }) +
    ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}

function createUuid() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (window.crypto?.getRandomValues) window.crypto.getRandomValues(bytes);
  else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function normalizeDraftPhoto(photo, index = 0) {
  const blob = photo?.file || photo?.blob;
  if (!(blob instanceof Blob) || !blob.size) return null;
  const name = photo.name || blob.name || `photo-${Date.now()}-${index + 1}.jpg`;
  const type = photo.type || blob.type || 'image/jpeg';
  const file = typeof File !== 'undefined' && blob instanceof File ? blob : new File([blob], name, { type });
  return { file, url: URL.createObjectURL(file), approvalAttachmentId: photo.approvalAttachmentId || null };
}

function hasDraftPhotoFile(photo) {
  return Boolean(photo?.file instanceof Blob && photo.file.size);
}

// Phone originals are needlessly large for a repair record. Keep a single
// correctly-oriented browser-decoded copy that is readable on a 1600–2000 px
// screen and can be stored durably in IndexedDB without exhausting storage.
async function optimizePhoto(file, maxSide = 1920) {
  if (!(file instanceof Blob) || !String(file.type || '').startsWith('image/')) return file;
  try {
    const image = await createImageBitmap(file, { imageOrientation: 'from-image' });
    const scale = Math.min(1, maxSide / Math.max(image.width, image.height));
    if (scale === 1 && file.size <= 1_500_000) { image.close?.(); return file; }
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(image.width * scale));
    canvas.height = Math.max(1, Math.round(image.height * scale));
    canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
    image.close?.();
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', .82));
    if (!blob || !blob.size) return file;
    const base = (file.name || 'photo').replace(/\.[^.]+$/, '');
    return new File([blob], `${base}.jpg`, { type: 'image/jpeg' });
  } catch (_) {
    // Camera / older browser fallback: retaining the original is safer than
    // losing field evidence when image decoding is unavailable.
    return file;
  }
}

const RequestDraftStore = (() => {
  if (!window.indexedDB) return { get: async () => null, put: async () => null, remove: async () => null };
  const dbPromise = new Promise((resolve, reject) => {
    const request = window.indexedDB.open('fixit-request-drafts', 1);
    request.onupgradeneeded = () => { if (!request.result.objectStoreNames.contains('drafts')) request.result.createObjectStore('drafts', { keyPath: 'key' }); };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  const run = async (mode, action) => new Promise(async (resolve, reject) => {
    try { const store = (await dbPromise).transaction('drafts', mode).objectStore('drafts'); const request = action(store); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); } catch (error) { reject(error); }
  });
  return { get: (key) => run('readonly', (store) => store.get(key)), put: (draft) => run('readwrite', (store) => store.put(draft)), remove: (key) => run('readwrite', (store) => store.delete(key)) };
})();

function requestDraftKey(requestId) {
  return `fixit-request-draft:${state.me?.organization_id || state.me?.organization?.id || 'org'}:${state.me?.id || 'user'}:${requestId}`;
}

function navigateToServiceRequest(id) {
  if (!id) return toast('Не удалось определить заявку', 'error');
  location.hash = `requests/${id}`;
}

function toast(message, type = 'success') {
  const root = document.getElementById('toast-root');
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function closeModal() {
  stopAdminQrScan();
  const el = document.querySelector('.modal-backdrop');
  if (el) {
    el.querySelectorAll('[data-object-url]').forEach((node) => {
      const url = node.getAttribute('src') || node.getAttribute('href');
      if (url?.startsWith('blob:')) URL.revokeObjectURL(url);
    });
    el.remove();
  }
}

function closeImageLightbox() {
  if (!activeImageLightbox) return;
  const { element, url, onKeydown } = activeImageLightbox;
  document.removeEventListener('keydown', onKeydown);
  if (url?.startsWith('blob:')) URL.revokeObjectURL(url);
  element.remove();
  activeImageLightbox = null;
}

function stopAdminQrScan() {
  if (adminScanStream) {
    adminScanStream.getTracks().forEach((track) => track.stop());
    adminScanStream = null;
  }
}

function qrTokenFromValue(rawValue) {
  let token = String(rawValue || '').trim();
  try {
    const url = new URL(token);
    const parts = url.pathname.split('/').filter(Boolean);
    token = parts[parts.length - 1] || token;
  } catch (_) {}
  return token;
}

function openModal(title, bodyHtml, footerHtml) {
  closeModal();
  const backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';
  backdrop.innerHTML = `
    <div class="modal">
      <h2>${esc(title)}</h2>
      <div id="modal-body">${bodyHtml}</div>
      <div class="modal-actions">${footerHtml || ''}</div>
    </div>`;
  backdrop.addEventListener('click', (e) => { if (e.target === backdrop) closeModal(); });
  document.body.appendChild(backdrop);
  return backdrop;
}

async function openProtectedImage(path, title = 'Фотография') {
  try {
    closeImageLightbox();
    const url = URL.createObjectURL(await apiBlob(path));
    const element = document.createElement('div');
    element.className = 'image-lightbox';
    element.innerHTML = `<div class="image-lightbox-panel" role="dialog" aria-modal="true" aria-label="${esc(title)}"><header><strong>${esc(title)}</strong><button type="button" aria-label="Закрыть просмотр">×</button></header><img src="${url}" alt="${esc(title)}"></div>`;
    const close = () => closeImageLightbox();
    const onKeydown = (event) => { if (event.key === 'Escape') close(); };
    element.addEventListener('click', (event) => { if (event.target === element) close(); });
    element.querySelector('button').addEventListener('click', close);
    document.addEventListener('keydown', onKeydown);
    document.body.appendChild(element);
    activeImageLightbox = { element, url, onKeydown };
  } catch (error) {
    toast(error.message || 'Не удалось открыть фотографию', 'error');
  }
}

function openApprovalDialog(action, onSubmit) {
  const rejected = action === 'rejected';
  const element = document.createElement('div');
  element.className = 'pulse-dialog-backdrop';
  element.innerHTML = `<form class="pulse-dialog" aria-label="${rejected ? 'Отклонить согласование' : 'Согласовать работы'}"><header><span>${rejected ? 'СОГЛАСОВАНИЕ' : 'СОГЛАСОВАНИЕ РАБОТ'}</span><h2>${rejected ? 'Отклонить согласование' : 'Согласовать работы'}</h2></header><label>${rejected ? 'Причина отклонения' : 'Комментарий'}<textarea id="approval-comment" ${rejected ? 'required' : ''} placeholder="${rejected ? 'Укажите причину для мастера' : 'Необязательно'}"></textarea></label><footer><button type="button" class="btn btn-secondary" data-approval-cancel>Отмена</button><button class="btn btn-primary" type="submit">${rejected ? 'Отклонить' : 'Согласовать'}</button></footer></form>`;
  const close = () => element.remove();
  element.addEventListener('click', (event) => { if (event.target === element) close(); });
  element.querySelector('[data-approval-cancel]').addEventListener('click', close);
  element.querySelector('form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const comment = element.querySelector('#approval-comment').value.trim();
    if (rejected && !comment) return toast('Укажите причину отклонения', 'error');
    const submit = element.querySelector('[type="submit"]');
    submit.disabled = true;
    try {
      await onSubmit(comment || null);
      close();
    } catch (error) {
      submit.disabled = false;
      toast(error.message || 'Не удалось обработать согласование', 'error');
    }
  });
  document.body.appendChild(element);
  element.querySelector('#approval-comment').focus();
}

async function uploadEquipmentPhoto(equipmentId, file) {
  const form = new FormData();
  const optimized = await optimizePhoto(file);
  form.append('file', optimized, optimized.name || 'equipment.jpg');
  return api(`/equipment/${equipmentId}/photo`, { method: 'POST', body: form });
}

// ---------- Справочники (общие) ----------

const EQUIPMENT_STATUS = {
  working: { label: 'Работает', cls: 'good' },
  needs_repair: { label: 'Требует ремонта', cls: 'warn' },
  mothballed: { label: 'На консервации', cls: 'idle' },
  decommissioned: { label: 'Списано', cls: 'idle' },
};
const ROLE_LABEL = { owner: 'Владелец', admin: 'Администратор', dispatcher: 'Диспетчер', technician: 'Техник', client_admin: 'Представитель клиента', client_site_user: 'Представитель объекта' };

function badge(map, key) {
  const info = map[key] || { label: key, cls: 'idle' };
  return `<span class="badge badge-${info.cls}"><span class="badge-dot"></span>${esc(info.label)}</span>`;
}

// ---------- Навигация ----------

const NAV = {
  owner: [
    ['pulse', 'Pulse'], ['requests', 'Заявки'],
    ['clients', 'Клиенты и объекты'], ['equipment', 'Оборудование'],
    ['warehouse', 'Склад'], ['users', 'Пользователи'],
  ],
  admin: [
    ['pulse', 'Pulse'], ['requests', 'Заявки'],
    ['clients', 'Клиенты и объекты'],
    ['equipment', 'Оборудование'],
    ['warehouse', 'Склад и запчасти'],
    ['users', 'Пользователи'],
  ],
  dispatcher: [
    ['pulse', 'Pulse'], ['requests', 'Заявки'],
    ['clients', 'Клиенты и объекты'],
    ['equipment', 'Оборудование'],
    ['warehouse', 'Склад и запчасти'],
  ],
  technician: [
    ['pulse', 'Pulse'], ['requests', 'Мои заявки'], ['equipment', 'Оборудование'],
    ['warehouse', 'Мой склад'],
  ],
  client_admin: [['pulse', 'Главная'], ['requests', 'Заявки'], ['equipment', 'Оборудование'], ['clients', 'Команда'], ['documents', 'Документы']],
  client_site_user: [['pulse', 'Главная'], ['requests', 'Заявки'], ['equipment', 'Оборудование'], ['documents', 'Документы']],
};

function renderNav() {
  const items = NAV[state.me.role] || [];
  document.getElementById('nav').innerHTML = items
    .map(([key, label]) => `<button class="nav-item ${state.route === key ? 'active' : ''}" data-route="${key}"><span class="nav-icon nav-icon-${key}"></span>${esc(label)}</button>`)
    .join('');
  document.querySelectorAll('.nav-item').forEach((btn) => {
    btn.addEventListener('click', () => { location.hash = btn.dataset.route; });
  });
  document.getElementById('user-name').textContent = state.me.full_name;
  document.getElementById('user-role').textContent = ROLE_LABEL[state.me.role] || state.me.role;
  renderMobileNav(items);
}

function renderMobileNav(items) {
  const mobileNav = document.getElementById('mobile-nav');
  const moreMenu = document.getElementById('more-menu');
  const primary = state.me.role.startsWith('client_') ? [
    ['pulse', 'Главная', 'pulse'], ['requests', 'Заявки', 'tasks'], ['equipment', 'Оборудование', 'equipment'], ['documents', 'Документы', 'warehouse'], ['more', 'Ещё', 'more'],
  ] : [
    ['pulse', 'Пульс', 'pulse'], ['requests', 'Заявки', 'tasks'], ['qr', 'QR', 'qr'],
    ['equipment', 'Оборудование', 'equipment'], ['more', 'Ещё', 'more'],
  ];
  mobileNav.innerHTML = primary.map(([route, label, icon]) => `
    <button class="mobile-nav-item ${state.route === route ? 'active' : ''}" data-mobile-route="${route}">
      <span class="mobile-nav-icon icon-${icon}"></span><span>${label}</span>
    </button>`).join('');
  moreMenu.innerHTML = `<div class="more-menu-head"><span>Разделы</span><button id="more-close-btn">Закрыть</button></div>${pwaControls()}${items
    .filter(([route]) => !['pulse', 'requests', 'equipment'].includes(route))
    .map(([route, label]) => `<button data-more-route="${route}">${esc(label)}<span>→</span></button>`).join('')}
    <button id="more-logout-btn" class="more-logout">Выйти<span>↗</span></button>`;
  document.querySelectorAll('[data-mobile-route]').forEach((button) => button.addEventListener('click', () => {
    const route = button.dataset.mobileRoute;
    if (route === 'more') { moreMenu.classList.toggle('hidden'); return; }
    if (route === 'qr') { openQrQuickAction(); return; }
    moreMenu.classList.add('hidden');
    location.hash = route;
  }));
  moreMenu.querySelectorAll('[data-more-route]').forEach((button) => button.addEventListener('click', () => {
    moreMenu.classList.add('hidden'); location.hash = button.dataset.moreRoute;
  }));
  moreMenu.querySelector('#more-close-btn').addEventListener('click', () => moreMenu.classList.add('hidden'));
  moreMenu.querySelector('#more-logout-btn').addEventListener('click', logout);
  moreMenu.querySelector('.pwa-install-btn')?.addEventListener('click', async () => {
    const result = await requestPwaInstall();
    if (result !== 'accepted') localStorage.setItem('fixit-install-dismissed', '1');
    renderNav();
  });
  moreMenu.querySelector('.pwa-dismiss-btn')?.addEventListener('click', () => { localStorage.setItem('fixit-install-dismissed', '1'); renderNav(); });
  moreMenu.querySelector('.pwa-push-btn')?.addEventListener('click', enablePush);
  document.getElementById('mobile-profile-btn').onclick = () => moreMenu.classList.toggle('hidden');
}

function openQrQuickAction() {
  const httpsUrl = location.href.replace(/^http:/, 'https:');
  const secureWarning = !window.isSecureContext
    ? `<div class="qr-security-note">Камера блокируется браузером на HTTP. Откройте <a href="${esc(httpsUrl)}">защищённую версию HTTPS</a>.</div>`
    : '';
  const backdrop = openModal('Сканировать QR', `
    <div class="admin-qr-scanner"><video id="admin-qr-video" autoplay muted playsinline></video><div class="admin-qr-frame"></div></div>
    <p class="text-soft" id="admin-qr-hint" style="line-height:1.55">Наведите камеру на QR-код оборудования.</p>${secureWarning}
    <div class="field" style="margin-top:14px"><label>Или вставьте ссылку / код вручную</label><input id="admin-qr-manual" placeholder="https://…/e/…"></div>`,
    '<button class="btn btn-secondary" id="modal-cancel">Закрыть</button><button class="btn btn-secondary" id="admin-qr-start">Включить камеру</button><button class="btn btn-primary" id="admin-qr-open">Открыть</button>');
  backdrop.querySelector('#modal-cancel').addEventListener('click', closeModal);
  const hint = backdrop.querySelector('#admin-qr-hint');
  const openScannedEquipment = async (rawValue) => {
    const token = qrTokenFromValue(rawValue);
    if (!token) return toast('Считайте QR-код или вставьте ссылку', 'error');
    try {
      const equipment = await api(`/equipment/by-qr/${encodeURIComponent(token)}`);
      closeModal();
      if (equipment.passport_allowed === false) {
        toast(`Оборудование: ${equipment.serial_number || equipment.id}. Полный паспорт доступен после назначения клиента в обслуживание.`, 'info');
        return;
      }
      await openEquipmentPassport(equipment.id);
    } catch (error) { toast(error.message || 'Оборудование по QR не найдено', 'error'); }
  };
  const startCamera = async () => {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      hint.textContent = 'Камера доступна только через HTTPS. Откройте защищённую версию сайта.';
      return;
    }
    if (!('BarcodeDetector' in window)) {
      hint.textContent = 'В этом браузере нет встроенного QR-сканера. Вставьте ссылку из QR вручную.';
      return;
    }
    try {
      stopAdminQrScan();
      adminScanStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
      const video = backdrop.querySelector('#admin-qr-video');
      video.srcObject = adminScanStream;
      await video.play();
      hint.textContent = 'Камера включена. Наведите её на QR-код оборудования.';
      const detector = new BarcodeDetector({ formats: ['qr_code'] });
      const scanFrame = async () => {
        if (!adminScanStream || !document.body.contains(backdrop)) return;
        try {
          const codes = await detector.detect(video);
          if (codes.length) { await openScannedEquipment(codes[0].rawValue); return; }
        } catch (_) {}
        requestAnimationFrame(scanFrame);
      };
      requestAnimationFrame(scanFrame);
    } catch (error) {
      hint.textContent = error.name === 'NotAllowedError'
        ? 'Доступ к камере запрещён. Разрешите камеру в настройках браузера и повторите.'
        : 'Не удалось включить камеру. Проверьте разрешение и подключение.';
    }
  };
  backdrop.querySelector('#admin-qr-start').addEventListener('click', startCamera);
  backdrop.querySelector('#admin-qr-open').addEventListener('click', () => openScannedEquipment(backdrop.querySelector('#admin-qr-manual').value));
  backdrop.querySelector('#admin-qr-manual').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); openScannedEquipment(event.currentTarget.value); }
  });
  startCamera();
}

async function router() {
  closeImageLightbox();
  activeClientPhotoUrls.forEach((url) => URL.revokeObjectURL(url));
  activeClientPhotoUrls = [];
  const defaultRoute = 'pulse';
  const hashRoute = location.hash.replace('#', '') || defaultRoute;
  const [route, routeId, routeTab, routeChildId] = hashRoute.split('/');
  state.route = route;
  state.requestId = route === 'requests' && routeId ? routeId : null;
  state.clientId = route === 'clients' && routeId ? routeId : null;
  state.clientTab = state.clientId ? (routeTab || 'overview') : null;
  state.clientSiteId = state.clientTab === 'sites' && routeChildId ? routeChildId : null;
  const allowedRoutes = (NAV[state.me?.role] || []).map(([key]) => key);
  if (!allowedRoutes.includes(state.route)) {
    state.route = defaultRoute;
    history.replaceState(null, '', `#${defaultRoute}`);
  }
  renderNav();
  const content = document.getElementById('content');
  if (activeTechnicianWorkspaceCleanup) {
    activeTechnicianWorkspaceCleanup();
    activeTechnicianWorkspaceCleanup = null;
  }
  if (activeServiceRequestDetailCleanup) {
    activeServiceRequestDetailCleanup();
    activeServiceRequestDetailCleanup = null;
  }
  content.innerHTML = '<div class="section-loading">Загрузка…</div>';
  try {
    if (state.route === 'pulse') await renderPulse(content);
    else if (state.me.role.startsWith('client_') && state.route === 'requests' && state.requestId) await renderClientRequest(content, state.requestId);
    else if (state.route === 'requests' && state.requestId) await openServiceRequest(state.requestId);
    else if (state.me.role.startsWith('client_') && state.route === 'requests') await renderClientRequests(content);
    else if (state.route === 'requests') await renderServiceRequests(content);
    else if (state.route === 'clients' && state.clientId) await renderClientDetail(content, state.clientId, state.clientTab);
    else if (state.route === 'clients') await renderClients(content);
    else if (state.me.role.startsWith('client_') && state.route === 'equipment') await renderClientEquipment(content);
    else if (state.route === 'equipment') await renderEquipment(content);
    else if (state.me.role.startsWith('client_') && state.route === 'documents') await renderClientDocuments(content);
    else if (state.route === 'warehouse') await renderWarehouse(content);
    else if (state.route === 'users') await renderUsers(content);
    else content.innerHTML = '<div class="section-loading">Раздел не найден</div>';
  } catch (e) {
    content.innerHTML = `<div class="section-loading">Не удалось загрузить раздел: ${esc(e.message)}</div>`;
  }
}
window.addEventListener('hashchange', router);

async function renderServiceRequests(content) {
  const requests = await api('/service-requests');
  const statusLabel = { new: 'Новая', assigned: 'Назначена', on_the_way: 'В пути', arrived: 'На объекте', in_progress: 'В работе', waiting_parts: 'Ждёт запчасти', waiting_approval: 'Требует согласования', completed: 'Выполнена', closed: 'Закрыта', cancelled: 'Отменена' };
  const requestBadge = (item) => `<span class="badge badge-${['completed', 'closed'].includes(item.status) ? 'good' : item.status.startsWith('waiting') ? 'amber' : item.status === 'cancelled' ? 'idle' : 'warn'}"><span class="badge-dot"></span>${esc(statusLabel[item.status] || item.status)}</span>`;
  const requestRows = requests.length ? requests.map((item) => `<tr class="clickable request-row" data-id="${item.id}"><td><strong>SR-${String(item.number).padStart(5, '0')}</strong><div class="text-soft">${esc(item.title || item.description || 'Без описания')}</div></td><td>${esc(item.client_name || '—')}<div class="text-soft">${esc(item.site_name || '')}</div></td><td>${esc(item.equipment_name)}<div class="text-soft mono">${esc(item.serial_number)}</div></td><td>${esc(item.assigned_technician_name || 'Не назначен')}</td><td>${requestBadge(item)}</td></tr>`).join('') : '<tr class="empty-row"><td colspan="5">Заявок пока нет</td></tr>';
  const requestCards = requests.length ? requests.map((item) => `<button class="mobile-info-card request-card request-row" data-id="${item.id}"><div class="mobile-card-top"><span class="request-number">SR-${String(item.number).padStart(5, '0')}</span>${requestBadge(item)}</div><strong>${esc(item.title || item.description || 'Без описания')}</strong><span class="text-soft">${esc(item.equipment_name || 'Оборудование не указано')} · <span class="mono">${esc(item.serial_number || '—')}</span></span><div class="request-card-detail"><span>${esc(item.client_name || 'Клиент не указан')}<small>${esc(item.site_name || 'Объект не указан')}</small></span><span class="assigned-master">${esc(item.assigned_technician_name || 'Мастер не назначен')}</span></div></button>`).join('') : '<div class="mobile-empty">Заявок пока нет</div>';
  content.innerHTML = `<div class="page-header"><div><h1>Заявки</h1><div class="page-subtitle">Единый путь обращения: от QR до сервисного акта</div></div></div><div class="card mobile-table" style="padding:0"><table><thead><tr><th>№ / проблема</th><th>Клиент и объект</th><th>Оборудование</th><th>Мастер</th><th>Статус</th></tr></thead><tbody>${requestRows}</tbody></table></div><div class="mobile-card-list" id="request-cards">${requestCards}</div>`;
  content.querySelectorAll('.request-row').forEach((row) => row.addEventListener('click', () => navigateToServiceRequest(row.dataset.id)));
}

const CLIENT_STATUS = { new: 'Заявка принята', assigned: 'Мастер назначен', on_the_way: 'Мастер в пути', arrived: 'Мастер прибыл', in_progress: 'В работе', waiting_parts: 'Ожидание запчастей', waiting_approval: 'Требуется согласование', completed: 'Ремонт выполнен', closed: 'Заявка закрыта', cancelled: 'Заявка отменена' };
const clientBadge = (status) => `<span class="badge badge-${['completed','closed'].includes(status) ? 'good' : status === 'waiting_approval' ? 'amber' : status === 'cancelled' ? 'idle' : 'warn'}"><span class="badge-dot"></span>${esc(CLIENT_STATUS[status] || status)}</span>`;

async function renderClientPulse(content) {
  const data = await api('/client-portal/dashboard');
  content.innerHTML = `<section class="client-home"><div class="page-header"><div><span class="client-kicker">FIXIT PULSE</span><h1>Добрый день</h1><div class="page-subtitle">${esc(data.client_name)}</div></div></div><div class="client-summary-grid"><article><span>ОБОРУДОВАНИЕ</span><strong>${data.equipment_total}</strong><p>● ${data.working} работает<br>● ${data.needs_repair} в ремонте<br>● ${data.waiting_approval} ожидают согласования</p></article><article><span>ЗАЯВКИ</span><strong>${data.active_requests}</strong><p>активных<br>${data.approval_requests ? `<b>${data.approval_requests} требует вашего решения</b>` : 'Нет заявок, требующих согласования'}</p></article></div><div class="client-actions"><button class="btn btn-primary" id="client-new-request">+ Создать заявку</button><button class="btn btn-secondary" data-client-route="equipment">Оборудование</button><button class="btn btn-secondary" data-client-route="requests">Заявки</button><button class="btn btn-secondary" data-client-route="documents">Документы</button></div></section>`;
  content.querySelectorAll('[data-client-route]').forEach((button) => button.addEventListener('click', () => location.hash = button.dataset.clientRoute));
  content.querySelector('#client-new-request').addEventListener('click', () => openClientRequestForm());
}

async function renderClientRequests(content) {
  const requests = await api('/client-portal/requests');
  const cards = requests.length ? requests.map((item) => `<button class="client-request-card" data-client-request="${item.id}"><div><span>SR-${String(item.number).padStart(5,'0')}</span>${clientBadge(item.status)}</div><strong>${esc(item.title || item.description || 'Заявка')}</strong><p>${esc(item.equipment_name)} · ${esc(item.site_name || '')}</p><small>Создана: ${fmtDate(item.created_at)}</small></button>`).join('') : '<div class="client-empty">Нет активных заявок<br><small>✓ Всё оборудование работает</small></div>';
  content.innerHTML = `<div class="page-header"><div><h1>Заявки</h1><div class="page-subtitle">Что происходит с вашим сервисом</div></div><button class="btn btn-primary" id="client-new-request">+ Создать</button></div><div class="client-filter"><button class="active">Все</button><button>Активные</button><button>Ожидают меня</button><button>Завершённые</button></div><div class="client-request-list">${cards}</div>`;
  content.querySelector('#client-new-request').addEventListener('click', () => openClientRequestForm());
  content.querySelectorAll('[data-client-request]').forEach((button) => button.addEventListener('click', () => navigateToServiceRequest(button.dataset.clientRequest)));
}

async function renderClientRequest(content, id) {
  const item = await api(`/client-portal/requests/${id}`);
  const events = item.history.filter((entry) => ['request.created','technician.assigned','technician.arrived','work.started','request.waiting_parts','request.waiting_approval','approval.approved','approval.rejected','repair.completed','service_act.generated'].includes(entry.type));
  const timeline = events.map((entry) => `<div class="client-timeline-item"><i></i><div><strong>${esc(entry.type === 'approval.rejected' ? 'Согласование отклонено' : entry.type === 'approval.approved' ? 'Работы согласованы' : CLIENT_STATUS[entry.details?.to] || entry.message)}</strong>${entry.details?.comment ? `<p>${esc(entry.details.comment)}</p>` : ''}<small>${fmtDate(entry.at)}</small></div></div>`).join('') || '<div class="client-empty">История появится после начала работы.</div>';
  const approval = item.status === 'waiting_approval' && item.approval_target === 'client' ? `<section class="client-approval"><span>ТРЕБУЕТСЯ СОГЛАСОВАНИЕ</span><h3>Сервис просит подтвердить работы</h3><p>${esc(item.outcome || item.description || 'Откройте историю и фотографии для деталей.')}</p><button class="btn btn-secondary" id="client-reject">Отклонить</button><button class="btn btn-primary" id="client-approve">Согласовать</button></section>` : '';
  content.innerHTML = `<section class="client-request-detail"><button class="sr-back" id="client-back">← К заявкам</button><header><span>SR-${String(item.number).padStart(5,'0')}</span>${clientBadge(item.status)}</header><h1>${esc(item.title || item.description || 'Заявка')}</h1><section><h3>Оборудование</h3><strong>${esc(item.equipment_type || item.equipment_name)}</strong><p>${esc([item.manufacturer,item.model].filter(Boolean).join(' '))} · S/N ${esc(item.serial_number)}</p><small>${esc(item.site_name || '')}</small></section><section><h3>Проблема</h3><p>${esc(item.description || 'Описание не добавлено')}</p></section>${approval}<section><h3>Ход заявки</h3>${timeline}</section></section>`;
  content.querySelector('#client-back').addEventListener('click', () => location.hash = 'requests');
  const approve = async (action) => { const comment = action === 'rejected' ? prompt('Причина отказа (обязательно):') : prompt('Комментарий (необязательно):'); if (action === 'rejected' && !comment?.trim()) return; await api(`/client-portal/requests/${id}/approval`, { method: 'PATCH', body: JSON.stringify({ action, comment: comment || null }) }); await renderClientRequest(content, id); };
  content.querySelector('#client-approve')?.addEventListener('click', () => approve('approved'));
  content.querySelector('#client-reject')?.addEventListener('click', () => approve('rejected'));
}

async function renderClientEquipment(content) {
  const equipment = await api('/client-portal/equipment');
  const cards = equipment.length ? equipment.map((item) => `<button class="client-equipment-card" data-client-equipment="${item.id}">${item.primary_photo ? `<img data-client-equipment-photo="${item.id}" alt="Фото оборудования">` : '<div class="client-equipment-placeholder">FIXIT</div>'}<div><strong>${esc([item.manufacturer,item.model].filter(Boolean).join(' ') || item.name)}</strong><span>${esc(item.name)}</span><small>S/N ${esc(item.serial_number)} · ${esc(item.site_name)}</small>${clientBadge(item.status === 'needs_repair' ? 'in_progress' : 'completed')}</div></button>`).join('') : '<div class="client-empty">Нет оборудования на объекте</div>';
  const addButton = state.me.role === 'client_site_user' ? '<button class="btn btn-primary" id="client-add-equipment">+ Добавить оборудование</button>' : '';
  content.innerHTML = `<div class="page-header"><div><h1>Оборудование</h1><div class="page-subtitle">Моё оборудование и сервис</div></div>${addButton}</div><input class="client-search" placeholder="Поиск оборудования"><div class="client-equipment-list">${cards}</div>`;
  content.querySelector('#client-add-equipment')?.addEventListener('click', async () => { await ensureCustomers(true); openCreateEquipmentModal(); });
  content.querySelectorAll('[data-client-equipment]').forEach((button) => button.addEventListener('click', () => openClientRequestForm(button.dataset.clientEquipment)));
  content.querySelectorAll('[data-client-equipment-photo]').forEach((image) => apiBlob(`/equipment/${image.dataset.clientEquipmentPhoto}/photo`).then((blob) => { const url = URL.createObjectURL(blob); activeClientPhotoUrls.push(url); image.src = url; }).catch(() => image.remove()));
}

async function renderClientDocuments(content) {
  const documents = await api('/client-portal/documents');
  content.innerHTML = `<div class="page-header"><div><h1>Документы</h1><div class="page-subtitle">Сервисные акты и документы оборудования</div></div></div><div class="client-documents">${documents.length ? documents.map((item) => `<article><strong>Сервисный акт · SR-${String(item.number).padStart(5,'0')}</strong><span>${esc(item.equipment_name)} · ${esc(item.site_name)}</span><small>${fmtDate(item.closed_at)}</small><button class="btn btn-ghost btn-sm" data-client-act="${item.repair_id}">Скачать PDF</button></article>`).join('') : '<div class="client-empty">Нет документов</div>'}</div>`;
  content.querySelectorAll('[data-client-act]').forEach((button) => button.addEventListener('click', async () => downloadBlob(await apiBlob(`/repairs/${button.dataset.clientAct}/act.pdf`), 'service-act.pdf')));
}

async function openClientRequestForm(preselectedId = null) {
  const equipment = await api('/client-portal/equipment');
  const options = equipment.map((item) => `<option value="${item.id}" ${item.id === preselectedId ? 'selected' : ''}>${esc([item.manufacturer,item.model].filter(Boolean).join(' ') || item.name)} · ${esc(item.site_name)}</option>`).join('');
  const backdrop = openModal('Новая заявка', `<label>Оборудование<select id="client-request-equipment">${options}</select></label><label>Проблема<textarea id="client-request-problem" required placeholder="Что случилось?"></textarea></label><label>Приоритет<select id="client-request-priority"><option value="planned">Обычный</option><option value="urgent">Срочно</option></select></label>`, '<button class="btn btn-secondary" id="client-request-cancel">Отмена</button><button class="btn btn-primary" id="client-request-submit">Отправить</button>');
  backdrop.querySelector('#client-request-cancel').addEventListener('click', closeModal);
  backdrop.querySelector('#client-request-submit').addEventListener('click', async () => { const title = backdrop.querySelector('#client-request-problem').value.trim(); if (!title) return toast('Опишите проблему', 'error'); const result = await api('/client-portal/requests', { method: 'POST', body: JSON.stringify({ equipment_id: backdrop.querySelector('#client-request-equipment').value, title, description: title, priority: backdrop.querySelector('#client-request-priority').value }) }); closeModal(); navigateToServiceRequest(result.id); });
}

async function openServiceRequest(id) {
  if (!id) {
    toast('Не удалось определить заявку', 'error');
    return;
  }
  try {
    const item = await api(`/service-requests/${id}`);
    if (!item || !item.id) throw new Error('Сервис не вернул данные заявки');
    closeModal();
    if (state.me?.role === 'technician') return openTechnicianRequestWorkspace(id, item);
    return renderServiceRequestDetail(document.getElementById('content'), item);
  } catch (e) {
    toast(`Не удалось открыть заявку: ${e.message || 'неизвестная ошибка'}`, 'error');
  }
}

function renderServiceRequestDetail(content, item) {
    const historyItems = Array.isArray(item.history) ? item.history : [];
    const statusLabel = { new: 'Новая', assigned: 'Назначена', on_the_way: 'В пути', arrived: 'На объекте', in_progress: 'В работе', waiting_parts: 'Ждёт запчасти', waiting_approval: 'Требует согласования', completed: 'Выполнена', closed: 'Закрыта', cancelled: 'Отменена' };
    const statusClass = ['completed', 'closed'].includes(item.status) ? 'good' : item.status?.startsWith('waiting') ? 'amber' : item.status === 'cancelled' ? 'idle' : 'warn';
    const statusBadge = `<span class="badge badge-${statusClass}"><span class="badge-dot"></span>${esc(statusLabel[item.status] || item.status || '—')}</span>`;
    const approvalEvent = [...historyItems].reverse().find((entry) => entry.type === 'request.waiting_approval');
    const approval = approvalEvent?.details?.approval || {};
    const actorRole = (role) => ({ technician: 'МАСТЕР', dispatcher: 'ДИСПЕТЧЕР', admin: 'АДМИНИСТРАТОР', owner: 'АДМИНИСТРАТОР' }[role] || 'СИСТЕМА');
    const timelineCopy = (entry) => {
      const details = entry.details || {};
      if (entry.type === 'approval.approved') return { title: 'Работы согласованы', extra: details.comment ? `Комментарий: ${details.comment}` : '' };
      if (entry.type === 'approval.rejected') return { title: 'Согласование отклонено', extra: details.comment ? `Причина: ${details.comment}` : '' };
      if (entry.type === 'request.waiting_parts') return { title: 'Мастер приостановил работу', extra: 'Причина: Ожидание запчастей' };
      if (entry.type === 'request.waiting_approval') {
        const approvalDetails = details.approval || {};
        return { title: 'Мастер запросил согласование', extra: [
          approvalDetails.diagnostic && `Диагностика: ${approvalDetails.diagnostic}`,
          approvalDetails.work && `Предлагаемые работы: ${approvalDetails.work}`,
          approvalDetails.parts?.length && `Запчасти: ${approvalDetails.parts.map((part) => `${part.name} ×${part.quantity}`).join(', ')}`,
          approvalDetails.comment && `Комментарий: ${approvalDetails.comment}`,
          approvalDetails.photo_count ? `Фото: ${approvalDetails.photo_count}` : '',
        ].filter(Boolean).join(' · ') };
      }
      if (entry.type === 'work.started' && details.from === 'waiting_parts') return { title: 'Мастер возобновил работу после получения запчастей', extra: '' };
      if (entry.type === 'work.started' && details.from === 'waiting_approval') return { title: 'Работы согласованы — мастер продолжил ремонт', extra: '' };
      return { title: entry.message || 'Событие заявки', extra: '' };
    };
    const history = historyItems.map((entry) => {
      const copy = timelineCopy(entry); const actor = entry.actor;
      return `<article class="sr-timeline-entry"><div class="sr-timeline-dot"></div><div><span class="sr-timeline-role">${actorRole(actor?.role)}</span><strong>${esc(actor?.full_name || 'Система')}</strong><p>${esc(copy.title)}</p>${copy.extra ? `<small>${esc(copy.extra)}</small>` : ''}<time>${fmtDate(entry.at)}</time></div></article>`;
    }).join('') || '<div class="passport-empty">История пока пуста</div>';
    const repairPhotos = (item.attachments || []).filter((attachment) => ['before', 'after'].includes(attachment.kind));
    const requestPhotos = (item.request_attachments || []).filter((attachment) => String(attachment.media_type || '').startsWith('image/'));
    const repairGallery = repairPhotos.length ? `<div class="sr-photo-grid">${repairPhotos.map((attachment) => `<button type="button" class="sr-photo-thumb" data-repair-photo="${attachment.id}"><span>${attachment.kind === 'before' ? 'До ремонта' : 'После ремонта'}</span><img alt="${attachment.kind === 'before' ? 'До ремонта' : 'После ремонта'}"></button>`).join('')}</div>` : '';
    const requestGallery = requestPhotos.length ? `<div class="sr-photo-grid sr-request-photo-grid">${requestPhotos.map((attachment) => `<button type="button" class="sr-photo-thumb" data-request-photo="${attachment.id}"><span>${attachment.kind === 'approval' ? 'Для согласования' : 'К заявке'}</span><img alt="Фото заявки"></button>`).join('')}</div>` : '';
    const mediaGallery = requestGallery || repairGallery ? `${requestGallery}${repairGallery}` : '<div class="sr-empty">Фотографии пока не добавлены</div>';
    const equipmentPhoto = item.primary_photo ? `<button type="button" class="sr-equipment-photo" id="sr-equipment-photo"><img alt="Фото оборудования"><span>Открыть фото</span></button>` : '<div class="sr-equipment-placeholder">FIXIT<br>оборудование</div>';
    const rejected = [...historyItems].reverse().find((entry) => entry.type === 'approval.rejected');
    const rejectionNotice = item.status === 'cancelled' && rejected ? `<section class="sr-rejection"><strong>Согласование отклонено диспетчером</strong>${rejected.details?.comment ? `<span>Причина: ${esc(rejected.details.comment)}</span>` : ''}</section>` : '';
    const approvalPhotos = requestPhotos.filter((attachment) => attachment.kind === 'approval');
    const approvalContext = item.status === 'waiting_approval' ? `<section class="approval-context"><span>Требуется согласование</span><strong>${esc(item.equipment_name || 'Оборудование')}</strong><p>Проблема: ${esc(item.description || 'Не указана')}</p><p>Диагностика: ${esc(approval.diagnostic || 'Не указана')}</p><p>Предлагаемые работы: ${esc(approval.work || 'Не указаны')}</p><p>Запчасти: ${esc((approval.parts || []).map((part) => `${part.name} ×${part.quantity}`).join(', ') || 'Не выбраны')}</p><p>Комментарий мастера: ${esc(approval.comment || 'Не указан')}</p>${approvalPhotos.length ? `<p>Фотографии для согласования: ${approvalPhotos.length}</p><div class="sr-photo-grid sr-approval-photo-grid">${approvalPhotos.map((attachment) => `<button type="button" class="sr-photo-thumb" data-request-photo="${attachment.id}"><span>Для согласования</span><img alt="Фото для согласования"></button>`).join('')}</div>` : '<p>Фотографии не добавлены</p>'}</section>` : '';
    const approvalActions = item.status === 'waiting_approval' && ['admin', 'dispatcher'].includes(state.me?.role) ? '<button class="btn btn-secondary" id="approval-reject">Отклонить</button><button class="btn btn-primary" id="approval-approve">Согласовать</button>' : '';
    if (activeServiceRequestDetailCleanup) activeServiceRequestDetailCleanup();
    const objectUrls = new Set();
    activeServiceRequestDetailCleanup = () => {
      objectUrls.forEach((url) => URL.revokeObjectURL(url));
      objectUrls.clear();
    };
    content.innerHTML = `<section class="service-request-screen"><button class="sr-back" id="request-detail-back">← <span>К заявкам</span></button><section class="service-request-detail"><header class="sr-detail-header"><div><span>SR-${String(item.number).padStart(5, '0')}</span><h2>Заявка на сервис</h2></div>${statusBadge}</header>${rejectionNotice}<section class="sr-equipment-hero">${equipmentPhoto}<div><span class="sr-kicker">${esc(item.equipment_type || item.equipment_name || 'Оборудование')}</span><h3>${esc([item.manufacturer, item.model].filter(Boolean).join(' ') || item.equipment_name || 'Оборудование')}</h3><p>S/N ${esc(item.serial_number || '—')}</p></div></section><section class="sr-detail-grid"><div><span>Клиент / объект</span><strong>${esc(item.client_name || 'Клиент не указан')}</strong><small>${esc(item.site_name || 'Объект не указан')}</small></div><div><span>Мастер</span><strong>${esc(item.assigned_technician_name || 'Не назначен')}</strong></div></section><section class="sr-problem"><span>Проблема</span><p>${esc(item.description || 'Без описания')}</p></section>${approvalContext}<section class="sr-photos"><h3>Фотографии</h3>${mediaGallery}</section><section class="sr-timeline"><h3>Ход заявки</h3>${history}</section>${approvalActions ? `<footer class="sr-detail-actions">${approvalActions}</footer>` : ''}</section></section>`;
    content.querySelector('#request-detail-back').addEventListener('click', () => { location.hash = 'requests'; });
    if (item.primary_photo) {
      apiBlob(`/equipment/${item.equipment_id}/photo`).then((blob) => {
        const image = content.querySelector('#sr-equipment-photo img');
        if (!image) return;
        const url = URL.createObjectURL(blob); objectUrls.add(url); image.src = url;
      }).catch(() => {});
      content.querySelector('#sr-equipment-photo')?.addEventListener('click', () => openProtectedImage(`/equipment/${item.equipment_id}/photo`, 'Фото оборудования'));
    }
    content.querySelectorAll('[data-repair-photo]').forEach((button) => {
      const attachment = repairPhotos.find((photo) => photo.id === button.dataset.repairPhoto);
      apiBlob(`/repairs/attachments/${button.dataset.repairPhoto}`).then((blob) => {
        const image = button.querySelector('img'); if (!image) return;
        const url = URL.createObjectURL(blob); objectUrls.add(url); image.src = url;
      }).catch(() => { button.classList.add('is-unavailable'); });
      button.addEventListener('click', () => openProtectedImage(`/repairs/attachments/${attachment.id}`, attachment.kind === 'before' ? 'До ремонта' : 'После ремонта'));
    });
    content.querySelectorAll('[data-request-photo]').forEach((button) => {
      const attachment = requestPhotos.find((photo) => photo.id === button.dataset.requestPhoto);
      apiBlob(`/service-requests/attachments/${button.dataset.requestPhoto}`).then((blob) => {
        const image = button.querySelector('img'); if (!image) return;
        const url = URL.createObjectURL(blob); objectUrls.add(url); image.src = url;
      }).catch(() => { button.classList.add('is-unavailable'); });
      button.addEventListener('click', () => openProtectedImage(`/service-requests/attachments/${attachment.id}`, attachment.kind === 'approval' ? 'Фото для согласования' : 'Фото заявки'));
    });
    const decideApproval = (action) => openApprovalDialog(action, async (comment) => {
      await api(`/service-requests/${item.id}/approval`, { method: 'PATCH', body: JSON.stringify({ action, comment }) });
      await openServiceRequest(item.id);
    });
    content.querySelector('#approval-approve')?.addEventListener('click', () => decideApproval('approved'));
    content.querySelector('#approval-reject')?.addEventListener('click', () => decideApproval('rejected'));
}

async function openTechnicianRequestWorkspace(id, loadedRequest = null) {
  const content = document.getElementById('content');
  let request = loadedRequest;
  if (!request) {
    try { request = await api(`/service-requests/${id}`); } catch (e) { return toast(`Не удалось открыть заявку: ${e.message}`, 'error'); }
  }
  request.history = Array.isArray(request.history) ? request.history : [];
  request.attachments = Array.isArray(request.attachments) ? request.attachments : [];
  let equipmentPhotoUrl = null;
  if (request.primary_photo) {
    try { equipmentPhotoUrl = URL.createObjectURL(await apiBlob(`/equipment/${request.equipment_id}/photo`)); } catch (_) {}
  }
  const draft = { diagnostic: '', work: '', comment: '', usedParts: {}, photos: [] };
  const draftKey = requestDraftKey(request.id);
  const persistedDraft = await RequestDraftStore.get(draftKey).catch(() => null);
  if (persistedDraft) {
    draft.diagnostic = persistedDraft.diagnostic || '';
    draft.work = persistedDraft.work || '';
    draft.comment = persistedDraft.comment || '';
    draft.usedParts = persistedDraft.usedParts || {};
    draft.photos = (persistedDraft.photos || []).map(normalizeDraftPhoto).filter(Boolean);
  }
  let completionLocalUuid = persistedDraft?.completionLocalUuid || null;
  let completionRepairId = persistedDraft?.completionRepairId || null;
  let completionQueued = persistedDraft?.completionQueued || false;
  let completionSync = { repairPending: false, attachmentsPending: 0, fullySynced: true, repairId: null };
  let completionInFlight = false;
  let draftCompleted = false;
  let attachmentPhotoUrls = [];
  const statusText = { assigned: 'Назначена', on_the_way: 'В пути', arrived: 'На объекте', in_progress: 'В работе', waiting_parts: 'Ждёт запчасти', waiting_approval: 'Ждёт согласование', completed: 'Выполнена' };
  // ``arrived`` is only a compatibility row from older deployments; new work
  // starts directly after the technician confirms the trip.
  const statusAction = { assigned: ['on_the_way', 'Выехал'], on_the_way: ['in_progress', 'Начать работу'], arrived: ['in_progress', 'Начать работу'] };
  const statusBadge = () => `<span class="badge badge-${request.status === 'completed' ? 'good' : request.status.startsWith('waiting') ? 'amber' : 'warn'}"><span class="badge-dot"></span>${esc(statusText[request.status] || request.status)}</span>`;
  const eventLabels = { 'request.created': 'Заявка создана', 'technician.assigned': 'Мастер назначен', 'technician.on_the_way': 'Мастер выехал', 'technician.arrived': 'Мастер прибыл на объект', 'work.started': 'Работа начата', 'parts.used': 'Использованы запчасти', 'photos.added': 'Добавлены фотографии', 'request.waiting_parts': 'Ожидание запчастей', 'request.waiting_approval': 'Ожидание согласования', 'repair.completed': 'Ремонт завершён', 'service_act.generated': 'Сервисный акт сформирован' };
  const workStatuses = new Set(['in_progress', 'waiting_parts', 'waiting_approval']);
  let stock = workStatuses.has(request.status) ? await api('/warehouses/mine/stock').catch(() => []) : [];
  const rememberDraft = () => {
    draft.diagnostic = content.querySelector('#request-diagnostic')?.value ?? draft.diagnostic;
    draft.work = content.querySelector('#request-work')?.value ?? draft.work;
    draft.comment = content.querySelector('#request-comment')?.value ?? draft.comment;
  };
  const persistDraft = async () => {
    if (draftCompleted) return;
    rememberDraft();
    await RequestDraftStore.put({ key: draftKey, diagnostic: draft.diagnostic, work: draft.work, comment: draft.comment, usedParts: draft.usedParts, photos: draft.photos.filter(hasDraftPhotoFile).map(({ file, approvalAttachmentId }) => ({ blob: file, name: file.name, type: file.type, approvalAttachmentId })), completionLocalUuid, completionRepairId, completionQueued, timestamp: new Date().toISOString() }).catch(() => null);
  };
  const releasePhotos = () => draft.photos.forEach((photo) => URL.revokeObjectURL(photo.url));
  let workCameraStream = null;
  const stopWorkCamera = () => { workCameraStream?.getTracks().forEach((track) => track.stop()); workCameraStream = null; };
  const disposeWorkspace = () => { persistDraft(); stopWorkCamera(); releasePhotos(); attachmentPhotoUrls.forEach((url) => URL.revokeObjectURL(url)); attachmentPhotoUrls = []; if (equipmentPhotoUrl) URL.revokeObjectURL(equipmentPhotoUrl); window.removeEventListener('fixit-offline-sync', onOfflineSync); window.removeEventListener('pagehide', persistOnBackground); document.removeEventListener('visibilitychange', persistOnBackground); };
  const persistOnBackground = (lifecycleEvent) => { if (document.visibilityState === 'hidden' || lifecycleEvent?.type === 'pagehide') persistDraft(); };
  const addDraftFiles = async (files) => {
    const available = 5 - draft.photos.length;
    for (const file of [...files].slice(0, available)) {
      const optimized = await optimizePhoto(file);
      const photo = normalizeDraftPhoto({ file: optimized, name: optimized.name, type: optimized.type }, draft.photos.length);
      if (photo) draft.photos.push(photo);
    }
    await persistDraft();
    draw();
  };
  const openWorkCamera = async () => {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) return content.querySelector('#request-gallery')?.click();
    await persistDraft();
    const backdrop = openModal('Добавить фото', '<div class="tech-camera"><video id="work-camera-video" autoplay muted playsinline></video><p id="work-camera-hint">Включаем заднюю камеру…</p><div id="work-camera-count"></div></div>', '<button class="btn btn-secondary" id="work-camera-close">Закрыть</button><button class="btn btn-primary" id="work-camera-capture">Сфотографировать</button>');
    const video = backdrop.querySelector('#work-camera-video');
    const hint = backdrop.querySelector('#work-camera-hint');
    const refreshCount = () => { backdrop.querySelector('#work-camera-count').textContent = `${draft.photos.length} из 5 фото`; backdrop.querySelector('#work-camera-capture').disabled = draft.photos.length >= 5; };
    const closeCamera = () => { stopWorkCamera(); closeModal(); };
    backdrop.querySelector('#work-camera-close').addEventListener('click', closeCamera);
    backdrop.addEventListener('click', (event) => { if (event.target === backdrop) stopWorkCamera(); });
    try {
      workCameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
      video.srcObject = workCameraStream;
      hint.textContent = 'Наведите камеру и сделайте снимок.';
      refreshCount();
    } catch (error) {
      hint.textContent = 'Камера недоступна. Выберите фото из галереи.';
      backdrop.querySelector('#work-camera-capture').disabled = true;
    }
    backdrop.querySelector('#work-camera-capture').addEventListener('click', () => {
      if (!video.videoWidth || draft.photos.length >= 5) return;
      const canvas = document.createElement('canvas'); canvas.width = video.videoWidth; canvas.height = video.videoHeight;
      canvas.getContext('2d').drawImage(video, 0, 0);
      canvas.toBlob(async (blob) => { if (!blob) return toast('Не удалось сохранить снимок', 'error'); await addDraftFiles([new File([blob], `photo-${Date.now()}.jpg`, { type: 'image/jpeg' })]); refreshCount(); }, 'image/jpeg', .88);
    });
  };
  const openEquipmentPhotoPicker = () => {
    persistDraft();
    const backdrop = openModal('Фото оборудования', '<div class="equipment-photo-picker"><div class="equipment-photo-picker-preview" id="equipment-photo-preview">FIXIT</div><p>Снимите машину или выберите фотографию из галереи.</p><input id="equipment-photo-camera" type="file" accept="image/*" capture="environment" hidden><input id="equipment-photo-gallery" type="file" accept="image/*" hidden></div>', '<label class="btn btn-secondary" for="equipment-photo-gallery">Из галереи</label><label class="btn btn-secondary" for="equipment-photo-camera">Сфотографировать</label><button class="btn btn-primary" id="equipment-photo-save" disabled>Сохранить</button>');
    let selected = null;
    let selectedUrl = null;
    const choose = async (file) => {
      if (!file) return;
      if (selectedUrl) URL.revokeObjectURL(selectedUrl);
      selected = await optimizePhoto(file);
      selectedUrl = URL.createObjectURL(selected);
      backdrop.querySelector('#equipment-photo-preview').innerHTML = `<img src="${selectedUrl}" data-object-url alt="Новое фото оборудования">`;
      backdrop.querySelector('#equipment-photo-save').disabled = false;
    };
    backdrop.querySelector('#equipment-photo-camera').addEventListener('change', (event) => choose(event.target.files?.[0]));
    backdrop.querySelector('#equipment-photo-gallery').addEventListener('change', (event) => choose(event.target.files?.[0]));
    backdrop.querySelector('#equipment-photo-save').addEventListener('click', async () => {
      if (!selected) return;
      const button = backdrop.querySelector('#equipment-photo-save'); button.disabled = true;
      try {
        await uploadEquipmentPhoto(request.equipment_id, selected);
        if (equipmentPhotoUrl) URL.revokeObjectURL(equipmentPhotoUrl);
        equipmentPhotoUrl = URL.createObjectURL(await apiBlob(`/equipment/${request.equipment_id}/photo`));
        request.primary_photo = { id: 'updated' };
        closeModal(); draw(); toast('Фото оборудования обновлено');
      } catch (error) { button.disabled = false; toast(error.message || 'Не удалось загрузить фото оборудования', 'error'); }
    });
  };
  const refreshCompletionSync = async () => {
    if (!window.FixitOffline) return completionSync;
    completionSync = await window.FixitOffline.queueStatus(completionLocalUuid || { serviceRequestId: request.id });
    completionLocalUuid ||= completionSync.localUuid;
    completionRepairId ||= completionSync.repairId;
    completionQueued ||= Boolean(completionLocalUuid && !completionSync.fullySynced);
    return completionSync;
  };
  const refreshCompletedRequest = async () => {
    request = await api(`/service-requests/${request.id}`);
    request.history = Array.isArray(request.history) ? request.history : [];
    request.attachments = Array.isArray(request.attachments) ? request.attachments : [];
    request.request_attachments = Array.isArray(request.request_attachments) ? request.request_attachments : [];
  };
  const completeWithOfflineQueue = async () => {
    rememberDraft();
    if (!draft.work.trim()) return toast('Опишите выполненные работы', 'error');
    if (completionInFlight) return;
    completionInFlight = true;
    const parts_used = Object.entries(draft.usedParts).filter(([, quantity]) => quantity > 0).map(([part_id, quantity]) => ({ part_id, quantity }));
    const started = request.history.find((item) => item.type === 'work.started')?.at || new Date().toISOString();
    try {
      completionLocalUuid ||= window.FixitOffline?.uuid?.() || createUuid();
      await persistDraft();
      if (!window.FixitOffline) throw new Error('Офлайн-движок недоступен; обновите приложение');
      const payload = { local_uuid: completionLocalUuid, equipment_id: request.equipment_id, service_request_id: request.id, fault_type: draft.diagnostic.trim() || null, description: [draft.diagnostic.trim() && `Диагностика: ${draft.diagnostic.trim()}`, `Работы: ${draft.work.trim()}`, draft.comment.trim() && `Комментарий: ${draft.comment.trim()}`].filter(Boolean).join('\n'), labor_minutes: 0, client_signer_name: null, client_signed_at: null, started_at: started, closed_at: new Date().toISOString(), device_updated_at: new Date().toISOString(), base_equipment_version: request.equipment_version || 1, parts_used };
      if (!completionQueued) {
        await window.FixitOffline.enqueueRepair(payload, draft.photos.map((photo) => ({ file: photo.file, kind: 'after' })));
        completionQueued = true;
        // The blobs now have their own durable lifecycle in pendingAttachments.
        // Do not retain a second fragile copy in the UI draft after queuing.
        releasePhotos();
        draft.photos = [];
        await RequestDraftStore.remove(draftKey).catch(() => null);
      }
      const syncResult = await window.FixitOffline.sync({ token: state.token, deviceId: 'fixit-pulse', onError: () => null });
      const result = syncResult.results.get(completionLocalUuid);
      completionSync = await refreshCompletionSync();
      if (!result || result.resolved_as === 'failed') {
        toast(navigator.onLine ? 'Ремонт сохранён локально и будет повторён автоматически.' : 'Ремонт и фото сохранены на устройстве и будут отправлены при появлении сети.', 'info');
        draw();
        return;
      }
      completionRepairId = result.server_id;
      await refreshCompletedRequest();
      if (completionSync.attachmentsPending) {
        toast(`Работа завершена · ${completionSync.attachmentsPending} фото ожидают отправки`, 'info');
      } else {
        draftCompleted = true;
        await RequestDraftStore.remove(draftKey).catch(() => null);
        toast('Работы завершены, сервисный акт сформирован');
      }
      draw();
    } catch (error) { toast(error.message || 'Не удалось завершить работы', 'error'); }
    finally { completionInFlight = false; }
  };
  const draw = () => {
    attachmentPhotoUrls.forEach((url) => URL.revokeObjectURL(url));
    attachmentPhotoUrls = [];
    const timeline = request.history.map((item) => {
      const resumedAfterParts = item.type === 'work.started' && item.details?.from === 'waiting_parts';
      const resumedAfterApproval = item.type === 'work.started' && item.details?.from === 'waiting_approval';
      const label = resumedAfterParts ? 'Работа возобновлена после ожидания запчастей' : resumedAfterApproval ? 'Работа возобновлена после согласования' : eventLabels[item.type] || item.message;
      return `<div class="tech-request-timeline"><span></span><div><strong>${esc(label)}</strong><small>${fmtDate(item.at)}</small></div></div>`;
    }).join('');
    const repairPhotos = (request.attachments || []).filter((item) => ['before', 'after'].includes(item.kind) && String(item.media_type || '').startsWith('image/'));
    const repairDocuments = (request.attachments || []).filter((item) => !repairPhotos.includes(item));
    const attachments = repairPhotos.length ? `<div class="tech-request-saved-photo-grid">${repairPhotos.map((item) => `<button type="button" data-repair-photo="${item.id}"><img alt="${item.kind === 'before' ? 'До ремонта' : 'После ремонта'}"><span>${item.kind === 'before' ? 'До ремонта' : 'После ремонта'}</span></button>`).join('')}</div>${repairDocuments.map((item) => `<button class="tech-request-file" data-attachment="${item.id}">Документ · ${esc(item.name || 'вложение')}</button>`).join('')}` : repairDocuments.length ? repairDocuments.map((item) => `<button class="tech-request-file" data-attachment="${item.id}">Документ · ${esc(item.name || 'вложение')}</button>`).join('') : '<div class="tech-request-empty">Фотографии пока не добавлены</div>';
    const parts = stock.length ? stock.map((part) => `<div class="tech-request-part"><span><b>${esc(part.name)}</b><small>${esc(part.article)} · остаток ${part.quantity}</small></span><div><button type="button" data-part-minus="${part.part_id}">−</button><b id="part-${part.part_id}">${draft.usedParts[part.part_id] || 0}</b><button type="button" data-part-plus="${part.part_id}" ${(draft.usedParts[part.part_id] || 0) >= part.quantity ? 'disabled' : ''}>+</button></div></div>`).join('') : '<div class="tech-request-empty">На мобильном складе нет доступных запчастей</div>';
    const isWorkStatus = workStatuses.has(request.status);
    const syncNotice = completionQueued && !completionSync.fullySynced
      ? `<div class="tech-request-sync ${completionSync.repairPending ? 'pending' : 'attachments'}">${completionSync.repairPending ? '⟳ Работа сохранена на устройстве и будет отправлена автоматически' : `⟳ Работа завершена · ${completionSync.attachmentsPending} фото ожидают отправки`}</div>`
      : completionQueued && completionSync.fullySynced ? '<div class="tech-request-sync synced">✓ Синхронизировано</div>' : '';
    const waitingBanner = request.status === 'waiting_parts' ? '<div class="tech-request-state-banner"><strong>Ожидаем запчасти</strong><span>Черновик работ сохранён. После поступления запчастей продолжите работу.</span></div>' : request.status === 'waiting_approval' ? '<div class="tech-request-state-banner"><strong>Ожидается согласование</strong><span>После согласования диспетчер вернёт заявку в работу.</span></div>' : '';
    const photoPreview = draft.photos.length ? `<div class="tech-request-photo-grid">${draft.photos.map((photo, index) => `<figure><img src="${esc(photo.url)}" alt="Фото ${index + 1}"><figcaption>Фото ${index + 1}<button type="button" data-photo-remove="${index}" aria-label="Удалить фото ${index + 1}">×</button></figcaption></figure>`).join('')}</div><div class="tech-request-photo-count">Выбрано ${draft.photos.length} из 5</div>` : '<div class="tech-request-empty">Фотографии пока не выбраны</div>';
    const workArea = isWorkStatus ? `<section class="tech-request-section tech-request-work">${waitingBanner}<h2>Рабочая зона</h2><label>Диагностика<textarea id="request-diagnostic" placeholder="Что обнаружено">${esc(draft.diagnostic)}</textarea></label><label>Выполненные работы<textarea id="request-work" placeholder="Что сделано">${esc(draft.work)}</textarea></label><label>Комментарий<textarea id="request-comment" placeholder="Комментарий для диспетчера">${esc(draft.comment)}</textarea></label><h3>Использованные запчасти</h3>${parts}<h3>Фотографии</h3>${photoPreview}<div class="tech-request-photo-actions"><button type="button" class="tech-request-photo-add" id="request-camera">Добавить фото</button><button type="button" class="btn btn-ghost btn-sm" id="request-gallery-open">Выбрать из галереи</button><input id="request-gallery" type="file" accept="image/*" multiple hidden></div>${request.status === 'in_progress' ? '<div class="tech-request-secondary"><button type="button" id="request-wait-parts">Жду запчасти</button><button type="button" id="request-wait-approval">Жду согласование</button></div>' : ''}</section>` : '';
    const nextAction = statusAction[request.status];
    const action = nextAction
      ? `<button class="btn btn-primary tech-request-main" id="request-next" data-status="${nextAction[0]}">${nextAction[1]}</button>`
      : request.status === 'in_progress' && completionQueued ? '<button class="btn btn-primary tech-request-main" id="request-retry-sync">Повторить синхронизацию</button>'
      : request.status === 'in_progress' ? '<button class="btn btn-primary tech-request-main" id="request-complete">Завершить работу</button>'
      : request.status === 'waiting_parts' ? '<button class="btn btn-primary tech-request-main" id="request-resume">Продолжить работу</button>'
      : request.status === 'completed' && completionQueued && !completionSync.fullySynced ? '<button class="btn btn-primary tech-request-main" id="request-retry-sync">Повторить отправку фото</button>' : '';
    content.innerHTML = `<section class="tech-request-workspace"><header class="tech-request-header"><button class="tech-request-back" id="request-back">←</button><div><span>Заявка SR-${String(request.number).padStart(5, '0')}</span><h1>${esc(request.title || request.description || 'Сервисная заявка')}</h1></div>${statusBadge()}</header><div class="tech-request-scroll"><section class="tech-request-meta"><div><small>Приоритет</small><strong>${request.priority === 'urgent' ? 'Срочно' : 'Плановая'}</strong></div><div><small>Создана</small><strong>${fmtDate(request.created_at)}</strong></div></section>${syncNotice}<section class="tech-request-section"><h2>Клиент и объект</h2><strong>${esc(request.client_name || request.site_name || 'Клиент')}</strong><p>${esc(request.site_name || 'Объект не указан')}${request.site_address ? ` · ${esc(request.site_address)}` : ''}</p>${request.contact_name || request.contact_phone ? `<a href="tel:${esc(request.contact_phone || '')}">${esc(request.contact_name || 'Контакт')} · ${esc(request.contact_phone || '')}</a>` : ''}</section><section class="tech-request-section tech-request-equipment"><div><h2>Оборудование</h2><div><button class="btn btn-ghost btn-sm" id="request-equipment-photo">Фото оборудования</button><button class="btn btn-ghost btn-sm" id="request-passport">Открыть паспорт</button></div></div>${equipmentPhotoUrl ? `<img class="tech-request-equipment-photo" src="${equipmentPhotoUrl}" alt="Фото оборудования">` : '<div class="tech-request-equipment-placeholder">FIXIT</div>'}<strong>${esc(request.equipment_type || request.equipment_name)}</strong><p>${esc([request.manufacturer, request.model].filter(Boolean).join(' ') || 'Модель не указана')} · <span class="mono">S/N ${esc(request.serial_number)}</span></p>${badge(EQUIPMENT_STATUS, request.equipment_status || 'working')}</section><section class="tech-request-section"><h2>Проблема</h2><p>${esc(request.description || 'Описание не добавлено')}</p><div class="tech-request-files">${attachments}</div></section>${workArea}<section class="tech-request-section"><h2>История</h2><div class="tech-request-timeline-list">${timeline}</div></section></div><footer>${action}</footer></section>`;
    content.querySelector('#request-back').addEventListener('click', () => { disposeWorkspace(); activeTechnicianWorkspaceCleanup = null; location.hash = 'requests'; });
    content.querySelector('#request-passport').addEventListener('click', () => openEquipmentPassport(request.equipment_id));
    content.querySelector('#request-equipment-photo')?.addEventListener('click', openEquipmentPhotoPicker);
    content.querySelectorAll('[data-repair-photo]').forEach((button) => {
      const attachment = repairPhotos.find((item) => item.id === button.dataset.repairPhoto);
      apiBlob(`/repairs/attachments/${attachment.id}`).then((blob) => {
        const image = button.querySelector('img'); if (!image) return;
        const url = URL.createObjectURL(blob); attachmentPhotoUrls.push(url); image.src = url;
      }).catch(() => { button.classList.add('is-unavailable'); });
      button.addEventListener('click', () => openProtectedImage(`/repairs/attachments/${attachment.id}`, attachment.kind === 'before' ? 'До ремонта' : 'После ремонта'));
    });
    content.querySelectorAll('[data-attachment]').forEach((button) => button.addEventListener('click', async () => { try { downloadBlob(await apiBlob(`/repairs/attachments/${button.dataset.attachment}`), button.textContent.trim()); } catch (e) { toast(e.message, 'error'); } }));
    const transition = async (status, note = null, details = null) => { rememberDraft(); await persistDraft(); try { request = await api(`/service-requests/${request.id}/status`, { method: 'PATCH', body: JSON.stringify({ status, note, details }) }); request.history = Array.isArray(request.history) ? request.history : []; request.attachments = Array.isArray(request.attachments) ? request.attachments : []; request.request_attachments = Array.isArray(request.request_attachments) ? request.request_attachments : []; if (workStatuses.has(status) && !stock.length) stock = await api('/warehouses/mine/stock').catch(() => []); draw(); } catch (e) { toast(`${e.message}. Заявка обновлена на сервере.`, 'error'); request = await api(`/service-requests/${request.id}`).catch(() => request); draw(); } };
    content.querySelector('#request-next')?.addEventListener('click', () => transition(content.querySelector('#request-next').dataset.status));
    content.querySelector('#request-resume')?.addEventListener('click', () => transition('in_progress'));
    content.querySelector('#request-retry-sync')?.addEventListener('click', async () => {
      if (completionInFlight) return;
      completionInFlight = true;
      try {
        const syncResult = await window.FixitOffline.sync({ token: state.token, deviceId: 'fixit-pulse', onError: () => null });
        const result = syncResult.results.get(completionLocalUuid);
        completionRepairId ||= result?.server_id || null;
        completionSync = await refreshCompletionSync();
        if (!completionSync.repairPending) await refreshCompletedRequest();
        if (completionSync.fullySynced) { draftCompleted = true; await RequestDraftStore.remove(draftKey).catch(() => null); toast('Ремонт и фотографии синхронизированы'); }
        else toast(completionSync.repairPending ? 'Работа всё ещё ожидает отправки' : `${completionSync.attachmentsPending} фото ожидают отправки`, 'info');
        draw();
      } catch (error) { toast(error.message || 'Не удалось синхронизировать фото', 'error'); }
      finally { completionInFlight = false; }
    });
    content.querySelector('#request-wait-parts')?.addEventListener('click', () => { rememberDraft(); transition('waiting_parts', draft.comment.trim() || null); });
    content.querySelector('#request-wait-approval')?.addEventListener('click', async () => {
      rememberDraft();
      const pendingPhotos = draft.photos.filter((photo) => !photo.approvalAttachmentId && hasDraftPhotoFile(photo));
      if (pendingPhotos.length) {
        const uploads = await Promise.allSettled(pendingPhotos.map(async (photo) => {
          const form = new FormData(); form.append('kind', 'approval'); form.append('file', photo.file);
          const attachment = await api(`/service-requests/${request.id}/attachments`, { method: 'POST', body: form });
          photo.approvalAttachmentId = attachment.id;
        }));
        const failures = uploads.filter((upload) => upload.status === 'rejected').length;
        if (failures) { await persistDraft(); return toast(`Не удалось загрузить ${failures} фото для согласования. Заявка остаётся в работе.`, 'error'); }
        await persistDraft();
      }
      const parts = Object.entries(draft.usedParts).filter(([, quantity]) => quantity > 0).map(([partId, quantity]) => ({ name: stock.find((part) => part.part_id === partId)?.name || 'Запчасть', quantity }));
      transition('waiting_approval', 'Требуется согласование диспетчером', { approval: { diagnostic: draft.diagnostic, work: draft.work, comment: draft.comment, parts, photo_count: draft.photos.length } });
    });
    content.querySelectorAll('[data-part-plus]').forEach((button) => button.addEventListener('click', () => { rememberDraft(); const part = stock.find((item) => item.part_id === button.dataset.partPlus); if (!part) return; draft.usedParts[part.part_id] = Math.min(part.quantity, (draft.usedParts[part.part_id] || 0) + 1); draw(); }));
    content.querySelectorAll('[data-part-minus]').forEach((button) => button.addEventListener('click', () => { rememberDraft(); const key = button.dataset.partMinus; draft.usedParts[key] = Math.max(0, (draft.usedParts[key] || 0) - 1); draw(); }));
    content.querySelectorAll('[data-photo-remove]').forEach((button) => button.addEventListener('click', async () => { const index = Number(button.dataset.photoRemove); const [photo] = draft.photos.splice(index, 1); if (photo) URL.revokeObjectURL(photo.url); await persistDraft(); draw(); }));
    content.querySelector('#request-camera')?.addEventListener('click', openWorkCamera);
    content.querySelector('#request-gallery-open')?.addEventListener('click', () => content.querySelector('#request-gallery').click());
    content.querySelector('#request-gallery')?.addEventListener('change', async (event) => { await addDraftFiles(event.target.files); event.target.value = ''; });
    content.querySelector('#request-complete')?.addEventListener('click', completeWithOfflineQueue);
  };
  const onOfflineSync = async () => {
    if (!completionLocalUuid) return;
    const before = completionSync.attachmentsPending + Number(completionSync.repairPending);
    completionSync = await refreshCompletionSync();
    if (!completionSync.repairPending && completionQueued) await refreshCompletedRequest().catch(() => null);
    if (completionSync.fullySynced && completionQueued) {
      draftCompleted = true;
      await RequestDraftStore.remove(draftKey).catch(() => null);
    }
    if (before !== completionSync.attachmentsPending + Number(completionSync.repairPending)) draw();
  };
  activeTechnicianWorkspaceCleanup = disposeWorkspace;
  window.addEventListener('pagehide', persistOnBackground);
  document.addEventListener('visibilitychange', persistOnBackground);
  window.addEventListener('fixit-offline-sync', onOfflineSync);
  await refreshCompletionSync();
  draw();
}

// ============================================================
// Раздел: Fixit Pulse
// ============================================================

async function renderPulse(content) {
  if (state.me.role === 'technician') return renderTechnicianPulse(content);
  if (state.me.role.startsWith('client_')) return renderClientPulse(content);
  const [clients, sites, equipment, requests, users] = await Promise.all([
    api('/clients'), api('/sites'), api('/equipment'), api('/service-requests'), api('/users'), ensureEquipmentTypes(),
  ]);
  state.clients = clients;
  state.sites = sites;
  const activeRequests = requests.filter((request) => !['completed', 'closed', 'cancelled'].includes(request.status));
  const workRequests = activeRequests.filter((request) => ['on_the_way', 'arrived', 'in_progress'].includes(request.status));
  const urgentRequests = activeRequests.filter((request) => request.priority === 'urgent');
  const newRequests = requests.filter((request) => request.status === 'new');
  const now = new Date();
  const technicians = users.filter((user) => user.role === 'technician' && user.is_active);
  const activeTechIds = new Set(workRequests.map((request) => request.assigned_technician_id).filter(Boolean));
  const activeTechnicians = technicians.filter((tech) => activeTechIds.has(tech.id));
  const teamRoute = 'users';
  const attentionEquipment = equipment.filter((item) => item.status === 'needs_repair');
  const workingEquipment = equipment.filter((item) => item.status === 'working').length;
  const uptime = equipment.length ? Math.round((workingEquipment / equipment.length) * 100) : 100;
  const requestRows = activeRequests.sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
  const requestBadge = (request) => badge({
    new: { label: 'Новая', cls: 'warn' }, assigned: { label: 'Назначена', cls: 'amber' },
    on_the_way: { label: 'В пути', cls: 'amber' }, arrived: { label: 'На объекте', cls: 'amber' },
    in_progress: { label: 'В работе', cls: 'amber' }, waiting_parts: { label: 'Ждёт запчасти', cls: 'amber' },
    waiting_approval: { label: 'Требует согласования', cls: 'amber' }, completed: { label: 'Выполнена', cls: 'good' },
    closed: { label: 'Закрыта', cls: 'good' }, cancelled: { label: 'Отменена', cls: 'idle' },
  }, request.status);
  content.innerHTML = `
    <section class="pulse-command">
      <div class="pulse-command-copy"><div class="eyebrow">FIXIT PULSE · LIVE CONTROL</div><h1>Пульс сервиса</h1><p>Заявки, объекты и команда в одном рабочем контуре.</p></div>
      <div class="pulse-command-live"><span></span><div><b>Онлайн</b><small>${activeRequests.length} активных заявок</small></div></div>
      <div class="pulse-orbit orbit-a"></div><div class="pulse-orbit orbit-b"></div>
    </section>
    <div class="metric-grid">
      <button class="metric-card metric-new" data-jump="requests"><span class="metric-label">Новые заявки</span><strong>${newRequests.length}</strong><small>из QR и диспетчерских обращений</small></button>
      <button class="metric-card metric-dark" data-jump="requests"><span class="metric-label">В работе</span><strong>${workRequests.length}</strong><small>${urgentRequests.length ? `${urgentRequests.length} срочных` : 'спокойная очередь'}</small></button>
      <button class="metric-card metric-alert" data-jump="requests"><span class="metric-label">Требуют внимания</span><strong>${requests.filter((request) => request.status === 'waiting_approval').length}</strong><small>ожидают согласования</small></button>
      <button class="metric-card metric-accent" data-jump="${teamRoute}"><span class="metric-label">Мастера в работе</span><strong>${activeTechnicians.length}</strong><small>из ${technicians.length} активных</small></button>
    </div>
    <section class="quick-actions"><div class="section-caption">Быстрые действия</div><div class="quick-action-grid">
      <button data-jump="requests"><span class="quick-action-icon qa-ticket">+</span><b>Открыть заявки</b><small>${newRequests.length} новых</small></button>
      <button data-jump="requests"><span class="quick-action-icon qa-task">↗</span><b>Активные работы</b><small>${workRequests.length} в работе</small></button>
      <button data-quick="qr"><span class="quick-action-icon qa-qr">⌘</span><b>QR оборудования</b><small>Наклейки и паспорта</small></button>
      <button data-jump="equipment"><span class="quick-action-icon qa-equipment">◌</span><b>Оборудование</b><small>${attentionEquipment.length} требует внимания</small></button>
    </div></section>
    <div class="pulse-grid">
      <section class="card pulse-panel">
        <div class="panel-head"><div><span class="eyebrow">АКТИВНО</span><h2>Последние активные заявки</h2></div><button class="text-link" data-jump="requests">Все заявки →</button></div>
        <div class="pulse-list">${requestRows.length ? requestRows.slice(0, 6).map((request) => `<button class="pulse-row" data-request-id="${request.id}"><span class="priority-mark ${request.priority === 'urgent' ? 'urgent' : ''}"></span><div><strong>${esc(request.title || request.description || 'Заявка')}</strong><small>${esc(request.site_name || 'Объект не указан')} · ${esc(request.equipment_name || '')}</small></div><div>${requestBadge(request)}</div></button>`).join('') : '<div class="pulse-empty">Активных заявок нет — сервис работает штатно</div>'}</div>
      </section>
      <section class="card pulse-panel">
        <div class="panel-head"><div><span class="eyebrow">КОМАНДА</span><h2>Мастера на линии</h2></div><button class="text-link" data-jump="${teamRoute}">Команда →</button></div>
        <div class="team-list">${technicians.length ? technicians.slice(0, 6).map((tech) => {
          const count = workRequests.filter((request) => request.assigned_technician_id === tech.id).length;
          return `<div class="team-row"><span class="team-avatar">${esc(tech.full_name.split(/\s+/).slice(0, 2).map((part) => part[0]).join(''))}</span><div><strong>${esc(tech.full_name)}</strong><small>${count ? `${count} активн. ${count === 1 ? 'заявка' : 'заявки'}` : 'Свободен'}</small></div><span class="team-state ${count ? 'busy' : ''}">${count ? 'В работе' : 'Свободен'}</span></div>`;
        }).join('') : '<div class="pulse-empty">Добавьте мастеров, чтобы видеть загрузку</div>'}</div>
        <div class="network-strip"><span>${clients.length}<small>клиентов</small></span><span>${sites.length}<small>объектов</small></span><span>${uptime}%<small>готовность</small></span></div>
      </section>
    </div>`;

  content.querySelectorAll('[data-jump]').forEach((button) => {
    button.addEventListener('click', () => { location.hash = button.dataset.jump; });
  });
  content.querySelectorAll('[data-request-id]').forEach((button) => button.addEventListener('click', () => navigateToServiceRequest(button.dataset.requestId)));
  content.querySelectorAll('[data-quick="qr"]').forEach((button) => button.addEventListener('click', openQrQuickAction));
}

async function renderTechnicianPulse(content) {
  const [requests, equipment] = await Promise.all([
    api('/service-requests'), api('/equipment'), ensureEquipmentTypes(),
  ]);
  const active = requests.filter((item) => !['completed', 'closed', 'cancelled'].includes(item.status));
  const inProgress = requests.filter((item) => ['on_the_way', 'arrived', 'in_progress'].includes(item.status));
  const queued = requests.filter((item) => ['new', 'assigned', 'waiting_parts', 'waiting_approval'].includes(item.status));
  const statusLabel = { new: 'Новая', assigned: 'Назначена', on_the_way: 'В пути', arrived: 'На объекте', in_progress: 'В работе', waiting_parts: 'Ждёт запчасти', waiting_approval: 'Ждёт согласование', completed: 'Выполнена', closed: 'Закрыта', cancelled: 'Отменена' };
  const requestBadge = (item) => `<span class="badge badge-${['completed', 'closed'].includes(item.status) ? 'good' : item.status.startsWith('waiting') ? 'amber' : item.status === 'cancelled' ? 'idle' : 'warn'}"><span class="badge-dot"></span>${esc(statusLabel[item.status] || item.status)}</span>`;
  const nextRequests = [...active].sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || ''))).slice(0, 6);
  const attentionEquipment = equipment.filter((item) => item.status === 'needs_repair').length;

  content.innerHTML = `
    <section class="pulse-command technician-pulse">
      <div class="pulse-command-copy"><div class="eyebrow">FIXIT PULSE · МОЯ СМЕНА</div><h1>Пульс мастера</h1><p>Назначенные работы, маршрут по объектам и очередь на сегодня.</p></div>
      <div class="pulse-command-live"><span></span><div><b>На линии</b><small>${active.length} активных заявок</small></div></div>
      <div class="pulse-orbit orbit-a"></div><div class="pulse-orbit orbit-b"></div>
    </section>
    <div class="metric-grid technician-metrics">
      <button class="metric-card metric-new" data-jump="requests"><span class="metric-label">Назначено мне</span><strong>${active.length}</strong><small>всего в работе и очереди</small></button>
      <button class="metric-card metric-dark" data-jump="requests"><span class="metric-label">В работе</span><strong>${inProgress.length}</strong><small>в пути или на объекте</small></button>
      <button class="metric-card metric-alert" data-jump="requests"><span class="metric-label">Ожидают</span><strong>${queued.length}</strong><small>в очереди или ожидании</small></button>
      <button class="metric-card metric-accent" data-jump="equipment"><span class="metric-label">Оборудование</span><strong>${attentionEquipment}</strong><small>единиц требуют ремонта</small></button>
    </div>
    <section class="quick-actions"><div class="section-caption">Рабочие действия</div><div class="quick-action-grid technician-actions">
      <button data-jump="requests"><span class="quick-action-icon qa-ticket">→</span><b>Моя очередь</b><small>${queued.length} ждут выполнения</small></button>
      <button data-jump="requests"><span class="quick-action-icon qa-task">↗</span><b>Активные заявки</b><small>работы и сервисные акты</small></button>
      <button data-quick="qr"><span class="quick-action-icon qa-qr">⌘</span><b>Сканировать QR</b><small>открыть паспорт техники</small></button>
      <button data-jump="equipment"><span class="quick-action-icon qa-equipment">◌</span><b>Оборудование</b><small>паспорта и новая единица</small></button>
    </div></section>
    <section class="card pulse-panel technician-queue"><div class="panel-head"><div><span class="eyebrow">ОЧЕРЕДЬ</span><h2>Следующие заявки</h2></div><button class="text-link" data-jump="requests">Все заявки →</button></div>
      <div class="pulse-list">${nextRequests.length ? nextRequests.map((item) => `<button class="pulse-row" data-jump="requests"><span class="priority-mark ${item.priority === 'urgent' ? 'urgent' : ''}"></span><div><strong>SR-${String(item.number).padStart(5, '0')} · ${esc(item.description || 'Без описания')}</strong><small>${esc(item.client_name || 'Клиент')} · ${esc(item.site_name || 'Объект не указан')} · ${esc(item.equipment_name || '')}</small></div><div>${requestBadge(item)}</div></button>`).join('') : '<div class="pulse-empty">В очереди нет назначенных заявок</div>'}</div>
    </section>`;

  content.querySelectorAll('[data-jump]').forEach((button) => {
    button.addEventListener('click', () => { location.hash = button.dataset.jump; });
  });
  content.querySelectorAll('[data-quick="qr"]').forEach((button) => button.addEventListener('click', openQrQuickAction));
}

// ============================================================
// Раздел: Клиенты и объекты обслуживания
// ============================================================

async function ensureCustomers(force = false) {
  if (force || !state.clients.length || !state.sites.length) {
    [state.clients, state.sites] = await Promise.all([api('/clients'), api('/sites')]);
  }
}

async function renderClients(content) {
  await ensureCustomers(true);
  const canEdit = state.me.role !== 'technician';
  const clientName = (id) => (state.clients.find((client) => client.id === id) || {}).name || '—';
  content.innerHTML = `
    <div class="page-header">
      <div><h1>Клиенты и объекты</h1><div class="page-subtitle">Заказчики, площадки обслуживания и установленное оборудование</div></div>
      ${canEdit ? `<div style="display:flex;gap:10px">
        <button class="btn btn-secondary" id="add-client-btn">+ Клиент</button>
        <button class="btn btn-primary" id="add-site-btn">+ Объект</button>
      </div>` : ''}
    </div>
    <div class="card client-desktop-table" style="padding:0;margin-bottom:18px">
      <table>
        <thead><tr><th>Клиент</th><th>Реквизиты и контакт</th><th>Объектов</th><th>Оборудования</th><th>Статус</th>${canEdit ? '<th></th>' : ''}</tr></thead>
        <tbody>${state.clients.length ? state.clients.map((client) => `
          <tr class="client-table-row" data-client-open="${client.id}">
            <td><strong>${esc(client.name)}</strong>${client.legal_name ? `<div class="text-soft">${esc(client.legal_name)}</div>` : ''}</td>
            <td>${client.tax_id ? `<div>ИНН ${esc(client.tax_id)}</div>` : ''}<div class="text-soft">${esc(client.contact_name || '')} ${esc(client.contact_phone || '')}</div></td>
            <td>${client.site_count}</td><td>${client.equipment_count}</td>
            <td>${client.is_active ? badge({ active: { label: 'Активен', cls: 'good' } }, 'active') : badge({ inactive: { label: 'Отключён', cls: 'idle' } }, 'inactive')}</td>
            ${canEdit ? `<td><button class="btn btn-secondary client-users-btn" data-client-users="${client.id}">Пользователи</button></td>` : ''}
          </tr>`).join('') : '<tr class="empty-row"><td colspan="5">Клиентов пока нет</td></tr>'}</tbody>
      </table>
    </div>
    <div class="client-mobile-list">${state.clients.length ? state.clients.map((client) => `<button class="client-mobile-card" data-client-open="${client.id}"><div><strong>${esc(client.legal_name || client.name)}</strong>${client.tax_id ? `<small>ИНН ${esc(client.tax_id)}</small>` : ''}</div><p>${client.site_count} объект(ов) · ${client.equipment_count} оборудование</p>${client.contact_name || client.contact_phone ? `<span>Контакт: ${esc([client.contact_name, client.contact_phone].filter(Boolean).join(' · '))}</span>` : '<span>Контакт не указан</span>'}<b>Открыть клиента →</b></button>`).join('') : '<div class="client-empty">Клиентов пока нет</div>'}</div>
    <div class="page-header" style="margin-bottom:10px"><div><h1 style="font-size:20px">Объекты обслуживания</h1></div></div>
    <div class="card client-desktop-table" style="padding:0">
      <table>
        <thead><tr><th>Клиент</th><th>Объект</th><th>Адрес</th><th>Контакт</th><th>Оборудования</th></tr></thead>
        <tbody>${state.sites.length ? state.sites.map((site) => `
          <tr>
            <td>${esc(clientName(site.client_id))}</td><td><strong>${esc(site.name)}</strong></td>
            <td>${esc(site.address || '—')}</td>
            <td>${esc(site.contact_name || '')}<div class="text-soft">${esc(site.contact_phone || '')}</div></td>
            <td>${site.equipment_count}</td>
          </tr>`).join('') : '<tr class="empty-row"><td colspan="5">Объектов пока нет</td></tr>'}</tbody>
      </table>
    </div>
    <div class="site-mobile-list">${state.sites.length ? state.sites.map((site) => `<article class="site-mobile-card"><strong>${esc(site.name)}</strong><span>${esc(clientName(site.client_id))}</span><p>${esc(site.address || 'Адрес не указан')}</p><small>Оборудование: ${site.equipment_count}</small></article>`).join('') : '<div class="client-empty">Объектов пока нет</div>'}</div>`;

  if (canEdit) {
    document.getElementById('add-client-btn').addEventListener('click', openCreateClientModal);
    document.getElementById('add-site-btn').addEventListener('click', openCreateSiteModal);
  }
  content.querySelectorAll('[data-client-open]').forEach((element) => element.addEventListener('click', (event) => {
    if (event.target.closest('[data-client-users]')) return;
    location.hash = `clients/${element.dataset.clientOpen}`;
  }));
  content.querySelectorAll('[data-client-users]').forEach((button) => button.addEventListener('click', () => {
    location.hash = `clients/${button.dataset.clientUsers}/users`;
  }));
}

async function renderClientDetail(content, clientId, tab = 'overview') {
  await ensureCustomers(true);
  const client = state.clients.find((item) => item.id === clientId);
  if (!client) { content.innerHTML = '<div class="section-loading">Клиент не найден</div>'; return; }
  const canManageUsers = ['owner', 'admin', 'dispatcher'].includes(state.me.role);
  const canManageClientTeam = canManageUsers || state.me.role === 'client_admin';
  const accessCount = canManageClientTeam ? (await api(`/client-portal/access?client_id=${encodeURIComponent(client.id)}`)).length : 0;
  const staffUsersTabLabel = `Пользователи${canManageUsers ? ` (${accessCount})` : ''}`;
  const tabs = [['overview', 'Обзор'], ['sites', 'Объекты'], ['equipment', 'Оборудование'], ['users', canManageClientTeam ? `Пользователи (${accessCount})` : staffUsersTabLabel]];
  const actions = ['owner','admin','dispatcher'].includes(state.me.role) ? `<div class="client-detail-actions"><button class="btn btn-secondary" id="client-action-site">+ Объект</button><button class="btn btn-secondary" id="client-action-user">+ Пользователь</button><button class="btn btn-primary" id="client-action-equipment">+ Оборудование</button></div>` : '';
  content.innerHTML = `<section class="client-detail-screen"><button class="sr-back" id="client-detail-back">← Клиенты</button><header class="client-detail-hero"><div><span>КЛИЕНТ</span><h1>${esc(client.legal_name || client.name)}</h1><p>${client.is_active ? '● Активен' : '● Отключён'}</p></div>${actions}</header><div class="client-detail-meta">${client.tax_id ? `<div><span>ИНН</span><strong>${esc(client.tax_id)}</strong></div>` : ''}<div><span>Контакт</span><strong>${esc(client.contact_name || 'Не указан')}</strong><small>${esc(client.contact_phone || client.contact_email || '')}</small></div></div><nav class="client-detail-tabs">${tabs.map(([key,label]) => `<button data-client-tab="${key}" class="${tab === key ? 'active' : ''}">${label}</button>`).join('')}</nav><div id="client-detail-panel"></div></section>`;
  content.querySelector('#client-detail-back').addEventListener('click', () => location.hash = 'clients');
  content.querySelectorAll('[data-client-tab]').forEach((button) => button.addEventListener('click', () => location.hash = `clients/${client.id}/${button.dataset.clientTab}`));
  content.querySelector('#client-action-site')?.addEventListener('click', () => openCreateSiteModal(client.id));
  content.querySelector('#client-action-user')?.addEventListener('click', () => openClientUserEditor(client, null, () => router(), false));
  content.querySelector('#client-action-equipment')?.addEventListener('click', () => openCreateEquipmentModal(client.id));
  const panel = content.querySelector('#client-detail-panel');
  if (tab === 'sites') {
    if (state.clientSiteId) return renderClientSiteDetail(content, client, state.clientSiteId);
    const sites = state.sites.filter((site) => site.client_id === client.id);
    panel.innerHTML = `<div class="client-detail-card-list">${sites.length ? sites.map((site) => `<button class="client-site-card" data-client-site="${site.id}"><strong>${esc(site.name)}</strong><span>${esc(site.address || 'Адрес не указан')}</span><small>${esc([site.contact_name, site.contact_phone].filter(Boolean).join(' · ') || 'Контакт не указан')} · Оборудование: ${site.equipment_count}</small><b>Открыть объект →</b></button>`).join('') : '<div class="client-empty">У клиента пока нет объектов.</div>'}</div>`;
    panel.querySelectorAll('[data-client-site]').forEach((button) => button.addEventListener('click', () => location.hash = `clients/${client.id}/sites/${button.dataset.clientSite}`));
  } else if (tab === 'equipment') {
    const items = await api('/equipment');
    const sites = new Map(state.sites.filter((site) => site.client_id === client.id).map((site) => [site.id, site]));
    const equipment = items.filter((item) => sites.has(item.site_id));
    panel.innerHTML = `<div class="client-equipment-detail-list">${equipment.length ? equipment.map((item) => `<button class="client-equipment-detail-card" data-client-equipment="${item.id}"><span class="client-equipment-photo" data-client-equipment-photo="${item.id}">FIXIT</span><div><strong>${esc([item.manufacturer, item.model].filter(Boolean).join(' ') || item.name)}</strong><span>${esc(item.name || 'Оборудование')}</span><small>S/N ${esc(item.serial_number || '—')} · ${esc(sites.get(item.site_id).name)}</small>${badge(EQUIPMENT_STATUS, item.status)}</div></button>`).join('') : '<div class="client-empty">Оборудования пока нет.</div>'}</div>`;
    bindClientEquipmentCards(panel);
  } else if (tab === 'users') {
    if (!canManageClientTeam) { panel.innerHTML = '<div class="client-empty">У вас нет права управлять пользователями клиента.</div>'; return; }
    await renderClientUsersPanel(panel, client);
  } else {
    const [summary, serviceTechnicians] = await Promise.all([
      api(`/clients/${client.id}/summary`),
      canManageUsers ? api(`/clients/${client.id}/technicians`) : Promise.resolve([]),
    ]);
    const technicianPanel = canManageUsers ? `<section class="client-detail-contact"><h2>Сервисные техники</h2><p>Техники видят всё оборудование этого клиента, но работают только со своими назначенными заявками.</p><div class="client-technician-list">${serviceTechnicians.length ? serviceTechnicians.map((item) => `<label><input type="checkbox" data-service-technician="${item.id}" ${item.assigned ? 'checked' : ''}> ${esc(item.full_name)}</label>`).join('') : '<p>Нет активных техников организации.</p>'}</div><button class="btn btn-primary" id="save-service-technicians">Сохранить назначение</button></section>` : '';
    panel.innerHTML = `<div class="client-detail-overview"><article><span>ОБЪЕКТЫ</span><strong>${client.site_count}</strong><p>Площадки обслуживания клиента</p></article><article><span>ОБОРУДОВАНИЕ</span><strong>${client.equipment_count}</strong><p>Единиц в сервисе</p></article><article><span>АКТИВНЫЕ ЗАЯВКИ</span><strong>${summary.active_requests}</strong><p>Требуют внимания</p></article><article><span>В РЕМОНТЕ</span><strong>${summary.in_repair}</strong><p>${summary.waiting_approval} ожидают согласования</p></article><article><span>ЗАВЕРШЕНО · 30 ДНЕЙ</span><strong>${summary.completed_last_30_days}</strong><p>Закрытых сервисных работ</p></article></div><section class="client-detail-contact"><h2>Контактные данные</h2><p>${esc(client.contact_name || 'Контактное лицо не указано')}</p><a href="tel:${esc(client.contact_phone || '')}">${esc(client.contact_phone || '')}</a><p>${esc(client.contact_email || '')}</p></section>${technicianPanel}`;
    panel.querySelector('#save-service-technicians')?.addEventListener('click', async () => {
      const technician_ids = [...panel.querySelectorAll('[data-service-technician]:checked')].map((input) => input.dataset.serviceTechnician);
      try {
        await api(`/clients/${client.id}/technicians`, { method: 'PUT', body: JSON.stringify({ technician_ids }) });
        toast('Сервисные техники назначены');
      } catch (error) { toast(error.message || 'Не удалось сохранить назначение', 'error'); }
    });
  }
}

async function renderClientSiteDetail(content, client, siteId) {
  const site = state.sites.find((item) => item.id === siteId && item.client_id === client.id);
  if (!site) { content.innerHTML = '<div class="section-loading">Объект не найден</div>'; return; }
  const [items, summary] = await Promise.all([api('/equipment'), api(`/clients/${client.id}/summary`)]);
  const equipment = items.filter((item) => item.site_id === site.id);
  const activeRequests = summary.sites?.[site.id]?.active_requests || 0;
  content.innerHTML = `<section class="client-detail-screen"><button class="sr-back" id="client-site-back">← ${esc(client.legal_name || client.name)}</button><header class="client-detail-hero"><div><span>ОБЪЕКТ</span><h1>${esc(site.name)}</h1><p>${esc(site.address || 'Адрес не указан')}</p></div></header><div class="client-detail-meta"><div><span>КОНТАКТ</span><strong>${esc(site.contact_name || 'Не указан')}</strong><small>${esc(site.contact_phone || '')}</small></div><div><span>АКТИВНЫЕ ЗАЯВКИ</span><strong>${activeRequests}</strong><small>Оборудование: ${equipment.length}</small></div></div><section class="client-site-equipment"><h2>Оборудование на объекте</h2><div class="client-equipment-detail-list">${equipment.length ? equipment.map((item) => `<button class="client-equipment-detail-card" data-client-equipment="${item.id}"><span class="client-equipment-photo" data-client-equipment-photo="${item.id}">FIXIT</span><div><strong>${esc([item.manufacturer, item.model].filter(Boolean).join(' ') || item.name)}</strong><span>${esc(item.name || 'Оборудование')}</span><small>S/N ${esc(item.serial_number || '—')}</small>${badge(EQUIPMENT_STATUS, item.status)}</div></button>`).join('') : '<div class="client-empty">На объекте пока нет оборудования.</div>'}</div></section></section>`;
  content.querySelector('#client-site-back').addEventListener('click', () => location.hash = `clients/${client.id}/sites`);
  bindClientEquipmentCards(content);
}

function bindClientEquipmentCards(container) {
  container.querySelectorAll('[data-client-equipment]').forEach((button) => button.addEventListener('click', () => openEquipmentPassport(button.dataset.clientEquipment)));
  container.querySelectorAll('[data-client-equipment-photo]').forEach((frame) => {
    apiBlob(`/equipment/${frame.dataset.clientEquipmentPhoto}/photo`).then((blob) => {
      const url = URL.createObjectURL(blob); activeClientPhotoUrls.push(url);
      frame.innerHTML = `<img src="${url}" alt="Фото оборудования">`;
    }).catch(() => { /* Placeholder is intentional when a primary photo is absent. */ });
  });
}

async function renderClientUsersPanel(panel, client) {
  panel.innerHTML = '<div class="section-loading">Загрузка пользователей…</div>';
  try {
    const accesses = await api(`/client-portal/access?client_id=${encodeURIComponent(client.id)}`);
    const grouped = Object.values(accesses.reduce((result, access) => {
      const group = result[access.user_id] || (result[access.user_id] = { ...access, accesses: [] });
      group.accesses.push(access); return result;
    }, {}));
    panel.innerHTML = `<div class="client-users-head"><div><span>КОМАНДА</span><p>Доступ к личному кабинету клиента и его объектам.</p></div><button class="btn btn-secondary" id="client-invite-manager">Пригласить менеджера</button><button class="btn btn-primary" id="client-invite-director">Подключить руководителя</button></div><div class="client-users-list">${grouped.length ? grouped.map((group) => `<article class="client-user-group"><header><div><strong>${esc(group.full_name)}</strong><small>${esc(group.email)}</small></div><span>${esc(clientRoleLabel(group.role))}</span></header><div class="client-user-scopes">${group.accesses.map((access) => `<div class="client-user-row ${access.is_active ? '' : 'is-disabled'}"><div><span>${esc(clientAccessLabel(access))}</span><small>${access.is_active ? 'Активен' : 'Отключён'}</small></div><button class="client-user-more" data-client-access-menu="${access.id}" aria-label="Действия для доступа">⋯</button></div>`).join('')}</div></article>`).join('') : '<div class="client-empty">У клиента пока нет пользователей кабинета</div>'}</div>`;
    const refresh = () => renderClientDetail(document.getElementById('content'), client.id, 'users');
    panel.querySelector('#client-invite-manager').addEventListener('click', () => openClientInviteModal(client, 'site-manager'));
    panel.querySelector('#client-invite-director').addEventListener('click', () => openClientInviteModal(client, 'director'));
    panel.querySelectorAll('[data-client-access-menu]').forEach((button) => button.addEventListener('click', () => {
      const access = accesses.find((item) => item.id === button.dataset.clientAccessMenu);
      if (access) openClientAccessActions(client, access, refresh, false);
    }));
  } catch (error) { panel.innerHTML = `<div class="client-empty">${esc(error.message)}</div>`; }
}

function clientRoleLabel(role) {
  return role === 'client_admin' ? 'Администратор клиента' : 'Менеджер объекта';
}

function clientAccessLabel(access) {
  return access.role === 'client_admin' ? 'Все объекты' : (access.site_name ? `Объект ${access.site_name}` : 'Объект не выбран');
}

async function openClientUsersModal(client) {
  let accesses = [];
  const backdrop = openModal(`Пользователи · ${client.name}`, '<div class="client-users-loading">Загрузка пользователей…</div>');
  const draw = () => {
    const body = backdrop.querySelector('#modal-body');
    body.innerHTML = `<div class="client-users-head"><div><span>ДОСТУП К КАБИНЕТУ КЛИЕНТА</span><p>Пользователь получает доступ только к выбранному клиенту и его объектам.</p></div><button class="btn btn-primary" id="client-user-add">+ Добавить пользователя</button></div>
      <div class="client-users-list">${accesses.length ? accesses.map((access) => `<article class="client-user-row ${access.is_active ? '' : 'is-disabled'}">
        <div><strong>${esc(access.full_name)}</strong><small>${esc(access.email)}</small></div>
        <div><span>${esc(clientRoleLabel(access.role))}</span><small>${esc(clientAccessLabel(access))}</small></div>
        <div class="client-user-state">${access.is_active ? 'Активен' : 'Отключён'}</div>
        <button class="client-user-more" data-client-access-menu="${access.id}" aria-label="Действия">⋯</button>
      </article>`).join('') : '<div class="client-empty">Пользователей с доступом пока нет</div>'}</div>`;
    body.querySelector('#client-user-add').addEventListener('click', () => openClientUserEditor(client, null, refresh));
    body.querySelectorAll('[data-client-access-menu]').forEach((button) => button.addEventListener('click', () => {
      const access = accesses.find((item) => item.id === button.dataset.clientAccessMenu);
      if (access) openClientAccessActions(client, access, refresh);
    }));
  };
  const refresh = async () => {
    try { accesses = await api(`/client-portal/access?client_id=${encodeURIComponent(client.id)}`); draw(); }
    catch (error) { backdrop.querySelector('#modal-body').innerHTML = `<div class="client-empty">${esc(error.message)}</div>`; }
  };
  await refresh();
}

async function openClientUserEditor(client, access = null, done = () => {}, reopenModal = true) {
  let users = [];
  try { users = await api('/users'); } catch (error) { return toast(error.message, 'error'); }
  const clientUsers = users.filter((item) => ['client_admin', 'client_site_user'].includes(item.role));
  const sites = state.sites.filter((site) => site.client_id === client.id && site.is_active);
  const backdrop = openModal(access ? 'Изменить доступ' : 'Добавить пользователя', `
    <form class="client-user-editor" id="client-user-access-form">
      ${access ? `<div class="field"><label>Пользователь</label><input value="${esc(access.full_name)}" disabled></div>` : `
      <div class="field"><label>Пользователь</label><select id="client-access-user"><option value="">Создать нового пользователя…</option>${clientUsers.map((item) => `<option value="${item.id}">${esc(item.full_name)} · ${esc(item.email)}</option>`).join('')}</select></div>
      <div class="client-new-user-fields"><div class="field"><label>ФИО</label><input id="client-user-name" autocomplete="name"></div><div class="field"><label>Email</label><input id="client-user-email" type="email" autocomplete="email"></div><div class="field"><label>Телефон</label><input id="client-user-phone" autocomplete="tel"></div><div class="field"><label>Временный пароль</label><input id="client-user-password" type="password" autocomplete="new-password"></div></div>`}
      <div class="field"><label>Роль</label><select id="client-access-role" ${access ? 'disabled' : ''}><option value="client_admin" ${access?.role === 'client_admin' ? 'selected' : ''}>Администратор клиента — все объекты</option><option value="client_site_user" ${access?.role === 'client_site_user' ? 'selected' : ''}>Менеджер объекта — один объект</option></select></div>
      <div class="field" id="client-access-site-field"><label>Объект</label><select id="client-access-site"><option value="">Выберите объект</option>${sites.map((site) => `<option value="${site.id}" ${access?.site_id === site.id ? 'selected' : ''}>${esc(site.name)}</option>`).join('')}</select></div>
      ${access ? `<div class="field"><label><input id="client-access-active" type="checkbox" ${access.is_active ? 'checked' : ''}> Доступ активен</label></div>` : ''}
    </form>`, '<button class="btn btn-secondary" id="modal-cancel">Отмена</button><button class="btn btn-primary" id="modal-save">Сохранить</button>');
  const roleInput = backdrop.querySelector('#client-access-role');
  const siteField = backdrop.querySelector('#client-access-site-field');
  const toggleScope = () => { siteField.classList.toggle('hidden', roleInput.value === 'client_admin'); };
  roleInput.addEventListener('change', toggleScope); toggleScope();
  backdrop.querySelector('#modal-cancel').addEventListener('click', () => { closeModal(); if (reopenModal) openClientUsersModal(client); else done(); });
  backdrop.querySelector('#modal-save').addEventListener('click', async () => {
    try {
      let userId = access?.user_id;
      const role = roleInput.value;
      const siteId = role === 'client_site_user' ? backdrop.querySelector('#client-access-site').value : null;
      if (role === 'client_site_user' && !siteId) return toast('Выберите объект для менеджера', 'error');
      if (!userId) {
        userId = backdrop.querySelector('#client-access-user').value;
        if (!userId) {
          const full_name = backdrop.querySelector('#client-user-name').value.trim();
          const email = backdrop.querySelector('#client-user-email').value.trim();
          const password = backdrop.querySelector('#client-user-password').value;
          if (!full_name || !email || password.length < 8) return toast('Укажите ФИО, email и временный пароль не короче 8 символов', 'error');
          const account = await api('/users', { method: 'POST', body: JSON.stringify({ full_name, email, password, role, phone: backdrop.querySelector('#client-user-phone').value.trim() || null }) });
          userId = account.id;
        }
      }
      if (access) await api(`/client-portal/access/${access.id}`, { method: 'PATCH', body: JSON.stringify({ site_id: siteId, is_active: backdrop.querySelector('#client-access-active').checked }) });
      else await api('/client-portal/access', { method: 'POST', body: JSON.stringify({ user_id: userId, client_id: client.id, site_id: siteId }) });
      closeModal(); toast(access ? 'Доступ обновлён' : 'Пользователь добавлен'); await done(); if (reopenModal) openClientUsersModal(client);
    } catch (error) { toast(error.message, 'error'); }
  });
}

function openClientAccessActions(client, access, done, reopenModal = true) {
  const backdrop = openModal(access.full_name, `<div class="client-access-actions"><button id="client-access-edit">Изменить доступ</button><button id="client-access-toggle">${access.is_active ? 'Отключить' : 'Активировать'}</button><button class="danger" id="client-access-delete">Удалить доступ</button></div>`);
  backdrop.querySelector('#client-access-edit').addEventListener('click', () => openClientUserEditor(client, access, done, reopenModal));
  backdrop.querySelector('#client-access-toggle').addEventListener('click', async () => {
    try { await api(`/client-portal/access/${access.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: !access.is_active }) }); closeModal(); await done(); if (reopenModal) openClientUsersModal(client); }
    catch (error) { toast(error.message, 'error'); }
  });
  backdrop.querySelector('#client-access-delete').addEventListener('click', async () => {
    try { await api(`/client-portal/access/${access.id}`, { method: 'DELETE' }); closeModal(); toast('Доступ удалён'); await done(); if (reopenModal) openClientUsersModal(client); }
    catch (error) { toast(error.message, 'error'); }
  });
}

function openCreateClientModal() {
  const backdrop = openModal('Новый клиент', `
    <form id="client-form">
      <div class="field"><label>Рабочее название</label><input id="f-client-name" required></div>
      <div class="field"><label>Юридическое название</label><input id="f-client-legal"></div>
      <div class="field-row"><div class="field"><label>ИНН</label><input id="f-client-tax"></div><div class="field"><label>Контактное лицо</label><input id="f-client-contact"></div></div>
      <div class="field-row"><div class="field"><label>Телефон</label><input id="f-client-phone"></div><div class="field"><label>Email</label><input type="email" id="f-client-email"></div></div>
    </form>`,
    '<button class="btn btn-secondary" id="modal-cancel">Отмена</button><button class="btn btn-primary" id="modal-save">Создать</button>');
  backdrop.querySelector('#modal-cancel').addEventListener('click', closeModal);
  backdrop.querySelector('#modal-save').addEventListener('click', async () => {
    const name = backdrop.querySelector('#f-client-name').value.trim();
    if (name.length < 2) return toast('Укажите название клиента', 'error');
    try {
      await api('/clients', { method: 'POST', body: JSON.stringify({
        name,
        legal_name: backdrop.querySelector('#f-client-legal').value.trim() || null,
        tax_id: backdrop.querySelector('#f-client-tax').value.trim() || null,
        contact_name: backdrop.querySelector('#f-client-contact').value.trim() || null,
        contact_phone: backdrop.querySelector('#f-client-phone').value.trim() || null,
        contact_email: backdrop.querySelector('#f-client-email').value.trim() || null,
      }) });
      closeModal(); toast('Клиент создан'); router();
    } catch (e) { toast(e.message, 'error'); }
  });
}

function openCreateSiteModal(preselectedClientId = null) {
  const activeClients = state.clients.filter((client) => client.is_active);
  if (!activeClients.length) return toast('Сначала создайте активного клиента', 'error');
  const backdrop = openModal('Новый объект обслуживания', `
    <form id="site-form">
      <div class="field"><label>Клиент</label><select id="f-site-client" required>${activeClients.map((client) => `<option value="${client.id}" ${client.id === preselectedClientId ? 'selected' : ''}>${esc(client.name)}</option>`).join('')}</select></div>
      <div class="field"><label>Название объекта</label><input id="f-site-name" required></div>
      <div class="field"><label>Адрес</label><input id="f-site-address"></div>
      <div class="field-row"><div class="field"><label>Контактное лицо</label><input id="f-site-contact"></div><div class="field"><label>Телефон</label><input id="f-site-phone"></div></div>
      <div class="field"><label>Email</label><input type="email" id="f-site-email"></div>
    </form>`,
    '<button class="btn btn-secondary" id="modal-cancel">Отмена</button><button class="btn btn-primary" id="modal-save">Создать</button>');
  backdrop.querySelector('#modal-cancel').addEventListener('click', closeModal);
  backdrop.querySelector('#modal-save').addEventListener('click', async () => {
    const name = backdrop.querySelector('#f-site-name').value.trim();
    if (name.length < 2) return toast('Укажите название объекта', 'error');
    try {
      await api('/sites', { method: 'POST', body: JSON.stringify({
        client_id: backdrop.querySelector('#f-site-client').value,
        name,
        address: backdrop.querySelector('#f-site-address').value.trim() || null,
        contact_name: backdrop.querySelector('#f-site-contact').value.trim() || null,
        contact_phone: backdrop.querySelector('#f-site-phone').value.trim() || null,
        contact_email: backdrop.querySelector('#f-site-email').value.trim() || null,
      }) });
      closeModal(); toast('Объект создан'); router();
    } catch (e) { toast(e.message, 'error'); }
  });
}

// ============================================================
// Раздел: Оборудование
// ============================================================

async function ensureEquipmentTypes() {
  if (!state.equipmentTypes.length) {
    state.equipmentTypes = await api('/equipment-types');
  }
}

async function renderEquipment(content) {
  const [items] = await Promise.all([api('/equipment'), ensureEquipmentTypes(), ensureCustomers()]);
  const typeName = (id) => (state.equipmentTypes.find((t) => t.id === id) || {}).name || '—';
  const siteOf = (id) => state.sites.find((site) => site.id === id);
  const clientOf = (id) => state.clients.find((client) => client.id === id);
  const canEdit = state.me.role !== 'technician';
  const technicianFleet = state.me.role === 'technician';
  const activeSites = state.sites.filter((site) => site.is_active);

  content.innerHTML = `
    <div class="page-header">
      <div><h1>Оборудование</h1><div class="page-subtitle">${technicianFleet ? 'Оборудование закреплённых клиентов' : 'Цифровой паспорт и лента ремонтов по каждой единице техники'}</div></div>
      <div style="display:flex;gap:10px;align-items:center">
        ${technicianFleet ? `<select id="equipment-client-filter" aria-label="Клиент"><option value="">Все закреплённые клиенты</option>${state.clients.map((client) => `<option value="${client.id}">${esc(client.legal_name || client.name)}</option>`).join('')}</select>` : ''}
        <select id="equipment-location-filter" aria-label="Фильтр по объекту"><option value="">Все объекты</option>${activeSites.map((site) => `<option value="${site.id}">${esc(readableClientName(clientOf(site.client_id)?.legal_name || clientOf(site.client_id)?.name, site.name))} · ${esc(site.name)}</option>`).join('')}</select>
        <div class="site-picker" id="equipment-site-picker">
          <button type="button" class="site-picker-trigger" id="equipment-site-trigger"><span id="equipment-site-label">Все объекты</span><i>⌄</i></button>
          <div class="site-picker-menu hidden" id="equipment-site-menu">
            <button type="button" data-site-value="">Все объекты</button>${activeSites.map((site) => `<button type="button" data-site-value="${site.id}"><small>${esc(readableClientName(clientOf(site.client_id)?.legal_name || clientOf(site.client_id)?.name, site.name))}</small>${esc(site.name)}</button>`).join('')}
          </div>
        </div>
        ${canEdit ? '<button class="btn btn-primary" id="add-equipment-btn">+ Добавить оборудование</button>' : ''}
      </div>
    </div>
    <div class="card mobile-table" style="padding:0">
      <table>
        <thead><tr><th>Тип оборудования</th><th>Серийный №</th><th>Статус</th><th>Клиент и объект</th></tr></thead>
        <tbody id="equipment-rows"></tbody>
      </table>
    </div><div class="mobile-card-list" id="equipment-cards"></div>`;

  const rows = document.getElementById('equipment-rows');
  const cards = document.getElementById('equipment-cards');
  const renderRows = () => {
    const selectedLocation = document.getElementById('equipment-location-filter').value;
    const visibleItems = items
      .filter((eq) => !selectedLocation || eq.site_id === selectedLocation)
      .sort((a, b) => {
        const byLocation = (siteOf(a.site_id)?.name || '').localeCompare(siteOf(b.site_id)?.name || '', 'ru');
        return byLocation || typeName(a.equipment_type_id).localeCompare(typeName(b.equipment_type_id), 'ru');
      });
    rows.innerHTML = visibleItems.length ? visibleItems.map((eq) => {
      const site = siteOf(eq.site_id);
      const client = site ? clientOf(site.client_id) : null;
      return `
      <tr class="clickable" data-id="${eq.id}">
      <td><strong>${esc(typeName(eq.equipment_type_id))}</strong><div class="text-soft">${esc(eq.manufacturer || '')} ${esc(eq.model || '')}</div></td>
      <td class="mono">${esc(eq.serial_number)}</td>
      <td>${badge(EQUIPMENT_STATUS, eq.status)}</td>
      <td>${esc(readableClientName(client?.legal_name || client?.name, site?.name || eq.location))}<div class="text-soft">${esc(site?.name || eq.location || '—')}</div></td>
      </tr>`;
    }).join('') : '<tr class="empty-row"><td colspan="4">На этом объекте оборудования нет</td></tr>';
    cards.innerHTML = visibleItems.length ? visibleItems.map((eq) => {
      const site = siteOf(eq.site_id); const client = site ? clientOf(site.client_id) : null;
      return `<button class="mobile-info-card equipment-card" data-id="${eq.id}"><div class="mobile-card-top"><span class="equipment-glyph">◌</span>${badge(EQUIPMENT_STATUS, eq.status)}</div><strong>${esc(typeName(eq.equipment_type_id))}</strong><span class="text-soft">${esc(eq.manufacturer || '')} ${esc(eq.model || '')}</span><div class="mobile-card-meta"><span class="mono">${esc(eq.serial_number)}</span><span>${esc(readableClientName(client?.legal_name || client?.name, site?.name || eq.location))} · ${esc(site?.name || eq.location || '—')}</span></div></button>`;
    }).join('') : '<div class="mobile-empty">На этом объекте оборудования нет</div>';

    rows.querySelectorAll('tr[data-id]').forEach((tr) => {
      tr.addEventListener('click', () => openEquipmentPassport(tr.dataset.id));
    });
    cards.querySelectorAll('[data-id]').forEach((card) => card.addEventListener('click', () => openEquipmentPassport(card.dataset.id)));
  };
  const sitePicker = document.getElementById('equipment-site-picker');
  const siteMenu = document.getElementById('equipment-site-menu');
  const bindSitePicker = () => {
    siteMenu.querySelectorAll('[data-site-value]').forEach((button) => button.addEventListener('click', () => {
      const select = document.getElementById('equipment-location-filter');
      select.value = button.dataset.siteValue;
      document.getElementById('equipment-site-label').textContent = button.textContent.trim().replace(/\s+/g, ' ');
      siteMenu.classList.add('hidden'); renderRows();
    }));
  };
  const setSiteOptions = (sites) => {
    const select = document.getElementById('equipment-location-filter');
    select.innerHTML = `<option value="">Все объекты</option>${sites.map((site) => `<option value="${site.id}">${esc(site.name)}</option>`).join('')}`;
    siteMenu.innerHTML = `<button type="button" data-site-value="">Все объекты</button>${sites.map((site) => `<button type="button" data-site-value="${site.id}">${esc(site.name)}</button>`).join('')}`;
    document.getElementById('equipment-site-label').textContent = 'Все объекты';
    bindSitePicker();
  };
  renderRows();
  document.getElementById('equipment-client-filter')?.addEventListener('change', async (event) => {
    const clientId = event.target.value;
    const sites = await api(`/sites${clientId ? `?client_id=${encodeURIComponent(clientId)}` : ''}`);
    setSiteOptions(sites);
    const nextItems = await api(`/equipment${clientId ? `?client_id=${encodeURIComponent(clientId)}` : ''}`);
    items.splice(0, items.length, ...nextItems); renderRows();
  });
  document.getElementById('equipment-location-filter').addEventListener('change', renderRows);
  document.getElementById('equipment-site-trigger').addEventListener('click', () => siteMenu.classList.toggle('hidden'));
  bindSitePicker();
  content.addEventListener('click', (event) => {
    if (!sitePicker.contains(event.target)) siteMenu.classList.add('hidden');
  });

  if (canEdit) {
    document.getElementById('add-equipment-btn').addEventListener('click', openCreateEquipmentModal);
  }
}

function openCreateEquipmentModal(preselectedClientId = null) {
  const typeOptions = state.equipmentTypes.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join('');
  const activeSites = state.sites.filter((site) => site.is_active && (!preselectedClientId || site.client_id === preselectedClientId));
  if (!activeSites.length) return toast('Сначала создайте объект обслуживания', 'error');
  const siteOptions = activeSites.map((site) => {
    const client = state.clients.find((item) => item.id === site.client_id);
    return `<option value="${site.id}">${esc(readableClientName(client?.legal_name || client?.name, site.name))} · ${esc(site.name)}</option>`;
  }).join('');
  const backdrop = openModal('Новое оборудование', `
    <form id="equipment-form">
      <div class="field"><label>Тип оборудования</label>
        <select id="f-type" required>${typeOptions}<option value="__new">+ Новый тип…</option></select>
      </div>
      <div class="field hidden" id="f-newtype-wrap"><label>Название нового типа</label><input id="f-newtype"></div>
      <div class="field-row">
        <div class="field"><label>Производитель</label><input id="f-manufacturer"></div>
        <div class="field"><label>Модель</label><input id="f-model"></div>
      </div>
      <div class="field"><label>Серийный номер</label><input id="f-serial" required></div>
      <div class="field"><label>Объект обслуживания</label><select id="f-site" required>${siteOptions}</select></div>
      <div class="field"><label>Фото оборудования <span class="text-soft">(необязательно)</span></label><div class="equipment-photo-inputs"><label class="btn btn-ghost btn-sm">Сфотографировать<input id="f-equipment-camera" type="file" accept="image/*" capture="environment" hidden></label><label class="btn btn-ghost btn-sm">Выбрать фото<input id="f-equipment-photo" type="file" accept="image/*" hidden></label><span id="f-equipment-photo-name" class="text-soft">Фото не выбрано</span></div></div>
    </form>`,
    `<button class="btn btn-secondary" id="modal-cancel">Отмена</button>
     <button class="btn btn-primary" id="modal-save">Создать</button>`);

  backdrop.querySelector('#modal-cancel').addEventListener('click', closeModal);
  backdrop.querySelector('#f-type').addEventListener('change', (e) => {
    backdrop.querySelector('#f-newtype-wrap').classList.toggle('hidden', e.target.value !== '__new');
  });
  let selectedPhoto = null;
  const selectPhoto = (event) => {
    selectedPhoto = event.target.files?.[0] || null;
    backdrop.querySelector('#f-equipment-photo-name').textContent = selectedPhoto ? selectedPhoto.name : 'Фото не выбрано';
  };
  backdrop.querySelector('#f-equipment-camera').addEventListener('change', selectPhoto);
  backdrop.querySelector('#f-equipment-photo').addEventListener('change', selectPhoto);

  backdrop.querySelector('#modal-save').addEventListener('click', async () => {
    try {
      let typeId = backdrop.querySelector('#f-type').value;
      if (typeId === '__new') {
        const name = backdrop.querySelector('#f-newtype').value.trim();
        if (!name) return toast('Укажите название типа', 'error');
        const created = await api('/equipment-types', { method: 'POST', body: JSON.stringify({ name }) });
        state.equipmentTypes.push(created);
        typeId = created.id;
      }
      const serial = backdrop.querySelector('#f-serial').value.trim();
      if (!serial) return toast('Укажите серийный номер', 'error');
      const equipment = await api('/equipment', {
        method: 'POST',
        body: JSON.stringify({
          equipment_type_id: Number(typeId),
          manufacturer: backdrop.querySelector('#f-manufacturer').value.trim() || null,
          model: backdrop.querySelector('#f-model').value.trim() || null,
          serial_number: serial,
          site_id: backdrop.querySelector('#f-site').value,
        }),
      });
      closeModal();
      if (selectedPhoto) {
        try { await uploadEquipmentPhoto(equipment.id, selectedPhoto); toast('Оборудование и фото добавлены'); }
        catch (_) { toast('Оборудование создано, фото не удалось загрузить. Повторите загрузку из паспорта.', 'error'); }
      } else toast('Оборудование добавлено');
      router();
    } catch (e) {
      toast(e.message, 'error');
    }
  });
}

function readableClientName(name, siteName) {
  const value = String(name || '').trim();
  return value && !/^импортированные\s+клиенты$/i.test(value) ? value : (siteName || 'Клиент не указан');
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url; link.download = filename;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function openEquipmentManageModal(passport) {
  const sites = state.sites.filter((site) => site.is_active);
  const options = sites.map((site) => {
    const client = state.clients.find((item) => item.id === site.client_id);
    return `<option value="${site.id}" ${site.id === passport.site_id ? 'selected' : ''}>${esc(readableClientName(client?.legal_name || client?.name, site.name))} · ${esc(site.name)}</option>`;
  }).join('');
  const backdrop = openModal('Управление оборудованием', `
    <div class="field"><label>Объект обслуживания</label><select id="passport-site">${options}</select></div>
    <div class="field"><label>Статус</label><select id="passport-status">${Object.entries(EQUIPMENT_STATUS).map(([key, item]) => `<option value="${key}" ${passport.status === key ? 'selected' : ''}>${item.label}</option>`).join('')}</select></div>`,
    '<button class="btn btn-secondary" id="passport-manage-cancel">Отмена</button><button class="btn btn-primary" id="passport-manage-save">Сохранить</button>');
  backdrop.querySelector('#passport-manage-cancel').addEventListener('click', closeModal);
  backdrop.querySelector('#passport-manage-save').addEventListener('click', async () => {
    try {
      await api(`/equipment/${passport.id}`, { method: 'PATCH', body: JSON.stringify({ site_id: backdrop.querySelector('#passport-site').value, status: backdrop.querySelector('#passport-status').value }) });
      closeModal(); toast('Паспорт оборудования обновлён'); router();
    } catch (e) { toast(e.message, 'error'); }
  });
}

async function openCreateServiceRequestForEquipment(passport) {
  try {
    const technicians = (await api('/users')).filter((item) => item.role === 'technician' && item.is_active);
    const backdrop = openModal('Создать заявку', `
      <div class="passport-create-context">${esc(passport.manufacturer || '')} ${esc(passport.model || passport.name)} · <span class="mono">${esc(passport.serial_number)}</span></div>
      <div class="field"><label>Проблема</label><input id="passport-request-title" required placeholder="Например: не набирает воду"></div>
      <div class="field"><label>Описание</label><textarea id="passport-request-description" rows="3"></textarea></div>
      <div class="field-row"><div class="field"><label>Приоритет</label><select id="passport-request-priority"><option value="planned">Плановая</option><option value="urgent">Срочно</option></select></div><div class="field"><label>Мастер</label><select id="passport-request-tech"><option value="">Назначить позже</option>${technicians.map((tech) => `<option value="${tech.id}">${esc(tech.full_name)}</option>`).join('')}</select></div></div>`,
      '<button class="btn btn-secondary" id="passport-request-cancel">Отмена</button><button class="btn btn-primary" id="passport-request-save">Создать заявку</button>');
    backdrop.querySelector('#passport-request-cancel').addEventListener('click', closeModal);
    backdrop.querySelector('#passport-request-save').addEventListener('click', async () => {
      const title = backdrop.querySelector('#passport-request-title').value.trim();
      if (!title) return toast('Опишите проблему', 'error');
      try {
        await api('/service-requests', { method: 'POST', body: JSON.stringify({ equipment_id: passport.id, title, description: backdrop.querySelector('#passport-request-description').value.trim() || null, priority: backdrop.querySelector('#passport-request-priority').value, assigned_technician_id: backdrop.querySelector('#passport-request-tech').value || null }) });
        closeModal(); toast('Заявка создана'); router();
      } catch (e) { toast(e.message, 'error'); }
    });
  } catch (e) { toast(e.message, 'error'); }
}

async function openEquipmentPassport(id) {
  try {
    const [passport, qrBlob] = await Promise.all([api(`/equipment/${id}/passport`), apiBlob(`/equipment/${id}/qr`)]);
    const qrObjectUrl = URL.createObjectURL(qrBlob);
    const equipmentTypeName = (state.equipmentTypes.find((type) => type.id === passport.equipment_type_id) || {}).name || passport.name;
    const clientName = readableClientName(passport.client_name, passport.site_name);
    const isStaff = state.me.role !== 'technician';
    const statusLabels = { new: 'Новая', assigned: 'Назначена', on_the_way: 'В пути', arrived: 'На объекте', in_progress: 'В работе', waiting_parts: 'Ждёт запчасти', waiting_approval: 'Ждёт согласования', completed: 'Выполнена', closed: 'Закрыта', cancelled: 'Отменена', legacy: 'Историческая запись' };
    const requestBadge = (request) => `<span class="badge badge-${['completed', 'closed'].includes(request.status) ? 'good' : request.status.startsWith('waiting') ? 'amber' : request.status === 'cancelled' ? 'idle' : 'warn'}"><span class="badge-dot"></span>${esc(statusLabels[request.status] || request.status)}</span>`;
    const normalizeHistoryText = (value) => String(value || '').toLocaleLowerCase('ru-RU').replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
    const compactTechnicianName = (value) => String(value || '').trim().split(/\s+/).slice(0, 2).join(' ');
    const history = passport.history.map((entry) => {
      const title = entry.title || entry.problem || 'Без описания';
      const showProblem = entry.problem && normalizeHistoryText(entry.problem) !== normalizeHistoryText(title);
      const number = entry.service_request_number ? `SR-${String(entry.service_request_number).padStart(5, '0')}` : 'История';
      const fields = [
        showProblem ? ['Проблема', entry.problem] : null,
        entry.work_summary ? ['Работы', entry.work_summary] : null,
        entry.cancellation_reason ? ['Причина отмены', entry.cancellation_reason] : null,
      ].filter(Boolean).map(([label, value]) => `<div class="equipment-history-field"><span>${label}</span><p>${esc(value)}</p></div>`).join('');
      const parts = entry.parts?.length ? `<div class="equipment-history-field equipment-history-parts"><span>Запчасти</span><p>${entry.parts.map((part) => `${esc(part.part_name)} ×${part.quantity}`).join(' · ')}</p></div>` : '';
      const photos = entry.photos?.length ? `<div class="equipment-history-photos">${entry.photos.slice(0, 3).map((photo) => `<button type="button" aria-label="Открыть фото работ" data-history-photo-url="${photo.download_url}" data-history-photo-kind="${photo.kind}"><img alt="Фото работ"><span>Фото</span></button>`).join('')}</div>` : '';
      const technician = entry.technician_name ? `<footer class="equipment-history-technician">Мастер: ${esc(compactTechnicianName(entry.technician_name))}</footer>` : '';
      return `<article class="equipment-history-card${entry.service_request_id ? ' is-clickable' : ''}${entry.legacy ? ' is-legacy' : ''}" ${entry.service_request_id ? `data-history-request="${entry.service_request_id}" tabindex="0" role="link"` : ''}><header class="equipment-history-card-head"><time>${fmtDate(entry.completed_at || entry.occurred_at)}</time>${requestBadge(entry)}<strong>${number}${entry.service_request_id ? ' ›' : ''}</strong></header><h3>${esc(title)}</h3>${fields}${parts}${photos}${technician}</article>`;
    }).join('') || '<div class="passport-empty"><strong>История обслуживания</strong><br>Ремонтов ещё не было.</div>';
    const documents = passport.documents.map((document) => `<button class="passport-document" data-document-kind="${esc(document.kind)}" data-repair-id="${document.repair_id || ''}" data-attachment-id="${document.attachment_id || ''}"><span class="passport-document-icon">${document.kind === 'service_act' ? 'PDF' : document.kind === 'before' || document.kind === 'after' ? 'Фото' : 'Файл'}</span><span><strong>${esc(document.title)}</strong><small>${fmtDate(document.created_at)}${document.media_type ? ` · ${esc(document.media_type)}` : ''}</small></span><b>↓</b></button>`).join('') || '<div class="passport-empty">Фотографии и сервисные акты появятся здесь после выполнения работ.</div>';
    const qrFilename = `QR — ${String(passport.model || equipmentTypeName).replace(/[<>:"/\\|?*\x00-\x1F]/g, '_')}.svg`;
    const primaryAction = passport.active_request
      ? `<button class="btn btn-primary" id="passport-primary-request">Открыть заявку SR-${String(passport.active_request.number).padStart(5, '0')}</button>`
      : isStaff ? '<button class="btn btn-primary" id="passport-create-request">Создать заявку</button>' : '';
    const photoControl = `<section class="passport-photo"><div class="passport-photo-frame">${passport.primary_photo ? '<img id="passport-primary-photo" alt="Фото оборудования">' : '<span>FIXIT<br>оборудование</span>'}</div><div><span>Фото оборудования</span><p>${passport.primary_photo ? 'Основное фото паспорта' : 'Добавьте фото, чтобы быстрее узнать машину на объекте.'}</p><label class="btn btn-ghost btn-sm">${passport.primary_photo ? 'Заменить фото' : 'Добавить фото'}<input id="passport-photo-upload" type="file" accept="image/*" hidden></label>${passport.primary_photo && isStaff ? '<button class="btn btn-ghost btn-sm" id="passport-photo-delete">Удалить</button>' : ''}</div></section>`;
    const backdrop = openModal('', `<section class="equipment-passport">
      <header class="passport-hero"><div><span class="passport-eyebrow">${esc(equipmentTypeName)}</span><h2>${esc([passport.manufacturer, passport.model].filter(Boolean).join(' ') || passport.name)}</h2><div class="passport-status-row">${badge(EQUIPMENT_STATUS, passport.status)}<span class="mono">S/N ${esc(passport.serial_number)}</span></div></div><button type="button" class="passport-more" id="passport-more" aria-label="Дополнительные действия" aria-expanded="false">•••</button><div class="passport-more-menu hidden" id="passport-more-menu" role="menu"><button type="button" role="menuitem" id="passport-download-qr">Скачать QR</button>${isStaff ? '<button type="button" role="menuitem" id="passport-manage">Редактировать и переместить</button><button type="button" role="menuitem" class="passport-menu-danger" id="passport-archive">Архивировать</button>' : ''}</div></header>
      <div class="passport-context"><div><small>Клиент</small><strong>${esc(clientName)}</strong></div><div><small>Объект</small><strong>${esc(passport.site_name || 'Не указан')}</strong>${passport.site_address ? `<span>${esc(passport.site_address)}</span>` : ''}</div></div>${photoControl}
      <nav class="passport-tabs" aria-label="Разделы паспорта"><button class="active" data-passport-tab="overview">Обзор</button><button data-passport-tab="history">История</button><button data-passport-tab="documents">Документы <span>${passport.documents.length}</span></button></nav>
      <section data-passport-panel="overview"><div class="passport-overview-grid"><div class="passport-data"><span>Серийный номер</span><strong class="mono">${esc(passport.serial_number)}</strong></div>${passport.inventory_number ? `<div class="passport-data"><span>Инвентарный номер</span><strong>${esc(passport.inventory_number)}</strong></div>` : ''}<div class="passport-data"><span>Текущий статус</span>${badge(EQUIPMENT_STATUS, passport.status)}</div></div>${passport.active_request ? `<div class="passport-active-request"><div><span>Активная заявка SR-${String(passport.active_request.number).padStart(5, '0')}</span><strong>${esc(passport.active_request.title)}</strong><small>${esc(passport.active_request.assigned_technician_name || 'Мастер ещё не назначен')}</small></div>${requestBadge(passport.active_request)}</div>` : '<div class="passport-no-request">Активных заявок нет — оборудование готово к работе.</div>'}<div class="passport-qr"><img src="${qrObjectUrl}" data-object-url alt="QR-код оборудования"><div><span>QR оборудования</span><p>Используйте для быстрого открытия паспорта и обращения в сервис.</p><button class="btn btn-ghost btn-sm" id="passport-qr-download-inline">Скачать QR</button></div></div></section>
      <section class="hidden" data-passport-panel="history"><div class="equipment-history"><h3>История обслуживания</h3>${history}</div></section>
      <section class="hidden" data-passport-panel="documents"><div class="passport-documents">${documents}</div></section>
    </section>`, `<span class="passport-footer-action">${primaryAction}</span><button class="btn btn-secondary" id="passport-close">Закрыть</button>`);
    backdrop.querySelector('#passport-close').addEventListener('click', closeModal);
    if (passport.primary_photo) {
      apiBlob(`/equipment/${passport.id}/photo`).then((blob) => {
        const image = backdrop.querySelector('#passport-primary-photo');
        if (!image) return;
        image.src = URL.createObjectURL(blob); image.setAttribute('data-object-url', '');
      }).catch(() => toast('Фото оборудования временно недоступно', 'error'));
    }
    backdrop.querySelector('#passport-photo-upload').addEventListener('change', async (event) => {
      const file = event.target.files?.[0]; if (!file) return;
      try { await uploadEquipmentPhoto(passport.id, file); toast('Фото оборудования сохранено'); closeModal(); openEquipmentPassport(passport.id); }
      catch (error) { toast(error.message || 'Не удалось загрузить фото', 'error'); }
    });
    backdrop.querySelector('#passport-photo-delete')?.addEventListener('click', async () => {
      if (!confirm('Удалить основное фото оборудования?')) return;
      try { await api(`/equipment/${passport.id}/photo`, { method: 'DELETE' }); toast('Фото удалено'); closeModal(); openEquipmentPassport(passport.id); }
      catch (error) { toast(error.message || 'Не удалось удалить фото', 'error'); }
    });
    const downloadQr = () => downloadBlob(qrBlob, qrFilename);
    backdrop.querySelector('#passport-download-qr').addEventListener('click', downloadQr);
    backdrop.querySelector('#passport-qr-download-inline').addEventListener('click', downloadQr);
    backdrop.querySelector('#passport-more').addEventListener('click', (event) => {
      const menu = backdrop.querySelector('#passport-more-menu');
      const isOpen = menu.classList.toggle('hidden') === false;
      event.currentTarget.setAttribute('aria-expanded', String(isOpen));
    });
    backdrop.querySelectorAll('[data-passport-tab]').forEach((tab) => tab.addEventListener('click', () => {
      backdrop.querySelectorAll('[data-passport-tab]').forEach((item) => item.classList.toggle('active', item === tab));
      backdrop.querySelectorAll('[data-passport-panel]').forEach((panel) => panel.classList.toggle('hidden', panel.dataset.passportPanel !== tab.dataset.passportTab));
    }));
    backdrop.querySelectorAll('[data-history-request]').forEach((card) => {
      const open = () => navigateToServiceRequest(card.dataset.historyRequest);
      card.addEventListener('click', (event) => { if (!event.target.closest('[data-history-photo-url]')) open(); });
      card.addEventListener('keydown', (event) => { if (!event.target.closest('[data-history-photo-url]') && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); open(); } });
    });
    backdrop.querySelector('#passport-primary-request')?.addEventListener('click', () => navigateToServiceRequest(passport.active_request.id));
    backdrop.querySelector('#passport-create-request')?.addEventListener('click', () => openCreateServiceRequestForEquipment(passport));
    backdrop.querySelector('#passport-manage')?.addEventListener('click', () => openEquipmentManageModal(passport));
    backdrop.querySelector('#passport-archive')?.addEventListener('click', async () => {
      if (!confirm('Архивировать оборудование? Его можно вернуть через редактирование статуса.')) return;
      try { await api(`/equipment/${passport.id}`, { method: 'PATCH', body: JSON.stringify({ status: 'mothballed' }) }); closeModal(); toast('Оборудование архивировано'); router(); } catch (e) { toast(e.message, 'error'); }
    });
    const downloadAct = async (repairId) => {
      try { downloadBlob(await apiBlob(`/repairs/${repairId}/act.pdf`), `service-act-${repairId.slice(0, 8)}.pdf`); } catch (e) { toast(e.message, 'error'); }
    };
    backdrop.querySelectorAll('.download-act-btn').forEach((button) => button.addEventListener('click', () => downloadAct(button.dataset.repairId)));
    backdrop.querySelectorAll('[data-history-photo-url]').forEach((button) => {
      const photoUrl = button.dataset.historyPhotoUrl;
      apiBlob(photoUrl).then((blob) => {
        const image = button.querySelector('img'); if (!image) return;
        const url = URL.createObjectURL(blob); image.src = url; image.setAttribute('data-object-url', '');
      }).catch(() => button.classList.add('is-unavailable'));
      button.addEventListener('click', (event) => { event.stopPropagation(); openProtectedImage(photoUrl, 'Фото работ'); });
    });
    backdrop.querySelectorAll('.passport-document').forEach((button) => button.addEventListener('click', async () => {
      try {
        if (button.dataset.documentKind === 'service_act') return downloadAct(button.dataset.repairId);
        downloadBlob(await apiBlob(`/repairs/attachments/${button.dataset.attachmentId}`), button.querySelector('strong').textContent || 'document');
      } catch (e) { toast(e.message, 'error'); }
    }));
  } catch (e) { toast(e.message, 'error'); }
}

// ============================================================
// Раздел: Склад и запчасти
// ============================================================

async function renderWarehouse(content) {
  const isStaff = state.me.role !== 'technician';
  const warehouses = await api('/warehouses');
  const myWarehouse = isStaff ? null : warehouses.find((w) => w.owner_user_id === state.me.id);
  const activeWarehouseId = isStaff ? (warehouses[0] && warehouses[0].id) : (myWarehouse && myWarehouse.id);

  content.innerHTML = `
    <div class="page-header">
      <div><h1>${isStaff ? 'Склад и запчасти' : 'Мой склад'}</h1><div class="page-subtitle">${isStaff ? 'Остатки по центральному и мобильным складам' : 'Запчасти в вашем автомобиле'}</div></div>
      ${isStaff ? '<div style="display:flex;gap:8px"><button class="btn btn-secondary" id="receive-btn">Приёмка</button><button class="btn btn-secondary" id="transfer-btn">Перемещение</button><button class="btn btn-primary" id="add-part-btn">+ Запчасть</button></div>' : ''}
    </div>
    ${isStaff ? `<div class="field" style="max-width:320px"><label>Склад</label><select id="warehouse-select">${warehouses.map((w) => `<option value="${w.id}" ${w.id === activeWarehouseId ? 'selected' : ''}>${esc(w.name)} ${w.type === 'central' ? '(центральный)' : ''}</option>`).join('')}</select></div>` : ''}
    <div class="card" style="padding:0">
      <table>
        <thead><tr><th>Запчасть</th><th>Артикул</th><th>Остаток</th></tr></thead>
        <tbody id="stock-rows"></tbody>
      </table>
    </div>`;

  async function loadStock(warehouseId) {
    if (!warehouseId) {
      document.getElementById('stock-rows').innerHTML = '<tr class="empty-row"><td colspan="3">Склад не настроен</td></tr>';
      return;
    }
    const stock = await api(`/warehouses/${warehouseId}/stock`);
    document.getElementById('stock-rows').innerHTML = stock.length ? stock.map((s) => `
      <tr>
        <td>${esc(s.name)}</td>
        <td class="mono text-soft">${esc(s.article)}</td>
        <td class="${s.is_critical ? 'stat-critical' : ''}">${s.quantity}${s.is_critical ? ' · ниже минимума' : ''}</td>
      </tr>`).join('') : '<tr class="empty-row"><td colspan="3">На складе пусто</td></tr>';
  }

  await loadStock(activeWarehouseId);

  if (isStaff) {
    document.getElementById('warehouse-select').addEventListener('change', (e) => loadStock(e.target.value));
    document.getElementById('receive-btn').addEventListener('click', () => openStockMoveModal('receipt', warehouses));
    document.getElementById('transfer-btn').addEventListener('click', () => openStockMoveModal('transfer', warehouses));
    document.getElementById('add-part-btn').addEventListener('click', openCreatePartModal);
  }
}

async function openStockMoveModal(type, warehouses) {
  const parts = await api('/parts');
  const isTransfer = type === 'transfer';
  const backdrop = openModal(isTransfer ? 'Перемещение между складами' : 'Приёмка на склад', `
    <div class="field"><label>Запчасть</label>
      <select id="f-part">${parts.map((p) => `<option value="${p.id}">${esc(p.name)} (${esc(p.article)})</option>`).join('')}</select>
    </div>
    ${isTransfer ? `<div class="field"><label>Со склада</label><select id="f-from">${warehouses.map((w) => `<option value="${w.id}">${esc(w.name)}</option>`).join('')}</select></div>` : ''}
    <div class="field"><label>${isTransfer ? 'На склад' : 'Склад назначения'}</label>
      <select id="f-to">${warehouses.map((w) => `<option value="${w.id}">${esc(w.name)}</option>`).join('')}</select>
    </div>
    <div class="field"><label>Количество</label><input type="number" id="f-qty" min="1" value="1"></div>`,
    `<button class="btn btn-secondary" id="modal-cancel">Отмена</button>
     <button class="btn btn-primary" id="modal-save">${isTransfer ? 'Переместить' : 'Принять'}</button>`);

  backdrop.querySelector('#modal-cancel').addEventListener('click', closeModal);
  backdrop.querySelector('#modal-save').addEventListener('click', async () => {
    const qty = Number(backdrop.querySelector('#f-qty').value);
    if (!qty || qty < 1) return toast('Укажите количество', 'error');
    try {
      const payload = {
        type,
        part_id: backdrop.querySelector('#f-part').value,
        to_warehouse_id: backdrop.querySelector('#f-to').value,
        quantity: qty,
      };
      if (isTransfer) payload.from_warehouse_id = backdrop.querySelector('#f-from').value;
      await api(`/warehouses/movements/${isTransfer ? 'transfer' : 'receive'}`, { method: 'POST', body: JSON.stringify(payload) });
      closeModal();
      toast(isTransfer ? 'Перемещение выполнено' : 'Приёмка выполнена');
      router();
    } catch (e) { toast(e.message, 'error'); }
  });
}

function openCreatePartModal() {
  const backdrop = openModal('Новая запчасть', `
    <div class="field"><label>Артикул</label><input id="f-article" required></div>
    <div class="field"><label>Название</label><input id="f-name" required></div>
    <div class="field-row">
      <div class="field"><label>Ед. измерения</label><input id="f-unit" value="шт"></div>
      <div class="field"><label>Мин. остаток</label><input type="number" id="f-min" value="0" min="0"></div>
    </div>`,
    `<button class="btn btn-secondary" id="modal-cancel">Отмена</button>
     <button class="btn btn-primary" id="modal-save">Создать</button>`);

  backdrop.querySelector('#modal-cancel').addEventListener('click', closeModal);
  backdrop.querySelector('#modal-save').addEventListener('click', async () => {
    const article = backdrop.querySelector('#f-article').value.trim();
    const name = backdrop.querySelector('#f-name').value.trim();
    if (!article || !name) return toast('Заполните артикул и название', 'error');
    try {
      await api('/parts', {
        method: 'POST',
        body: JSON.stringify({
          article, name,
          unit: backdrop.querySelector('#f-unit').value.trim() || 'шт',
          min_critical_qty: Number(backdrop.querySelector('#f-min').value) || 0,
        }),
      });
      closeModal();
      toast('Запчасть добавлена');
      router();
    } catch (e) { toast(e.message, 'error'); }
  });
}

// ============================================================
// Раздел: Пользователи
// ============================================================

async function renderUsers(content) {
  const users = await api('/users');
  content.innerHTML = `
    <div class="page-header">
      <div><h1>Пользователи</h1><div class="page-subtitle">Сотрудники, у которых есть доступ к системе</div></div>
      <button class="btn btn-primary" id="add-user-btn">+ Добавить пользователя</button>
    </div>
    <div class="card" style="padding:0">
      <table>
        <thead><tr><th>Имя</th><th>Email</th><th>Роль</th><th>Телефон</th><th></th></tr></thead>
        <tbody id="user-rows"></tbody>
      </table>
    </div>`;

  document.getElementById('user-rows').innerHTML = users.length ? users.map((u) => `
    <tr>
      <td><strong>${esc(u.full_name)}</strong></td>
      <td>${esc(u.email)}</td>
      <td>${esc(ROLE_LABEL[u.role] || u.role)}</td>
      <td>${esc(u.phone || '—')}</td>
      <td><button class="btn btn-secondary btn-compact" data-edit-user="${u.id}">Редактировать</button></td>
    </tr>`).join('') : '<tr class="empty-row"><td colspan="4">Пользователей пока нет</td></tr>';

  document.getElementById('add-user-btn').addEventListener('click', openCreateUserModal);
  document.getElementById('user-rows').addEventListener('click', (event) => {
    const button = event.target.closest('[data-edit-user]');
    if (!button) return;
    const user = users.find((item) => item.id === button.dataset.editUser);
    if (user) openEditUserModal(user);
  });
}

function openEditUserModal(user) {
  const availability = user.role === 'technician' ? `
    <div class="field"><label><input type="checkbox" id="f-active" ${user.is_active ? 'checked' : ''}> Активен и доступен для назначения</label></div>` : '';
  const backdrop = openModal('Редактировать пользователя', `
    <div class="field"><label>ФИО</label><input id="f-name" required value="${esc(user.full_name)}"></div>
    <div class="field"><label>Телефон</label><input id="f-phone" value="${esc(user.phone || '')}"></div>
    ${availability}`,
    `<button class="btn btn-secondary" id="modal-cancel">Отмена</button>
     <button class="btn btn-primary" id="modal-save">Сохранить</button>`);
  backdrop.querySelector('#modal-cancel').addEventListener('click', closeModal);
  backdrop.querySelector('#modal-save').addEventListener('click', async () => {
    const full_name = backdrop.querySelector('#f-name').value.trim();
    if (!full_name) return toast('Укажите ФИО', 'error');
    const payload = { full_name, phone: backdrop.querySelector('#f-phone').value.trim() || null };
    if (user.role === 'technician') payload.is_active = backdrop.querySelector('#f-active').checked;
    try {
      await api(`/users/${user.id}`, { method: 'PATCH', body: JSON.stringify(payload) });
      closeModal();
      toast('Данные пользователя сохранены');
      router();
    } catch (e) { toast(e.message, 'error'); }
  });
}

function openCreateUserModal() {
  const backdrop = openModal('Новый пользователь', `
    <div class="field"><label>ФИО</label><input id="f-name" required></div>
    <div class="field"><label>Email</label><input type="email" id="f-email" required></div>
    <div class="field"><label>Телефон</label><input id="f-phone"></div>
    <div class="field"><label>Роль</label>
      <select id="f-role">
        <option value="technician">Техник</option>
        <option value="dispatcher">Диспетчер</option>
        <option value="admin">Администратор</option>
      </select>
    </div>
    <div class="field"><label>Пароль</label><input type="password" id="f-password" required></div>`,
    `<button class="btn btn-secondary" id="modal-cancel">Отмена</button>
     <button class="btn btn-primary" id="modal-save">Создать</button>`);

  backdrop.querySelector('#modal-cancel').addEventListener('click', closeModal);
  backdrop.querySelector('#modal-save').addEventListener('click', async () => {
    const full_name = backdrop.querySelector('#f-name').value.trim();
    const email = backdrop.querySelector('#f-email').value.trim();
    const password = backdrop.querySelector('#f-password').value;
    if (!full_name || !email || !password) return toast('Заполните обязательные поля', 'error');
    try {
      await api('/users', {
        method: 'POST',
        body: JSON.stringify({
          full_name, email, password,
          phone: backdrop.querySelector('#f-phone').value.trim() || null,
          role: backdrop.querySelector('#f-role').value,
        }),
      });
      closeModal();
      toast('Пользователь создан');
      router();
    } catch (e) { toast(e.message, 'error'); }
  });
}

// ============================================================
// Авторизация и запуск
// ============================================================

function logout() {
  void removePushSubscription(state.token);
  state.token = null;
  state.me = null;
  localStorage.removeItem('token');
  window.FixitOffline?.db?.kvDelete?.('token').catch(() => null);
  document.getElementById('app').classList.add('hidden');
  document.getElementById('login-screen').classList.remove('hidden');
}

async function boot() {
  if (!state.token) {
    document.getElementById('login-screen').classList.remove('hidden');
    return;
  }
  try {
    state.me = await api('/users/me');
    await registerPulseWorker();
    window.FixitOffline?.configure?.({ token: state.token });
    window.FixitOffline?.sync?.({ token: state.token, deviceId: 'fixit-pulse' });
    document.getElementById('login-screen').classList.add('hidden');
    document.getElementById('app').classList.remove('hidden');
    const joinRoute = sessionStorage.getItem('fixit-join-route');
    if (joinRoute) { sessionStorage.removeItem('fixit-join-route'); location.hash = joinRoute; }
    router();
    setTimeout(() => { maybeStartPwaOnboarding().catch(() => null); }, 0);
  } catch (e) {
    logout();
  }
}

document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById('login-error');
  errorEl.classList.add('hidden');
  const email = document.getElementById('login-email').value.trim();
  const password = document.getElementById('login-password').value;
  try {
    const res = await api('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
    state.token = res.access_token;
    localStorage.setItem('token', state.token);
    await boot();
  } catch (err) {
    errorEl.textContent = err.message || 'Не удалось войти';
    errorEl.classList.remove('hidden');
  }
});

document.getElementById('logout-btn').addEventListener('click', logout);

async function showJoinScreen(token) {
  const host = document.getElementById('join-form-host');
  const login = document.getElementById('login-form');
  const errorEl = document.getElementById('login-error');
  login.classList.add('hidden');
  errorEl.classList.add('hidden');
  errorEl.textContent = '';
  try {
    const invite = await api(`/join/${encodeURIComponent(token)}`);
    host.innerHTML = `<div class="subtitle">${esc(invite.role === 'client_admin' ? 'Подключение руководителя клиента' : 'Подключение менеджера объекта')}<br><b>${esc(invite.client_name)}</b>${invite.site_name ? ` · ${esc(invite.site_name)}` : ''}</div><form id="join-form"><div class="field"><label>ФИО ${invite.requires_existing_login ? '(для нового пользователя)' : ''}</label><input id="join-name" autocomplete="name"></div><div class="field"><label>Email</label><input id="join-email" type="email" required autocomplete="username"></div><div class="field"><label>Пароль</label><input id="join-password" type="password" required minlength="8" autocomplete="current-password"></div><div class="field"><label>Телефон</label><input id="join-phone" autocomplete="tel"></div><button class="btn btn-primary" style="width:100%;justify-content:center">Продолжить</button></form>`;
    host.querySelector('#join-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      try {
        const result = await api(`/join/${encodeURIComponent(token)}/accept`, {method:'POST', body: JSON.stringify({full_name: host.querySelector('#join-name').value.trim() || null, email: host.querySelector('#join-email').value.trim(), password: host.querySelector('#join-password').value, phone: host.querySelector('#join-phone').value.trim() || null})});
        state.token = result.access_token; localStorage.setItem('token', state.token);
        sessionStorage.setItem('fixit-join-route', invite.role === 'client_admin' ? `clients/${invite.client_id}/users` : 'equipment');
        history.replaceState(null, '', '/'); await boot();
      } catch (error) { document.getElementById('login-error').textContent = error.message; document.getElementById('login-error').classList.remove('hidden'); }
    });
  } catch (error) { host.innerHTML = `<div class="login-error">${esc(error.message)}</div><button class="btn btn-secondary" id="join-back">Ко входу</button>`; host.querySelector('#join-back').addEventListener('click', () => { history.replaceState(null, '', '/'); login.classList.remove('hidden'); host.innerHTML=''; }); }
}

async function openClientInviteModal(client, kind) {
  await ensureCustomers(true);
  const manager = kind === 'site-manager';
  const sites = state.sites.filter((site) => site.client_id === client.id && site.is_active);
  const backdrop = openModal(manager ? 'Пригласить менеджера объекта' : 'Подключить руководителя', `<p class="onboarding-intro">${manager ? 'Менеджер получит доступ только к выбранному объекту.' : 'Руководитель увидит уже созданные объекты, оборудование, заявки и команду этого клиента.'}</p><div class="field"><label>Email (необязательно)</label><input id="invite-email" type="email" autocomplete="email" placeholder="name@company.ru"></div>${manager ? `<div class="field"><label>Объект</label><select id="invite-site"><option value="">Выберите объект</option>${sites.map((site) => `<option value="${site.id}">${esc(site.name)}</option>`).join('')}</select></div>` : ''}`, '<button class="btn btn-secondary" id="modal-cancel">Отмена</button><button class="btn btn-primary" id="modal-save">Создать безопасную ссылку</button>');
  const emailInput = backdrop.querySelector('#invite-email');
  // A newly opened invite form must never retain a previously generated URL.
  emailInput.value = '';
  backdrop.querySelector('#modal-cancel').addEventListener('click', closeModal);
  backdrop.querySelector('#modal-save').addEventListener('click', async () => {
    const site_id = manager ? backdrop.querySelector('#invite-site').value : null;
    if (manager && !site_id) return toast('Выберите объект', 'error');
    const invited_email = emailInput.value.trim();
    if (invited_email && !emailInput.checkValidity()) {
      return toast('Укажите корректный email или оставьте поле пустым', 'error');
    }
    try {
      const invite = await api(`/client-portal/clients/${client.id}/invites/${kind}`, {method:'POST', body: JSON.stringify({site_id, invited_email: invited_email || null})});
      backdrop.querySelector('#modal-body').innerHTML = `<p>Скопируйте ссылку или покажите QR сотруднику. Она действует до ${fmtDate(invite.expires_at)} и принимается один раз.</p><div class="field"><label>Ссылка-приглашение</label><input value="${esc(invite.join_url)}" readonly id="invite-url"></div><div id="invite-qr"></div><button class="btn btn-primary" id="copy-invite">Скопировать ссылку</button>`;
      apiBlob(invite.qr_url).then((blob) => { const url = URL.createObjectURL(blob); activeClientPhotoUrls.push(url); backdrop.querySelector('#invite-qr').innerHTML = `<img src="${url}" alt="QR для приглашения">`; }).catch(() => null);
      backdrop.querySelector('#copy-invite').addEventListener('click', async () => { await navigator.clipboard.writeText(invite.join_url); toast('Ссылка скопирована'); });
    } catch (error) { toast(error.message, 'error'); }
  });
}

const joinMatch = location.pathname.match(/^\/join\/([^/]+)$/);
if (joinMatch && !state.token) { document.getElementById('login-screen').classList.remove('hidden'); showJoinScreen(joinMatch[1]); }
else boot();
