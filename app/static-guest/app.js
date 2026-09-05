// Гостевая страница — без авторизации. Токен из QR передаётся через ?token=...
// (см. redirect /e/{token} -> /guest/?token=... в main.py).

const params = new URLSearchParams(location.search);
const qrToken = params.get('token');

const state = { severity: 'not_working', tags: new Set(), equipment: null, submitting: false, uploadingPhotos: false, createdRequest: null, photos: [] };

function createIdempotencyKey() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

async function init() {
  if (!qrToken) return showError('Некорректная ссылка — попробуйте отсканировать QR ещё раз.');
  try {
    const res = await fetch(`/api/public/equipment/${qrToken}`);
    if (!res.ok) throw new Error();
    const eq = await res.json();
    state.equipment = eq;
    document.getElementById('eq-name').textContent = `${eq.name}${eq.model ? ' · ' + eq.model : ''}`;
    document.getElementById('eq-meta').textContent = `S/N ${eq.serial_number || '—'} · ${eq.site_name || 'Объект'} · ${eq.status === 'needs_repair' ? 'Требует ремонта' : 'Работает'}`;
    if (eq.photo_url) { const photo = document.getElementById('eq-photo'); photo.src = eq.photo_url; photo.classList.remove('hidden'); }
    document.getElementById('loading').classList.add('hidden');
    document.getElementById('content').classList.remove('hidden');
  } catch (_) {
    showError('Не удалось найти оборудование по этому QR-коду.');
  }
}

function showError(text) {
  document.getElementById('loading').classList.add('hidden');
  document.getElementById('card').innerHTML = `<div class="msg msg-error">${text}</div>`;
}

document.getElementById('photos').addEventListener('change', (event) => {
  document.getElementById('photo-count').textContent = `Выбрано: ${Math.min(event.target.files.length, 3)} из 3`;
});

function photoSummary() {
  const total = state.photos.length;
  const success = state.photos.filter((photo) => photo.status === 'success').length;
  const uploading = state.photos.filter((photo) => photo.status === 'uploading').length;
  const failed = state.photos.filter((photo) => photo.status === 'failed');
  const retryable = failed.filter((photo) => photo.retryable);
  return { total, success, uploading, failed, retryable };
}

function renderUploadState() {
  const success = document.getElementById('success');
  const number = `SR-${String(state.createdRequest.number || '').padStart(5, '0')}`;
  const summary = photoSummary();
  const rows = state.photos.map((photo) => {
    const label = photo.status === 'success' ? 'Отправлено' : photo.status === 'uploading' ? 'Загружается…' : photo.status === 'failed' ? (photo.retryable ? `Не отправлено: ${photo.error}` : `Фото отклонено: ${photo.error}`) : 'Ожидает отправки';
    const icon = photo.status === 'success' ? '✓' : photo.status === 'failed' ? '!' : '…';
    return `<li class="upload-item upload-${photo.status}"><span>${icon}</span><div><b>${escapeHtml(photo.name)}</b><small>${label}</small></div></li>`;
  }).join('');
  const isDone = !summary.uploading && !summary.failed.length;
  const heading = isDone ? '✓ Заявка отправлена' : 'Заявка создана';
  const detail = summary.total
    ? `Фотографии: ${summary.success} из ${summary.total} отправлено${summary.uploading ? ' · идёт загрузка' : ''}`
    : 'Сервисная служба получила сообщение.';
  const failure = summary.failed.length ? `<p class="upload-warning">Не удалось отправить ${summary.failed.length} из ${summary.total} фотографий.</p>` : '';
  const retry = summary.retryable.length ? `<button type="button" class="btn" id="retry-photos" ${state.uploadingPhotos ? 'disabled' : ''}>ПОВТОРИТЬ ОТПРАВКУ</button>` : '';
  success.innerHTML = `<div class="msg msg-success"><strong>${heading}</strong><br><span>${number}${state.createdRequest.active_request ? ' · Заявка уже в работе' : ''}</span><br><span>${detail}</span></div>${state.photos.length ? `<ul class="upload-list">${rows}</ul>` : ''}${failure}${retry}<button type="button" class="btn btn-secondary" id="upload-done">Готово</button>`;
  success.classList.remove('hidden');
  success.querySelector('#retry-photos')?.addEventListener('click', retryFailedPhotos);
  success.querySelector('#upload-done').addEventListener('click', () => { success.querySelector('#upload-done').textContent = 'Можно закрыть страницу'; });
}

function escapeHtml(value) {
  const node = document.createElement('span');
  node.textContent = value || 'Фотография';
  return node.innerHTML;
}

async function sendPhotos() {
  if (state.uploadingPhotos) return;
  state.uploadingPhotos = true;
  try {
    await window.FixitGuestPhotoUpload.uploadPending(state.photos, { qrToken, requestId: state.createdRequest.service_request_id }, renderUploadState);
  } finally {
    state.uploadingPhotos = false;
    renderUploadState();
  }
}

async function retryFailedPhotos() {
  await sendPhotos();
}

document.getElementById('form').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (state.submitting || state.createdRequest) return;
  state.submitting = true;
  const errorEl = document.getElementById('error');
  errorEl.classList.add('hidden');
  const btn = document.getElementById('submit-btn');
  btn.disabled = true;

  // Идемпотентность: один и тот же ключ на повторных сабмитах (двойной тап,
  // разрыв связи) — храним в localStorage per-QR, чтобы дубль не улетел дважды.
  // Ключ нужен только на время повторной отправки одного обращения. Версия
  // отделяет новые заявки от ключей, которые прежняя версия страницы могла
  // оставить навсегда в браузере.
  const idKey = `fixit-ticket-key:v2:${qrToken}`;
  try {
    let idempotencyKey = localStorage.getItem(idKey);
    if (!idempotencyKey) {
      idempotencyKey = createIdempotencyKey();
      localStorage.setItem(idKey, idempotencyKey);
    }
    const res = await fetch(`/api/public/equipment/${qrToken}/tickets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        severity: state.severity,
        symptom_tags: ['Сообщение оператора'],
        comment: document.getElementById('comment').value.trim(),
        reporter_name: document.getElementById('name').value.trim() || null,
        reporter_phone: document.getElementById('phone').value.trim() || null,
        idempotency_key: idempotencyKey,
      }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(typeof body.detail === 'string' ? body.detail : 'Не удалось отправить заявку');
    }
    const body = await res.json();
    if (!body.service_request_id) throw new Error('Не удалось определить созданную заявку');
    state.createdRequest = body;
    state.photos = [...document.getElementById('photos').files].slice(0, 3).map((file) => ({ id: createIdempotencyKey(), file, name: file.name || 'Фотография', status: 'pending', error: null, retryable: false }));
    // From this point retries operate only on attachment client_ids.  A
    // ServiceRequest must never be submitted again from this page session.
    localStorage.removeItem(idKey);
    document.getElementById('content').classList.add('hidden');
    renderUploadState();
    await sendPhotos();
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove('hidden');
    btn.disabled = false;
  } finally {
    state.submitting = false;
  }
});

init();
