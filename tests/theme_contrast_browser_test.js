// Actual Pulse shell/renderers and styles, synthetic read-only API fixtures.
// No production traffic; contrast is measured from computed foreground/backdrop colors.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium } = require('playwright');
const client = {id:'client',name:'Тестовый клиент',legal_name:'ООО Тест',tax_id:'0000000000',is_active:true,site_count:1,equipment_count:1,contact_name:'Контакт',contact_phone:'0000000000',contact_email:'test@example.invalid'};
const site = {id:'site',client_id:client.id,client_name:client.name,name:'Тестовый объект',address:'Адрес объекта',is_active:true,equipment_count:1};
const equipment = {id:'equipment',name:'Поломоечная машина',equipment_type_id:1,site_id:site.id,site_name:site.name,client_name:client.name,status:'working',serial_number:'TEST-001',manufacturer:'TestCo',model:'Test-1',inventory_number:1,version:1,location_details:'Склад',created_at:'2026-10-01',history:[],documents:[]};
const request = {id:'request',number:1,equipment_id:equipment.id,title:'Не собирает воду',description:'Проверить привод',status:'waiting_approval',approval_target:'internal',priority:'urgent',client_id:client.id,site_id:site.id,client_name:client.name,site_name:site.name,equipment_name:equipment.name,serial_number:equipment.serial_number,assigned_technician_name:'Тестовый техник',assigned_technician_id:'technician',created_at:'2026-10-01',equipment_status:'needs_repair',equipment_version:1,site_address:site.address,history:[{type:'request.waiting_approval',message:'Нужны запчасти',created_at:'2026-10-01',details:{approval:{diagnostic:'Износ привода',work:'Замена узла',comment:'Нужен комплект',parts:[{name:'Комплект',quantity:1}],photo_count:0}}}],parts_used:[],attachments:[],request_attachments:[]};
const users = [{id:'owner',role:'owner',full_name:'Владелец',email:'owner@example.invalid',is_active:true},{id:'technician',role:'technician',full_name:'Тестовый техник',email:'tech@example.invalid',is_active:true},{id:'client-user',role:'client_site_user',full_name:'Менеджер',email:'client@example.invalid',is_active:true}];
const warehouse = {id:'warehouse',name:'Центральный склад',type:'central',owner_user_id:'technician'};
const fixtures = {
  '/clients':[client], '/sites':[site], '/equipment':[equipment], '/equipment-types':[{id:1,name:equipment.name}],
  '/service-requests':[request], '/service-requests/request':request, '/users':users, '/warehouses':[warehouse],
  '/warehouses/warehouse/stock':[{part_id:'part',name:'Комплект',article:'TEST',quantity:2,is_critical:true}],
  '/warehouses/mine/stock':[{part_id:'part',name:'Комплект',article:'TEST',quantity:2}], '/parts':[{id:'part',name:'Комплект',article:'TEST'}],
  '/equipment/equipment/passport':{...equipment,active_request:request,history:[{status:'completed',title:'Замена узла',problem:'Не работал привод',work_summary:'Заменён узел',service_request_id:'request',service_request_number:1,occurred_at:'2026-10-01',technician_name:'Тестовый техник',parts:[{part_name:'Комплект',quantity:1}]}],documents:[{title:'Сервисный акт',kind:'service_act',repair_id:'repair',created_at:'2026-10-01'}]},
  '/clients/client/summary':{active_requests:1,in_repair:1,waiting_approval:1,completed_last_30_days:1},
  '/clients/client/technicians':[{...users[1],assigned:true}],
  '/client-portal/access':[{id:'access',user_id:'client-user',full_name:'Менеджер',email:'client@example.invalid',role:'client_site_user',client_id:'client',site_id:'site',site_name:site.name,is_active:true}],
  '/client-portal/clients/client/invites':[{id:'invite',status:'pending',role:'client_site_user',site_name:site.name,invited_email:'new@example.invalid',expires_at:'2099-10-01',created_at:'2026-10-01'}],
  '/client-portal/equipment':[equipment], '/client-portal/requests':[request], '/client-portal/requests/request':request,
  '/client-portal/documents':[{number:1,equipment_name:equipment.name,site_name:site.name,repair_id:'repair',closed_at:'2026-10-01'}],
  '/client-portal/dashboard':{client_name:client.name,equipment_total:1,working:1,needs_repair:0,waiting_approval:1,active_requests:1,approval_requests:1},
  '/equipment-inventory/batches':[],
};
const server = http.createServer((req,res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  if(pathname==='/api/public/equipment/synthetic' && req.method==='GET') {res.setHeader('Content-Type','application/json');return res.end(JSON.stringify(equipment));}
  if (pathname.startsWith('/api/')) {res.writeHead(500);return res.end('Unexpected real API call');}
  const root=pathname.startsWith('/guest/')?'app/static-guest':'app/static';
  const file = pathname === '/' || pathname==='/guest/' ? 'index.html' : pathname.replace(/^\/(static|guest)\//,'');
  const target = path.resolve(root,file);
  if (!target.startsWith(path.resolve(root) + path.sep) || !fs.existsSync(target)) {res.writeHead(404);return res.end();}
  res.setHeader('Content-Type', file.endsWith('.css')?'text/css':file.endsWith('.js')?'application/javascript':file.endsWith('.svg')?'image/svg+xml':file.endsWith('.png')?'image/png':'text/html; charset=utf-8');
  res.end(fs.readFileSync(target));
});

async function audit(page) {
  return page.evaluate(() => {
    const rgb = value => (value.match(/[\d.]+/g)||[]).map(Number);
    const blend = (fg,bg) => fg.slice(0,3).map((v,i) => v*(fg[3]??1)+bg[i]*(1-(fg[3]??1)));
    const luminance = c => c.map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0);
    const backdrop = element => {
      const ancestors=[]; for(let p=element;p;p=p.parentElement) ancestors.unshift(p);
      let color=document.documentElement.dataset.theme==='light'?[243,247,252]:[11,18,32];
      for(const p of ancestors) {
        const style=getComputedStyle(p); color=blend(rgb(style.backgroundColor),color);
        // Gradients are sampled at both ends separately in visual QA; CSS fallback
        // backgrounds still detect light text accidentally used on light surfaces.
        if(style.backgroundImage.startsWith('linear-gradient')||style.backgroundImage.startsWith('radial-gradient')) {
          const first=style.backgroundImage.match(/rgba?\([^)]+\)/); if(first) color=blend(rgb(first[0]),color);
        }
      }
      return color;
    };
    const failures=[];
    for(const el of document.querySelectorAll('body *')) {
      const style=getComputedStyle(el),rect=el.getBoundingClientRect();
      if(!rect.width||!rect.height||style.visibility==='hidden'||el.closest('.hidden')||el.disabled||['SCRIPT','STYLE','IMG','VIDEO','OBJECT'].includes(el.tagName)) continue;
      const ownText=[...el.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join(' ').trim();
      const text=el.matches('input,select,textarea')?(el.value||el.placeholder||''):ownText;
      if(!text) continue;
      const bg=backdrop(el), fg=blend(rgb(style.color),bg);
      const l1=luminance(fg),l2=luminance(bg),ratio=(Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05);
      const large=parseFloat(style.fontSize)>=24||(parseFloat(style.fontSize)>=18.66&&parseInt(style.fontWeight)>=700);
      const min=large?3:4.5;
      if(ratio+.03<min) failures.push({tag:el.tagName,id:el.id,cls:el.className,text:text.slice(0,65),ratio:+ratio.toFixed(2),fg:style.color,bg:bg.map(Math.round)});
      if(el.matches('input,textarea')&&el.placeholder) {
        const placeholder=getComputedStyle(el,'::placeholder');
        const pl=blend(rgb(placeholder.color).map((v,i)=>i===3?v*Number(placeholder.opacity):v),bg);
        const l=luminance(pl),pr=(Math.max(l,l2)+.05)/(Math.min(l,l2)+.05);
        if(pr+.03<4.5) failures.push({tag:'placeholder',id:el.id,text:el.placeholder,ratio:+pr.toFixed(2)});
      }
    }
    // Native option popups have no DOM box when closed. Check their explicit styles.
    for(const select of document.querySelectorAll('select')) {
      if(!select.getBoundingClientRect().width) continue;
      for(const option of select.options) {
        const s=getComputedStyle(option),bg=rgb(s.backgroundColor),fg=rgb(s.color);
        const l1=luminance(fg),l2=luminance(bg);
        const ratio=(Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05);
        if((bg[3]??1)!==1||ratio<4.5) failures.push({tag:'option',id:select.id,text:option.text,ratio:+ratio.toFixed(2),fg:s.color,bg:s.backgroundColor});
      }
    }
    return failures;
  });
}

