// Labels have their own lifecycle. Creating a sheet never creates machines.
async function renderQRLabels(content) {
  await ensureCustomers(true);
  const canPrint = ['owner', 'admin', 'dispatcher'].includes(state.me.role);
  content.innerHTML = `<div class="page-header"><div><h1>QR-наклейки</h1><div class="page-subtitle">Напечатайте → отсканируйте → привяжите к машине</div></div></div>
    <div class="qr-section-tabs"><button class="btn btn-secondary" onclick="location.hash='equipment'">Оборудование</button><button class="btn btn-primary" aria-current="page">QR-наклейки</button></div>
    <section class="qr-workflow-card"><div><strong>Наклейка отдельно. История — у оборудования.</strong><p>Свободный QR можно привязать к существующей машине или создать новую карточку. Уже привязанный код открывает её паспорт.</p></div><div class="qr-toolbar">${canPrint ? '<button class="btn btn-primary" id="labels-batch">Подготовить наклейки</button>' : ''}<button class="btn btn-secondary" id="labels-scan">Сканировать QR</button></div></section>
    <div class="qr-toolbar"><div class="field"><label for="labels-site">Объект</label><select id="labels-site"><option value="">Все объекты</option>${state.sites.map(site => `<option value="${site.id}">${esc(site.name)} · ${esc(site.client_name || '')}</option>`).join('')}</select></div><div class="field"><label for="labels-status">Наклейки</label><select id="labels-status"><option value="free">Свободные</option><option value="bound">Привязанные</option><option value="all">Все</option></select></div><div class="field"><label for="labels-search">Поиск</label><input id="labels-search" placeholder="Номер, модель или объект"></div></div>
    <section class="qr-print-controls" aria-label="Печать наклеек"><div class="qr-toolbar"><button class="btn btn-secondary" id="labels-select-visible">Выбрать показанные</button><button class="btn btn-secondary" id="labels-select-free">Выбрать только свободные</button><button class="btn btn-secondary" id="labels-clear">Снять выбор</button></div><div class="qr-toolbar"><strong id="labels-selected-count" role="status">Выбрано: 0</strong><button class="btn btn-primary" id="labels-preview" disabled>Предпросмотр и печать</button></div><small>Выбор действует в текущем фильтре. A4 · 8 наклеек 90 × 60 мм на листе.</small></section>
    <p id="labels-summary" role="status"></p><div id="labels-list" class="qr-label-grid"></div>`;
  let labels = [], visible = [];
  const selected = new Set();
  const updateSelection = () => {
    const count = selected.size;
    content.querySelector('#labels-selected-count').textContent = `Выбрано: ${count} · Листов A4: ${Math.ceil(count / 8)}${count > 500 ? ' — максимум 500 наклеек' : ''}`;
    content.querySelector('#labels-preview').disabled = !count || count > 500;
    content.querySelector('#labels-clear').disabled = !count;
    content.querySelector('#labels-select-visible').disabled = !visible.length;
    content.querySelectorAll('[data-label-select]').forEach(input => {
      input.checked = selected.has(input.dataset.labelSelect);
      input.closest('.qr-label-card').classList.toggle('is-selected', input.checked);
    });
  };
  const paint = () => {
    const site = content.querySelector('#labels-site').value;
    const status = content.querySelector('#labels-status').value;
    const search = content.querySelector('#labels-search').value.trim().toLocaleLowerCase();
    const scoped = labels.filter(item => !site || item.site_id === site);
    visible = scoped.filter(item => (status === 'all' || item.status === status) &&
      `${item.number ?? ''} ${item.site_name} ${item.equipment_name || ''}`.toLocaleLowerCase().includes(search));
    const visibleTokens = new Set(visible.map(item => item.token));
    for (const token of selected) if (!visibleTokens.has(token)) selected.delete(token);
    content.querySelector('#labels-summary').textContent = `Свободно: ${scoped.filter(item => item.status === 'free').length} · Привязано: ${scoped.filter(item => item.status === 'bound').length}`;
    content.querySelector('#labels-list').innerHTML = visible.length ? visible.map(item => `<article class="qr-label-card"><label class="qr-print-choice"><input type="checkbox" data-label-select="${item.token}" aria-label="Выбрать QR ${item.number ?? 'оборудования'} · ${esc(item.site_name)}"> В печать</label><div class="qr-label-top"><strong>${item.number != null ? `QR № ${item.number}` : 'QR оборудования'}</strong><span class="badge ${item.status === 'free' ? 'badge-amber' : 'badge-green'}">${item.status === 'free' ? 'Свободна' : 'Привязана'}</span></div><p>${esc(item.site_name)}</p><div class="qr-label-target">${esc(item.equipment_name || 'Оборудование ещё не назначено')}</div>${item.location_details ? `<small>${esc(item.location_details)}</small>` : ''}<div class="qr-toolbar"><button class="btn ${item.status === 'free' ? 'btn-primary' : 'btn-secondary'}" data-label-open="${item.token}">${item.status === 'free' ? 'Привязать оборудование' : 'Открыть паспорт'}</button><button class="btn btn-secondary" data-label-pdf="${item.token}" aria-label="Скачать PDF наклейки ${item.number ?? ''}">PDF</button></div></article>`).join('') : `<div class="qr-empty"><strong>${status === 'free' ? 'Свободных наклеек не найдено' : 'Наклеек не найдено'}</strong><p>Измените фильтр${canPrint ? ' или подготовьте новую партию' : ''}.</p></div>`;
    content.querySelectorAll('[data-label-select]').forEach(input => input.onchange = () => { if (input.checked) selected.add(input.dataset.labelSelect); else selected.delete(input.dataset.labelSelect); updateSelection(); });
    updateSelection();
    content.querySelectorAll('[data-label-open]').forEach(button => button.onclick = () => { location.hash = `inventory/${button.dataset.labelOpen}`; });
    content.querySelectorAll('[data-label-pdf]').forEach(button => button.onclick = async () => {
      button.disabled = true;
      try { downloadBlob(await apiBlob(`/qr-labels/${button.dataset.labelPdf}/pdf`), `fixit-label-${button.dataset.labelPdf}.pdf`); }
      catch (error) { toast(error.message, 'error'); }
      finally { button.disabled = false; }
    });
  };
  const refresh = async () => { labels = await api('/qr-labels'); if (content.querySelector('#labels-list')) paint(); };
  content.querySelector('#labels-select-visible').onclick = () => { visible.forEach(item => selected.add(item.token)); updateSelection(); };
  content.querySelector('#labels-select-free').onclick = () => {
    selected.clear(); content.querySelector('#labels-status').value = 'free'; paint();
    visible.forEach(item => selected.add(item.token)); updateSelection();
  };
  content.querySelector('#labels-clear').onclick = () => { selected.clear(); updateSelection(); };
  content.querySelector('#labels-preview').onclick = async event => {
    const button = event.currentTarget;
    const chosen = visible.filter(item => selected.has(item.token));
    button.disabled = true; button.textContent = 'Подготовка листов…';
    try { await openQRPrintPreview(chosen, content.querySelector('#labels-status').value === 'free'); }
    catch (error) { toast(error.message, 'error'); await refresh(); }
    finally { if (button.isConnected) { button.textContent = 'Предпросмотр и печать'; updateSelection(); } }
  };
  content.querySelector('#labels-site').onchange = paint;
  content.querySelector('#labels-status').onchange = paint;
  content.querySelector('#labels-search').oninput = paint;
  content.querySelector('#labels-scan').onclick = openQrQuickAction;
  content.querySelector('#labels-batch')?.addEventListener('click', () => openInventoryBatches(content.querySelector('#labels-site').value, refresh).catch(error => toast(error.message, 'error')));
  await refresh();
}

