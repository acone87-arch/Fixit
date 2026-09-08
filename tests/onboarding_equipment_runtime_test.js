// Выполняет реальные функции UI с тестовым DOM/API; не browser E2E.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app/static/app.js', 'utf8');
function functionSource(name) {
  const start = source.search(new RegExp('(?:async )?function ' + name + '\\('));
  assert.ok(start >= 0, name);
  const rest = source.slice(start);
  const next = rest.slice(1).search(/\n(?:async )?function /);
  return next < 0 ? rest : rest.slice(0, next + 1);
}
(async () => {
  const handlers = {}, calls = [], messages = [];
  const nodes = new Map();
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {value: '', classList: {toggle() {}},
      addEventListener(event, fn) { handlers[id + ':' + event] = fn; }});
    return nodes.get(id);
  };
  let body = '';
  const state = {me: {role: 'client_site_user'}, equipmentTypes: [],
    sites: [{id: 'own-site', client_id: 'client', name: 'Объект', is_active: true}],
    clients: [{id: 'client', name: 'Клиент'}]};
  const context = vm.createContext({state, console,
    api: async (path, options) => {
      calls.push([path, options]);
      if (path === '/equipment-types') return [{id: 7, name: 'Поломойка'}];
      if (path === '/client-portal/equipment') return [];
      if (path === '/equipment') return {id: 'created-equipment'};
      throw new Error('Неожиданный API: ' + path);
    },
    ensureCustomers: async () => {},
    openModal(title, html) { body = html; node('#f-type').value = state.equipmentTypes[0]?.id || ''; return {querySelector: node}; },
    closeModal() {}, toast: text => messages.push(text),
    esc: String, readableClientName: name => name,
    openEquipmentPassport: async id => calls.push(['passport', id]),
    clientBadge: () => '', apiBlob: async () => {throw new Error('Фото не ожидалось');},
  });
  vm.runInContext(['ensureEquipmentTypes', 'renderClientEquipment', 'openCreateEquipmentModal'].map(functionSource).join('\n'), context);
  const content = {querySelector: node, querySelectorAll: () => [], innerHTML: ''};
  await context.renderClientEquipment(content);
  await handlers['#client-empty-add-equipment:click']();
  assert.ok(calls.some(([p]) => p === '/equipment-types'), 'Свежий менеджер получает типы');
  assert.ok(body.includes('Поломойка'), 'Тип присутствует в форме');
  assert.ok(!body.includes('+ Новый тип'), 'Менеджеру не предлагается запрещённое действие');
  node('#f-site').value = 'own-site'; node('#f-serial').value = 'PILOT-001';
  await handlers['#modal-save:click']();
  const payload = JSON.parse(calls.find(([p]) => p === '/equipment')[1].body);
  assert.equal(payload.equipment_type_id, 7);
  assert.equal(payload.site_id, 'own-site');
  assert.ok(calls.some(([p,id]) => p === 'passport' && id === 'created-equipment'));
  // Сбой справочника не открывает неполную форму.
  state.equipmentTypes = []; body = '';
  context.api = async () => { throw new Error('Нет сети'); };
  await context.openCreateEquipmentModal();
  assert.equal(body, '');
  assert.match(messages.at(-1), /Не удалось загрузить типы/);
  context.api = async () => [];
  await context.openCreateEquipmentModal();
  assert.equal(body, '');
  assert.match(messages.at(-1), /Сервисная компания ещё не добавила типы/);
  state.me.role = 'owner';
  await context.openCreateEquipmentModal();
  assert.ok(body.includes('+ Новый тип'), 'Существующее staff-действие сохранено');

  // Выполняем install handler SW: кеш должен включать фактический JS HTML.
  const events = {}; let cached = [];
  const worker = vm.createContext({importScripts() {}, self: {
    addEventListener(name, fn) { events[name] = fn; }, skipWaiting: async () => {}},
    caches: {open: async () => ({addAll: async files => { cached = files; }})}});
  vm.runInContext(fs.readFileSync('app/static/sw.js', 'utf8'), worker);
  let installation;
  events.install({waitUntil(promise) { installation = promise; }});
  await installation;
  const html = fs.readFileSync('app/static/index.html', 'utf8');
  const scriptUrl = html.match(/src="([^"\n]*\/app\.js\?[^"\n]+)"/)[1];
  assert.ok(cached.includes(scriptUrl), 'SW устанавливает ту же версию JS, что HTML');
  console.log('Onboarding UI/SW runtime: 5 сценариев пройдено');
})().catch(error => { console.error(error); process.exitCode = 1; });