(async()=>{
  let browser; const report=[];
  try {
    await new Promise(r=>server.listen(0,'127.0.0.1',r));
    browser=await chromium.launch();
    const page=await browser.newPage();
    await page.route('https://fonts.googleapis.com/**',route=>route.abort());
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.waitForFunction(()=>typeof router==='function');
    await page.evaluate(fixtures=>{
      window.auditFixtures=fixtures;
      api=async (url,options={})=> {
        if(options.method && options.method!=='GET') throw Error('Audit forbids writes');
        const key=url.split('?')[0]; if(!(key in auditFixtures)) throw Error('Missing fixture: '+url);
        return structuredClone(auditFixtures[key]);
      };
      apiBlob=async()=>new Blob(['test'],{type:'application/pdf'});
      state.token='synthetic';
    },fixtures);
    let screens=0;
    const inspect=async(label,action)=>{
      screens++;
      await action(); await page.evaluate(()=>new Promise(requestAnimationFrame));
      const failures=await audit(page); if(failures.length) report.push({label,failures});
    };
    for(const theme of ['light','dark']) for(const width of [1280,390,320]) {
      await page.setViewportSize({width,height:900});
      await page.evaluate(({theme,width})=>{applyAppearance(theme,width===320?'xlarge':'standard'); document.querySelector('#app').classList.remove('hidden'); document.querySelector('#login-screen').classList.add('hidden');},{theme,width});
      for(const role of ['owner','technician','client_site_user']) {
        await page.evaluate(role=>{state.me={...auditFixtures['/users'].find(u=>u.role===role),organization_id:'test-org'};auditFixtures['/service-requests/request'].status='waiting_approval';auditFixtures['/client-portal/requests/request'].approval_target='client';renderNav();},role);
        const routes=role==='owner'?['pulse','requests','equipment','warehouse','users','profile','clients','clients/client','clients/client/sites','clients/client/users','requests/request']:role==='technician'?['pulse','requests','equipment','warehouse','profile','requests/request']:['pulse','requests','equipment','documents','profile','requests/request'];
        for(const route of routes) await inspect(`${theme}/${width}/${role}/${route}`,async()=>{
          await page.evaluate(route=>{history.replaceState(null,'','#'+route); return router();},route);
          assert.equal(await page.locator('#content').innerText().then(t=>/Не удалось загрузить раздел/.test(t)),false,route);
          if(route==='requests'&&width===320) {
            const overflow=await page.evaluate(()=>[...document.querySelectorAll('.mobile-nav-item,.mobile-info-card,.client-request-card')].filter(el=>{const r=el.getBoundingClientRect();return r.width&&(r.right>innerWidth+1||r.left<0||el.scrollWidth>el.clientWidth+1)}).map(el=>el.className));
            assert.deepEqual(overflow,[],`${theme}/${role}: large text overflow`);
          }
          if(role==='owner'&&route==='requests'&&process.env.FIXIT_CONTRAST_SCREENSHOTS) {
            fs.mkdirSync('test-results',{recursive:true});
            await page.screenshot({path:`test-results/readable-requests-${theme}-${width}.png`,fullPage:true});
          }
        });
        if(role==='technician') for(const status of ['assigned','in_progress','waiting_parts','completed']) {
          await inspect(`${theme}/${width}/technician/request-${status}`,async()=>{
            await page.evaluate(status=>{auditFixtures['/service-requests/request'].status=status;history.replaceState(null,'','#requests/request');return router();},status);
          });
        }
      }
      await page.evaluate(()=>{state.me={...auditFixtures['/users'][0],organization_id:'test-org'};state.clients=auditFixtures['/clients'];state.sites=auditFixtures['/sites'];});
      const dialogs={
        'onboarding':()=>openPwaOnboarding(), 'create-equipment':()=>openCreateEquipmentModal(),
        'edit-client':()=>openClientEditModal(auditFixtures['/clients'][0]), 'create-site':()=>openCreateSiteModal('client'),
        'invite':()=>openClientInviteModal(auditFixtures['/clients'][0],'site-manager'),
        'client-access':()=>openClientUserEditor(auditFixtures['/clients'][0]),
        'create-user':()=>openCreateUserModal(), 'part':()=>openCreatePartModal(),
        'stock-move':()=>openStockMoveModal('transfer',auditFixtures['/warehouses']),
        'inventory':()=>openInventoryBatches('site'), 'passport':()=>openEquipmentPassport('equipment'),
        'inventory-editor':()=>openEquipmentDetailsEditor(auditFixtures['/equipment/equipment/passport']),
        'qr-scanner':()=>openQrQuickAction(),
      };
      // Function bodies execute inside the real page, not Node.
      for(const [name,fn] of Object.entries(dialogs)) await inspect(`${theme}/${width}/dialog/${name}`,async()=>{
        await page.evaluate(()=>closeModal()); await page.evaluate(fn);
        assert.equal(await page.locator('.modal').count(),1,name);
      });
      await page.evaluate(()=>{closeModal();return openEquipmentPassport('equipment');});
      for(const tab of ['history','documents']) await inspect(`${theme}/${width}/passport/${tab}`,()=>page.locator(`[data-passport-tab="${tab}"]`).click());
      await inspect(`${theme}/${width}/passport/menu`,()=>page.locator('#passport-more').click());
      await page.evaluate(()=>closeModal());
      await inspect(`${theme}/${width}/approval-dialog`,()=>page.evaluate(()=>openApprovalDialog('rejected',()=>{})));
      await page.locator('[data-approval-cancel]').click();
      await inspect(`${theme}/${width}/hover-secondary`,()=>page.locator('.btn-secondary').filter({visible:true}).first().hover());
      await inspect(`${theme}/${width}/toasts`,()=>page.evaluate(()=>{toast('Ошибка подключения','error');toast('Сохранено','success');}));
      await page.evaluate(()=>document.querySelector('#toast-root').innerHTML='');
      await inspect(`${theme}/${width}/equipment/site-menu`,async()=>{
        await page.evaluate(()=>{history.replaceState(null,'','#equipment');return router();});
        if(width<768) await page.locator('.site-picker-trigger').click();
      });
      await page.evaluate(()=>{document.querySelector('#app').classList.add('hidden');document.querySelector('#login-screen').classList.remove('hidden');});
      await inspect(`${theme}/${width}/login`,async()=>{});
      await inspect(`${theme}/${width}/forgot-password`,()=>page.evaluate(()=>showForgotPassword()));
      await page.locator('#password-back').click();
    }
    for(const width of [1280,390]) {
      await page.setViewportSize({width,height:900});
      await page.goto(`http://127.0.0.1:${server.address().port}/guest/?token=synthetic`);
      await page.waitForFunction(()=>document.querySelector('#eq-name')?.textContent.includes('Test-1'));
      await inspect(`guest/${width}/form`,async()=>{});
      await inspect(`guest/${width}/upload-states`,()=>page.evaluate(()=>{
        document.querySelector('#form').classList.add('hidden');
        state.createdRequest={number:1};state.photos=[{name:'Тестовое фото',status:'success'},{name:'Неотправленное фото',status:'failed',retryable:true,error:'Нет сети'}];renderUploadState();
      }));
    }
    fs.mkdirSync('test-results',{recursive:true});
    fs.writeFileSync('test-results/theme-contrast.json',JSON.stringify(report,null,2));
    console.log(JSON.stringify({screens,screensWithFailures:report.length,failures:report.reduce((n,r)=>n+r.failures.length,0),sample:report.slice(0,2)},null,2));
    if(!process.env.FIXIT_CONTRAST_REPORT_ONLY) assert.equal(report.length,0,'Contrast failures; see test-results/theme-contrast.json');
  } finally {await browser?.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