async function renderLabelBinding(content, token) {
  const label = await api(`/qr-labels/${encodeURIComponent(token)}`).catch(async error => {
    // Equipment created before its first label is printed retains its original QR.
    const equipment = await api(`/equipment/by-qr/${encodeURIComponent(token)}`).catch(() => { throw error; });
    if (equipment.passport_allowed === false) throw new Error('Оборудование не назначено вам для обслуживания');
    return {equipment_id: equipment.id, status: 'bound', token};
  });
  const title = label.number != null ? `QR № ${label.number}` : 'QR оборудования';
  if (label.status === 'bound') {
    content.innerHTML = `<button class="btn btn-secondary" onclick="location.hash='labels'">← QR-наклейки</button><section class="qr-workflow-card"><div><h1>${esc(title)}</h1><p>Наклейка уже привязана${label.equipment_name ? `: ${esc(label.equipment_name)}` : ''}. История и заявки сохраняются в паспорте оборудования.</p></div><button class="btn btn-primary" id="label-passport">Открыть паспорт</button></section>`;
    content.querySelector('#label-passport').onclick = () => openEquipmentPassport(label.equipment_id);
    await openEquipmentPassport(label.equipment_id);
    return;
  }
  if (!label.can_bind) {
    content.innerHTML = `<h1>${esc(title)}</h1><p>Наклейка ещё свободна. Для привязки обратитесь к администратору, диспетчеру или мастеру объекта.</p><button class="btn btn-secondary" onclick="location.hash='labels'">К наклейкам</button>`;
    return;
  }
  const [items] = await Promise.all([api(`/equipment?site_id=${encodeURIComponent(label.site_id)}`), ensureEquipmentTypes()]);
  const key = `fixit-label-bind:${state.me.id}:${token}`;
  let attempt;
  try { attempt = JSON.parse(localStorage.getItem(key) || 'null'); } catch (_) {}
  let mode = attempt?.payload?.new_equipment ? 'new' : 'existing';
  const equipmentTitle = item => [item.manufacturer, item.model].filter(Boolean).join(' ') || item.name;
  content.innerHTML = `<button class="btn btn-secondary" onclick="location.hash='labels'">← QR-наклейки</button>
    <section class="qr-binding-header"><span class="badge badge-amber">Свободная наклейка</span><h1>${esc(title)}</h1><p>${esc(label.site_name)}</p><div class="qr-steps"><strong>1. Выберите машину</strong><span>2. Проверьте и привяжите</span></div></section>
    <section class="qr-binding-card"><div class="qr-section-tabs" role="group" aria-label="Способ привязки"><button class="btn" id="label-existing">Выбрать существующую</button><button class="btn" id="label-new">Добавить новую</button></div>
    <form id="label-form"><div id="label-existing-fields"><div class="field"><label for="label-search">Найти оборудование на объекте</label><input id="label-search" placeholder="Модель, серийный номер, расположение"></div><div class="field"><label for="label-equipment">Оборудование</label><select id="label-equipment"><option value="">Выберите машину</option></select></div><p id="label-selected" class="qr-selection-note"></p></div>
    <div id="label-new-fields" class="hidden"><p class="text-soft">Проверьте, нет ли машины в существующем списке. Новая карточка и привязка будут сохранены вместе.</p><div class="field"><label for="label-type">Тип оборудования *</label><select id="label-type"><option value="">Выберите тип</option>${state.equipmentTypes.map(kind => `<option value="${kind.id}">${esc(kind.name)}</option>`).join('')}</select></div><div class="field-row"><div class="field"><label for="label-maker">Производитель</label><input id="label-maker" maxlength="255"></div><div class="field"><label for="label-model">Модель</label><input id="label-model" maxlength="255"></div></div><div class="field"><label for="label-serial">Серийный номер (если есть)</label><input id="label-serial" maxlength="255"></div><div class="field"><label for="label-location">Где находится на объекте</label><input id="label-location" maxlength="500" placeholder="Корпус 2, прачечная, 1 этаж"></div></div>
    <p id="label-error" role="alert"></p><button class="btn btn-primary" id="label-review" type="submit">Проверить привязку →</button></form></section>`;
  const field = id => content.querySelector(`#${id}`);
  const populate = () => {
    const value = field('label-equipment').value;
    const q = field('label-search').value.toLocaleLowerCase();
    const found = items.filter(item => `${equipmentTitle(item)} ${item.serial_number || ''} ${item.location_details || ''}`.toLocaleLowerCase().includes(q));
    field('label-equipment').innerHTML = '<option value="">Выберите машину</option>' + found.map(item => `<option value="${item.id}">${esc(equipmentTitle(item))}${item.serial_number ? ` · S/N ${esc(item.serial_number)}` : ''}${item.location_details ? ` · ${esc(item.location_details)}` : ''} · ID ${item.id.slice(0,8)}</option>`).join('');
    if (found.some(item => item.id === value)) field('label-equipment').value = value;
    selection();
  };
  const selection = () => {
    const item = items.find(item => item.id === field('label-equipment').value);
    field('label-selected').textContent = item ? `${equipmentTitle(item)} · ${item.location_details || 'Место не указано'}. История и текущие QR этой машины сохранятся.` : (items.length ? 'Выберите именно ту машину, на которую приклеите наклейку.' : 'На объекте пока нет оборудования. Выберите «Добавить новую».');
  };
  const switchMode = value => {
    mode = value;
    field('label-existing-fields').classList.toggle('hidden', mode !== 'existing');
    field('label-new-fields').classList.toggle('hidden', mode !== 'new');
    field('label-existing').className = `btn ${mode === 'existing' ? 'btn-primary' : 'btn-secondary'}`;
    field('label-new').className = `btn ${mode === 'new' ? 'btn-primary' : 'btn-secondary'}`;
  };
  field('label-existing').onclick = () => switchMode('existing');
  field('label-new').onclick = () => switchMode('new');
  field('label-search').oninput = populate;
  field('label-equipment').onchange = selection;
  populate(); switchMode(mode);
  if (attempt?.payload?.equipment_id) field('label-equipment').value = attempt.payload.equipment_id;
  if (attempt?.payload?.new_equipment) {
    const saved = attempt.payload.new_equipment;
    for (const [id, prop] of [['label-type','equipment_type_id'],['label-maker','manufacturer'],['label-model','model'],['label-serial','serial_number'],['label-location','location_details']]) field(id).value = saved[prop] || '';
  }
  field('label-form').onsubmit = async event => {
    event.preventDefault();
    field('label-error').textContent = '';
    let payload, chosenTitle, details;
    if (mode === 'existing') {
      const item = items.find(item => item.id === field('label-equipment').value);
      if (!item) { field('label-error').textContent = 'Выберите оборудование'; return; }
      payload = {equipment_id: item.id}; chosenTitle = equipmentTitle(item);
      details = [item.serial_number ? `S/N ${item.serial_number}` : 'Без серийного номера', item.location_details || 'Место не указано'].join(' · ');
    } else {
      if (!field('label-type').value) { field('label-error').textContent = 'Выберите тип оборудования'; return; }
      payload = {new_equipment: {equipment_type_id: Number(field('label-type').value), manufacturer: field('label-maker').value.trim() || null, model: field('label-model').value.trim() || null, serial_number: field('label-serial').value.trim() || null, location_details: field('label-location').value.trim() || null}};
      chosenTitle = [payload.new_equipment.manufacturer, payload.new_equipment.model].filter(Boolean).join(' ') || state.equipmentTypes.find(kind => kind.id === payload.new_equipment.equipment_type_id)?.name;
      details = [payload.new_equipment.serial_number ? `S/N ${payload.new_equipment.serial_number}` : 'Без серийного номера', payload.new_equipment.location_details || 'Место не указано'].join(' · ');
    }
    if (!attempt || JSON.stringify(attempt.payload) !== JSON.stringify(payload)) attempt = {id: crypto.randomUUID(), payload};
    localStorage.setItem(key, JSON.stringify(attempt));
    const modal = openModal('Проверьте привязку', `<div class="qr-confirm"><span class="badge badge-amber">${esc(title)}</span><h3>${esc(chosenTitle)}</h3><p>${esc(label.site_name)}</p><p>${esc(details)}</p><p>${mode === 'new' ? 'Будет создана новая карточка оборудования.' : 'Будет использована существующая карточка. История ремонтов сохранится.'}</p><strong>Наклейте этот QR именно на выбранную машину.</strong><p id="label-bind-error" role="alert"></p></div>`, '<button class="btn btn-secondary" id="label-back">Назад</button><button class="btn btn-primary" id="label-confirm">Привязать наклейку</button>');
    modal.querySelector('#label-back').onclick = closeModal;
    modal.querySelector('#label-confirm').onclick = async event => {
      const button = event.currentTarget; button.disabled = true;
      modal.querySelector('#label-back').disabled = true;
      try {
        const result = await api(`/qr-labels/${encodeURIComponent(token)}/bind`, {method:'POST', body:JSON.stringify({...attempt.payload, idempotency_key: attempt.id})});
        localStorage.removeItem(key); closeModal(); window.scrollTo({top:0, behavior:'instant'});
        content.innerHTML = `<section class="qr-binding-card qr-success"><span class="badge badge-green">Привязка сохранена</span><h1>${esc(title)} → ${esc(result.equipment_name)}</h1><p>${esc(label.site_name)}</p><p>QR открывает паспорт этой машины. Старые коды и история оборудования сохранены.</p><div class="qr-toolbar"><button class="btn btn-primary" id="label-next">Сканировать следующий QR</button><button class="btn btn-secondary" id="label-done-passport">Открыть паспорт</button><button class="btn btn-secondary" onclick="location.hash='labels'">К наклейкам</button></div></section>`;
        window.scrollTo({top:0, behavior:'instant'});
        content.querySelector('#label-next').onclick = openQrQuickAction;
        content.querySelector('#label-done-passport').onclick = () => openEquipmentPassport(result.equipment_id);
      } catch (error) {
        modal.querySelector('#label-bind-error').textContent = error.message;
        button.disabled = false; modal.querySelector('#label-back').disabled = false;
      }
    };
  };
}


