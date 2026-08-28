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

let ticketsRefreshTimer = null;
let adminScanStream = null;
let activeTechnicianWorkspaceCleanup = null;

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
  const res = await fetch('/api' + path, { headers });
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
    const url = URL.createObjectURL(await apiBlob(path));
    const backdrop = openModal(title, `<div class="protected-image-viewer"><img src="${url}" data-object-url alt="${esc(title)}"></div>`, '<button class="btn btn-secondary" id="image-viewer-close">Закрыть</button>');
    backdrop.querySelector('#image-viewer-close').addEventListener('click', closeModal);
  } catch (error) {
    toast(error.message || 'Не удалось открыть фотографию', 'error');
  }
}

async function uploadEquipmentPhoto(equipmentId, file) {
  const form = new FormData();
  form.append('file', file);
  return api(`/equipment/${equipmentId}/photo`, { method: 'POST', body: form });
}

// ---------- Справочники (общие) ----------

const EQUIPMENT_STATUS = {
  working: { label: 'Работает', cls: 'good' },
  needs_repair: { label: 'Требует ремонта', cls: 'warn' },
  mothballed: { label: 'На консервации', cls: 'idle' },
  decommissioned: { label: 'Списано', cls: 'idle' },
};
const TASK_STATUS = {
  new: { label: 'Новая', cls: 'idle' },
  assigned: { label: 'Назначена', cls: 'amber' },
  in_progress: { label: 'В работе', cls: 'amber' },
  closed: { label: 'Закрыта', cls: 'good' },
  cancelled: { label: 'Отменена', cls: 'idle' },
};
const TASK_PRIORITY = {
  urgent: { label: 'Срочно', cls: 'warn' },
  planned: { label: 'Плановая', cls: 'idle' },
};
const TICKET_STATUS = {
  new: { label: 'Новая', cls: 'warn' },
  assigned: { label: 'Назначена', cls: 'amber' },
  resolved: { label: 'Решена', cls: 'good' },
};
const TICKET_SEVERITY = {
  not_working: 'Не работает',
  partially_working: 'Работает с перебоями',
};
const ROLE_LABEL = { owner: 'Владелец', admin: 'Администратор', dispatcher: 'Диспетчер', technician: 'Техник' };

function badge(map, key) {
  const info = map[key] || { label: key, cls: 'idle' };
  return `<span class="badge badge-${info.cls}"><span class="badge-dot"></span>${esc(info.label)}</span>`;
}

// ---------- Навигация ----------

