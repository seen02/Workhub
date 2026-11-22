// Bounded local verification. Only the existing disposable employee is changed;
// its original Authentik name and active state are restored even on failure.
import fs from 'node:fs';import path from 'node:path';import {createRequire} from 'node:module';import {execFileSync} from 'node:child_process';
import {Session,root,settings,credentials} from './sso_test_client.mjs';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE||'playwright');
const manifest=JSON.parse(fs.readFileSync(path.join(root,'reports/accounts-live-verification.json'))),checks=[];
const assert=(ok,name)=>{if(!ok)throw Error(name);checks.push(name);console.log('PASS',name)};
async function ak(body){const r=await fetch(settings.urls.auth+'/api/v3/core/users/'+manifest.employee.pk+'/',{method:body?'PATCH':'GET',headers:{Authorization:'Bearer '+credentials.bootstrapToken,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});if(!r.ok)throw Error('Authentik HTTP '+r.status);return r.json()}
function probe(security=false){
 const code=`from workhub import lifecycle as lc, outline, provision; import json\n${security?'lc.reconcile(sync_names=False)\n':''}r=next(r for r in lc.records() if r['email']=='workhub.demo@example.com'); o=outline.api('users.info',{'id':r['outline_id']}); c=provision.get_mongo().rocketchat.users.find_one({'services.authentik.id':r['sub']}); print(json.dumps({'name':r['name'],'outline':o['name'],'chat':c['name'],'suspended':o['isSuspended'],'chatActive':c.get('active',True),'services':r.get('services'),'security':lc.store.get('employee_security_sync')}))`;
 return JSON.parse(execFileSync('docker',['compose','exec','-T','workhub','python','-c',code],{cwd:root,encoding:'utf8',stdio:['ignore','pipe','pipe']}));
}
const original=await ak();
if(original.email!=='workhub.demo@example.com')throw Error('Not the disposable demo employee');
const admin=new Session();await admin.portal();
const browser=await chromium.launch({headless:true,channel:'msedge'});
let failure;
try{
 await ak({is_active:true,name:'박지민'});await admin.api('/api/accounts/sync',{});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 await context.addCookies([...admin.jar].filter(([k])=>k==='workhub_session').map(([name,value])=>({name,value,domain:'localhost',path:'/',httpOnly:true,sameSite:'Lax'})));
 const page=await context.newPage(),errors=[];let syncRequests=0;
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(new URL(r.url()).pathname==='/api/accounts/sync')syncRequests++});
 await page.goto(new URL('/',settings.urls.portal).href);await page.locator('#tasks').waitFor({state:'visible',timeout:60000});
 const before=probe();await ak({name:'박지민 · 수동 동기화 확인'});
 console.log('Waiting 66 seconds to observe real security and board timers');
 await new Promise(r=>setTimeout(r,66000));
 const idle=probe();
 fs.writeFileSync(path.join(root,'reports/name-sync-idle.json'),JSON.stringify({before,idle,syncRequests,url:page.url()},null,2));
 assert(idle.security.at!==before.security.at,'security timer ran while the board was open');
 assert(idle.name==='박지민'&&idle.outline==='박지민'&&idle.chat==='박지민','timer does not propagate a display-name-only change');
 assert(JSON.stringify(idle.services)===JSON.stringify(before.services),'unchanged accounts do not repeat full service synchronization');
 assert(syncRequests===0,'20-second board refresh never requests account name synchronization');
 async function completed(action){const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/accounts/sync'&&r.request().method()==='POST',{timeout:60000});await action();const r=await response;assert(r.ok()&&(await r.json()).ok,'foreground synchronization succeeded');await page.waitForFunction(()=>!document.querySelector('#accounts-sync').disabled,{timeout:60000})}
 await completed(()=>page.getByRole('button',{name:'계정 · 인수인계',exact:true}).click());
 let after=probe();assert([after.name,after.outline,after.chat].every(n=>n==='박지민 · 수동 동기화 확인'),'opening account tab propagates names to all three services');
 await ak({name:'박지민 · 버튼 확인'});await completed(()=>page.locator('#accounts-sync').click());
 after=probe();assert([after.name,after.outline,after.chat].every(n=>n==='박지민 · 버튼 확인'),'explicit synchronization button propagates names');
 await ak({name:'박지민 · 새로고침 확인'});const count=syncRequests;
 await completed(()=>page.reload());after=probe();
 assert([after.name,after.outline,after.chat].every(n=>n==='박지민 · 새로고침 확인'),'browser refresh on account tab propagates names');
 assert(syncRequests===count+1&&new URL(page.url()).hash==='#accounts','refresh preserves account screen and sends exactly one synchronization request');
 assert((await page.locator('#accounts-state').innerText()).includes('요청 반영 완료'),'synchronization result is visible');
 await page.screenshot({path:path.join(root,'reports/name-sync-ui.png'),fullPage:true});
 await ak({is_active:false});after=probe(true);
 assert(after.suspended&&!after.chatActive,'security-only reconciliation still disables Outline and Rocket.Chat');
 assert(!errors.length,'account screen has no JavaScript errors');
}catch(e){failure=e;console.error(e.message)}
finally{
 try{
  // Restore display names while active, then restore the original active state.
  await ak({name:original.name,is_active:true});await admin.api('/api/accounts/sync',{});
  await ak({is_active:original.is_active});await admin.api('/api/accounts/sync',{});
  const restored=await ak();assert(restored.name===original.name&&restored.is_active===original.is_active,'demo account original state restored');
 }finally{await browser.close();fs.writeFileSync(path.join(root,'reports/name-sync-verification.json'),JSON.stringify({at:new Date().toISOString(),ok:!failure,checks,error:failure?.message},null,2))}
}
if(failure)process.exitCode=1;
