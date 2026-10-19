/* Explicit AI drafts. No storage, background generation, or business mutations. */
(() => {
  'use strict';
  function mount(root, options) {
    const abort = new AbortController();
    let disposed = false, busy = false, preview = null, baseline = null;
    const alive = () => !disposed && root.isConnected;
    const snapshot = () => JSON.stringify(options.getSnapshot());
    const el = (tag, text, className) => {
      const node = document.createElement(tag);
      if (text !== undefined) node.textContent = text;
      if (className) node.className = className;
      return node;
    };
    const title = el('h2', 'Помощник Fixit');
    const message = el('p', 'Проверяем доступность…', 'ai-message');
    message.setAttribute('role', 'status'); message.setAttribute('aria-live', 'polite');
    const controls = el('div', undefined, 'ai-controls');
    const output = el('div', undefined, 'ai-output');
    root.replaceChildren(title, message, controls, output);
    const online = () => navigator.onLine !== false;
    const tell = text => { if (alive()) message.textContent = text; };
    const button = (text, action) => {
      const node = el('button', text, 'btn btn-secondary'); node.type = 'button';
      node.addEventListener('click', action); return node;
    };
    const fields = ['diagnostic', 'work', 'comment'];
    const validResult = result => fields.every(key => typeof result[key] === 'string')
      && Array.isArray(result.questions) && result.questions.every(q => typeof q === 'string');
    const call = (path, body) => options.api(path, {
      method: body === undefined ? 'GET' : 'POST',
      ...(body === undefined ? {} : {body: JSON.stringify(body)}), signal: abort.signal,
    });
    const report = async (result, action, reason) => {
      if (!result.generation_id) return true;
      try {
        await call(`/ai/generations/${result.generation_id}/feedback`, {action, ...(reason ? {reason} : {})});
        return true;
      } catch (_) { return false; }
    };
    let format, brief;
    const updateOnline = () => {
      if (format) format.disabled = busy || !online();
      if (brief) brief.disabled = busy || !online();
      if (!online()) tell('Нет сети. Черновик можно заполнить и сохранить обычным способом.');
    };
    window.addEventListener('online', updateOnline);
    window.addEventListener('offline', updateOnline);
    async function load() {
      try {
        const capability = await call('/ai/capabilities');
        if (!alive()) return;
        if (!capability.repair_draft && !capability.equipment_brief) {
          tell('Помощник пока не включён для вашей организации.'); return;
        }
        if (capability.repair_draft && options.writable) {
          const label = el('label', 'Короткая заметка о результате');
          const note = el('textarea'); note.id = 'request-ai-note'; note.maxLength = 3000;
          note.value = options.note || ''; note.placeholder = 'Что обнаружено, что сделано, что осталось';
          label.append(note); controls.append(label);
          note.addEventListener('input', () => { options.onNote(note.value); });
          const consent = el('label', undefined, 'ai-consent');
          const check = document.createElement('input'); check.type = 'checkbox'; check.id = 'request-ai-consent';
          consent.append(check, document.createTextNode('Отправить этот текст в YandexGPT. Контакты и ссылки из заметки убраны.'));
          controls.append(consent);
          format = button('Оформить результат', async () => {
            if (busy || !online()) return;
            if (!check.checked) return tell('Подтвердите отправку заметки в YandexGPT.');
            if (!note.value.trim()) return tell('Добавьте короткую заметку.');
            const base = snapshot(), source = note.value;
            busy = true; updateOnline(); output.replaceChildren(); preview = null;
            const operation = options.uuid();
            tell('Готовим черновик… Можно продолжать редактировать форму.');
            try {
              const result = await call(`/ai/service-requests/${options.requestId}/repair-draft`, {
                operation_id: operation, revision: operation, note: source,
              });
              if (!alive()) return;
              if (snapshot() !== base || note.value !== source) return tell('Форма изменилась. Ответ не применён — новый текст сохранён.');
              if (result.revision !== operation || !validResult(result)) throw new Error('Ответ AI не прошёл проверку.');
              preview = result; baseline = base;
              const names = { diagnostic: 'Диагностика', work: 'Выполненные работы', comment: 'Комментарий' };
              output.append(el('h3', 'Проверьте черновик'));
              fields.forEach(key => { output.append(el('strong', names[key]), el('p', result[key] || 'Не указано')); });
              if (result.questions.length) {
                output.append(el('h3', 'Нужно уточнить'));
                result.questions.forEach(q => output.append(el('p', q)));
              }
              const reason = el('select'); reason.setAttribute('aria-label', 'Причина оценки черновика');
              for (const [value, text] of [['', 'Причина оценки (необязательно)'], ['accurate', 'Текст соответствует заметке'], ['missing_facts', 'Пропущены сведения'], ['wrong_meaning', 'Искажён смысл'], ['other', 'Другая причина']]) {
                const option = el('option', text); option.value = value; reason.append(option);
              }
              const ratingStatus = el('p'); ratingStatus.setAttribute('role', 'status');
              const rate = async action => {
                const recorded = await report(result, action, reason.value);
                if (alive()) ratingStatus.textContent = recorded ? 'Оценка записана.' : 'Оценка не отправлена. Проверьте сеть и повторите.';
              };
              output.append(reason, button('Полезно', () => rate('helpful')), button('Не полезно', () => rate('not_helpful')), ratingStatus);
              output.append(button('Применить в форму', async () => {
                if (!preview || !alive()) return;
                if (snapshot() !== baseline || note.value !== source || !options.writable) {
                  preview = null; output.replaceChildren();
                  return tell('Форма изменилась. Повторно проверьте текст; старый ответ не применён.');
                }
                const accepted = preview; preview = null;
                try {
                  if (await options.onApply(accepted) === false) return tell('Текст в форме. Сохранение черновика не удалось — оставьте страницу открытой.');
                  if (!alive()) return;
                  output.replaceChildren(); tell('Текст применён в форму. Сохраните результат обычным способом.');
                  if (!await report(accepted, 'applied')) tell('Текст применён в форму. Сохраните результат обычным способом; отметка применения не отправлена.');
                } catch (_) { tell('Не удалось применить текст. Проверьте форму и сохраните черновик.'); }
              }), button('Отмена', async () => { const declined = preview; preview = null; output.replaceChildren(); tell('Исходная заметка сохранена.'); if (declined && !await report(declined, 'rejected')) tell('Исходная заметка сохранена; отметка отказа не отправлена.'); }));
              tell('Черновик готов. Применение заменит три текстовых поля формы.');
            } catch (error) { if (alive() && error.name !== 'AbortError') tell(error.message || 'AI недоступен. Заполните форму вручную.'); }
            finally { busy = false; if (alive()) updateOnline(); }
          });
          format.id = 'request-ai-format'; controls.append(format);
        }
        if (capability.equipment_brief) {
          brief = button('Что важно знать', async () => {
            if (busy || !online()) return;
            busy = true; updateOnline(); tell('Читаем доступную историю…');
            try {
              const result = await call(`/ai/equipment/${options.equipmentId}/brief`, {});
              if (!alive()) return;
              preview = null; output.replaceChildren(el('h3', 'Последние записи оборудования'));
              if (!result.facts.length) output.append(el('p', 'Истории пока недостаточно.'));
              for (const fact of result.facts) {
                const card = el('div', undefined, 'ai-source');
                card.append(el('small', new Date(fact.date).toLocaleDateString('ru-RU')), el('p', fact.text));
                if (fact.service_request_id && /^[0-9a-f-]{36}$/i.test(fact.service_request_id)) {
                  const link = el('a', 'Открыть исходную заявку'); link.href = `/#requests/${fact.service_request_id}`;
                  card.append(link);
                }
                output.append(card);
              }
              if (result.coverage.truncated) output.append(el('p', `Показаны ${result.coverage.included_count} последних записей из ${result.coverage.available_count}.`));
              tell('История взята из доступных записей Fixit. Модель не вызывалась.');
            } catch (error) { if (alive() && error.name !== 'AbortError') tell(error.message || 'История недоступна.'); }
            finally { busy = false; if (alive()) updateOnline(); }
          });
          brief.id = 'request-ai-brief'; controls.append(brief);
        }
        tell('Проверьте текст перед применением.'); updateOnline();
      } catch (error) { if (alive() && error.name !== 'AbortError') tell('Помощник недоступен. Заполните форму обычным способом.'); }
    }
    void load();
    return () => { disposed = true; preview = null; abort.abort(); window.removeEventListener('online', updateOnline); window.removeEventListener('offline', updateOnline); };
  }
  window.FixitAIWorkspace = { mount };
})();