const NAV = {
  owner: [
    ['pulse', 'Pulse'], ['requests', 'Заявки'],
    ['clients', 'Клиенты и объекты'], ['equipment', 'Оборудование'], ['tasks', 'Наряды'], ['tickets', 'Заявки от гостей'],
    ['warehouse', 'Склад'], ['users', 'Пользователи'],
  ],
  admin: [
    ['pulse', 'Pulse'], ['requests', 'Заявки'],
    ['clients', 'Клиенты и объекты'],
    ['equipment', 'Оборудование'],
    ['tasks', 'Наряды'],
    ['tickets', 'Заявки от гостей'],
    ['warehouse', 'Склад и запчасти'],
    ['users', 'Пользователи'],
  ],
  dispatcher: [
    ['pulse', 'Pulse'], ['requests', 'Заявки'],
    ['clients', 'Клиенты и объекты'],
    ['equipment', 'Оборудование'],
    ['tasks', 'Наряды'],
    ['tickets', 'Заявки от гостей'],
    ['warehouse', 'Склад и запчасти'],
  ],
  technician: [
    ['pulse', 'Pulse'], ['requests', 'Мои заявки'], ['equipment', 'Оборудование'], ['tasks', 'Мои наряды'],
    ['warehouse', 'Мой склад'],
  ],
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
  const primary = [
    ['pulse', 'Пульс', 'pulse'], ['requests', 'Заявки', 'tasks'], ['qr', 'QR', 'qr'],
    ['equipment', 'Оборудование', 'equipment'], ['more', 'Ещё', 'more'],
  ];
  mobileNav.innerHTML = primary.map(([route, label, icon]) => `
    <button class="mobile-nav-item ${state.route === route ? 'active' : ''}" data-mobile-route="${route}">
      <span class="mobile-nav-icon icon-${icon}"></span><span>${label}</span>
    </button>`).join('');
  moreMenu.innerHTML = `<div class="more-menu-head"><span>Разделы</span><button id="more-close-btn">Закрыть</button></div>${items
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
  const defaultRoute = 'pulse';
  const hashRoute = location.hash.replace('#', '') || defaultRoute;
  const [route, requestId] = hashRoute.split('/');
  state.route = route;
  state.requestId = route === 'requests' && requestId ? requestId : null;
  const allowedRoutes = (NAV[state.me?.role] || []).map(([key]) => key);
  if (!allowedRoutes.includes(state.route)) {
    state.route = defaultRoute;
    history.replaceState(null, '', `#${defaultRoute}`);
  }
  if (state.route !== 'tickets' && ticketsRefreshTimer) {
    clearTimeout(ticketsRefreshTimer);
    ticketsRefreshTimer = null;
  }
  renderNav();
  const content = document.getElementById('content');
  if (activeTechnicianWorkspaceCleanup) {
    activeTechnicianWorkspaceCleanup();
    activeTechnicianWorkspaceCleanup = null;
  }
  content.innerHTML = '<div class="section-loading">Загрузка…</div>';
  try {
    if (state.route === 'pulse') await renderPulse(content);
    else if (state.route === 'requests' && state.requestId) await openServiceRequest(state.requestId);
    else if (state.route === 'requests') await renderServiceRequests(content);
    else if (state.route === 'clients') await renderClients(content);
    else if (state.route === 'equipment') await renderEquipment(content);
    else if (state.route === 'tasks') await renderTasks(content);
    else if (state.route === 'tickets') await renderTickets(content);
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

async function openServiceRequest(id) {
  if (!id) {
    toast('Не удалось определить заявку', 'error');
    return;
  }
  try {
    const item = await api(`/service-requests/${id}`);
    if (!item || !item.id) throw new Error('Сервис не вернул данные заявки');
    // Passport is itself a modal. Replace it explicitly instead of relying on
    // openModal side effects; otherwise it can remain above the technician workspace.
    closeModal();
    if (state.me?.role === 'technician') return openTechnicianRequestWorkspace(id, item);
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
    const approvalActions = item.status === 'waiting_approval' ? '<button class="btn btn-secondary" id="approval-reject">Отклонено</button><button class="btn btn-primary" id="approval-approve">Согласовано</button>' : '';
    const backdrop = openModal('', `<section class="service-request-detail"><header class="sr-detail-header"><div><span>SR-${String(item.number).padStart(5, '0')}</span><h2>Заявка на сервис</h2></div>${statusBadge}</header>${rejectionNotice}<section class="sr-equipment-hero">${equipmentPhoto}<div><span class="sr-kicker">${esc(item.equipment_type || item.equipment_name || 'Оборудование')}</span><h3>${esc([item.manufacturer, item.model].filter(Boolean).join(' ') || item.equipment_name || 'Оборудование')}</h3><p>S/N ${esc(item.serial_number || '—')}</p></div></section><section class="sr-detail-grid"><div><span>Клиент / объект</span><strong>${esc(item.client_name || 'Клиент не указан')}</strong><small>${esc(item.site_name || 'Объект не указан')}</small></div><div><span>Мастер</span><strong>${esc(item.assigned_technician_name || 'Не назначен')}</strong></div></section><section class="sr-problem"><span>Проблема</span><p>${esc(item.description || 'Без описания')}</p></section>${approvalContext}<section class="sr-photos"><h3>Фотографии</h3>${mediaGallery}</section><section class="sr-timeline"><h3>Ход заявки</h3>${history}</section></section>`, `<button class="btn btn-secondary" id="modal-cancel">Закрыть</button>${approvalActions}`);
    backdrop.querySelector('#modal-cancel').addEventListener('click', closeModal);
    if (item.primary_photo) {
      apiBlob(`/equipment/${item.equipment_id}/photo`).then((blob) => {
        const image = backdrop.querySelector('#sr-equipment-photo img');
        if (!image) return;
        image.src = URL.createObjectURL(blob); image.setAttribute('data-object-url', '');
      }).catch(() => {});
      backdrop.querySelector('#sr-equipment-photo')?.addEventListener('click', () => openProtectedImage(`/equipment/${item.equipment_id}/photo`, 'Фото оборудования'));
    }
    backdrop.querySelectorAll('[data-repair-photo]').forEach((button) => {
      const attachment = repairPhotos.find((photo) => photo.id === button.dataset.repairPhoto);
      apiBlob(`/repairs/attachments/${button.dataset.repairPhoto}`).then((blob) => {
        const image = button.querySelector('img'); if (!image) return;
        image.src = URL.createObjectURL(blob); image.setAttribute('data-object-url', '');
      }).catch(() => { button.classList.add('is-unavailable'); });
      button.addEventListener('click', () => openProtectedImage(`/repairs/attachments/${attachment.id}`, attachment.kind === 'before' ? 'До ремонта' : 'После ремонта'));
    });
    backdrop.querySelectorAll('[data-request-photo]').forEach((button) => {
      const attachment = requestPhotos.find((photo) => photo.id === button.dataset.requestPhoto);
      apiBlob(`/service-requests/attachments/${button.dataset.requestPhoto}`).then((blob) => {
        const image = button.querySelector('img'); if (!image) return;
        image.src = URL.createObjectURL(blob); image.setAttribute('data-object-url', '');
      }).catch(() => { button.classList.add('is-unavailable'); });
      button.addEventListener('click', () => openProtectedImage(`/service-requests/attachments/${attachment.id}`, attachment.kind === 'approval' ? 'Фото для согласования' : 'Фото заявки'));
    });
    const decideApproval = async (action) => {
      const comment = prompt(action === 'rejected' ? 'Укажите причину отклонения' : 'Комментарий к согласованию (необязательно)');
      if (comment === null) return;
      if (action === 'rejected' && !comment.trim()) return toast('Укажите причину отклонения', 'error');
      try { await api(`/service-requests/${item.id}/approval`, { method: 'PATCH', body: JSON.stringify({ action, comment: comment.trim() || null }) }); closeModal(); openServiceRequest(item.id); } catch (error) { toast(error.message, 'error'); }
    };
    backdrop.querySelector('#approval-approve')?.addEventListener('click', () => decideApproval('approved'));
    backdrop.querySelector('#approval-reject')?.addEventListener('click', () => decideApproval('rejected'));
  } catch (e) {
    toast(`Не удалось открыть заявку: ${e.message || 'неизвестная ошибка'}`, 'error');
  }
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
  let completionInFlight = false;
  let draftCompleted = false;
  const statusText = { assigned: 'Назначена', on_the_way: 'В пути', arrived: 'На объекте', in_progress: 'В работе', waiting_parts: 'Ждёт запчасти', waiting_approval: 'Ждёт согласование', completed: 'Выполнена' };
  const statusAction = { assigned: ['on_the_way', 'Выехал'], on_the_way: ['arrived', 'Я на объекте'], arrived: ['in_progress', 'Начать работу'] };
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
    await RequestDraftStore.put({ key: draftKey, diagnostic: draft.diagnostic, work: draft.work, comment: draft.comment, usedParts: draft.usedParts, photos: draft.photos.filter(hasDraftPhotoFile).map(({ file, approvalAttachmentId }) => ({ blob: file, name: file.name, type: file.type, approvalAttachmentId })), completionLocalUuid, completionRepairId, timestamp: new Date().toISOString() }).catch(() => null);
  };
  const releasePhotos = () => draft.photos.forEach((photo) => URL.revokeObjectURL(photo.url));
  let workCameraStream = null;
  const stopWorkCamera = () => { workCameraStream?.getTracks().forEach((track) => track.stop()); workCameraStream = null; };
  const disposeWorkspace = () => { persistDraft(); stopWorkCamera(); releasePhotos(); if (equipmentPhotoUrl) URL.revokeObjectURL(equipmentPhotoUrl); window.removeEventListener('pagehide', persistOnBackground); document.removeEventListener('visibilitychange', persistOnBackground); };
  const persistOnBackground = (lifecycleEvent) => { if (document.visibilityState === 'hidden' || lifecycleEvent?.type === 'pagehide') persistDraft(); };
  const addDraftFiles = async (files) => {
    const available = 5 - draft.photos.length;
    for (const file of [...files].slice(0, available)) {
      const photo = normalizeDraftPhoto({ file, name: file.name, type: file.type }, draft.photos.length);
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
  const uploadPendingRepairPhotos = async () => {
    if (!completionRepairId) throw new Error('Не найден созданный ремонт для загрузки фото');
    const pending = draft.photos.map((photo, index) => ({ photo, index })).filter(({ photo }) => hasDraftPhotoFile(photo));
    const uploads = await Promise.allSettled(pending.map(async ({ photo }) => {
      const form = new FormData();
      form.append('kind', 'after');
      form.append('file', photo.file, photo.file.name || 'photo.jpg');
      await api(`/repairs/${completionRepairId}/attachments`, { method: 'POST', body: form });
    }));
    const successfulIndexes = pending.filter((_, index) => uploads[index].status === 'fulfilled').map(({ index }) => index).sort((a, b) => b - a);
    successfulIndexes.forEach((index) => {
      const [photo] = draft.photos.splice(index, 1);
      if (photo?.url) URL.revokeObjectURL(photo.url);
    });
    await persistDraft();
    return uploads.filter((upload) => upload.status === 'rejected').length;
  };
  const refreshCompletedRequest = async () => {
    request = await api(`/service-requests/${request.id}`);
    request.history = Array.isArray(request.history) ? request.history : [];
    request.attachments = Array.isArray(request.attachments) ? request.attachments : [];
    request.request_attachments = Array.isArray(request.request_attachments) ? request.request_attachments : [];
  };
  const draw = () => {
    const timeline = request.history.map((item) => {
      const resumedAfterParts = item.type === 'work.started' && item.details?.from === 'waiting_parts';
      const resumedAfterApproval = item.type === 'work.started' && item.details?.from === 'waiting_approval';
      const label = resumedAfterParts ? 'Работа возобновлена после ожидания запчастей' : resumedAfterApproval ? 'Работа возобновлена после согласования' : eventLabels[item.type] || item.message;
      return `<div class="tech-request-timeline"><span></span><div><strong>${esc(label)}</strong><small>${fmtDate(item.at)}</small></div></div>`;
    }).join('');
    const attachments = request.attachments?.length ? request.attachments.map((item) => `<button class="tech-request-file" data-attachment="${item.id}">${item.kind === 'before' || item.kind === 'after' ? 'Фото работ' : 'Документ'} · ${esc(item.name || 'вложение')}</button>`).join('') : '<div class="tech-request-empty">Фотографии пока не добавлены</div>';
    const parts = stock.length ? stock.map((part) => `<div class="tech-request-part"><span><b>${esc(part.name)}</b><small>${esc(part.article)} · остаток ${part.quantity}</small></span><div><button type="button" data-part-minus="${part.part_id}">−</button><b id="part-${part.part_id}">${draft.usedParts[part.part_id] || 0}</b><button type="button" data-part-plus="${part.part_id}" ${(draft.usedParts[part.part_id] || 0) >= part.quantity ? 'disabled' : ''}>+</button></div></div>`).join('') : '<div class="tech-request-empty">На мобильном складе нет доступных запчастей</div>';
    const isWorkStatus = workStatuses.has(request.status);
    const waitingBanner = request.status === 'waiting_parts' ? '<div class="tech-request-state-banner"><strong>Ожидаем запчасти</strong><span>Черновик работ сохранён. После поступления запчастей продолжите работу.</span></div>' : request.status === 'waiting_approval' ? '<div class="tech-request-state-banner"><strong>Ожидается согласование</strong><span>После согласования диспетчер вернёт заявку в работу.</span></div>' : '';
    const photoPreview = draft.photos.length ? `<div class="tech-request-photo-grid">${draft.photos.map((photo, index) => `<figure><img src="${esc(photo.url)}" alt="Фото ${index + 1}"><figcaption>Фото ${index + 1}<button type="button" data-photo-remove="${index}" aria-label="Удалить фото ${index + 1}">×</button></figcaption></figure>`).join('')}</div><div class="tech-request-photo-count">Выбрано ${draft.photos.length} из 5</div>` : '<div class="tech-request-empty">Фотографии пока не выбраны</div>';
    const workArea = isWorkStatus ? `<section class="tech-request-section tech-request-work">${waitingBanner}<h2>Рабочая зона</h2><label>Диагностика<textarea id="request-diagnostic" placeholder="Что обнаружено">${esc(draft.diagnostic)}</textarea></label><label>Выполненные работы<textarea id="request-work" placeholder="Что сделано">${esc(draft.work)}</textarea></label><label>Комментарий<textarea id="request-comment" placeholder="Комментарий для диспетчера">${esc(draft.comment)}</textarea></label><h3>Использованные запчасти</h3>${parts}<h3>Фотографии</h3>${photoPreview}<div class="tech-request-photo-actions"><button type="button" class="tech-request-photo-add" id="request-camera">Добавить фото</button><button type="button" class="btn btn-ghost btn-sm" id="request-gallery-open">Выбрать из галереи</button><input id="request-gallery" type="file" accept="image/*" multiple hidden></div>${request.status === 'in_progress' ? '<div class="tech-request-secondary"><button type="button" id="request-wait-parts">Жду запчасти</button><button type="button" id="request-wait-approval">Жду согласование</button></div>' : ''}</section>` : '';
    const nextAction = statusAction[request.status];
    const action = nextAction
      ? `<button class="btn btn-primary tech-request-main" id="request-next" data-status="${nextAction[0]}">${nextAction[1]}</button>`
      : request.status === 'in_progress' ? '<button class="btn btn-primary tech-request-main" id="request-complete">Завершить работу</button>'
      : request.status === 'waiting_parts' ? '<button class="btn btn-primary tech-request-main" id="request-resume">Продолжить работу</button>'
      : request.status === 'completed' && completionRepairId && draft.photos.length ? '<button class="btn btn-primary tech-request-main" id="request-retry-photos">Повторить загрузку фото</button>' : '';
    content.innerHTML = `<section class="tech-request-workspace"><header class="tech-request-header"><button class="tech-request-back" id="request-back">←</button><div><span>Заявка SR-${String(request.number).padStart(5, '0')}</span><h1>${esc(request.title || request.description || 'Сервисная заявка')}</h1></div>${statusBadge()}</header><div class="tech-request-scroll"><section class="tech-request-meta"><div><small>Приоритет</small><strong>${request.priority === 'urgent' ? 'Срочно' : 'Плановая'}</strong></div><div><small>Создана</small><strong>${fmtDate(request.created_at)}</strong></div></section><section class="tech-request-section"><h2>Клиент и объект</h2><strong>${esc(request.client_name || request.site_name || 'Клиент')}</strong><p>${esc(request.site_name || 'Объект не указан')}${request.site_address ? ` · ${esc(request.site_address)}` : ''}</p>${request.contact_name || request.contact_phone ? `<a href="tel:${esc(request.contact_phone || '')}">${esc(request.contact_name || 'Контакт')} · ${esc(request.contact_phone || '')}</a>` : ''}</section><section class="tech-request-section tech-request-equipment"><div><h2>Оборудование</h2><button class="btn btn-ghost btn-sm" id="request-passport">Открыть паспорт</button></div>${equipmentPhotoUrl ? `<img class="tech-request-equipment-photo" src="${equipmentPhotoUrl}" alt="Фото оборудования">` : '<div class="tech-request-equipment-placeholder">FIXIT</div>'}<strong>${esc(request.equipment_type || request.equipment_name)}</strong><p>${esc([request.manufacturer, request.model].filter(Boolean).join(' ') || 'Модель не указана')} · <span class="mono">S/N ${esc(request.serial_number)}</span></p>${badge(EQUIPMENT_STATUS, request.equipment_status || 'working')}</section><section class="tech-request-section"><h2>Проблема</h2><p>${esc(request.description || 'Описание не добавлено')}</p><div class="tech-request-files">${attachments}</div></section>${workArea}<section class="tech-request-section"><h2>История</h2><div class="tech-request-timeline-list">${timeline}</div></section></div><footer>${action}</footer></section>`;
    content.querySelector('#request-back').addEventListener('click', () => { disposeWorkspace(); activeTechnicianWorkspaceCleanup = null; location.hash = 'requests'; });
    content.querySelector('#request-passport').addEventListener('click', () => openEquipmentPassport(request.equipment_id));
    content.querySelectorAll('[data-attachment]').forEach((button) => button.addEventListener('click', async () => { try { downloadBlob(await apiBlob(`/repairs/attachments/${button.dataset.attachment}`), button.textContent.trim()); } catch (e) { toast(e.message, 'error'); } }));
    const transition = async (status, note = null, details = null) => { rememberDraft(); await persistDraft(); try { request = await api(`/service-requests/${request.id}/status`, { method: 'PATCH', body: JSON.stringify({ status, note, details }) }); request.history = Array.isArray(request.history) ? request.history : []; request.attachments = Array.isArray(request.attachments) ? request.attachments : []; request.request_attachments = Array.isArray(request.request_attachments) ? request.request_attachments : []; if (workStatuses.has(status) && !stock.length) stock = await api('/warehouses/mine/stock').catch(() => []); draw(); } catch (e) { toast(e.message, 'error'); } };
    content.querySelector('#request-next')?.addEventListener('click', () => transition(content.querySelector('#request-next').dataset.status));
    content.querySelector('#request-resume')?.addEventListener('click', () => transition('in_progress'));
    content.querySelector('#request-retry-photos')?.addEventListener('click', async () => {
      if (completionInFlight) return;
      completionInFlight = true;
      try {
        const failedUploads = await uploadPendingRepairPhotos();
        await refreshCompletedRequest();
        if (failedUploads) toast(`Не удалось загрузить ${failedUploads} фото. Повторите попытку позже.`, 'error');
        else { releasePhotos(); draft.photos = []; draftCompleted = true; await RequestDraftStore.remove(draftKey).catch(() => null); toast('Все фотографии загружены'); }
        draw();
      } catch (error) { toast(error.message || 'Не удалось загрузить фото', 'error'); }
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
    content.querySelector('#request-complete')?.addEventListener('click', async () => {
      rememberDraft();
      if (!draft.work.trim()) return toast('Опишите выполненные работы', 'error');
      if (completionInFlight) return;
      completionInFlight = true;
      const parts_used = Object.entries(draft.usedParts).filter(([, quantity]) => quantity > 0).map(([part_id, quantity]) => ({ part_id, quantity }));
      const started = request.history.find((item) => item.type === 'work.started')?.at || new Date().toISOString();
      try {
        if (!completionRepairId) {
          completionLocalUuid ||= createUuid();
          await persistDraft();
          const result = await api('/v1/sync/repairs', { method: 'POST', body: JSON.stringify({ device_id: 'web-technician-workspace', repairs: [{ local_uuid: completionLocalUuid, equipment_id: request.equipment_id, task_id: request.task_id, ticket_id: request.ticket_id, fault_type: draft.diagnostic.trim() || null, description: [draft.diagnostic.trim() && `Диагностика: ${draft.diagnostic.trim()}`, `Работы: ${draft.work.trim()}`, draft.comment.trim() && `Комментарий: ${draft.comment.trim()}`].filter(Boolean).join('\n'), labor_minutes: 0, client_signer_name: null, client_signed_at: null, started_at: started, closed_at: new Date().toISOString(), device_updated_at: new Date().toISOString(), base_equipment_version: request.equipment_version || 1, parts_used }] }) });
          completionRepairId = result.results?.[0]?.server_id;
          if (!completionRepairId || result.results?.[0]?.resolved_as === 'failed') throw new Error(result.results?.[0]?.error || 'Не удалось завершить работы');
          await persistDraft();
        }
        const failedUploads = await uploadPendingRepairPhotos();
        await refreshCompletedRequest();
        if (failedUploads) {
          toast(`Ремонт завершён, но ${failedUploads} фото не загрузилось. Повторите загрузку.`, 'error');
        } else {
          releasePhotos(); draft.photos = []; draftCompleted = true; await RequestDraftStore.remove(draftKey).catch(() => null);
          toast('Работы завершены, сервисный акт сформирован');
        }
        draw();
      } catch (e) { toast(e.message, 'error'); } finally { completionInFlight = false; }
    });
  };
  activeTechnicianWorkspaceCleanup = disposeWorkspace;
  window.addEventListener('pagehide', persistOnBackground);
  document.addEventListener('visibilitychange', persistOnBackground);
  draw();
}

// ============================================================
// Раздел: Fixit Pulse
// ============================================================

async function renderPulse(content) {
  if (state.me.role === 'technician') return renderTechnicianPulse(content);
  const [clients, sites, equipment, tasks, tickets, users] = await Promise.all([
    api('/clients'), api('/sites'), api('/equipment'), api('/tasks'), api('/tickets'), api('/users'), ensureEquipmentTypes(),
  ]);
  state.clients = clients;
  state.sites = sites;
  const activeTasks = tasks.filter((task) => !['closed', 'cancelled'].includes(task.status));
  const workTasks = activeTasks.filter((task) => ['assigned', 'in_progress'].includes(task.status));
  const urgentTasks = activeTasks.filter((task) => task.priority === 'urgent');
  const newTickets = tickets.filter((ticket) => ticket.status === 'new');
  const now = new Date();
  const overdueTasks = activeTasks.filter((task) => task.due_at && new Date(task.due_at) < now);
  const technicians = users.filter((user) => user.role === 'technician' && user.is_active);
  const activeTechIds = new Set(workTasks.map((task) => task.assigned_to).filter(Boolean));
  const activeTechnicians = technicians.filter((tech) => activeTechIds.has(tech.id));
  const teamRoute = state.me.role === 'dispatcher' ? 'tasks' : 'users';
  const attentionEquipment = equipment.filter((item) => item.status === 'needs_repair');
  const workingEquipment = equipment.filter((item) => item.status === 'working').length;
  const uptime = equipment.length ? Math.round((workingEquipment / equipment.length) * 100) : 100;
  const siteOf = (id) => sites.find((site) => site.id === id);
  const clientOf = (id) => clients.find((client) => client.id === id);
  const typeName = (id) => (state.equipmentTypes.find((type) => type.id === id) || {}).name || 'Оборудование';

  const taskRows = activeTasks.sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
  content.innerHTML = `
    <section class="pulse-command">
      <div class="pulse-command-copy"><div class="eyebrow">FIXIT PULSE · LIVE CONTROL</div><h1>Пульс сервиса</h1><p>Заявки, объекты и команда в одном рабочем контуре.</p></div>
      <div class="pulse-command-live"><span></span><div><b>Онлайн</b><small>${activeTasks.length} активных работ</small></div></div>
      <div class="pulse-orbit orbit-a"></div><div class="pulse-orbit orbit-b"></div>
    </section>
    <div class="metric-grid">
      <button class="metric-card metric-new" data-jump="tickets"><span class="metric-label">Новые заявки</span><strong>${newTickets.length}</strong><small>из QR и гостевой формы</small></button>
      <button class="metric-card metric-dark" data-jump="tasks"><span class="metric-label">В работе</span><strong>${workTasks.length}</strong><small>${urgentTasks.length ? `${urgentTasks.length} срочных` : 'спокойная очередь'}</small></button>
      <button class="metric-card metric-alert" data-jump="tasks"><span class="metric-label">Просрочено</span><strong>${overdueTasks.length}</strong><small>нужна реакция диспетчера</small></button>
      <button class="metric-card metric-accent" data-jump="${teamRoute}"><span class="metric-label">Мастера в работе</span><strong>${activeTechnicians.length}</strong><small>из ${technicians.length} активных</small></button>
    </div>
    <section class="quick-actions"><div class="section-caption">Быстрые действия</div><div class="quick-action-grid">
      <button data-jump="tickets"><span class="quick-action-icon qa-ticket">+</span><b>Разобрать заявки</b><small>${newTickets.length} новых</small></button>
      <button data-jump="tasks"><span class="quick-action-icon qa-task">↗</span><b>Открыть наряды</b><small>${workTasks.length} в работе</small></button>
      <button data-quick="qr"><span class="quick-action-icon qa-qr">⌘</span><b>QR оборудования</b><small>Наклейки и паспорта</small></button>
      <button data-jump="equipment"><span class="quick-action-icon qa-equipment">◌</span><b>Оборудование</b><small>${attentionEquipment.length} требует внимания</small></button>
    </div></section>
    <div class="pulse-grid">
      <section class="card pulse-panel">
        <div class="panel-head"><div><span class="eyebrow">АКТИВНО</span><h2>Последние активные заявки</h2></div><button class="text-link" data-jump="tasks">Все наряды →</button></div>
        <div class="pulse-list">${taskRows.length ? taskRows.slice(0, 6).map((task) => {
          const item = equipment.find((eq) => eq.id === task.equipment_id);
          const site = item ? siteOf(item.site_id) : null;
          const overdue = task.due_at && new Date(task.due_at) < now;
          return `<button class="pulse-row" data-jump="tasks"><span class="priority-mark ${task.priority === 'urgent' || overdue ? 'urgent' : ''}"></span><div><strong>${esc(task.title)}</strong><small>${esc(site?.name || item?.location || 'Объект не указан')} · ${esc(item ? typeName(item.equipment_type_id) : '')}</small></div><div>${overdue ? '<span class="overdue-tag">Просрочено</span>' : badge(TASK_STATUS, task.status)}</div></button>`;
        }).join('') : '<div class="pulse-empty">Активных нарядов нет — сервис работает штатно</div>'}</div>
      </section>
      <section class="card pulse-panel">
        <div class="panel-head"><div><span class="eyebrow">КОМАНДА</span><h2>Мастера на линии</h2></div><button class="text-link" data-jump="${teamRoute}">Команда →</button></div>
        <div class="team-list">${technicians.length ? technicians.slice(0, 6).map((tech) => {
          const count = workTasks.filter((task) => task.assigned_to === tech.id).length;
          return `<div class="team-row"><span class="team-avatar">${esc(tech.full_name.split(/\s+/).slice(0, 2).map((part) => part[0]).join(''))}</span><div><strong>${esc(tech.full_name)}</strong><small>${count ? `${count} активн. ${count === 1 ? 'наряд' : 'наряда'}` : 'Свободен'}</small></div><span class="team-state ${count ? 'busy' : ''}">${count ? 'В работе' : 'Свободен'}</span></div>`;
        }).join('') : '<div class="pulse-empty">Добавьте мастеров, чтобы видеть загрузку</div>'}</div>
        <div class="network-strip"><span>${clients.length}<small>клиентов</small></span><span>${sites.length}<small>объектов</small></span><span>${uptime}%<small>готовность</small></span></div>
      </section>
    </div>`;

  content.querySelectorAll('[data-jump]').forEach((button) => {
    button.addEventListener('click', () => { location.hash = button.dataset.jump; });
  });
  content.querySelectorAll('[data-quick="qr"]').forEach((button) => button.addEventListener('click', openQrQuickAction));
}

async function renderTechnicianPulse(content) {
  const [requests, tasks, equipment] = await Promise.all([
    api('/service-requests'), api('/tasks'), api('/equipment'), ensureEquipmentTypes(),
  ]);
  const active = requests.filter((item) => !['completed', 'closed', 'cancelled'].includes(item.status));
  const inProgress = requests.filter((item) => ['on_the_way', 'arrived', 'in_progress'].includes(item.status));
  const queued = requests.filter((item) => ['new', 'assigned', 'waiting_parts', 'waiting_approval'].includes(item.status));
  const today = new Date();
  const overdue = tasks.filter((task) => task.due_at && new Date(task.due_at) < today && !['closed', 'cancelled'].includes(task.status));
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
      <button class="metric-card metric-alert" data-jump="tasks"><span class="metric-label">Просрочено</span><strong>${overdue.length}</strong><small>требует внимания</small></button>
      <button class="metric-card metric-accent" data-jump="equipment"><span class="metric-label">Оборудование</span><strong>${attentionEquipment}</strong><small>единиц требуют ремонта</small></button>
    </div>
    <section class="quick-actions"><div class="section-caption">Рабочие действия</div><div class="quick-action-grid technician-actions">
      <button data-jump="requests"><span class="quick-action-icon qa-ticket">→</span><b>Моя очередь</b><small>${queued.length} ждут выполнения</small></button>
      <button data-jump="tasks"><span class="quick-action-icon qa-task">↗</span><b>Наряды</b><small>открыть работы и акты</small></button>
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
    <div class="card" style="padding:0;margin-bottom:18px">
      <table>
        <thead><tr><th>Клиент</th><th>Реквизиты и контакт</th><th>Объектов</th><th>Оборудования</th><th>Статус</th></tr></thead>
        <tbody>${state.clients.length ? state.clients.map((client) => `
          <tr>
            <td><strong>${esc(client.name)}</strong>${client.legal_name ? `<div class="text-soft">${esc(client.legal_name)}</div>` : ''}</td>
            <td>${client.tax_id ? `<div>ИНН ${esc(client.tax_id)}</div>` : ''}<div class="text-soft">${esc(client.contact_name || '')} ${esc(client.contact_phone || '')}</div></td>
            <td>${client.site_count}</td><td>${client.equipment_count}</td>
            <td>${client.is_active ? badge({ active: { label: 'Активен', cls: 'good' } }, 'active') : badge({ inactive: { label: 'Отключён', cls: 'idle' } }, 'inactive')}</td>
          </tr>`).join('') : '<tr class="empty-row"><td colspan="5">Клиентов пока нет</td></tr>'}</tbody>
      </table>
    </div>
    <div class="page-header" style="margin-bottom:10px"><div><h1 style="font-size:20px">Объекты обслуживания</h1></div></div>
    <div class="card" style="padding:0">
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
    </div>`;

  if (canEdit) {
    document.getElementById('add-client-btn').addEventListener('click', openCreateClientModal);
    document.getElementById('add-site-btn').addEventListener('click', openCreateSiteModal);
  }
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

function openCreateSiteModal() {
  const activeClients = state.clients.filter((client) => client.is_active);
  if (!activeClients.length) return toast('Сначала создайте активного клиента', 'error');
  const backdrop = openModal('Новый объект обслуживания', `
    <form id="site-form">
      <div class="field"><label>Клиент</label><select id="f-site-client" required>${activeClients.map((client) => `<option value="${client.id}">${esc(client.name)}</option>`).join('')}</select></div>
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
  const canEdit = true;
  const activeSites = state.sites.filter((site) => site.is_active);

  content.innerHTML = `
    <div class="page-header">
      <div><h1>Оборудование</h1><div class="page-subtitle">Цифровой паспорт и лента ремонтов по каждой единице техники</div></div>
      <div style="display:flex;gap:10px;align-items:center">
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
  renderRows();
  document.getElementById('equipment-location-filter').addEventListener('change', renderRows);
  const sitePicker = document.getElementById('equipment-site-picker');
  const siteMenu = document.getElementById('equipment-site-menu');
  document.getElementById('equipment-site-trigger').addEventListener('click', () => siteMenu.classList.toggle('hidden'));
  siteMenu.querySelectorAll('[data-site-value]').forEach((button) => button.addEventListener('click', () => {
    const select = document.getElementById('equipment-location-filter');
    select.value = button.dataset.siteValue;
    document.getElementById('equipment-site-label').textContent = button.textContent.trim().replace(/\s+/g, ' ');
    siteMenu.classList.add('hidden'); renderRows();
  }));
  content.addEventListener('click', (event) => {
    if (!sitePicker.contains(event.target)) siteMenu.classList.add('hidden');
  });

  if (canEdit) {
    document.getElementById('add-equipment-btn').addEventListener('click', openCreateEquipmentModal);
  }
}

function openCreateEquipmentModal() {
  const typeOptions = state.equipmentTypes.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join('');
  const activeSites = state.sites.filter((site) => site.is_active);
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

async function openCreateTaskForEquipment(passport) {
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
        await api('/tasks', { method: 'POST', body: JSON.stringify({ equipment_id: passport.id, title, description: backdrop.querySelector('#passport-request-description').value.trim() || null, priority: backdrop.querySelector('#passport-request-priority').value, assigned_to: backdrop.querySelector('#passport-request-tech').value || null }) });
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
    const statusLabels = { new: 'Новая', assigned: 'Назначена', on_the_way: 'В пути', in_progress: 'В работе', waiting_parts: 'Ждёт запчасти', waiting_approval: 'Ждёт согласование', completed: 'Выполнена', closed: 'Закрыта', cancelled: 'Отменена' };
    const requestBadge = (request) => `<span class="badge badge-${['completed', 'closed'].includes(request.status) ? 'good' : request.status.startsWith('waiting') ? 'amber' : request.status === 'cancelled' ? 'idle' : 'warn'}"><span class="badge-dot"></span>${esc(statusLabels[request.status] || request.status)}</span>`;
    const timeline = passport.timeline.map((entry) => `<article class="equipment-timeline-item"><span class="equipment-timeline-dot ${entry.kind.startsWith('repair') ? 'repair' : entry.kind.startsWith('request') ? 'request' : ''}"></span><div><div class="equipment-timeline-meta">${fmtDate(entry.occurred_at)} · ${entry.request_number ? `SR-${String(entry.request_number).padStart(5, '0')}` : entry.kind === 'repair.completed' ? 'Сервис' : 'Паспорт'}</div><strong>${esc(entry.title)}</strong>${entry.description ? `<p>${esc(entry.description)}</p>` : ''}${entry.parts_used?.length ? `<div class="equipment-parts">Запчасти: ${entry.parts_used.map((part) => `${esc(part.part_name)} ×${part.quantity}`).join(', ')}</div>` : ''}${entry.request_id ? `<button class="btn btn-ghost btn-sm open-request-btn" data-request-id="${entry.request_id}">Открыть заявку</button>` : ''}${entry.has_service_act ? `<button class="btn btn-ghost btn-sm download-act-btn" data-repair-id="${entry.repair_id}">Сервисный акт PDF</button>` : ''}</div></article>`).join('') || '<div class="passport-empty">Событий пока нет</div>';
    const documents = passport.documents.map((document) => `<button class="passport-document" data-document-kind="${esc(document.kind)}" data-repair-id="${document.repair_id || ''}" data-attachment-id="${document.attachment_id || ''}"><span class="passport-document-icon">${document.kind === 'service_act' ? 'PDF' : document.kind === 'before' || document.kind === 'after' ? 'Фото' : 'Файл'}</span><span><strong>${esc(document.title)}</strong><small>${fmtDate(document.created_at)}${document.media_type ? ` · ${esc(document.media_type)}` : ''}</small></span><b>↓</b></button>`).join('') || '<div class="passport-empty">Фотографии и сервисные акты появятся здесь после выполнения работ.</div>';
    const qrFilename = `QR — ${String(passport.model || equipmentTypeName).replace(/[<>:"/\\|?*\x00-\x1F]/g, '_')}.svg`;
    const primaryAction = passport.active_request
      ? `<button class="btn btn-primary" id="passport-primary-request">Открыть заявку SR-${String(passport.active_request.number).padStart(5, '0')}</button>`
      : isStaff ? '<button class="btn btn-primary" id="passport-create-request">Создать заявку</button>' : '';
    const photoControl = `<section class="passport-photo"><div class="passport-photo-frame">${passport.primary_photo ? '<img id="passport-primary-photo" alt="Фото оборудования">' : '<span>FIXIT<br>оборудование</span>'}</div><div><span>Фото оборудования</span><p>${passport.primary_photo ? 'Основное фото паспорта' : 'Добавьте фото, чтобы быстрее узнать машину на объекте.'}</p><label class="btn btn-ghost btn-sm">${passport.primary_photo ? 'Заменить фото' : 'Добавить фото'}<input id="passport-photo-upload" type="file" accept="image/*" hidden></label>${passport.primary_photo ? '<button class="btn btn-ghost btn-sm" id="passport-photo-delete">Удалить</button>' : ''}</div></section>`;
    const backdrop = openModal('', `<section class="equipment-passport">
      <header class="passport-hero"><div><span class="passport-eyebrow">${esc(equipmentTypeName)}</span><h2>${esc([passport.manufacturer, passport.model].filter(Boolean).join(' ') || passport.name)}</h2><div class="passport-status-row">${badge(EQUIPMENT_STATUS, passport.status)}<span class="mono">S/N ${esc(passport.serial_number)}</span></div></div><button type="button" class="passport-more" id="passport-more" aria-label="Дополнительные действия" aria-expanded="false">•••</button><div class="passport-more-menu hidden" id="passport-more-menu" role="menu"><button type="button" role="menuitem" id="passport-download-qr">Скачать QR</button>${isStaff ? '<button type="button" role="menuitem" id="passport-manage">Редактировать и переместить</button><button type="button" role="menuitem" class="passport-menu-danger" id="passport-archive">Архивировать</button>' : ''}</div></header>
      <div class="passport-context"><div><small>Клиент</small><strong>${esc(clientName)}</strong></div><div><small>Объект</small><strong>${esc(passport.site_name || 'Не указан')}</strong>${passport.site_address ? `<span>${esc(passport.site_address)}</span>` : ''}</div></div>${photoControl}
      <nav class="passport-tabs" aria-label="Разделы паспорта"><button class="active" data-passport-tab="overview">Обзор</button><button data-passport-tab="history">История</button><button data-passport-tab="documents">Документы <span>${passport.documents.length}</span></button></nav>
      <section data-passport-panel="overview"><div class="passport-overview-grid"><div class="passport-data"><span>Серийный номер</span><strong class="mono">${esc(passport.serial_number)}</strong></div>${passport.inventory_number ? `<div class="passport-data"><span>Инвентарный номер</span><strong>${esc(passport.inventory_number)}</strong></div>` : ''}<div class="passport-data"><span>Текущий статус</span>${badge(EQUIPMENT_STATUS, passport.status)}</div></div>${passport.active_request ? `<div class="passport-active-request"><div><span>Активная заявка SR-${String(passport.active_request.number).padStart(5, '0')}</span><strong>${esc(passport.active_request.title)}</strong><small>${esc(passport.active_request.assigned_technician_name || 'Мастер ещё не назначен')}</small></div>${requestBadge(passport.active_request)}</div>` : '<div class="passport-no-request">Активных заявок нет — оборудование готово к работе.</div>'}<div class="passport-qr"><img src="${qrObjectUrl}" data-object-url alt="QR-код оборудования"><div><span>QR оборудования</span><p>Используйте для быстрого открытия паспорта и обращения в сервис.</p><button class="btn btn-ghost btn-sm" id="passport-qr-download-inline">Скачать QR</button></div></div></section>
      <section class="hidden" data-passport-panel="history"><div class="equipment-timeline">${timeline}</div></section>
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
    backdrop.querySelectorAll('.open-request-btn').forEach((button) => button.addEventListener('click', () => navigateToServiceRequest(button.dataset.requestId)));
    backdrop.querySelector('#passport-primary-request')?.addEventListener('click', () => navigateToServiceRequest(passport.active_request.id));
    backdrop.querySelector('#passport-create-request')?.addEventListener('click', () => openCreateTaskForEquipment(passport));
    backdrop.querySelector('#passport-manage')?.addEventListener('click', () => openEquipmentManageModal(passport));
    backdrop.querySelector('#passport-archive')?.addEventListener('click', async () => {
      if (!confirm('Архивировать оборудование? Его можно вернуть через редактирование статуса.')) return;
      try { await api(`/equipment/${passport.id}`, { method: 'PATCH', body: JSON.stringify({ status: 'mothballed' }) }); closeModal(); toast('Оборудование архивировано'); router(); } catch (e) { toast(e.message, 'error'); }
    });
    const downloadAct = async (repairId) => {
      try { downloadBlob(await apiBlob(`/repairs/${repairId}/act.pdf`), `service-act-${repairId.slice(0, 8)}.pdf`); } catch (e) { toast(e.message, 'error'); }
    };
    backdrop.querySelectorAll('.download-act-btn').forEach((button) => button.addEventListener('click', () => downloadAct(button.dataset.repairId)));
    backdrop.querySelectorAll('.passport-document').forEach((button) => button.addEventListener('click', async () => {
      try {
        if (button.dataset.documentKind === 'service_act') return downloadAct(button.dataset.repairId);
        downloadBlob(await apiBlob(`/repairs/attachments/${button.dataset.attachmentId}`), button.querySelector('strong').textContent || 'document');
      } catch (e) { toast(e.message, 'error'); }
    }));
  } catch (e) { toast(e.message, 'error'); }
}

// ============================================================
// Раздел: Наряды
// ============================================================

async function renderTasks(content) {
  const isStaff = state.me.role !== 'technician';
  // GET /api/equipment не ограничен по роли — тянем список всегда, иначе
  // у техника в таблице вместо названия оборудования был виден сырой UUID.
  const [tasks, equipmentList, technicians] = await Promise.all([
    api('/tasks'),
    api('/equipment'),
    isStaff ? api('/users').then((u) => u.filter((x) => x.role === 'technician' && x.is_active)) : Promise.resolve([]),
    ensureEquipmentTypes(),
  ]);
  const orderedTasks = [...tasks].sort((a, b) => {
    const aClosed = a.status === 'closed' || a.status === 'cancelled';
    const bClosed = b.status === 'closed' || b.status === 'cancelled';
    if (aClosed !== bClosed) return Number(aClosed) - Number(bClosed);
    return String(b.created_at || '').localeCompare(String(a.created_at || ''));
  });
  const eqOf = (id) => equipmentList.find((x) => x.id === id);
  const typeName = (id) => (state.equipmentTypes.find((type) => type.id === id) || {}).name || '—';
  const eqName = (id) => { const e = eqOf(id); return e ? `${typeName(e.equipment_type_id)} · ${e.serial_number}` : id; };

  content.innerHTML = `
    <div class="page-header">
      <div><h1>${isStaff ? 'Наряды' : 'Мои наряды'}</h1><div class="page-subtitle">${isStaff ? 'Внутренние заявки на обслуживание оборудования' : 'Назначенные вам заявки — можно закрыть здесь или оформить акт ремонта в приложении техника'}</div></div>
      ${isStaff ? '<button class="btn btn-primary" id="add-task-btn">+ Новый наряд</button>' : '<a class="btn btn-secondary" href="/tech/" target="_blank" rel="noopener">Открыть приложение техника →</a>'}
    </div>
    <div class="card" style="padding:0">
      <table class="fixed-table">
        <colgroup>
          <col style="width:26%"><col style="width:22%"><col style="width:12%"><col style="width:12%"><col style="width:13%">${isStaff ? '<col style="width:15%">' : '<col style="width:15%">'}
        </colgroup>
        <thead><tr><th>Заявка</th><th>Оборудование</th><th>Приоритет</th><th>Статус</th><th>Срок</th>${isStaff ? '<th>Техник / действия</th>' : '<th>Действие</th>'}</tr></thead>
        <tbody id="task-rows"></tbody>
      </table>
    </div>`;

  const rows = document.getElementById('task-rows');
  rows.innerHTML = orderedTasks.length ? orderedTasks.map((t) => `
    <tr class="${!isStaff ? 'clickable ' : ''}${t.status === 'closed' || t.status === 'cancelled' ? 'task-row-closed' : 'task-row-active'}" data-eq="${t.equipment_id}">
      <td><strong>${esc(t.title)}</strong>${t.description ? `<div class="text-soft" style="font-size:12px">${esc(t.description)}</div>` : ''}</td>
      <td class="text-soft">${esc(eqName(t.equipment_id))}${eqOf(t.equipment_id)?.location ? `<div style="font-size:12px">${esc(eqOf(t.equipment_id).location)}</div>` : ''}</td>
      <td>${badge(TASK_PRIORITY, t.priority)}</td>
      <td>${badge(TASK_STATUS, t.status)}</td>
      <td class="text-soft">${fmtDate(t.due_at)}</td>
      ${isStaff ? `<td style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
          ${t.assigned_to ? '<span class="badge badge-good"><span class="badge-dot"></span>Назначен</span>' : `<select class="assign-select" data-task="${t.id}"><option value="">— назначить —</option>${technicians.map((tech) => `<option value="${tech.id}">${esc(tech.full_name)}</option>`).join('')}</select>`}
          <button class="btn btn-ghost btn-sm edit-task-btn" data-id="${t.id}">Изменить</button>
          ${t.status === 'new' && !t.assigned_to ? `<button class="btn btn-ghost btn-sm delete-task-btn" data-id="${t.id}" style="color:#b42318">Удалить</button>` : ''}
        </td>` : `<td>${t.status === 'assigned' || t.status === 'in_progress' ? `<button class="btn btn-primary btn-sm close-task-btn" data-id="${t.id}">Закрыть</button>` : '—'}</td>`}
    </tr>`).join('') : `<tr class="empty-row"><td colspan="6">Нарядов пока нет</td></tr>`;

  rows.querySelectorAll('.assign-select').forEach((sel) => {
    sel.addEventListener('change', async (e) => {
      e.stopPropagation();
      if (!sel.value) return;
      try {
        await api(`/tasks/${sel.dataset.task}/assign?technician_id=${sel.value}`, { method: 'PATCH' });
        toast('Техник назначен');
        router();
      } catch (err) { toast(err.message, 'error'); }
    });
    sel.addEventListener('click', (e) => e.stopPropagation());
  });

  rows.querySelectorAll('.edit-task-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const task = tasks.find((t) => t.id === btn.dataset.id);
      openEditTaskModal(task, technicians);
    });
  });

  rows.querySelectorAll('.delete-task-btn').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const task = tasks.find((t) => t.id === btn.dataset.id);
      if (!task || !confirm(`Удалить наряд «${task.title}»? Это действие нельзя отменить.`)) return;
      try {
        await api(`/tasks/${task.id}`, { method: 'DELETE' });
        toast('Наряд удалён');
        router();
      } catch (err) { toast(err.message, 'error'); }
    });
  });

  rows.querySelectorAll('.close-task-btn').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const task = tasks.find((t) => t.id === btn.dataset.id);
      if (!task || !confirm(`Закрыть наряд «${task.title}»?`)) return;
      try {
        await api(`/tasks/${task.id}/close`, { method: 'POST' });
        toast('Наряд закрыт');
        router();
      } catch (err) { toast(err.message, 'error'); }
    });
  });

  if (!isStaff) {
    rows.querySelectorAll('tr[data-eq]').forEach((tr) => {
      tr.addEventListener('click', () => openEquipmentPassport(tr.dataset.eq));
    });
  }

  if (isStaff) {
    document.getElementById('add-task-btn').addEventListener('click', () => openCreateTaskModal(equipmentList, technicians));
  }
}

function openEditTaskModal(task, technicians) {
  const backdrop = openModal('Изменить наряд', `
    <div class="field"><label>Заголовок</label><input id="f-title" value="${esc(task.title)}" required></div>
    <div class="field"><label>Описание</label><textarea id="f-desc" rows="3">${esc(task.description || '')}</textarea></div>
    <div class="field-row">
      <div class="field"><label>Приоритет</label>
        <select id="f-priority"><option value="planned" ${task.priority === 'planned' ? 'selected' : ''}>Плановая</option><option value="urgent" ${task.priority === 'urgent' ? 'selected' : ''}>Срочно</option></select>
      </div>
      <div class="field"><label>Статус</label>
        <select id="f-status">${Object.keys(TASK_STATUS).map((k) => `<option value="${k}" ${task.status === k ? 'selected' : ''}>${TASK_STATUS[k].label}</option>`).join('')}</select>
      </div>
    </div>
    <div class="field"><label>Техник</label>
      <select id="f-tech"><option value="">— не назначен —</option>${technicians.map((t) => `<option value="${t.id}" ${task.assigned_to === t.id ? 'selected' : ''}>${esc(t.full_name)}</option>`).join('')}</select>
    </div>`,
    `${task.status === 'closed' || task.status === 'cancelled' || (task.status === 'new' && !task.assigned_to) ? '<button class="btn btn-ghost" id="modal-delete" style="color:#b42318;margin-right:auto">Удалить</button>' : '<span style="margin-right:auto"></span>'}
     <button class="btn btn-secondary" id="modal-cancel">Отмена</button>
     <button class="btn btn-primary" id="modal-save">Сохранить</button>`);

  backdrop.querySelector('#modal-cancel').addEventListener('click', closeModal);
  backdrop.querySelector('#modal-delete')?.addEventListener('click', async () => {
    if (!confirm(`Удалить наряд «${task.title}»? Сам наряд исчезнет из списка, но оформленные акты ремонта сохранятся в истории.`)) return;
    try {
      await api(`/tasks/${task.id}`, { method: 'DELETE' });
      closeModal();
      toast('Наряд удалён');
      router();
    } catch (e) { toast(e.message, 'error'); }
  });
  backdrop.querySelector('#modal-save').addEventListener('click', async () => {
    const title = backdrop.querySelector('#f-title').value.trim();
    if (!title) return toast('Укажите заголовок', 'error');
    try {
      await api(`/tasks/${task.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          title,
          description: backdrop.querySelector('#f-desc').value.trim() || null,
          priority: backdrop.querySelector('#f-priority').value,
          status: backdrop.querySelector('#f-status').value,
          assigned_to: backdrop.querySelector('#f-tech').value || null,
        }),
      });
      closeModal();
      toast('Наряд обновлён');
      router();
    } catch (e) { toast(e.message, 'error'); }
  });
}

function openCreateTaskModal(equipmentList, technicians) {
  const locations = [...new Set(equipmentList.map((e) => (e.location || '').trim() || 'Не указано'))]
    .sort((a, b) => a.localeCompare(b, 'ru'));
  const backdrop = openModal('Новый наряд', `
    <div class="field"><label>Расположение</label>
      <select id="f-location"><option value="">— выберите объект —</option>${locations.map((location) => `<option value="${esc(location)}">${esc(location)}</option>`).join('')}</select>
    </div>
    <div class="field"><label>Оборудование на объекте</label>
      <select id="f-eq" disabled><option value="">Сначала выберите расположение</option></select>
    </div>
    <div class="field"><label>Заголовок</label><input id="f-title" required placeholder="Например: течёт бак"></div>
    <div class="field"><label>Описание</label><textarea id="f-desc" rows="3"></textarea></div>
    <div class="field-row">
      <div class="field"><label>Приоритет</label>
        <select id="f-priority"><option value="planned">Плановая</option><option value="urgent">Срочно</option></select>
      </div>
      <div class="field"><label>Техник (можно позже)</label>
        <select id="f-tech"><option value="">— не назначен —</option>${technicians.map((t) => `<option value="${t.id}">${esc(t.full_name)}</option>`).join('')}</select>
      </div>
    </div>`,
    `<button class="btn btn-secondary" id="modal-cancel">Отмена</button>
     <button class="btn btn-primary" id="modal-save">Создать</button>`);

  const locationSelect = backdrop.querySelector('#f-location');
  const equipmentSelect = backdrop.querySelector('#f-eq');
  locationSelect.addEventListener('change', () => {
    const location = locationSelect.value;
    const matchingEquipment = equipmentList.filter((e) => ((e.location || '').trim() || 'Не указано') === location);
    equipmentSelect.disabled = !location || !matchingEquipment.length;
    equipmentSelect.innerHTML = matchingEquipment.length
      ? `<option value="">— выберите технику —</option>${matchingEquipment.map((e) => `<option value="${e.id}">${esc((state.equipmentTypes.find((type) => type.id === e.equipment_type_id) || {}).name || e.name)} · ${esc(e.serial_number)}</option>`).join('')}`
      : '<option value="">На этом объекте техники нет</option>';
  });
  backdrop.querySelector('#modal-cancel').addEventListener('click', closeModal);
  backdrop.querySelector('#modal-save').addEventListener('click', async () => {
    const title = backdrop.querySelector('#f-title').value.trim();
    if (!title) return toast('Укажите заголовок', 'error');
    if (!equipmentSelect.value) return toast('Выберите расположение и технику', 'error');
    try {
      await api('/tasks', {
        method: 'POST',
        body: JSON.stringify({
          equipment_id: backdrop.querySelector('#f-eq').value,
          title,
          description: backdrop.querySelector('#f-desc').value.trim() || null,
          priority: backdrop.querySelector('#f-priority').value,
          assigned_to: backdrop.querySelector('#f-tech').value || null,
        }),
      });
      closeModal();
      toast('Наряд создан');
      router();
    } catch (e) { toast(e.message, 'error'); }
  });
}

// ============================================================
// Раздел: Гостевые заявки
// ============================================================

async function renderTickets(content) {
  const [tickets, technicians, equipmentList] = await Promise.all([
    api('/tickets'),
    api('/users').then((u) => u.filter((x) => x.role === 'technician' && x.is_active)),
    api('/equipment'),
    ensureEquipmentTypes(),
  ]);
  const equipmentOf = (id) => equipmentList.find((equipment) => equipment.id === id);
  const typeName = (id) => (state.equipmentTypes.find((type) => type.id === id) || {}).name || '—';

  content.innerHTML = `
    <div class="page-header">
      <div><h1>Заявки от гостей</h1><div class="page-subtitle">Обращения, оставленные через QR на оборудовании, без входа в систему</div></div>
    </div>
    <div class="card mobile-table" style="padding:0">
      <table>
        <thead><tr><th>Что сообщили</th><th>Серьёзность</th><th>Оборудование</th><th>Расположение</th><th>Статус</th><th>Когда</th><th>Назначить</th></tr></thead>
        <tbody id="ticket-rows"></tbody>
      </table>
    </div><div class="mobile-card-list" id="ticket-cards"></div>`;

  const rows = document.getElementById('ticket-rows');
  const cards = document.getElementById('ticket-cards');
  rows.innerHTML = tickets.length ? tickets.map((t) => {
    const equipment = equipmentOf(t.equipment_id);
    return `
    <tr>
      <td>${t.comment ? esc(t.comment) : '<span class="text-soft">без комментария</span>'}${t.symptom_tags.length ? `<div class="text-soft" style="font-size:12px">${t.symptom_tags.map(esc).join(', ')}</div>` : ''}</td>
      <td>${esc(TICKET_SEVERITY[t.severity] || t.severity)}</td>
      <td class="text-soft">${equipment ? `${esc(typeName(equipment.equipment_type_id))}<div style="font-size:12px">${esc(equipment.serial_number)}</div>` : '—'}</td>
      <td>${esc(equipment?.location || 'Не указано')}</td>
      <td>${badge(TICKET_STATUS, t.status)}</td>
      <td>${fmtDate(t.created_at)}</td>
      <td>${t.status === 'resolved' ? '—' : `<select class="ticket-assign" data-id="${t.id}"><option value="">— выбрать —</option>${technicians.map((tech) => `<option value="${tech.id}" ${t.assigned_technician_id === tech.id ? 'selected' : ''}>${esc(tech.full_name)}</option>`).join('')}</select>`}</td>
    </tr>`;
  }).join('') : '<tr class="empty-row"><td colspan="7">Гостевых заявок пока нет</td></tr>';
  cards.innerHTML = tickets.length ? tickets.map((t) => {
    const equipment = equipmentOf(t.equipment_id);
    return `<article class="mobile-info-card ticket-card"><div class="mobile-card-top">${badge(TICKET_STATUS, t.status)}<time>${fmtDate(t.created_at)}</time></div><strong>${esc(t.comment || t.symptom_tags.join(', ') || 'Без описания')}</strong><span class="text-soft">${esc(TICKET_SEVERITY[t.severity] || t.severity)} · ${esc(typeName(equipment?.equipment_type_id))} ${esc(equipment?.serial_number || '')}</span><div class="ticket-assignment"><label>Назначить мастера</label>${t.status === 'resolved' ? '<span class="assigned-master">Заявка решена</span>' : `<select class="ticket-assign" data-id="${t.id}"><option value="">Выберите мастера</option>${technicians.map((tech) => `<option value="${tech.id}" ${t.assigned_technician_id === tech.id ? 'selected' : ''}>${esc(tech.full_name)}</option>`).join('')}</select>`}</div></article>`;
  }).join('') : '<div class="mobile-empty">Гостевых заявок пока нет</div>';

  document.querySelectorAll('.ticket-assign').forEach((sel) => {
    sel.addEventListener('change', async () => {
      if (!sel.value) return;
      try {
        await api(`/tickets/${sel.dataset.id}/assign`, { method: 'PATCH', body: JSON.stringify({ technician_id: sel.value }) });
        toast('Заявка назначена технику');
        router();
      } catch (e) { toast(e.message, 'error'); }
    });
  });

  // Новые QR-обращения приходят без действий диспетчера. Обновляем только
  // открытый экран заявок и одним таймером, чтобы не плодить запросы.
  if (ticketsRefreshTimer) clearTimeout(ticketsRefreshTimer);
  ticketsRefreshTimer = window.setTimeout(() => {
    if (state.route === 'tickets') router();
  }, 15000);
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
  state.token = null;
  state.me = null;
  localStorage.removeItem('token');
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
    document.getElementById('login-screen').classList.add('hidden');
    document.getElementById('app').classList.remove('hidden');
    router();
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

boot();
