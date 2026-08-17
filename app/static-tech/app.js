// ============================================================
// Fixit — приложение техника (PWA, офлайн-first)
// ============================================================

const ICONS = {
  tasks: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 3v2h6V3"/><path d="M9 11h6M9 15h6"/></svg>',
  scan: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7V5a1 1 0 0 1 1-1h2M20 7V5a1 1 0 0 1-1-1h-2M4 17v2a1 1 0 0 0 1 1h2M20 17v2a1 1 0 0 1-1 1h-2"/><path d="M4 12h16"/></svg>',
  warehouse: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-6 9 6v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/><path d="M9 21V12h6v9"/></svg>',
  back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="22" height="22"><path d="M15 18l-6-6 6-6"/></svg>',
  camera: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" width="26" height="26"><path d="M4 8a2 2 0 0 1 2-2h1l1.5-2h7L17 6h1a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/><circle cx="12" cy="13" r="3.5"/></svg>',
};

const state = {
  token: null,
  me: null,
  online: navigator.onLine,
  syncing: false,
  tab: 'tasks',
  drill: null, // { screen: 'passport' | 'act', equipmentId, taskId }
};

const EQUIPMENT_STATUS = {
  working: { label: 'Работает', cls: 'good' },
  needs_repair: { label: 'Требует ремонта', cls: 'warn' },
  mothballed: { label: 'На консервации', cls: 'idle' },
  decommissioned: { label: 'Списано', cls: 'idle' },
};
const TASK_PRIORITY = { urgent: { label: 'Срочно', cls: 'warn' }, planned: { label: 'Плановая', cls: 'idle' } };
const TASK_STATUS = {
  new: { label: 'Новая', cls: 'idle' }, assigned: { label: 'Назначена', cls: 'amber' },
  in_progress: { label: 'В работе', cls: 'amber' }, closed: { label: 'Закрыта', cls: 'good' }, cancelled: { label: 'Отменена', cls: 'idle' },
};
const FAULT_TYPES = ['Электрика', 'Насос', 'Механика', 'Аккумулятор', 'Другое'];

