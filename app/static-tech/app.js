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

async function uploadAttachment(repairId, attachment) {
  const headers = state.token ? { Authorization: `Bearer ${state.token}` } : {};
  const data = await fetch(attachment.data_url).then((res) => res.blob());
  const form = new FormData();
  form.append('kind', attachment.kind);
  form.append('file', data, attachment.file_name || `${attachment.kind}.jpg`);
  const res = await fetch(`/api/repairs/${repairId}/attachments`, { method: 'POST', headers, body: form });
  if (!res.ok) {
    let message = 'Не удалось загрузить вложение';
    try { message = (await res.json()).detail || message; } catch (_) {}
    throw new Error(message);
  }
  return res.json();
}

async function syncPendingAttachments(resultsById = new Map()) {
  if (!navigator.onLine) return;
  const attachments = await TechDB.getAll('pendingAttachments');
  for (const attachment of attachments) {
    const result = resultsById.get(attachment.local_uuid);
    if (!attachment.repair_id && result?.server_id) {
      attachment.repair_id = result.server_id;
      await TechDB.put('pendingAttachments', attachment);
    }
    if (!attachment.repair_id) continue;
    try {
      await uploadAttachment(attachment.repair_id, attachment);
      await TechDB.delete('pendingAttachments', attachment.id);
    } catch (e) {
      // Ремонт уже закрыт, поэтому фотография останется в локальной очереди и
      // будет повторена при следующем выходе приложения в онлайн.
      toast(`Фото акта пока не отправлено: ${e.message}`, 'info');
      break;
    }
  }
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
    await syncPendingAttachments(resultsById);
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
      ${t.description ? `<div class="task-description">Проблема: ${esc(t.description)}</div>` : ''}
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
  const media = { before: [], after: [], signature: null };
  const formValues = { description: '', labor: '0', signer: '', confirmed: false };

  function mediaSummary(kind) {
    const item = kind === 'signature' ? (media.signature ? [media.signature] : []) : media[kind];
    return item.length ? `<div class="text-soft" style="font-size:12px;margin-top:6px">Добавлено: ${item.length}</div>` : '';
  }

  async function compressPhoto(file) {
    const source = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(file); });
    const image = await new Promise((resolve, reject) => { const img = new Image(); img.onload = () => resolve(img); img.onerror = reject; img.src = source; });
    const maxSide = 1600;
    const scale = Math.min(1, maxSide / Math.max(image.width, image.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(image.width * scale)); canvas.height = Math.max(1, Math.round(image.height * scale));
    canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.78);
  }

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
    if (screen.querySelector('#f-desc')) {
      formValues.description = screen.querySelector('#f-desc').value;
      formValues.labor = screen.querySelector('#f-labor').value;
      formValues.signer = screen.querySelector('#f-signer').value;
      formValues.confirmed = screen.querySelector('#f-confirmed').checked;
    }
    screen.innerHTML = header('Акт ремонта', true) + `
      <div class="section-padding">
        <div class="text-soft" style="font-size:12.5px;margin-bottom:14px">${esc(eq.name)} · <span class="mono">${esc(eq.serial_number)}</span></div>

        <div class="field"><label>Тип поломки</label>
          <div class="chip-group" id="fault-chips">
            ${FAULT_TYPES.map((f) => `<button class="chip ${f === selectedFault ? 'active' : ''}" data-fault="${esc(f)}">${esc(f)}</button>`).join('')}
          </div>
        </div>

        <div class="field"><label>Описание работ</label><textarea id="f-desc" placeholder="Что сделано…">${esc(formValues.description)}</textarea></div>

        <div class="field"><label>Время работы, мин.</label><input id="f-labor" type="number" min="0" step="5" value="${esc(formValues.labor)}" inputmode="numeric"></div>

        <div class="field"><label>Использованные запчасти (мой склад)</label><div id="parts-list">${partsHtml()}</div></div>

        <div class="field"><label>Фото до ремонта</label><input id="f-before" type="file" accept="image/*" capture="environment" multiple>${mediaSummary('before')}</div>
        <div class="field"><label>Фото после ремонта</label><input id="f-after" type="file" accept="image/*" capture="environment" multiple>${mediaSummary('after')}</div>
        <div class="field"><label>Работы принял клиент</label><input id="f-signer" maxlength="255" placeholder="ФИО клиента" value="${esc(formValues.signer)}"><label style="display:flex;align-items:center;gap:8px;margin-top:8px;font-size:12px;text-transform:none;letter-spacing:0"><input id="f-confirmed" type="checkbox" style="width:auto" ${formValues.confirmed ? 'checked' : ''}> Подтверждаю, что клиент принял работы</label><div style="margin-top:10px"><canvas id="signature-pad" width="600" height="150" style="width:100%;height:90px;background:#fff;border:1px dashed var(--line);border-radius:8px;touch-action:none"></canvas><button class="btn btn-ghost" id="clear-signature" style="padding:5px 0;font-size:12px">${media.signature ? 'Подпись сохранена · очистить' : 'Очистить подпись'}</button></div></div>

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
    for (const [kind, inputId] of [['before', '#f-before'], ['after', '#f-after']]) {
      screen.querySelector(inputId).addEventListener('change', async (event) => {
        const selected = [...event.target.files].slice(0, 3 - media[kind].length);
        if (!selected.length) return;
        try {
          for (const file of selected) {
            if (file.size > 12 * 1024 * 1024) throw new Error('Фото должно быть не больше 12 МБ');
            media[kind].push({ id: createUuid(), kind, file_name: file.name || `${kind}.jpg`, data_url: await compressPhoto(file) });
          }
          draw();
        } catch (e) { toast(e.message || 'Не удалось обработать фото', 'error'); }
      });
    }
    const signaturePad = screen.querySelector('#signature-pad');
    const signatureContext = signaturePad.getContext('2d');
    signatureContext.strokeStyle = '#0F172A'; signatureContext.lineWidth = 2.5; signatureContext.lineCap = 'round';
    let signing = false;
    const signaturePoint = (event) => {
      const box = signaturePad.getBoundingClientRect();
      return { x: (event.clientX - box.left) * signaturePad.width / box.width, y: (event.clientY - box.top) * signaturePad.height / box.height };
    };
    signaturePad.addEventListener('pointerdown', (event) => { signing = true; signaturePad.setPointerCapture(event.pointerId); const p = signaturePoint(event); signatureContext.beginPath(); signatureContext.moveTo(p.x, p.y); });
    signaturePad.addEventListener('pointermove', (event) => { if (!signing) return; const p = signaturePoint(event); signatureContext.lineTo(p.x, p.y); signatureContext.stroke(); });
    signaturePad.addEventListener('pointerup', () => { if (!signing) return; signing = false; media.signature = { id: createUuid(), kind: 'signature', file_name: 'client-signature.png', data_url: signaturePad.toDataURL('image/png') }; });
    screen.querySelector('#clear-signature').addEventListener('click', () => { media.signature = null; signatureContext.clearRect(0, 0, signaturePad.width, signaturePad.height); });
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
    const signer = screen.querySelector('#f-signer').value.trim();
    const confirmed = screen.querySelector('#f-confirmed').checked;
    if (signer && !confirmed) return toast('Подтвердите приёмку работ клиентом', 'error');
    if (confirmed && (!signer || !media.signature)) return toast('Укажите ФИО и подпись клиента', 'error');
    const parts_used = Object.entries(usedQty).filter(([, q]) => q > 0).map(([part_id, quantity]) => ({ part_id, quantity }));

    const payload = {
      local_uuid: createUuid(),
      equipment_id: eq.id,
      task_id: state.drill.taskId || null,
      ticket_id: null,
      fault_type: selectedFault,
      description,
      labor_minutes: Math.max(0, Number(screen.querySelector('#f-labor').value || 0)),
      client_signer_name: confirmed ? signer : null,
      client_signed_at: confirmed ? new Date().toISOString() : null,
      started_at: null,
      closed_at: new Date().toISOString(),
      device_updated_at: new Date().toISOString(),
      base_equipment_version: eq.version,
      parts_used,
    };
    await TechDB.put('pendingRepairs', payload);
    for (const attachment of [...media.before, ...media.after, ...(media.signature ? [media.signature] : [])]) {
      await TechDB.put('pendingAttachments', { ...attachment, local_uuid: payload.local_uuid, repair_id: null });
    }
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

  const hint = document.getElementById('scan-hint');
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    const httpsUrl = location.href.replace(/^http:/, 'https:');
    hint.innerHTML = `Камера заблокирована, потому что приложение открыто без HTTPS. <a href="${esc(httpsUrl)}" style="color:var(--accent);font-weight:700">Открыть защищённую версию</a> или введите серийный номер ниже.`;
    return;
  }
  if (!('BarcodeDetector' in window)) {
    hint.textContent = 'Этот браузер не поддерживает встроенное QR-сканирование — используйте ручной ввод ниже.';
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
    hint.textContent = e.name === 'NotAllowedError'
      ? 'Доступ к камере запрещён. Разрешите камеру в настройках браузера и повторите.'
      : 'Не удалось включить камеру — используйте ручной ввод ниже.';
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
