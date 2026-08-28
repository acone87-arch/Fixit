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
    ['pulse', 'Pulse'],
    ['clients', 'Клиенты и объекты'], ['equipment', 'Оборудование'], ['tasks', 'Наряды'], ['tickets', 'Заявки от гостей'],
    ['warehouse', 'Склад'], ['users', 'Пользователи'],
  ],
  admin: [
    ['pulse', 'Pulse'],
    ['clients', 'Клиенты и объекты'],
    ['equipment', 'Оборудование'],
    ['tasks', 'Наряды'],
    ['tickets', 'Заявки от гостей'],
    ['warehouse', 'Склад и запчасти'],
    ['users', 'Пользователи'],
  ],
  dispatcher: [
    ['pulse', 'Pulse'],
    ['clients', 'Клиенты и объекты'],
    ['equipment', 'Оборудование'],
    ['tasks', 'Наряды'],
    ['tickets', 'Заявки от гостей'],
    ['warehouse', 'Склад и запчасти'],
  ],
  technician: [
    ['tasks', 'Мои наряды'],
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
    ['pulse', 'Пульс', 'pulse'], ['tasks', 'Заявки', 'tasks'], ['qr', 'QR', 'qr'],
    ['equipment', 'Оборудование', 'equipment'], ['more', 'Ещё', 'more'],
  ];
  mobileNav.innerHTML = primary.map(([route, label, icon]) => `
    <button class="mobile-nav-item ${state.route === route ? 'active' : ''}" data-mobile-route="${route}">
      <span class="mobile-nav-icon icon-${icon}"></span><span>${label}</span>
    </button>`).join('');
  moreMenu.innerHTML = `<div class="more-menu-head"><span>Разделы</span><button id="more-close-btn">Закрыть</button></div>${items
    .filter(([route]) => !['pulse', 'tasks', 'equipment'].includes(route))
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
  const defaultRoute = state.me?.role === 'technician' ? 'tasks' : 'pulse';
  state.route = location.hash.replace('#', '') || defaultRoute;
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
  content.innerHTML = '<div class="section-loading">Загрузка…</div>';
  try {
    if (state.route === 'pulse') await renderPulse(content);
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

// ============================================================
// Раздел: Fixit Pulse
// ============================================================

async function renderPulse(content) {
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
  const canEdit = state.me.role !== 'technician';
  const activeSites = state.sites.filter((site) => site.is_active);

  content.innerHTML = `
    <div class="page-header">
      <div><h1>Оборудование</h1><div class="page-subtitle">Цифровой паспорт и лента ремонтов по каждой единице техники</div></div>
      <div style="display:flex;gap:10px;align-items:center">
        <select id="equipment-location-filter" aria-label="Фильтр по объекту"><option value="">Все объекты</option>${activeSites.map((site) => `<option value="${site.id}">${esc(clientOf(site.client_id)?.name || '—')} · ${esc(site.name)}</option>`).join('')}</select>
        ${canEdit ? '<button class="btn btn-primary" id="add-equipment-btn">+ Добавить оборудование</button>' : ''}
      </div>
    </div>
    <div class="card" style="padding:0">
      <table>
        <thead><tr><th>Тип оборудования</th><th>Серийный №</th><th>Статус</th><th>Клиент и объект</th></tr></thead>
        <tbody id="equipment-rows"></tbody>
      </table>
    </div>`;

  const rows = document.getElementById('equipment-rows');
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
      <td>${esc(client?.name || '—')}<div class="text-soft">${esc(site?.name || eq.location || '—')}</div></td>
      </tr>`;
    }).join('') : '<tr class="empty-row"><td colspan="4">На этом объекте оборудования нет</td></tr>';

    rows.querySelectorAll('tr[data-id]').forEach((tr) => {
      tr.addEventListener('click', () => openEquipmentPassport(tr.dataset.id));
    });
  };
  renderRows();
  document.getElementById('equipment-location-filter').addEventListener('change', renderRows);

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
    return `<option value="${site.id}">${esc(client?.name || '—')} · ${esc(site.name)}</option>`;
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
    </form>`,
    `<button class="btn btn-secondary" id="modal-cancel">Отмена</button>
     <button class="btn btn-primary" id="modal-save">Создать</button>`);

  backdrop.querySelector('#modal-cancel').addEventListener('click', closeModal);
  backdrop.querySelector('#f-type').addEventListener('change', (e) => {
    backdrop.querySelector('#f-newtype-wrap').classList.toggle('hidden', e.target.value !== '__new');
  });

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
      await api('/equipment', {
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
      toast('Оборудование добавлено');
      router();
    } catch (e) {
      toast(e.message, 'error');
    }
  });
}

async function openEquipmentPassport(id) {
  const [passport, qrBlob] = await Promise.all([
    api(`/equipment/${id}/passport`),
    apiBlob(`/equipment/${id}/qr`),
  ]);
  const qrObjectUrl = URL.createObjectURL(qrBlob);
  const equipmentTypeName = (state.equipmentTypes.find((type) => type.id === passport.equipment_type_id) || {}).name || passport.name;
  const site = state.sites.find((item) => item.id === passport.site_id);
  const client = site ? state.clients.find((item) => item.id === site.client_id) : null;
  const canDelete = state.me.role === 'owner' || state.me.role === 'admin' || state.me.role === 'dispatcher';
  const historyHtml = passport.history.length ? passport.history.map((h) => `
    <div style="display:flex;gap:12px;padding:10px 0;border-bottom:1px solid var(--line)">
      <div style="width:8px;height:8px;border-radius:50%;background:var(--accent);margin-top:6px;flex-shrink:0"></div>
      <div>
        <div class="text-soft" style="font-size:12px;font-weight:600">${fmtDate(h.closed_at)} · ${esc(h.technician_name)}</div>
        <div style="margin-top:2px">${esc(h.description)}</div>
        ${h.parts_used.length ? `<div class="mono text-soft" style="font-size:12px;margin-top:2px">${h.parts_used.map((p) => `${esc(p.part_name)} ×${p.quantity}`).join(', ')}</div>` : ''}
        <button class="btn btn-ghost act-download-btn" data-repair-id="${h.repair_id}" style="padding:4px 0;margin-top:6px;font-size:12px;color:var(--accent-strong)">Скачать сервисный акт PDF</button>
      </div>
    </div>`).join('') : '<div class="text-soft" style="padding:12px 0">Ремонтов ещё не было</div>';

  const qrFilenamePart = (value) => String(value || 'без-названия')
    .trim().replace(/[<>:"/\\|?*\x00-\x1F]/g, '_').replace(/\s+/g, ' ');
  const qrFilename = `QR — ${qrFilenamePart(passport.location)} — ${qrFilenamePart(passport.model || equipmentTypeName)}.svg`;
  const backdrop = openModal(equipmentTypeName, `
    <div style="display:flex;gap:16px;align-items:flex-start;margin-bottom:16px">
      <img src="${qrObjectUrl}" data-object-url alt="QR" style="width:96px;height:96px;border:1px solid var(--line);border-radius:8px;padding:6px;background:#fff">
      <div>
        <div>${esc(passport.manufacturer || '')} ${esc(passport.model || '')}</div>
        <div class="mono text-soft" style="margin-top:4px">${esc(passport.serial_number)}</div>
        <div class="text-soft" style="margin-top:4px">${esc(client?.name || '')}${site ? ` · ${esc(site.name)}` : ''}</div>
        <div style="margin-top:8px">${badge(EQUIPMENT_STATUS, passport.status)}</div>
      </div>
    </div>
    <h2 style="font-size:14px;margin-bottom:6px">Лента истории</h2>
    <div>${historyHtml}</div>
  `, `${canDelete ? '<button class="btn btn-ghost" id="delete-equipment-btn" style="color:#b42318">Удалить оборудование</button>' : ''}
      <button class="btn btn-secondary" id="download-qr-btn">Скачать QR</button>
      <button class="btn btn-secondary" id="modal-close">Закрыть</button>`);

  backdrop.querySelector('#modal-close').addEventListener('click', closeModal);
  backdrop.querySelector('#download-qr-btn').addEventListener('click', () => {
    const link = document.createElement('a');
    link.href = qrObjectUrl;
    link.download = qrFilename;
    document.body.appendChild(link);
    link.click();
    link.remove();
  });
  backdrop.querySelectorAll('.act-download-btn').forEach((button) => button.addEventListener('click', async () => {
    const original = button.textContent;
    try {
      button.disabled = true;
      button.textContent = 'Готовим PDF…';
      const blob = await apiBlob(`/repairs/${button.dataset.repairId}/act.pdf`);
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = `service-act-${button.dataset.repairId.slice(0, 8)}.pdf`;
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    } catch (e) { toast(e.message, 'error'); }
    finally { button.disabled = false; button.textContent = original; }
  }));
  const deleteButton = backdrop.querySelector('#delete-equipment-btn');
  if (deleteButton) {
    deleteButton.addEventListener('click', async () => {
      if (!confirm(`Удалить оборудование «${equipmentTypeName}»? Это действие нельзя отменить.`)) return;
      try {
        await api(`/equipment/${id}`, { method: 'DELETE' });
        closeModal();
        toast('Оборудование удалено');
        router();
      } catch (e) { toast(e.message, 'error'); }
    });
  }
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
    <div class="card" style="padding:0">
      <table>
        <thead><tr><th>Что сообщили</th><th>Серьёзность</th><th>Оборудование</th><th>Расположение</th><th>Статус</th><th>Когда</th><th>Назначить</th></tr></thead>
        <tbody id="ticket-rows"></tbody>
      </table>
    </div>`;

  const rows = document.getElementById('ticket-rows');
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

  rows.querySelectorAll('.ticket-assign').forEach((sel) => {
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
