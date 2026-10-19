/* Read-only pilot settings. Reports remain in memory and follow the login scope. */
(() => {
  'use strict';
  function mount(content, options) {
    const abort = new AbortController(), session = options.getSession();
    let disposed = false, loading = false;
    const el = (tag, text, className) => {
      const node = document.createElement(tag);
      if (text !== undefined) node.textContent = text;
      if (className) node.className = className;
      return node;
    };
    const root = el('section', undefined, 'ai-pilot-screen'); root.id = 'ai-pilot-screen';
    content.replaceChildren(root);
    const back = el('a', '← Профиль и настройки', 'ai-pilot-back'); back.href = '#profile'; root.append(back);
    const header = el('header', undefined, 'page-header');
    const heading = el('div'); heading.append(el('span', 'НАСТРОЙКИ / AI', 'settings-kicker'), el('h1', 'Пилот YandexGPT'));
    header.append(heading); root.append(header);
    if (!['owner', 'admin', 'dispatcher'].includes(options.role)) {
      root.append(el('p', 'Показатели пилота доступны администратору и диспетчеру.', 'ai-pilot-notice'));
      return () => { disposed = true; abort.abort(); };
    }
    const refresh = el('button', 'Обновить', 'btn btn-secondary'); refresh.type = 'button'; header.append(refresh);
    const status = el('p', 'Загружаем показатели…', 'ai-pilot-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const body = el('div', undefined, 'ai-pilot-body'); root.append(status, body);
    const alive = () => !disposed && root.isConnected && options.getSession() === session;
    const number = value => new Intl.NumberFormat('ru-RU').format(value);
    const money = value => new Intl.NumberFormat('ru-RU', {minimumFractionDigits: 2, maximumFractionDigits: 4}).format(Number(value)) + ' ₽';
    const latency = value => value === null ? 'Пока нет данных' : number(Math.round(value / 100) / 10) + ' с';
    const panel = title => { const node = el('section', undefined, 'settings-card'); node.append(el('h2', title)); return node; };
    const line = (list, label, value) => { const row = el('div'); row.append(el('dt', label), el('dd', value)); list.append(row); };
    const stat = (label, value, detail) => {
      const card = el('article', undefined, 'ai-pilot-stat');
      card.append(el('span', label), el('strong', value)); if (detail) card.append(el('small', detail)); return card;
    };
    function render(data) {
      const m = data.metrics, config = data.configuration, caps = data.capabilities;
      const period = new Date(m.period_start).toLocaleDateString('ru-RU', {month: 'long', year: 'numeric', timeZone: data.timezone});
      body.replaceChildren();
      const scope = el('section', undefined, 'ai-pilot-scope');
      scope.append(el('h2', data.organization.name), el('p', `Показатели этой организации за ${period}. Часовой пояс — Екатеринбург.`));
      body.append(scope);
      const availability = panel('Настройки помощника');
      availability.id = 'ai-pilot-configuration';
      const state = !config.pilot_member ? 'Организация пока не включена в пилот' : caps.enabled ? 'Пилот включён для организации' : 'Помощник выключен';
      availability.append(el('p', state, 'ai-pilot-notice'));
      const settings = el('dl', undefined, 'ai-pilot-facts');
      line(settings, 'Модель', config.model);
      if (config.client_scope_restricted) line(settings, 'Клиенты пилота', config.pilot_clients.join(', ') || 'Нет клиентов этой организации');
      line(settings, 'Оформление результата', caps.repair_draft ? 'Доступно' : 'Выключено');
      line(settings, 'История оборудования', caps.equipment_brief ? 'Доступна' : 'Выключена');
      availability.append(settings);
      const budget = panel('Общий бюджет пилота'); budget.id = 'ai-pilot-budget';
      const limits = el('dl', undefined, 'ai-pilot-facts');
      line(limits, 'Лимит на месяц', money(config.monthly_limit_rub));
      line(limits, 'Лимит на день', money(config.daily_limit_rub));
      budget.append(el('p', 'Один лимит на всех клиентов и организации пилота.'), limits);
      const grid = el('div', undefined, 'ai-pilot-grid'); grid.append(availability, budget); body.append(grid);
      if (!m.calls) body.append(el('p', 'Запусков оформления результата в этом месяце пока нет. Показатели появятся после первых черновиков.', 'ai-pilot-notice'));
      const ratings = m.helpful + m.not_helpful;
      const stats = el('div', undefined, 'ai-pilot-stats');
      stats.append(stat('Запросы черновика', number(m.calls), 'Все попытки, включая ошибки'),
        stat('Применены в форму', number(m.applied), 'Отметки интерфейса'),
        stat('Сохранённые ремонты', number(m.saved_repairs), 'Подтверждены сервером'),
        stat('Полезные черновики', ratings ? number(Math.round(m.helpful / ratings * 100)) + '%' : '—',
          ratings ? `${number(m.helpful)} из ${number(ratings)} оценок` : 'Оценок пока нет'));
      body.append(stats);
      const outcomes = panel('Результаты оформления');
      const results = el('dl', undefined, 'ai-pilot-facts');
      [['Готовые черновики', m.statuses.succeeded], ['В процессе', m.statuses.pending], ['Ошибки', m.statuses.failed],
        ['Исход запроса не уточнён', m.statuses.unknown], ['Отказы от черновика', m.rejected], ['Полезно', m.helpful], ['Не полезно', m.not_helpful]]
        .forEach(([label, value]) => line(results, label, number(value)));
      outcomes.append(results);
      const performance = panel('Время ответа'); const timings = el('dl', undefined, 'ai-pilot-facts');
      line(timings, 'Медиана (p50)', latency(m.latency_ms.p50)); line(timings, 'p95', latency(m.latency_ms.p95));
      line(timings, 'Измеренные попытки', number(m.latency_ms.samples));
      performance.append(timings, el('p', 'p95 — время, в которое укладываются 95% измеренных попыток, включая ошибки.'));
      const details = el('div', undefined, 'ai-pilot-grid'); details.append(outcomes, performance); body.append(details);
      const cost = panel('Оценка стоимости этой организации'); cost.id = 'ai-pilot-cost';
      const costs = el('dl', undefined, 'ai-pilot-facts');
      line(costs, 'Расчёт по известному объёму', money(m.estimated_rub));
      line(costs, 'Резерв до уточнения', money(m.unresolved_reserve_rub));
      line(costs, 'Входные / выходные токены', `${number(m.input_tokens)} / ${number(m.output_tokens)}`);
      cost.append(costs, el('p', 'Это расчёт Fixit и внутренний резерв. Баланс и подтверждённые списания Yandex Cloud здесь не показаны. Суммы относятся только к этой организации и не включают предварительные проверки и другие сервисы. Общий остаток бюджета по ним не определяется.'));
      body.append(cost);
      const evaluation = panel('Как оценивать пилот');
      evaluation.append(el('p', 'Техник оценивает черновик после просмотра. Диспетчер проверяет смысл и полноту на примерах. Применение в форме и сохранение ремонта считаются отдельно; сохранённый текст мог быть отредактирован.'),
        el('p', 'Отчёт охватывает оформление результата. Просмотры истории и экономия времени пока не измеряются. Качество и экономию времени нужно сравнить с исходными замерами.'));
      body.append(evaluation);
      status.textContent = 'Обновлено ' + new Date(data.generated_at).toLocaleString('ru-RU', {timeZone: data.timezone}) + ' · Екатеринбург';
    }
    async function load() {
      if (loading || !alive()) return;
      loading = true; refresh.disabled = true;
      // Clear previous values before a refresh: a failed request must not look current.
      body.replaceChildren(); status.textContent = 'Загружаем показатели…';
      try {
        const data = await options.api('/ai/pilot', {signal: abort.signal});
        if (alive()) render(data);
      } catch (error) {
        if (alive() && error.name !== 'AbortError') status.textContent = 'Не удалось загрузить показатели. Проверьте подключение и нажмите «Обновить».';
      } finally { loading = false; if (alive()) refresh.disabled = false; }
    }
    refresh.addEventListener('click', load); void load();
    return () => { disposed = true; abort.abort(); root.replaceChildren(); };
  }
  window.FixitAIPilot = {mount};
})();