async function openQRPrintPreview(labels, freeOnly = false) {
  if (!labels.length || labels.length > 500) throw new Error('Выберите от 1 до 500 наклеек');
  const blob = await apiBlobPost('/qr-labels/print/pdf', {tokens:labels.map(item => item.token), free_only:freeOnly});
  const pages = Math.ceil(labels.length / 8);
  const modal = openModal('Предпросмотр печати', `<div class="qr-print-meta"><strong>Наклеек: ${labels.length} · Листов A4: ${pages}</strong><span>${freeOnly ? 'Только свободные на момент подготовки' : 'Выбранные наклейки'}</span></div><p class="text-soft">Размер наклейки 90 × 60 мм. Печать: A4, масштаб 100%, без колонтитулов.</p><div class="qr-page-nav"><button class="btn btn-secondary" id="qr-page-prev" disabled aria-label="Предыдущий лист">←</button><strong id="qr-page-number" role="status">Лист 1 из ${pages}</strong><button class="btn btn-secondary" id="qr-page-next" disabled aria-label="Следующий лист">→</button><button class="btn btn-secondary" id="qr-preview-zoom" aria-pressed="false">Крупнее</button></div><div class="qr-pdf-preview" id="qr-preview-area"><p id="qr-render-status" role="status">Отрисовка PDF…</p><canvas id="qr-preview-canvas" aria-label="Лист A4 с выбранными QR-наклейками"></canvas></div><details class="qr-print-composition"><summary>Состав листов</summary>${Array.from({length:pages}, (_,index) => `<p><strong>Лист ${index+1}:</strong> ${labels.slice(index*8,index*8+8).map(item => `${esc(item.site_name)} · ${item.number != null ? `№${item.number}` : esc(item.equipment_name || 'QR')}`).join('; ')}</p>`).join('')}</details><p id="qr-print-error" role="alert"></p>`, '<button class="btn btn-secondary" id="qr-print-close">Закрыть</button><button class="btn btn-secondary" id="qr-print-download">Скачать PDF</button><button class="btn btn-primary" id="qr-print-start" disabled>Печать</button>');
  modal.querySelector('.modal').classList.add('qr-print-modal');
  modal.querySelector('#qr-print-close').onclick = closeModal;
  modal.querySelector('#qr-print-download').onclick = () => downloadBlob(blob, 'fixit-qr-selected.pdf');
  modal.querySelector('#qr-preview-zoom').onclick = event => { const zoomed = modal.querySelector('#qr-preview-area').classList.toggle('is-zoomed'); event.currentTarget.textContent = zoomed ? 'Лист целиком' : 'Крупнее'; event.currentTarget.setAttribute('aria-pressed', String(zoomed)); };
  let documentPDF = null, loadingTask = null, pageNumber = 1, rendering = false, printing = false, printFrame = null;
  const prev = modal.querySelector('#qr-page-prev'), next = modal.querySelector('#qr-page-next');
  const printButton = modal.querySelector('#qr-print-start');
  const controls = () => {
    prev.disabled = rendering || printing || pageNumber === 1;
    next.disabled = rendering || printing || pageNumber === pages;
    printButton.disabled = !documentPDF || rendering || printing;
  };
  const renderPage = async () => {
    rendering = true; controls();
    try {
      const page = await documentPDF.getPage(pageNumber);
      if (!modal.isConnected) return;
      const canvas = modal.querySelector('#qr-preview-canvas');
      const viewport = page.getViewport({scale:1.5});
      canvas.width = viewport.width; canvas.height = viewport.height;
      await page.render({canvasContext:canvas.getContext('2d'), viewport}).promise;
      modal.querySelector('#qr-page-number').textContent = `Лист ${pageNumber} из ${pages}`;
      modal.querySelector('#qr-render-status').hidden = true;
    } finally { rendering = false; controls(); }
  };
  const changePage = async delta => {
    if (rendering || printing) return;
    pageNumber = Math.max(1, Math.min(pages, pageNumber + delta));
    try { await renderPage(); } catch (error) { modal.querySelector('#qr-print-error').textContent = 'Не удалось показать лист. Скачайте PDF: ' + error.message; }
  };
  prev.onclick = () => changePage(-1); next.onclick = () => changePage(1);
  printButton.onclick = async () => {
    if (!documentPDF || printing) return;
    printing = true; controls(); printButton.textContent = 'Подготовка печати…';
    modal.querySelector('#qr-print-error').textContent = '';
    try {
      printFrame?.remove();
      printFrame = document.createElement('iframe');
      printFrame.className = 'qr-print-frame'; printFrame.title = 'Листы для печати';
      document.body.appendChild(printFrame);
      const doc = printFrame.contentDocument;
      doc.open(); doc.write('<!doctype html><html><head><title>QR-наклейки Fixit</title><style>@page{size:A4;margin:0}html,body{margin:0;padding:0}img{display:block;width:210mm;height:297mm;break-after:page;page-break-after:always}img:last-child{break-after:auto;page-break-after:auto}</style></head><body></body></html>'); doc.close();
      for (let number = 1; number <= documentPDF.numPages; number++) {
        if (!modal.isConnected) return;
        const page = await documentPDF.getPage(number), viewport = page.getViewport({scale:2});
        const canvas = document.createElement('canvas'); canvas.width = viewport.width; canvas.height = viewport.height;
        await page.render({canvasContext:canvas.getContext('2d'), viewport}).promise;
        const img = doc.createElement('img'); img.src = canvas.toDataURL('image/png'); doc.body.appendChild(img); await img.decode();
      }
      printFrame.contentWindow.focus(); printFrame.contentWindow.print();
    } catch (error) {
      modal.querySelector('#qr-print-error').textContent = 'Браузер не открыл печать. Скачайте PDF и распечатайте его в масштабе 100%.';
    } finally { printing = false; controls(); printButton.textContent = 'Печать'; }
  };
  const cleanup = () => { observer.disconnect(); window.removeEventListener('hashchange', onRoute); printFrame?.remove(); loadingTask?.destroy(); };
  const observer = new MutationObserver(() => { if (!modal.isConnected) cleanup(); });
  const onRoute = () => { if (modal.isConnected) closeModal(); };
  observer.observe(document.body, {childList:true}); window.addEventListener('hashchange', onRoute);
  try {
    const pdfjs = await import('/static/vendor/pdfjs/pdf.min.mjs');
    if (!modal.isConnected) return;
    pdfjs.GlobalWorkerOptions.workerSrc = '/static/vendor/pdfjs/pdf.worker.min.mjs';
    loadingTask = pdfjs.getDocument({data:new Uint8Array(await blob.arrayBuffer()), isEvalSupported:false});
    documentPDF = await loadingTask.promise;
    if (!modal.isConnected) return;
    await renderPage();
  } catch (error) {
    if (modal.isConnected) modal.querySelector('#qr-render-status').textContent = 'Предпросмотр недоступен. Скачайте PDF для просмотра и печати.';
  }
}
