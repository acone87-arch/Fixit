// ============================================================
// Сервис и склад — панель администратора
// Vanilla JS SPA: без сборки, отдаётся FastAPI напрямую из app/static.
// ============================================================

const state = {
  token: localStorage.getItem('token') || null,
  me: null,
  equipmentTypes: [],
  route: location.hash.replace('#', '') || 'equipment',
};

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
  const el = document.querySelector('.modal-backdrop');
  if (el) el.remove();
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
const ROLE_LABEL = { admin: 'Администратор', dispatcher: 'Диспетчер', technician: 'Техник' };

function badge(map, key) {
  const info = map[key] || { label: key, cls: 'idle' };
  return `<span class="badge badge-${info.cls}"><span class="badge-dot"></span>${esc(info.label)}</span>`;
}

// ---------- Навигация ----------

const NAV = {
  admin: [
    ['equipment', 'Оборудование'],
    ['tasks', 'Наряды'],
    ['tickets', 'Заявки от гостей'],
    ['warehouse', 'Склад и запчасти'],
    ['users', 'Пользователи'],
  ],
  dispatcher: [
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
    .map(([key, label]) => `<button class="nav-item ${state.route === key ? 'active' : ''}" data-route="${key}">${esc(label)}</button>`)
    .join('');
  document.querySelectorAll('.nav-item').forEach((btn) => {
    btn.addEventListener('click', () => { location.hash = btn.dataset.route; });
  });
  document.getElementById('user-name').textContent = state.me.full_name;
  document.getElementById('user-role').textContent = ROLE_LABEL[state.me.role] || state.me.role;
}

async function router() {
  state.route = location.hash.replace('#', '') || 'equipment';
  renderNav();
  const content = document.getElementById('content');
  content.innerHTML = '<div class="section-loading">Загрузка…</div>';
  try {
    if (state.route === 'equipment') await renderEquipment(content);
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
// Раздел: Оборудование
// ============================================================

async function ensureEquipmentTypes() {
  if (!state.equipmentTypes.length) {
    state.equipmentTypes = await api('/equipment-types');
  }
}

async function renderEquipment(content) {
  const [items] = await Promise.all([api('/equipment'), ensureEquipmentTypes()]);
  const typeName = (id) => (state.equipmentTypes.find((t) => t.id === id) || {}).name || '—';
  const canEdit = state.me.role !== 'technician';

  content.innerHTML = `
    <div class="page-header">
      <div><h1>Оборудование</h1><div class="page-subtitle">Цифровой паспорт и лента ремонтов по каждой единице техники</div></div>
      ${canEdit ? '<button class="btn btn-primary" id="add-equipment-btn">+ Добавить оборудование</button>' : ''}
    </div>
    <div class="card" style="padding:0">
      <table>
        <thead><tr><th>Оборудование</th><th>Тип</th><th>Серийный №</th><th>Статус</th><th>Расположение</th></tr></thead>
        <tbody id="equipment-rows"></tbody>
      </table>
    </div>`;

  const rows = document.getElementById('equipment-rows');
  rows.innerHTML = items.length ? items.map((eq) => `
    <tr class="clickable" data-id="${eq.id}">
      <td><strong>${esc(eq.name)}</strong><div class="text-soft">${esc(eq.manufacturer || '')} ${esc(eq.model || '')}</div></td>
      <td>${esc(typeName(eq.equipment_type_id))}</td>
      <td class="mono">${esc(eq.serial_number)}</td>
      <td>${badge(EQUIPMENT_STATUS, eq.status)}</td>
      <td>${esc(eq.location || '—')}</td>
    </tr>`).join('') : '<tr class="empty-row"><td colspan="5">Оборудование ещё не добавлено</td></tr>';

  rows.querySelectorAll('tr[data-id]').forEach((tr) => {
    tr.addEventListener('click', () => openEquipmentPassport(tr.dataset.id));
  });

  if (canEdit) {
    document.getElementById('add-equipment-btn').addEventListener('click', openCreateEquipmentModal);
  }
}

function openCreateEquipmentModal() {
  const typeOptions = state.equipmentTypes.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join('');
  const backdrop = openModal('Новое оборудование', `
    <form id="equipment-form">
      <div class="field"><label>Тип оборудования</label>
        <select id="f-type" required>${typeOptions}<option value="__new">+ Новый тип…</option></select>
      </div>
      <div class="field hidden" id="f-newtype-wrap"><label>Название нового типа</label><input id="f-newtype"></div>
      <div class="field"><label>Название</label><input id="f-name" required placeholder="Поломоечная машина"></div>
      <div class="field-row">
        <div class="field"><label>Производитель</label><input id="f-manufacturer"></div>
        <div class="field"><label>Модель</label><input id="f-model"></div>
      </div>
      <div class="field"><label>Серийный номер</label><input id="f-serial" required></div>
      <div class="field"><label>Расположение</label><input id="f-location" placeholder="Объект, участок"></div>
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
      const name = backdrop.querySelector('#f-name').value.trim();
      const serial = backdrop.querySelector('#f-serial').value.trim();
      if (!name || !serial) return toast('Заполните название и серийный номер', 'error');
      await api('/equipment', {
        method: 'POST',
        body: JSON.stringify({
          equipment_type_id: Number(typeId),
          name,
          manufacturer: backdrop.querySelector('#f-manufacturer').value.trim() || null,
          model: backdrop.querySelector('#f-model').value.trim() || null,
          serial_number: serial,
          location: backdrop.querySelector('#f-location').value.trim() || null,
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
  const passport = await api(`/equipment/${id}/passport`);
  const historyHtml = passport.history.length ? passport.history.map((h) => `
    <div style="display:flex;gap:12px;padding:10px 0;border-bottom:1px solid var(--line)">
      <div style="width:8px;height:8px;border-radius:50%;background:var(--accent);margin-top:6px;flex-shrink:0"></div>
      <div>
        <div class="text-soft" style="font-size:12px;font-weight:600">${fmtDate(h.closed_at)} · ${esc(h.technician_name)}</div>
        <div style="margin-top:2px">${esc(h.description)}</div>
        ${h.parts_used.length ? `<div class="mono text-soft" style="font-size:12px;margin-top:2px">${h.parts_used.map((p) => `${esc(p.part_name)} ×${p.quantity}`).join(', ')}</div>` : ''}
      </div>
    </div>`).join('') : '<div class="text-soft" style="padding:12px 0">Ремонтов ещё не было</div>';

  openModal(passport.name, `
    <div style="display:flex;gap:16px;align-items:flex-start;margin-bottom:16px">
      <img src="/api/equipment/${id}/qr" alt="QR" style="width:96px;height:96px;border:1px solid var(--line);border-radius:8px;padding:6px;background:#fff">
      <div>
        <div>${esc(passport.manufacturer || '')} ${esc(passport.model || '')}</div>
        <div class="mono text-soft" style="margin-top:4px">${esc(passport.serial_number)}</div>
        <div style="margin-top:8px">${badge(EQUIPMENT_STATUS, passport.status)}</div>
      </div>
    </div>
    <h2 style="font-size:14px;margin-bottom:6px">Лента истории</h2>
    <div>${historyHtml}</div>
  `, `<button class="btn btn-secondary" id="modal-close">Закрыть</button>`);

  document.getElementById('modal-close').addEventListener('click', closeModal);
}

// ============================================================
// Раздел: Наряды
// ============================================================

async function renderTasks(content) {
  const isStaff = state.me.role !== 'technician';
  const [tasks, equipmentList, technicians] = await Promise.all([
    api('/tasks'),
    isStaff ? api('/equipment') : Promise.resolve([]),
    isStaff ? api('/users').then((u) => u.filter((x) => x.role === 'technician')) : Promise.resolve([]),
  ]);
  const eqName = (id) => { const e = equipmentList.find((x) => x.id === id); return e ? e.name : id; };

  content.innerHTML = `
    <div class="page-header">
      <div><h1>${isStaff ? 'Наряды' : 'Мои наряды'}</h1><div class="page-subtitle">${isStaff ? 'Внутренние заявки на обслуживание оборудования' : 'Назначенные вам заявки'}</div></div>
      ${isStaff ? '<button class="btn btn-primary" id="add-task-btn">+ Новый наряд</button>' : ''}
    </div>
    <div class="card" style="padding:0">
      <table>
        <thead><tr><th>Заявка</th><th>Оборудование</th><th>Приоритет</th><th>Статус</th><th>Срок</th>${isStaff ? '<th>Техник</th>' : ''}</tr></thead>
        <tbody id="task-rows"></tbody>
      </table>
    </div>`;

  const rows = document.getElementById('task-rows');
  rows.innerHTML = tasks.length ? tasks.map((t) => `
    <tr>
      <td><strong>${esc(t.title)}</strong>${t.description ? `<div class="text-soft">${esc(t.description)}</div>` : ''}</td>
      <td>${esc(isStaff ? eqName(t.equipment_id) : t.equipment_id)}</td>
      <td>${badge(TASK_PRIORITY, t.priority)}</td>
      <td>${badge(TASK_STATUS, t.status)}</td>
      <td>${fmtDate(t.due_at)}</td>
      ${isStaff ? `<td>${t.assigned_to ? '<span class="badge badge-good"><span class="badge-dot"></span>Назначен</span>' : `<select class="assign-select" data-task="${t.id}"><option value="">— назначить —</option>${technicians.map((tech) => `<option value="${tech.id}">${esc(tech.full_name)}</option>`).join('')}</select>`}</td>` : ''}
    </tr>`).join('') : `<tr class="empty-row"><td colspan="${isStaff ? 6 : 5}">Нарядов пока нет</td></tr>`;

  rows.querySelectorAll('.assign-select').forEach((sel) => {
    sel.addEventListener('change', async () => {
      if (!sel.value) return;
      try {
        await api(`/tasks/${sel.dataset.task}/assign?technician_id=${sel.value}`, { method: 'PATCH' });
        toast('Техник назначен');
        router();
      } catch (e) { toast(e.message, 'error'); }
    });
  });

  if (isStaff) {
    document.getElementById('add-task-btn').addEventListener('click', () => openCreateTaskModal(equipmentList, technicians));
  }
}

function openCreateTaskModal(equipmentList, technicians) {
  const backdrop = openModal('Новый наряд', `
    <div class="field"><label>Оборудование</label>
      <select id="f-eq">${equipmentList.map((e) => `<option value="${e.id}">${esc(e.name)} · ${esc(e.serial_number)}</option>`).join('')}</select>
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

  backdrop.querySelector('#modal-cancel').addEventListener('click', closeModal);
  backdrop.querySelector('#modal-save').addEventListener('click', async () => {
    const title = backdrop.querySelector('#f-title').value.trim();
    if (!title) return toast('Укажите заголовок', 'error');
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
  const [tickets, technicians] = await Promise.all([
    api('/tickets'),
    api('/users').then((u) => u.filter((x) => x.role === 'technician')),
  ]);

  content.innerHTML = `
    <div class="page-header">
      <div><h1>Заявки от гостей</h1><div class="page-subtitle">Обращения, оставленные через QR на оборудовании, без входа в систему</div></div>
    </div>
    <div class="card" style="padding:0">
      <table>
        <thead><tr><th>Что сообщили</th><th>Серьёзность</th><th>От кого</th><th>Статус</th><th>Когда</th><th>Назначить</th></tr></thead>
        <tbody id="ticket-rows"></tbody>
      </table>
    </div>`;

  const rows = document.getElementById('ticket-rows');
  rows.innerHTML = tickets.length ? tickets.map((t) => `
    <tr>
      <td>${t.comment ? esc(t.comment) : '<span class="text-soft">без комментария</span>'}${t.symptom_tags.length ? `<div class="text-soft" style="font-size:12px">${t.symptom_tags.map(esc).join(', ')}</div>` : ''}</td>
      <td>${esc(TICKET_SEVERITY[t.severity] || t.severity)}</td>
      <td class="text-soft">${esc(t.equipment_id).slice(0, 8)}…</td>
      <td>${badge(TICKET_STATUS, t.status)}</td>
      <td>${fmtDate(t.created_at)}</td>
      <td>${t.status === 'resolved' ? '—' : `<select class="ticket-assign" data-id="${t.id}"><option value="">— выбрать —</option>${technicians.map((tech) => `<option value="${tech.id}" ${t.assigned_technician_id === tech.id ? 'selected' : ''}>${esc(tech.full_name)}</option>`).join('')}</select>`}</td>
    </tr>`).join('') : '<tr class="empty-row"><td colspan="6">Гостевых заявок пока нет</td></tr>';

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
        <thead><tr><th>Имя</th><th>Email</th><th>Роль</th><th>Телефон</th></tr></thead>
        <tbody id="user-rows"></tbody>
      </table>
    </div>`;

  document.getElementById('user-rows').innerHTML = users.length ? users.map((u) => `
    <tr>
      <td><strong>${esc(u.full_name)}</strong></td>
      <td>${esc(u.email)}</td>
      <td>${esc(ROLE_LABEL[u.role] || u.role)}</td>
      <td>${esc(u.phone || '—')}</td>
    </tr>`).join('') : '<tr class="empty-row"><td colspan="4">Пользователей пока нет</td></tr>';

  document.getElementById('add-user-btn').addEventListener('click', openCreateUserModal);
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
