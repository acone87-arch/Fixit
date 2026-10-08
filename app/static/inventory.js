// Inventory keeps the existing Equipment ID and public QR throughout its life.
async function openEquipmentQRReprint(selectedSite = '') {
  await Promise.all([ensureCustomers(true), ensureEquipmentTypes()]);
  const sites = state.sites;
  if (!sites.length) return toast('Сначала создайте объект обслуживания', 'error');
  const modal = openModal('Перепечатать QR оборудования', `
    <div class="field"><label for="qr-reprint-site">Объект</label><select id="qr-reprint-site">${sites.map(site => `<option value="${site.id}" ${selectedSite === site.id ? 'selected' : ''}>${esc(site.name)} · ${esc(site.client_name || '')}</option>`).join('')}</select></div>
    <p class="text-soft">Существующие QR-коды сохраняются. PDF: A4, 8 этикеток 90 × 60 мм на листе, масштаб 100%. До 500 этикеток за раз.</p>
    <label class="qr-reprint-choice"><input type="checkbox" id="qr-reprint-all" disabled><strong>Выбрать все на объекте</strong></label>
    <p id="qr-reprint-count" role="status">Выбрано: 0</p>
    <div id="qr-reprint-list" class="qr-reprint-list">Загрузка оборудования…</div>`,
    '<button class="btn btn-secondary" id="qr-reprint-close">Закрыть</button><button class="btn btn-primary" id="qr-reprint-download" disabled>Скачать PDF</button>');
  const siteSelect = modal.querySelector('#qr-reprint-site'), all = modal.querySelector('#qr-reprint-all');
  const list = modal.querySelector('#qr-reprint-list'), download = modal.querySelector('#qr-reprint-download');
  let loading = false, downloading = false, generation = 0;
  const choices = () => [...list.querySelectorAll('input[data-equipment-id]')];
  const update = () => {
    const inputs = choices(), count = inputs.filter(input => input.checked).length;
    all.checked = inputs.length > 0 && count === inputs.length;
    all.indeterminate = count > 0 && count < inputs.length;
    modal.querySelector('#qr-reprint-count').textContent = `Выбрано: ${count}${count > 500 ? ' — выберите не более 500' : ''}`;
    download.disabled = loading || downloading || !count || count > 500;
  };
  const refresh = async () => {
    const attempt = ++generation;
    loading = true; all.disabled = true; all.checked = false; all.indeterminate = false;
    list.textContent = 'Загрузка оборудования…'; update();
    try {
      const items = await api(`/equipment?site_id=${encodeURIComponent(siteSelect.value)}`);
      if (attempt !== generation || !modal.isConnected) return;
      list.innerHTML = items.length ? items.map(item => {
        const type = state.equipmentTypes.find(kind => kind.id === item.equipment_type_id)?.name;
        const name = [item.manufacturer, item.model].filter(Boolean).join(' ') || type || item.name || 'Оборудование';
        return `<label class="qr-reprint-choice"><input type="checkbox" data-equipment-id="${item.id}"><span><strong>${esc(name)}</strong><small>${esc([item.serial_number ? `S/N ${item.serial_number}` : '', item.inventory_number != null ? `QR № ${item.inventory_number}` : '', item.location_details, item.inventory_pending ? 'Карточка не заполнена' : ''].filter(Boolean).join(' · '))}</small></span></label>`;
      }).join('') : '<p>На этом объекте оборудования нет.</p>';
      all.disabled = !items.length;
      choices().forEach(input => input.addEventListener('change', update));
    } catch (error) {
      if (attempt !== generation || !modal.isConnected) return;
      list.textContent = 'Не удалось загрузить оборудование. Выберите объект повторно.';
      toast(error.message, 'error');
    } finally {
      if (attempt === generation) { loading = false; update(); }
    }
  };
  all.onchange = () => { choices().forEach(input => { input.checked = all.checked; }); update(); };
  siteSelect.onchange = refresh;
  modal.querySelector('#qr-reprint-close').onclick = closeModal;
  download.onclick = async () => {
    const equipment_ids = choices().filter(input => input.checked).map(input => input.dataset.equipmentId);
    if (!equipment_ids.length || equipment_ids.length > 500 || downloading || loading) return;
    const site_id = siteSelect.value;
    downloading = true; siteSelect.disabled = true; update(); download.textContent = 'Подготовка PDF…';
    try {
      const blob = await apiBlob('/equipment-inventory/reprint/pdf', {method:'POST', body:JSON.stringify({site_id, equipment_ids})});
      const url = URL.createObjectURL(blob), link = document.createElement('a');
      link.href = url; link.download = `fixit-qr-reprint-${site_id}.pdf`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (error) { toast(error.message, 'error'); }
    finally { downloading = false; siteSelect.disabled = false; download.textContent = 'Скачать PDF'; update(); }
  };
  await refresh();
}

async function openInventoryBatches(selectedSite = '') {
  await ensureCustomers(true);
  const sites = state.sites.filter(site => site.is_active);
  if (!sites.length) return toast('Сначала создайте объект обслуживания', 'error');
  const modal = openModal('Первичная инвентаризация', `
    <p>Создайте пустые карточки, распечатайте QR и заполните оборудование на объекте с телефона.</p>
    <div class="field"><label for="inventory-site">Объект</label><select id="inventory-site">${sites.map(site => `<option value="${site.id}" ${selectedSite === site.id ? 'selected' : ''}>${esc(site.name)} · ${esc(site.client_name || '')}</option>`).join('')}</select></div>
    <div class="field"><label for="inventory-count">Количество оборудования</label><input id="inventory-count" type="number" min="1" max="500" value="10"></div>
    <p class="text-soft">От 1 до 500 QR в партии. PDF: A4, 8 этикеток на листе, печать в масштабе 100%.</p>
    <div id="inventory-batches">Загрузка партий…</div>`,
    '<button class="btn btn-secondary" id="inventory-close">Закрыть</button><button class="btn btn-primary" id="inventory-generate">Создать партию QR</button>');
  modal.querySelector('#inventory-close').onclick = closeModal;
  let attempt = null;
  const refresh = async () => {
    const siteId = modal.querySelector('#inventory-site').value;
    const batches = await api(`/equipment-inventory/batches?site_id=${encodeURIComponent(siteId)}`);
    if (siteId !== modal.querySelector('#inventory-site').value) return;
    modal.querySelector('#inventory-batches').innerHTML = batches.length ? batches.map(batch => `<p><strong>Партия ${esc(batch.id.slice(0,8))}</strong> · ${fmtDate(batch.created_at)}<br>Заполнено ${batch.completed} из ${batch.quantity} <button class="btn btn-secondary" data-inventory-pdf="${batch.id}">Скачать PDF</button></p>`).join('') : '<p>На этом объекте ещё нет партий QR.</p>';
    modal.querySelectorAll('[data-inventory-pdf]').forEach(button => button.onclick = async () => {
      button.disabled = true;
      try {
        const blob = await apiBlob(`/equipment-inventory/batches/${button.dataset.inventoryPdf}/pdf`);
        const url = URL.createObjectURL(blob), link = document.createElement('a');
        link.href = url; link.download = `fixit-qr-${button.dataset.inventoryPdf}.pdf`; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
      } catch (error) { toast(error.message, 'error'); }
      finally { button.disabled = false; }
    });
  };
  modal.querySelector('#inventory-site').onchange = () => refresh().catch(error => toast(error.message,'error'));
  modal.querySelector('#inventory-generate').onclick = async event => {
    const site_id = modal.querySelector('#inventory-site').value;
    const quantity = Number(modal.querySelector('#inventory-count').value);
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > 500) return toast('Укажите целое количество от 1 до 500', 'error');
    const storageKey = `fixit-inventory-attempt:${state.me.id}:${site_id}`;
    // Persist retry identity across lost responses and a closed browser page.
    try { attempt = JSON.parse(localStorage.getItem(storageKey) || 'null'); } catch (_) { attempt = null; }
    if (attempt && attempt.quantity !== quantity) return toast('Есть незавершённая попытка создания партии. Повторите с количеством ' + attempt.quantity, 'error');
    if (!attempt) attempt = {site_id, quantity, idempotency_key: crypto.randomUUID()};
    const button = event.currentTarget;
    try {
      localStorage.setItem(storageKey, JSON.stringify(attempt));
      button.disabled = true;
      await api('/equipment-inventory/batches', {method:'POST', body:JSON.stringify(attempt)});
      localStorage.removeItem(storageKey); attempt = null;
      toast('Партия создана. Скачайте PDF для печати');
      await refresh();
    } catch (error) { toast(error.message, 'error'); }
    finally { button.disabled = false; }
  };
  await refresh();
}

