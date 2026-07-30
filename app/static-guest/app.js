// Гостевая страница — без авторизации. Токен из QR передаётся через ?token=...
// (см. redirect /e/{token} -> /guest/?token=... в main.py).

const params = new URLSearchParams(location.search);
const qrToken = params.get('token');

const state = { severity: 'not_working', tags: new Set() };

async function init() {
  if (!qrToken) return showError('Некорректная ссылка — попробуйте отсканировать QR ещё раз.');
  try {
    const res = await fetch(`/api/public/equipment/${qrToken}`);
    if (!res.ok) throw new Error();
    const eq = await res.json();
    document.getElementById('eq-name').textContent = `${eq.name}${eq.model ? ' · ' + eq.model : ''}`;
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

document.addEventListener('click', (e) => {
  if (e.target.dataset.sev) {
    document.querySelectorAll('.severity button').forEach((b) => b.classList.remove('active'));
    e.target.classList.add('active');
    state.severity = e.target.dataset.sev;
  }
  if (e.target.dataset.tag) {
    e.target.classList.toggle('active');
    if (state.tags.has(e.target.dataset.tag)) state.tags.delete(e.target.dataset.tag);
    else state.tags.add(e.target.dataset.tag);
  }
});

document.getElementById('form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById('error');
  errorEl.classList.add('hidden');
  const btn = document.getElementById('submit-btn');
  btn.disabled = true;

  // Идемпотентность: один и тот же ключ на повторных сабмитах (двойной тап,
  // разрыв связи) — храним в localStorage per-QR, чтобы дубль не улетел дважды.
  const idKey = `fixit-ticket-key:${qrToken}`;
  let idempotencyKey = localStorage.getItem(idKey);
  if (!idempotencyKey) { idempotencyKey = crypto.randomUUID(); localStorage.setItem(idKey, idempotencyKey); }

  try {
    const res = await fetch(`/api/public/equipment/${qrToken}/tickets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        severity: state.severity,
        symptom_tags: Array.from(state.tags).length ? Array.from(state.tags) : ['Не указано'],
        comment: document.getElementById('comment').value.trim() || null,
        reporter_name: document.getElementById('name').value.trim() || null,
        reporter_phone: document.getElementById('phone').value.trim() || null,
        idempotency_key: idempotencyKey,
      }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(typeof body.detail === 'string' ? body.detail : 'Не удалось отправить заявку');
    }
    document.getElementById('content').classList.add('hidden');
    document.getElementById('success').classList.remove('hidden');
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove('hidden');
    btn.disabled = false;
  }
});

init();
