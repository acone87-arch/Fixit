// Real Chromium DOM with synthetic queue data; no production users or API writes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const vm = require('node:vm');
const { chromium } = require('playwright');
const source = fs.readFileSync('app/static/app.js', 'utf8');
function extract(name) {
  const start = source.search(new RegExp('(?:async )?function ' + name + '\\('));
  assert.ok(start >= 0, name);
  const rest = source.slice(start);
  const next = rest.slice(1).search(/\n(?:(?:async )?function |const )/);
  return next < 0 ? rest : rest.slice(0, next + 1);
}
const helpers = ['requestQueueRank', 'requestQueueDate', 'sortRequestQueue'].map(extract).join('\n');
const ctx = vm.createContext({}); vm.runInContext(helpers, ctx);
const requests = [
  { id:'done-old', number:1, status:'completed', created_at:'2026-10-01', completed_at:'2026-10-03', client_id:'a', site_id:'a1', site_name:'Склад', client_legal_name:'АО Альфа' },
  { id:'parts', number:2, status:'waiting_parts', created_at:'2026-10-04', client_id:'a', site_id:'a1', site_name:'Склад', client_legal_name:'АО Альфа' },
  { id:'done-new', number:3, status:'closed', created_at:'2026-09-01', completed_at:'2026-10-06', client_id:'b', site_id:'b1', site_name:'Склад', client_legal_name:'ООО Бета' },
  { id:'new', number:4, status:'new', created_at:'2026-10-05', client_id:'b', site_id:'b1', site_name:'Склад', client_legal_name:'ООО Бета' },
  { id:'assigned-old', number:5, status:'assigned', created_at:'2026-10-01', client_id:'a', site_id:'a2', site_name:'Ангар', client_legal_name:'АО Альфа' },
  { id:'assigned-new', number:6, status:'assigned', created_at:'2026-10-02', client_id:'a', site_id:'a2', site_name:'Ангар', client_legal_name:'АО Альфа' },
  { id:'cancelled', number:7, status:'cancelled', created_at:'2026-10-02', client_id:'b', site_id:'b1', site_name:'Склад', client_legal_name:'ООО Бета' },
].map(item => ({ ...item, title:'Проверка привода', equipment_name:'Поломоечная машина', serial_number:'TEST-01', assigned_technician_name:'Тестовый техник' }));
const ids = (order) => Array.from(ctx.sortRequestQueue(requests, order), item => item.id);
assert.deepEqual(ids('status'), ['assigned-new','assigned-old','parts','new','done-new','done-old','cancelled']);
assert.deepEqual(ids('newest'), ['done-new','new','parts','done-old','cancelled','assigned-new','assigned-old']);
assert.deepEqual(ids('oldest'), ['assigned-old','cancelled','assigned-new','done-old','parts','new','done-new']);
assert.deepEqual(ids('client').slice(0,4), ['assigned-new','assigned-old','parts','done-old']);
assert.deepEqual(ids('site').slice(0,2), ['assigned-new','assigned-old']);
assert.equal(requests[0].id, 'done-old', 'Sorting must not mutate the API result');
assert.doesNotThrow(() => ctx.sortRequestQueue([{id:'missing',number:8,status:'in_progress'}]));

const script = `const state = {me:{id:'synthetic-user',organization_id:'test-org'}};
const api = async () => ${JSON.stringify(requests)};
const navigateToServiceRequest = id => { window.openedRequest = id; };
const openClientRequestForm = () => {};
${['esc','fmtDate','requestQueueRank','requestQueueDate','sortRequestQueue','requestQueueControlsHtml','bindRequestQueueControls','renderServiceRequests'].map(extract).join('\n')}
${source.slice(source.indexOf('const CLIENT_STATUS ='), source.indexOf('async function renderClientPulse'))}
${extract('renderClientRequests')}`;
const server = http.createServer((req,res) => {
  res.setHeader('Content-Type', req.url === '/styles.css' ? 'text/css' : 'text/html; charset=utf-8');
  if (req.url === '/styles.css') return res.end(fs.readFileSync('app/static/styles.css'));
  res.end('<link rel="stylesheet" href="/styles.css"><main id="content" style="padding:20px"></main>');
});
(async () => {
  let browser;
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    browser = await chromium.launch();
    const page = await browser.newPage();
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    const render = async (client = false) => {
      await page.addScriptTag({content:script});
      await page.evaluate(client => (client ? renderClientRequests : renderServiceRequests)(document.querySelector('#content')), client);
    };
    await render();
    const visibleIds = () => page.locator('tbody .request-row').evaluateAll(rows => rows.map(row => row.dataset.id));
    assert.deepEqual(await visibleIds(), ids('status'));
    await page.locator('#request-order').selectOption('client');
    assert.deepEqual(await visibleIds(), ids('client'));
    await page.locator('#request-site').selectOption('a1');
    assert.deepEqual(await visibleIds(), ['parts','done-old']);
    await page.locator('#request-client').selectOption('b');
    assert.equal(await page.locator('#request-site').inputValue(), '', 'Changing client clears an incompatible site');
    assert.deepEqual(await page.locator('#request-site option').evaluateAll(options => options.map(option => option.value)), ['', 'b1']);
    assert.deepEqual(await visibleIds(), ['new','done-new','cancelled']);
    await page.locator('#request-reset').click();
    assert.deepEqual(await visibleIds(), ids('status'));
    await page.locator('#request-order').selectOption('oldest');
    await page.reload(); await render();
    assert.equal(await page.locator('#request-order').inputValue(), 'oldest', 'Order survives reload');
    assert.deepEqual(await visibleIds(), ids('oldest'));
    await page.locator('#request-reset').click();
    await page.locator('tbody .request-row').first().click();
    assert.equal(await page.evaluate(() => window.openedRequest), 'assigned-new');
    for (const [width,theme,text] of [[1280,'dark','standard'],[390,'light','xlarge'],[320,'dark','xlarge']]) {
      await page.setViewportSize({width,height:900});
      await page.evaluate(({theme,text}) => {document.documentElement.dataset.theme=theme;document.documentElement.dataset.textSize=text;}, {theme,text});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), true, `No overflow at ${width}`);
      assert.ok(await page.locator('#request-order').evaluate(el => el.getBoundingClientRect().height >= 44));
      if (process.env.FIXIT_QUEUE_SCREENSHOTS && width !== 320) {
        fs.mkdirSync('test-results', {recursive:true});
        await page.screenshot({path:`test-results/request-queue-${width}.png`,fullPage:true});
      }
    }
    // The client status tabs compose with the same site/order controls.
    await page.reload(); await render(true);
    assert.deepEqual(await page.locator('[data-client-request]').evaluateAll(rows => rows.map(row => row.dataset.clientRequest)), ids('status'));
    await page.locator('[data-client-filter="active"]').click();
    await page.locator('#request-client').selectOption('a');
    assert.equal(await page.locator('[data-client-request]').count(), 3);
    await page.locator('[data-client-filter="completed"]').click();
    assert.equal(await page.locator('[data-client-request]').count(), 1);
    await page.locator('#request-site').selectOption('a2');
    assert.equal(await page.locator('[data-client-request]').count(), 0);
    assert.match(await page.locator('#request-queue-summary').textContent(), /Показано 0 из 7/);
    await page.locator('#request-client').selectOption('b');
    assert.equal(await page.locator('[data-client-request]').count(), 1, 'Closed requests belong in the completed client tab');
    console.log('Request queue: sorting, scoped filters, reload, navigation, client tabs and responsive Chromium checks passed');
  } finally { await browser?.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode=1; });
