// Inventory keeps the existing Equipment ID and public QR throughout its life.
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
  if (!admin && !(pending && state.me.role === 'technician')) {
    return openModal('Карточка ещё не заполнена', '<p>Первичную инвентаризацию выполняет администратор или назначенный клиенту техник.</p>', '<button class="btn btn-secondary" onclick="closeModal()">Закрыть</button>');
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
    <div class="field"><label for="inventory-location">Расположение на объекте</label><input id="inventory-location" maxlength="255" value="${esc(passport.location || '')}"></div>
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
