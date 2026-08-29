// Гостевая страница — без авторизации. Токен из QR передаётся через ?token=...
// (см. redirect /e/{token} -> /guest/?token=... в main.py).

const params = new URLSearchParams(location.search);
const qrToken = params.get('token');

const state = { severity: 'not_working', tags: new Set(), equipment: null };

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

document.getElementById('photos').addEventListener('change', (event) => { document.getElementById('photo-count').textContent = `Выбрано: ${Math.min(event.target.files.length, 3)} из 3`; });

document.getElementById('form').addEventListener('submit', async (e) => {
  e.preventDefault();
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
    const files = [...document.getElementById('photos').files].slice(0, 3);
    const uploads = await Promise.allSettled(files.map((file) => { const data = new FormData(); data.append('file', file); return fetch(`/api/public/equipment/${qrToken}/requests/${body.service_request_id}/attachments`, { method: 'POST', body: data }); }));
    if (uploads.some((upload) => upload.status === 'rejected' || !upload.value.ok)) console.warn('Не все фотографии загружены');
    // Следующее обращение по этому QR — это уже новая заявка, а не повтор
    // предыдущей отправки. При ошибке ключ намеренно остаётся для ретрая.
    localStorage.removeItem(idKey);
    document.getElementById('content').classList.add('hidden');
    document.getElementById('success-number').textContent = `SR-${String(body.number || '').padStart(5, '0')} · ${body.active_request ? 'Заявка уже в работе' : 'Заявка принята'}`;
    document.getElementById('success').classList.remove('hidden');
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove('hidden');
    btn.disabled = false;
  }
});

init();
