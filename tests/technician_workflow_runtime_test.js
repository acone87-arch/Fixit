const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('app/static/app.js', 'utf8');

const utilitySource = source.slice(0, source.indexOf('function toast('));
const context = { window: { crypto: undefined }, localStorage: { getItem: () => null }, location: { hash: '' }, Uint8Array, Math };
vm.runInNewContext(`${utilitySource}; this.createUuidForTest = createUuid; this.navigateForTest = navigateToServiceRequest;`, context);
const fallbackUuid = context.createUuidForTest();
assert.match(fallbackUuid, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
context.navigateForTest('request-123');
assert.equal(context.location.hash, 'requests/request-123');

const mapping = source.match(/const statusAction = (\{[^;]+\});/);
const actionBlock = source.match(/const nextAction = statusAction\[request\.status\];[\s\S]*?: '';/);
assert.ok(mapping && actionBlock, 'Technician action renderer must be present');
const renderAction = new Function('status', `const statusAction = ${mapping[1]}; ${actionBlock[0].replaceAll('request.status', 'status')} return action;`);
assert.match(renderAction('assigned'), /data-status="on_the_way"[^>]*>Выехал/);
assert.match(renderAction('on_the_way'), /data-status="arrived"[^>]*>Я на объекте/);
assert.match(renderAction('arrived'), /data-status="in_progress"[^>]*>Начать работу/);
assert.match(renderAction('in_progress'), /Завершить работу/);
assert.match(renderAction('waiting_parts'), /Продолжить работу/);
assert.equal(renderAction('waiting_approval'), '');
assert.equal(renderAction('completed'), '');

assert.match(source, /const draft = \{ diagnostic: '', work: '', comment: '', usedParts: \{\}, photos: \[\] \}/);
assert.match(source, /URL\.createObjectURL\(file\)/);
assert.match(source, /URL\.revokeObjectURL\(photo\.url\)/);
assert.match(source, /completionLocalUuid \|\|= createUuid\(\)/);
assert.match(source, /\['on_the_way', 'arrived', 'in_progress'\]/);
assert.match(source, /Ожидается согласование/);
assert.match(source, /approval: \{ diagnostic: draft\.diagnostic/);
assert.match(source, /\/approval`, \{ method: 'PATCH'/);
assert.match(source, /const \[route, requestId\] = hashRoute\.split\('\/'\)/);
assert.match(source, /state\.route === 'requests' && state\.requestId/);
assert.match(source, /RequestDraftStore\.put/);
assert.match(source, /window\.addEventListener\('pagehide', persistOnBackground\)/);
assert.match(source, /navigator\.mediaDevices\?\.getUserMedia/);
assert.match(source, /facingMode: \{ ideal: 'environment' \}/);
const technicianWorkspaceStart = source.indexOf('async function openTechnicianRequestWorkspace');
const technicianWorkspaceEnd = source.indexOf('// ============================================================\n// Раздел: Fixit Pulse', technicianWorkspaceStart);
const technicianWorkspaceSource = source.slice(technicianWorkspaceStart, technicianWorkspaceEnd);
assert.doesNotMatch(technicianWorkspaceSource, /capture="environment"/);
console.log('technician workflow runtime: ok');