function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function createUuid() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
function badge(map, key) {
  const info = map[key] || { label: key, cls: 'idle' };
  return `<span class="badge badge-${info.cls}"><span class="badge-dot"></span>${esc(info.label)}</span>`;
}
function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' }) + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}
function toast(message, type = 'success') {
  const root = document.getElementById('toast-root');
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ---------- API-клиент (только когда есть сеть; офлайн-данные идут из TechDB) ----------

async function apiFetch(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (state.token) headers['Authorization'] = `Bearer ${state.token}`;
  if (options.body) headers['Content-Type'] = 'application/json';
  const res = await fetch('/api' + path, { ...options, headers });
  if (res.status === 401 && path !== '/auth/login') {
    await logout();
    throw new Error('Сессия устарела — войдите заново');
  }
  if (!res.ok) {
    let detail = res.statusText;
    try { const body = await res.json(); detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail); } catch (_) {}
    throw new Error(detail || 'Ошибка запроса');
  }
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

async function getDeviceId() {
  let id = await TechDB.kvGet('deviceId');
  if (!id) { id = createUuid(); await TechDB.kvSet('deviceId', id); }
  return id;
}

// ---------- Соединение и фоновая синхронизация ----------

async function pendingCount() {
  const items = await TechDB.getAll('pendingRepairs');
  return items.length;
}

async function renderConnStrip() {
  const strip = document.getElementById('conn-strip');
  const dot = document.getElementById('conn-dot');
  const label = document.getElementById('conn-label');
  const pending = await pendingCount();
  let color, text;
  if (state.syncing) { color = 'var(--amber)'; text = 'Синхронизация…'; strip.classList.add('syncing'); }
  else { strip.classList.remove('syncing');
    if (state.online) { color = 'var(--good)'; text = pending ? `Онлайн · отправляем ${pending}` : 'Онлайн · синхронизировано'; }
    else { color = 'var(--idle)'; text = `Офлайн${pending ? ` · ${pending} изм. ожидают отправки` : ''}`; }
  }
  dot.style.background = color;
  label.textContent = text;
}

async function syncPendingRepairs() {
  const resultsById = new Map();
  if (!navigator.onLine) return resultsById;
  const pending = await TechDB.getAll('pendingRepairs');
  if (!pending.length) return resultsById;
  state.syncing = true; renderConnStrip();
  try {
    const device_id = await getDeviceId();
    const payload = pending.map(({ _equipmentName, ...rest }) => rest);
    const res = await apiFetch('/v1/sync/repairs', { method: 'POST', body: JSON.stringify({ device_id, repairs: payload }) });
    for (const r of res.results) {
      resultsById.set(r.local_uuid, r);
      if (r.resolved_as === 'failed') {
        toast(`Не удалось отправить ремонт: ${r.error}`, 'error');
      } else {
        await TechDB.delete('pendingRepairs', r.local_uuid);
        if (r.resolved_as === 'applied_with_conflict') {
          toast('Ремонт отправлен, но оборудование менялось без вас — диспетчер проверит вручную', 'info');
        }
      }
    }
  } catch (e) {
    toast('Не удалось синхронизировать: ' + e.message, 'error');
  }
  state.syncing = false; renderConnStrip();
  return resultsById;
}

async function registerBackgroundSync() {
  try {
    const reg = await navigator.serviceWorker.ready;
    if ('sync' in reg) await reg.sync.register('sync-repairs');
  } catch (_) { /* Background Sync не поддерживается — синк всё равно случится по событию online */ }
}

window.addEventListener('online', () => { state.online = true; renderConnStrip(); syncPendingRepairs(); if (state.tab === 'tasks' && !state.drill) loadTasks(); });
window.addEventListener('offline', () => { state.online = false; renderConnStrip(); });

// ---------- Навигация ----------

function renderNav() {
  const nav = document.getElementById('bottom-nav');
  if (state.drill) { nav.classList.add('hidden'); return; }
  nav.classList.remove('hidden');
  const items = [['tasks', 'Заявки', ICONS.tasks], ['scan', 'Скан', ICONS.scan], ['warehouse', 'Склад', ICONS.warehouse]];
  nav.innerHTML = items.map(([key, label, icon]) => `
    <button class="nav-btn ${state.tab === key ? 'active' : ''}" data-tab="${key}">${icon}${esc(label)}</button>`).join('');
  nav.querySelectorAll('.nav-btn').forEach((btn) => btn.addEventListener('click', () => { state.tab = btn.dataset.tab; state.drill = null; render(); }));
}

function header(title, onBack) {
  return `<div class="screen-header">
    ${onBack ? `<button class="back-btn" id="back-btn">${ICONS.back}</button>` : ''}
    <h1>${esc(title)}</h1>
  </div>`;
}

async function render() {
  renderNav();
  renderConnStrip();
  const screen = document.getElementById('screen');
  if (state.drill?.screen === 'passport') return renderPassportScreen(screen);
  if (state.drill?.screen === 'act') return renderActScreen(screen);
  if (state.tab === 'tasks') return renderTasksScreen(screen);
  if (state.tab === 'scan') return renderScanScreen(screen);
  if (state.tab === 'warehouse') return renderWarehouseScreen(screen);
}

// ============================================================
// Экран: Заявки
// ============================================================

async function loadTasks() {
  if (navigator.onLine) {
    try {
      const tasks = await apiFetch('/tasks');
      await TechDB.clear('tasks');
      await TechDB.putAll('tasks', tasks);
      // Опережающая загрузка паспортов оборудования по назначенным заявкам —
      // чтобы карточку можно было открыть, даже если связь пропадёт уже в пути на объект.
      for (const t of tasks) {
        try {
          const passport = await apiFetch(`/equipment/${t.equipment_id}/passport`);
          await TechDB.put('equipment', passport);
        } catch (_) { /* не критично — просто не закэшируется на этот раз */ }
      }
      return tasks;
    } catch (e) { /* сеть моргнула — падаем на кэш ниже */ }
  }
  return TechDB.getAll('tasks');
}

async function renderTasksScreen(screen) {
  screen.innerHTML = header('Мои заявки') + '<div class="section-padding"><div class="section-loading">Загрузка…</div></div>';
  const tasks = await loadTasks();
  const equipmentCache = {};
  for (const t of tasks) equipmentCache[t.equipment_id] = await TechDB.get('equipment', t.equipment_id);
  const orderedTasks = [...tasks].sort((a, b) => {
    const aClosed = a.status === 'closed' || a.status === 'cancelled';
    const bClosed = b.status === 'closed' || b.status === 'cancelled';
    if (aClosed !== bClosed) return Number(aClosed) - Number(bClosed);
    return String(b.created_at || '').localeCompare(String(a.created_at || ''));
  });

  const body = orderedTasks.length ? orderedTasks.map((t) => {
    const eq = equipmentCache[t.equipment_id];
    const isClosed = t.status === 'closed' || t.status === 'cancelled';
    return `<button class="task-card ${isClosed ? 'task-card-closed' : 'task-card-active'}" data-task="${t.id}" data-eq="${t.equipment_id}">
      <div class="task-card-top">${badge(TASK_PRIORITY, t.priority)}<span class="text-soft" style="font-size:11.5px">${fmtDate(t.due_at)}</span></div>
      <div class="task-title">${esc(t.title)}</div>
      <div class="text-soft" style="font-size:12.5px">${eq ? esc(eq.name) + ' · ' + esc(eq.serial_number) : 'оборудование не в кэше'}</div>
      ${eq?.location ? `<div class="text-soft task-location">Расположение: ${esc(eq.location)}</div>` : ''}
      ${badge(TASK_STATUS, t.status)}
    </button>`;
  }).join('') : '<div class="empty-state">Заявок нет</div>';

  screen.innerHTML = header('Мои заявки') + `<div class="section-padding">${body}</div>`;
  screen.querySelectorAll('.task-card').forEach((card) => {
    card.addEventListener('click', () => openPassport(card.dataset.eq, card.dataset.task));
  });
}

// ============================================================
// Экран: Паспорт оборудования
// ============================================================

async function openPassport(equipmentId, taskId) {
  let eq = await TechDB.get('equipment', equipmentId);
  if (!eq && navigator.onLine) {
    try { eq = await apiFetch(`/equipment/${equipmentId}/passport`); await TechDB.put('equipment', eq); } catch (_) {}
  }
  if (!eq) return toast('Нет сохранённых данных по этому оборудованию — нужна связь', 'error');
  state.drill = { screen: 'passport', equipmentId, taskId };
  render();
}

async function renderPassportScreen(screen) {
  const eq = await TechDB.get('equipment', state.drill.equipmentId);
  const history = eq.history || [];
  const historyHtml = history.length ? history.map((h) => `
    <div class="timeline-item">
      <div class="timeline-dot"></div>
      <div>
        <div class="text-soft" style="font-size:11.5px;font-weight:600">${fmtDate(h.closed_at)} · ${esc(h.technician_name)}</div>
        <div style="margin-top:2px;font-size:13.5px">${esc(h.description)}</div>
        ${h.parts_used.length ? `<div class="mono text-soft" style="font-size:11.5px;margin-top:2px">${h.parts_used.map((p) => `${esc(p.part_name)} ×${p.quantity}`).join(', ')}</div>` : ''}
      </div>
    </div>`).join('') : '<div class="empty-state">Ремонтов ещё не было</div>';

  screen.innerHTML = header('Паспорт оборудования', true) + `
    <div class="eq-header">
      <div>
        <div class="display" style="font-size:16px">${esc(eq.name)}</div>
        <div class="eq-meta text-soft">${esc(eq.manufacturer || '')} ${esc(eq.model || '')}</div>
        <div class="eq-serial mono">${esc(eq.serial_number)}</div>
        <div style="margin-top:8px">${badge(EQUIPMENT_STATUS, eq.status)}</div>
      </div>
    </div>
    <div class="section-padding">
      <h2 style="font-size:13.5px;margin-bottom:8px">Лента истории</h2>
      ${historyHtml}
    </div>
    <div class="section-padding" style="padding-top:0">
      <button class="btn btn-primary btn-block" id="open-act-btn">Открыть акт ремонта</button>
    </div>`;

  screen.querySelector('#back-btn').addEventListener('click', () => { state.drill = null; render(); });
  screen.querySelector('#open-act-btn').addEventListener('click', () => {
    state.drill = { screen: 'act', equipmentId: eq.id, taskId: state.drill.taskId };
    render();
  });
}

// ============================================================
// Экран: Акт ремонта
// ============================================================

async function renderActScreen(screen) {
  const eq = await TechDB.get('equipment', state.drill.equipmentId);
  const stock = await TechDB.getAll('stock');
  let selectedFault = FAULT_TYPES[0];
  const usedQty = {};
  let savedPayload = null;

  function partsHtml() {
    return stock.length ? stock.map((p) => `
      <div class="part-row">
        <div><div class="part-name">${esc(p.name)}</div><div class="part-meta mono">${esc(p.article)} · остаток ${p.quantity}</div></div>
        <div class="qty-control">
          <button class="qty-btn" data-minus="${p.part_id}">−</button>
          <span class="mono" style="width:16px;text-align:center">${usedQty[p.part_id] || 0}</span>
          <button class="qty-btn" data-plus="${p.part_id}" ${(usedQty[p.part_id] || 0) >= p.quantity ? 'disabled' : ''}>+</button>
        </div>
      </div>`).join('') : '<div class="text-soft" style="font-size:13px">На вашем складе пусто</div>';
  }

  function draw() {
    screen.innerHTML = header('Акт ремонта', true) + `
      <div class="section-padding">
        <div class="text-soft" style="font-size:12.5px;margin-bottom:14px">${esc(eq.name)} · <span class="mono">${esc(eq.serial_number)}</span></div>

        <div class="field"><label>Тип поломки</label>
          <div class="chip-group" id="fault-chips">
            ${FAULT_TYPES.map((f) => `<button class="chip ${f === selectedFault ? 'active' : ''}" data-fault="${esc(f)}">${esc(f)}</button>`).join('')}
          </div>
        </div>

        <div class="field"><label>Описание работ</label><textarea id="f-desc" placeholder="Что сделано…"></textarea></div>

        <div class="field"><label>Использованные запчасти (мой склад)</label><div id="parts-list">${partsHtml()}</div></div>

        <div class="notice"><span>⟳</span><span>Акт сохраняется на устройстве и будет отправлен на сервер автоматически, как только появится связь.</span></div>

        <button class="btn btn-good btn-block" id="close-btn">Закрыть заявку</button>
      </div>`;

    screen.querySelector('#back-btn').addEventListener('click', () => { state.drill = { screen: 'passport', equipmentId: eq.id, taskId: state.drill.taskId }; render(); });
    screen.querySelectorAll('[data-fault]').forEach((btn) => btn.addEventListener('click', () => { selectedFault = btn.dataset.fault; draw(); }));
    screen.querySelectorAll('[data-plus]').forEach((btn) => btn.addEventListener('click', () => {
      const id = btn.dataset.plus; const item = stock.find((s) => s.part_id === id);
      usedQty[id] = Math.min(item.quantity, (usedQty[id] || 0) + 1); draw();
    }));
    screen.querySelectorAll('[data-minus]').forEach((btn) => btn.addEventListener('click', () => {
      const id = btn.dataset.minus; usedQty[id] = Math.max(0, (usedQty[id] || 0) - 1); draw();
    }));
    screen.querySelector('#close-btn').addEventListener('click', submit);
  }

  async function submit() {
    const closeButton = screen.querySelector('#close-btn');
    if (savedPayload) {
      closeButton.disabled = true;
      closeButton.textContent = 'Отправляем акт…';
      const retryResults = await syncPendingRepairs();
      const retryResult = retryResults.get(savedPayload.local_uuid);
      if (retryResult && retryResult.resolved_as !== 'failed') {
        toast('Акт принят, наряд закрыт');
        state.drill = null; state.tab = 'tasks'; render();
        return;
      }
      closeButton.disabled = false;
      closeButton.textContent = 'Повторить отправку';
      return;
    }

    const description = screen.querySelector('#f-desc').value.trim();
    if (!description) return toast('Опишите, что сделано', 'error');
    const parts_used = Object.entries(usedQty).filter(([, q]) => q > 0).map(([part_id, quantity]) => ({ part_id, quantity }));

    const payload = {
      local_uuid: createUuid(),
      equipment_id: eq.id,
      task_id: state.drill.taskId || null,
      ticket_id: null,
      fault_type: selectedFault,
      description,
      started_at: null,
      closed_at: new Date().toISOString(),
      device_updated_at: new Date().toISOString(),
      base_equipment_version: eq.version,
      parts_used,
    };
    await TechDB.put('pendingRepairs', payload);
    savedPayload = payload;

    // Оптимистично уменьшаем локальный кэш остатков — для немедленной обратной связи в UI,
    // не дожидаясь синка.
    for (const p of parts_used) {
      const item = await TechDB.get('stock', p.part_id);
      if (item) { item.quantity = Math.max(0, item.quantity - p.quantity); await TechDB.put('stock', item); }
    }

    if (!navigator.onLine) {
      toast('Акт сохранён на устройстве и будет отправлен при появлении связи');
      state.drill = null; state.tab = 'tasks';
      render();
      registerBackgroundSync();
      return;
    }

    closeButton.disabled = true;
    closeButton.textContent = 'Закрываем наряд…';
    const results = await syncPendingRepairs();
    const result = results.get(payload.local_uuid);
    if (result && result.resolved_as !== 'failed') {
      toast('Акт принят, наряд закрыт');
      state.drill = null; state.tab = 'tasks';
      render();
      return;
    }
    closeButton.disabled = false;
    closeButton.textContent = 'Повторить отправку';
  }

  draw();
}

// ============================================================
// Экран: Скан QR
// ============================================================

let scanStream = null;

async function renderScanScreen(screen) {
  screen.innerHTML = `
    <div class="scan-wrap">
      <video id="scan-video" autoplay muted playsinline></video>
      <div class="scan-frame">
        <div class="scan-corner" style="top:0;left:0;border-top:3px solid var(--accent);border-left:3px solid var(--accent)"></div>
        <div class="scan-corner" style="top:0;right:0;border-top:3px solid var(--accent);border-right:3px solid var(--accent)"></div>
        <div class="scan-corner" style="bottom:0;left:0;border-bottom:3px solid var(--accent);border-left:3px solid var(--accent)"></div>
        <div class="scan-corner" style="bottom:0;right:0;border-bottom:3px solid var(--accent);border-right:3px solid var(--accent)"></div>
      </div>
      <p class="text-soft" style="padding:16px;text-align:center;font-size:13px" id="scan-hint">Наведите камеру на QR-код на корпусе оборудования</p>
      <button class="btn btn-secondary" id="manual-entry-btn">Ввести серийный номер вручную</button>
    </div>`;

  screen.querySelector('#manual-entry-btn').addEventListener('click', () => {
    stopScan();
    const serial = prompt('Серийный номер оборудования:');
    if (serial) findEquipmentBySerial(serial.trim());
  });

  if (!('BarcodeDetector' in window)) {
    document.getElementById('scan-hint').textContent = 'Этот браузер не поддерживает сканирование камерой — используйте ручной ввод ниже.';
    return;
  }

  try {
    scanStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
    const video = document.getElementById('scan-video');
    video.srcObject = scanStream;
    const detector = new BarcodeDetector({ formats: ['qr_code'] });
    const loop = async () => {
      if (!scanStream || state.tab !== 'scan' || state.drill) return;
      try {
        const codes = await detector.detect(video);
        if (codes.length) { stopScan(); await handleScanResult(codes[0].rawValue); return; }
      } catch (_) {}
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  } catch (e) {
    document.getElementById('scan-hint').textContent = 'Нет доступа к камере — используйте ручной ввод ниже.';
  }
}

function stopScan() {
  if (scanStream) { scanStream.getTracks().forEach((t) => t.stop()); scanStream = null; }
}

async function handleScanResult(rawValue) {
  // QR хранит ссылку вида .../e/{token}; берём последний сегмент пути как токен.
  let token = rawValue;
  try { const u = new URL(rawValue); const parts = u.pathname.split('/').filter(Boolean); token = parts[parts.length - 1] || rawValue; } catch (_) {}
  await resolveByQrToken(token);
}

async function resolveByQrToken(token) {
  if (!navigator.onLine) return toast('Для первого скана этого оборудования нужна связь', 'error');
  try {
    const eq = await apiFetch(`/equipment/by-qr/${token}`);
    await TechDB.put('equipment', eq);
    state.drill = { screen: 'passport', equipmentId: eq.id, taskId: null };
    render();
  } catch (e) { toast(e.message, 'error'); }
}

async function findEquipmentBySerial(serial) {
  const all = await TechDB.getAll('equipment');
  const found = all.find((e) => e.serial_number.toLowerCase() === serial.toLowerCase());
  if (found) { state.drill = { screen: 'passport', equipmentId: found.id, taskId: null }; return render(); }
  if (!navigator.onLine) return toast('Оборудование не в кэше, а сети нет', 'error');
  try {
    const list = await apiFetch('/equipment');
    const match = list.find((e) => e.serial_number.toLowerCase() === serial.toLowerCase());
    if (!match) return toast('Оборудование с таким серийным номером не найдено', 'error');
    const passport = await apiFetch(`/equipment/${match.id}/passport`);
    await TechDB.put('equipment', passport);
    state.drill = { screen: 'passport', equipmentId: passport.id, taskId: null };
    render();
  } catch (e) { toast(e.message, 'error'); }
}

// ============================================================
// Экран: Мой склад
// ============================================================

async function renderWarehouseScreen(screen) {
  screen.innerHTML = header('Мой склад') + '<div class="section-padding"><div class="section-loading">Загрузка…</div></div>';
  let stock;
  if (navigator.onLine) {
    try { stock = await apiFetch('/warehouses/mine/stock'); await TechDB.clear('stock'); await TechDB.putAll('stock', stock); }
    catch (_) { stock = await TechDB.getAll('stock'); }
  } else {
    stock = await TechDB.getAll('stock');
  }

  const rows = stock.length ? stock.map((p) => `
    <div class="part-row">
      <div><div class="part-name">${esc(p.name)}</div><div class="part-meta mono">${esc(p.article)}</div></div>
      <div class="mono" style="font-weight:700;${p.is_critical ? 'color:var(--warn)' : ''}">${p.quantity}</div>
    </div>`).join('') : '<div class="empty-state">На складе пусто</div>';

  screen.innerHTML = header('Мой склад') + `<div class="section-padding">${rows}</div>`;
}

// ============================================================
// Авторизация и запуск
// ============================================================

function showLogin() {
  document.getElementById('app').classList.add('hidden');
  document.getElementById('login-screen').classList.remove('hidden');
}

async function logout() {
  await TechDB.kvDelete('token');
  await TechDB.kvDelete('me');
  state.token = null; state.me = null;
  showLogin();
}

async function boot() {
  const token = await TechDB.kvGet('token');
  if (!token) return showLogin();
  state.token = token;
  state.me = await TechDB.kvGet('me');
  if (!state.me && navigator.onLine) {
    try { state.me = await apiFetch('/users/me'); await TechDB.kvSet('me', state.me); }
    catch (_) { return logout(); }
  }
  if (!state.me) return showLogin(); // офлайн и профиль ещё ни разу не кэшировался

  document.getElementById('login-screen').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  render();
  if (navigator.onLine) syncPendingRepairs();
}

document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById('login-error');
  errorEl.classList.add('hidden');
  const email = document.getElementById('login-email').value.trim();
  const password = document.getElementById('login-password').value;
  try {
    const res = await apiFetch('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
    state.token = res.access_token;
    await TechDB.kvSet('token', state.token);
    const me = await apiFetch('/users/me');
    if (me.role !== 'technician') throw new Error('Это приложение только для техников — для остальных ролей используйте веб-панель');
    await TechDB.kvSet('me', me);
    await boot();
  } catch (err) {
    errorEl.textContent = err.message || 'Не удалось войти';
    errorEl.classList.remove('hidden');
  }
});

document.getElementById('logout-btn').addEventListener('click', () => {
  if (confirm('Выйти из приложения?')) logout();
});

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/tech/sw.js', { scope: '/tech/' }).catch(() => {});
}

boot();