async function openInventoryToken(token) {
  const equipment = await api(`/equipment/by-qr/${encodeURIComponent(token)}`);
  if (equipment.passport_allowed === false) throw new Error('Оборудование не назначено вам для обслуживания');
  await openEquipmentPassport(equipment.id);
}

async function openEquipmentDetailsEditor(passport) {
  const pending = passport.inventory_pending;
  const admin = ['owner','admin'].includes(state.me.role);
  if (!admin && !(pending && ['technician','client_site_user'].includes(state.me.role))) {
    return openModal('Карточка ещё не заполнена', '<p>Первичную инвентаризацию выполняет администратор, менеджер объекта или назначенный клиенту техник.</p>', '<button class="btn btn-secondary" onclick="closeModal()">Закрыть</button>');
  }
  await Promise.all([ensureEquipmentTypes(), ensureCustomers()]);
  const sites = state.sites.filter(site => site.is_active || site.id === passport.site_id);
  const modal = openModal(pending ? 'Заполнить оборудование' : 'Редактировать оборудование', `
    <p>${esc(passport.site_name || '')}${pending ? ` · QR № ${passport.inventory_number}` : ''}</p>
    <form id="inventory-form">
    <div class="field"><label for="inventory-type">Тип оборудования *</label><select id="inventory-type" required><option value="">Выберите тип</option>${state.equipmentTypes.map(type => `<option value="${type.id}" ${type.id === passport.equipment_type_id ? 'selected' : ''}>${esc(type.name)}</option>`).join('')}${admin ? '<option value="new">+ Новый тип</option>' : ''}</select></div>
    <div class="field hidden" id="inventory-new-type-wrap"><label for="inventory-new-type">Новый тип *</label><input id="inventory-new-type" maxlength="100"></div>
    <div class="field"><label for="inventory-maker">Производитель</label><input id="inventory-maker" maxlength="255" value="${esc(passport.manufacturer || '')}"></div>
    <div class="field"><label for="inventory-model">Модель</label><input id="inventory-model" maxlength="255" value="${esc(passport.model || '')}"></div>
    <div class="field"><label for="inventory-serial">Серийный номер *</label><input id="inventory-serial" required maxlength="255" value="${esc(passport.serial_number || '')}" autocapitalize="off"></div>
    <div class="field"><label for="inventory-location">Старое поле расположения</label><input id="inventory-location" maxlength="255" value="${esc(passport.location || '')}"></div>
    <div class="field"><label for="inventory-location-details">Расположение на объекте</label><input id="inventory-location-details" maxlength="500" placeholder="Например: прачечная, корпус 2, 1 этаж" value="${esc(passport.location_details || '')}"><small>Укажите, где именно искать оборудование внутри объекта.</small></div>
    ${!pending ? `<div class="field"><label for="inventory-edit-site">Объект обслуживания</label><select id="inventory-edit-site">${sites.map(site => `<option value="${site.id}" ${site.id === passport.site_id ? 'selected' : ''}>${esc(site.name)}</option>`).join('')}</select></div><div class="field"><label for="inventory-status">Статус</label><select id="inventory-status">${Object.entries(EQUIPMENT_STATUS).map(([key,item]) => `<option value="${key}" ${key === passport.status ? 'selected' : ''}>${item.label}</option>`).join('')}</select></div>` : ''}
    <div class="field"><label for="inventory-photo">${passport.primary_photo ? 'Заменить фото оборудования' : 'Фото оборудования'}</label><input id="inventory-photo" type="file" accept="image/*" capture="environment"></div>
    <p id="inventory-error" role="alert"></p>
    </form>`, '<button class="btn btn-secondary" id="inventory-cancel">Закрыть</button><button class="btn btn-primary" id="inventory-save">Сохранить карточку</button>');
  modal.querySelector('#inventory-cancel').onclick = closeModal;
  modal.querySelector('#inventory-type').onchange = event => modal.querySelector('#inventory-new-type-wrap').classList.toggle('hidden', event.target.value !== 'new');
  let saved = null;
  modal.querySelector('#inventory-save').onclick = async event => {
    const form = modal.querySelector('#inventory-form');
    if (!form.reportValidity()) return;
    const button = event.currentTarget, errorBox = modal.querySelector('#inventory-error');
    const serial = modal.querySelector('#inventory-serial').value.trim();
    if (!serial) { errorBox.textContent = 'Укажите серийный номер'; return; }
    button.disabled = true; errorBox.textContent = '';
    try {
      let equipment_type_id = modal.querySelector('#inventory-type').value;
      if (equipment_type_id === 'new') {
        const name = modal.querySelector('#inventory-new-type').value.trim();
        if (!name) throw new Error('Укажите название типа');
        const kind = await api('/equipment-types', {method:'POST',body:JSON.stringify({name})});
        state.equipmentTypes.push(kind);
        modal.querySelector('#inventory-type').add(new Option(kind.name, kind.id, true, true));
        equipment_type_id = kind.id;
      }
      const payload = {equipment_type_id:Number(equipment_type_id), serial_number:serial,
        manufacturer:modal.querySelector('#inventory-maker').value.trim() || null,
        model:modal.querySelector('#inventory-model').value.trim() || null,
        location:modal.querySelector('#inventory-location').value.trim() || null,
        location_details:modal.querySelector('#inventory-location-details').value.trim() || null,
        expected_version:saved?.version || passport.version};
      if (!pending) { payload.site_id = modal.querySelector('#inventory-edit-site').value; payload.status = modal.querySelector('#inventory-status').value; }
      if (!saved) saved = await api(pending ? `/equipment-inventory/${passport.id}/complete` : `/equipment/${passport.id}`, {method:pending ? 'POST' : 'PATCH',body:JSON.stringify(payload)});
      form.querySelectorAll('input:not([type=file]),select').forEach(input => { input.disabled = true; });
      const file = modal.querySelector('#inventory-photo').files?.[0];
      if (file) await uploadEquipmentPhoto(passport.id, file);
      closeModal();
      if (pending) {
        const done = openModal('Оборудование заполнено', `<p>${esc(saved.name)} · ${esc(saved.serial_number)}</p><p>Приклейте QR № ${passport.inventory_number} на эту машину и переходите к следующей.</p>`, '<button class="btn btn-secondary" id="inventory-passport">Открыть паспорт</button><button class="btn btn-primary" id="inventory-next">Сканировать следующий QR</button>');
        done.querySelector('#inventory-next').onclick = () => { closeModal(); openQrQuickAction(); };
        done.querySelector('#inventory-passport').onclick = () => { closeModal(); openEquipmentPassport(passport.id); };
      } else { toast('Карточка обновлена'); await openEquipmentPassport(passport.id); }
    } catch (error) { errorBox.textContent = (saved ? 'Карточка сохранена, фото не загружено. Повторите сохранение для загрузки фото. ' : '') + error.message; }
    finally { button.disabled = false; }
  };
}
