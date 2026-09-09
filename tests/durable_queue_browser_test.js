// Real Chromium IndexedDB + Web Locks + service worker. No production traffic.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const { chromium } = require('playwright');
const engine = () => fs.readFileSync('app/static/offline/engine.js');
const token = (sub = 'alice', org = 'org-a', exp = Math.floor(Date.now()/1000)+3600) => `e30.${Buffer.from(JSON.stringify({sub,org,exp})).toString('base64url')}.test`;
const server = http.createServer((req,res) => {
  if(req.url.startsWith('/sw.js')) {res.statusCode=404;return res.end();}
  res.setHeader('Content-Type', req.url === '/' ? 'text/html; charset=utf-8' : 'text/javascript; charset=utf-8');
  if (req.url === '/') return res.end('<script src="/engine.js"></script>');
  if (req.url === '/worker.js') return res.end("importScripts('/engine.js');self.addEventListener('install',e=>e.waitUntil(self.skipWaiting()));self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));self.addEventListener('message',e=>e.waitUntil(FixitOffline.sync().then(()=>e.ports[0].postMessage('done'))));");
  res.end(engine());
});
let browser, origin, failures = 0;
async function fixture(run) {
  const context = await browser.newContext();
  const page = await context.newPage();
  try { await page.goto(origin); await page.evaluate(t=>FixitOffline.configure({token:t}),token()); await run(page,context); }
  finally { await context.close(); }
}
async function enqueue(page,id='repair-1',legacy=false) {
  return page.evaluate(async ({id,legacy}) => FixitOffline.enqueueRepair({local_uuid:id,service_request_id:'sr-1',description:'work'},
    [legacy ? {data_url:'data:image/png;base64,cGhvdG8=',kind:'after'} : {file:new Blob(['photo'],{type:'image/png'})}]),{id,legacy});
}
async function mock(page, {lost=false, attachmentStatus=201}={}) {
  await page.evaluate(({lost,attachmentStatus})=>{
    window.calls=[]; window.receipts=new Map();
    window.fetch=async(url,options)=>{
      calls.push({url,auth:options?.headers?.Authorization});
      if(url==='/api/v1/sync/repairs') {
        const body=JSON.parse(options.body);
        const results=body.repairs.map(r=>({local_uuid:r.local_uuid,server_id:'server-1',resolved_as:'applied'}));
        if(lost){lost=false;throw new Error('Response lost after commit');}
        return {ok:true,json:async()=>({results})};
      }
      if(String(url).startsWith('data:')) return {ok:true,blob:async()=>new Blob(['photo'])};
      if(attachmentStatus!==201) return {ok:false,status:attachmentStatus,json:async()=>({detail:'Session expired'})};
      receipts.set(options.body.get('client_id'),options.body.get('file').size);
      return {ok:true};
    };
  },{lost,attachmentStatus});
}
const tests = {
  async 'repeat enqueue cannot duplicate photos or overwrite a queued repair'(page) {
    await enqueue(page); await enqueue(page);
    assert.equal(await page.evaluate(async()=> (await FixitOffline.db.getAll('pendingAttachments')).length),1);
    await mock(page); await page.evaluate(()=>FixitOffline.sync()); await enqueue(page);
    assert.equal(await page.evaluate(async()=> (await FixitOffline.db.getAll('pendingRepairs')).length),0);
  },
  async 'failed acknowledgement transaction retains retryable repair and unlinked photo'(page) {
    await enqueue(page); await mock(page);
    await page.evaluate(async()=>{
      const original=IDBObjectStore.prototype.put;
      IDBObjectStore.prototype.put=function(...args){const r=original.apply(this,args);if(this.name==='kv' && String(args[1]).startsWith('queue-receipt:'))this.transaction.abort();return r;};
      await FixitOffline.sync(); IDBObjectStore.prototype.put=original;
    });
    assert.equal(await page.evaluate(async()=> (await FixitOffline.db.getAll('pendingRepairs')).length),1);
    assert.equal(await page.evaluate(async()=> (await FixitOffline.db.getAll('pendingAttachments'))[0].repair_id),null);
    await page.evaluate(()=>FixitOffline.sync());
    assert.equal(await page.evaluate(async()=> (await FixitOffline.queueStatus()).fullySynced),true);
  },
  async 'logout preserves data and stale tab cannot sync or enqueue for the new login'(page,context) {
    await enqueue(page); const other=await context.newPage(); await other.goto(origin);
    await other.evaluate(t=>FixitOffline.configure({token:t}),token('bob','org-b'));
    await mock(page); await page.evaluate(()=>FixitOffline.sync());
    assert.equal(await page.evaluate(()=>calls.length),0);
    await assert.rejects(()=>enqueue(page,'stale'),/Аккаунт изменился/);
    await page.evaluate(()=>FixitOffline.logout());
    assert.equal(await page.evaluate(async()=>JSON.parse(atob((await FixitOffline.db.kvGet('token')).split('.')[1])).sub),'bob');
    assert.equal(await page.evaluate(async()=> (await FixitOffline.db.getAll('pendingAttachments')).length),1);
  },
  async 'expired JWT does not send requests and same owner can recover'(page) {
    await enqueue(page); await page.evaluate(t=>FixitOffline.configure({token:t}),token('alice','org-a',1));
    await mock(page); await page.evaluate(()=>FixitOffline.sync());
    assert.equal(await page.evaluate(()=>calls.length),0);
    assert.match(await page.evaluate(async()=> (await FixitOffline.queueStatus()).errors.join(' ')),/Сессия истекла/);
    await page.evaluate(t=>FixitOffline.configure({token:t}),token()); await page.evaluate(()=>FixitOffline.sync());
    assert.equal(await page.evaluate(async()=> (await FixitOffline.queueStatus()).fullySynced),true);
  },
  async 'unowned Blob and old data_url can be exported without deletion'(page) {
    await page.evaluate(async()=>{await FixitOffline.db.put('pendingAttachments',{id:'old-blob',file:new Blob(['photo'])});await FixitOffline.db.put('pendingAttachments',{id:'old-url',data_url:'data:image/png;base64,cGhvdG8='});});
    const backup=await page.evaluate(async()=>JSON.parse(await (await FixitOffline.exportUnowned()).text()));
    assert.equal(backup.attachments.length,2); assert.ok(backup.attachments.every(p=>p.data_url));
    assert.equal(await page.evaluate(async()=> (await FixitOffline.db.getAll('pendingAttachments')).length),2);
  },
  async 'foreground online recovery works without Background Sync'(page) {
    await enqueue(page); await mock(page); await page.evaluate(()=>window.dispatchEvent(new Event('online')));
    await page.waitForFunction(async()=> (await FixitOffline.queueStatus()).fullySynced);
    assert.equal(await page.evaluate(()=>receipts.size),1);
  },
  async 'legacy data_url is uploaded with a stable client_id'(page) {
    await mock(page); await enqueue(page,'legacy',true); await page.evaluate(()=>FixitOffline.sync());
    assert.equal(await page.evaluate(()=>receipts.size),1);
    assert.equal(await page.evaluate(async()=> (await FixitOffline.queueStatus()).fullySynced),true);
  },
  async 'account switch never sends another owners repair or photos'(page) {
    await enqueue(page); await page.evaluate(t=>FixitOffline.configure({token:t}),token('bob','org-b'));
    await mock(page); await page.evaluate(()=>FixitOffline.sync());
    assert.equal(await page.evaluate(()=>calls.length),0);
    assert.equal(await page.evaluate(async()=> (await FixitOffline.db.getAll('pendingRepairs')).length),1);
  },
  async 'transaction abort keeps repair and photos together'(page) {
    const state=await page.evaluate(async()=>{
      const original=IDBObjectStore.prototype.put;
      IDBObjectStore.prototype.put=function(...args){const r=original.apply(this,args);if(this.name==='pendingAttachments')this.transaction.abort();return r;};
      let rejected=false;
      try{await FixitOffline.enqueueRepair({local_uuid:'abort'},[{file:new Blob(['photo'])}]);}catch(e){rejected=true;}
      IDBObjectStore.prototype.put=original;
      return {rejected,repairs:(await FixitOffline.db.getAll('pendingRepairs')).length,photos:(await FixitOffline.db.getAll('pendingAttachments')).length};
    });
    assert.deepEqual(state,{rejected:true,repairs:0,photos:0});
  },
  async 'quota failure is reported without a partial repair'(page) {
    const state=await page.evaluate(async()=>{
      const original=IDBObjectStore.prototype.put;
      IDBObjectStore.prototype.put=function(...args){if(this.name==='pendingAttachments')throw new DOMException('Disk full','QuotaExceededError');return original.apply(this,args);};
      let rejected=false;
      try{await FixitOffline.enqueueRepair({local_uuid:'quota'},[{file:new Blob(['photo'])}]);}catch(e){rejected=true;}
      IDBObjectStore.prototype.put=original;
      return {rejected,repairs:(await FixitOffline.db.getAll('pendingRepairs')).length};
    });
    assert.deepEqual(state,{rejected:true,repairs:0});
  },
  async 'lost response restart and retry retain the original photo id'(page) {
    await enqueue(page); const id=await page.evaluate(async()=> (await FixitOffline.db.getAll('pendingAttachments'))[0].id);
    await mock(page,{lost:true});await page.evaluate(()=>FixitOffline.sync());
    assert.equal(await page.evaluate(async()=> (await FixitOffline.db.getAll('pendingRepairs')).length),1);
    await page.reload(); await mock(page); await page.evaluate(()=>FixitOffline.sync());
    assert.deepEqual(await page.evaluate(()=>[...receipts.keys()]),[id]);
  },
  async 'unowned historical entries are quarantined and preserved'(page) {
    await page.evaluate(()=>FixitOffline.db.put('pendingRepairs',{local_uuid:'old',description:'old work'}));
    await mock(page);await page.evaluate(()=>FixitOffline.sync());
    assert.equal(await page.evaluate(()=>calls.length),0);
    assert.equal(await page.evaluate(async()=> (await FixitOffline.db.getAll('pendingRepairs')).length),1);
  },
  async 'expired session exposes a durable error and relogin recovers'(page) {
    await enqueue(page);await mock(page,{attachmentStatus:401});await page.evaluate(()=>FixitOffline.sync());
    assert.match(await page.evaluate(async()=> (await FixitOffline.queueStatus()).errors.join(' ')),/401|сесси/i);
    await page.reload();await page.evaluate(t=>FixitOffline.configure({token:t}),token());await mock(page);await page.evaluate(()=>FixitOffline.sync());
    assert.equal(await page.evaluate(async()=> (await FixitOffline.queueStatus()).fullySynced),true);
  },
  async 'two tabs and a real worker share one sync lock'(page,context) {
    await enqueue(page);const other=await context.newPage();await other.goto(origin);
    // Browser-context routes also intercept service-worker initiated fetches.
    let repairCalls=0,photoCalls=0;
    await context.route('**/api/**',async route=>{
      const req=route.request();
      if(req.url().endsWith('/sync/repairs')) {
        repairCalls++;await new Promise(resolve=>setTimeout(resolve,80));
        await route.fulfill({json:{results:[{local_uuid:'repair-1',server_id:'server-1',resolved_as:'applied'}]}});
      } else {photoCalls++;await route.fulfill({status:201,body:'{}'});}
    });
    await page.evaluate(async()=>{await navigator.serviceWorker.register('/worker.js');await navigator.serviceWorker.ready;});
    await page.reload();
    await Promise.all([page.evaluate(()=>FixitOffline.sync()),other.evaluate(()=>FixitOffline.sync()),page.evaluate(()=>new Promise(resolve=>{const c=new MessageChannel();c.port1.onmessage=()=>resolve();navigator.serviceWorker.controller.postMessage('sync',[c.port2]);}))]);
    assert.equal(repairCalls,1);assert.equal(photoCalls,1);
  },
};
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));origin=`http://127.0.0.1:${server.address().port}`;
  browser=await chromium.launch({executablePath:process.env.FIXIT_CHROMIUM_PATH || undefined});
  for(const [name,test] of Object.entries(tests)) {try{await fixture(test);console.log('PASS',name);}catch(e){failures++;console.error('FAIL',name,e);}}
})().catch(e=>{failures++;console.error(e);}).finally(async()=>{await browser?.close();server.close();process.exitCode=failures?1:0;});
