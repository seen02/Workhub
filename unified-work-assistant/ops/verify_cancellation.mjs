import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {Session,root,settings,credentials} from './sso_test_client.mjs';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE||'playwright');
const manifest=JSON.parse(fs.readFileSync(path.join(root,'reports/team-demo-manifest.json'))),checks={},ids=[];
const assert=(v,key)=>{if(!v)throw Error(key);checks[key]=true;console.log('PASS',key)};
const s=new Session();await s.login(settings.urls.portal+'/auth/login',credentials.groupA);const me=await s.api('/api/me');s.csrf=me.csrf;
const other=new Session();await other.login(settings.urls.portal+'/auth/login',credentials.groupB);other.csrf=(await other.api('/api/me')).csrf;
const current=async()=>(await s.api('/api/tasks?collection_id='+manifest.project.id)).tasks.find(t=>t.id===manifest.task.id);
await s.api('/api/sync',{});const before=await current();
const browser=await chromium.launch({headless:true,channel:'msedge'});let page,portal;
try{
 const context=await browser.newContext({viewport:{width:1440,height:1050}});
 await context.addCookies([...s.jar].filter(([k])=>k.startsWith('workhub_')||k.startsWith('authentik_')).map(([name,value])=>({name,value,domain:name.startsWith('workhub_')?'localhost':new URL(settings.urls.auth).hostname,path:'/',httpOnly:true,sameSite:'Lax'})));
 page=await context.newPage();await page.goto(settings.urls.chat);await page.getByRole('button',{name:/Authentik/}).waitFor({timeout:45000});await page.getByRole('button',{name:/Authentik/}).click();
 await page.waitForURL(u=>u.origin===settings.urls.chat,{timeout:45000});await page.waitForFunction(()=>localStorage.getItem('Meteor.loginToken'),{timeout:45000});
 const rc=await page.evaluate(()=>({id:localStorage.getItem('Meteor.userId'),token:localStorage.getItem('Meteor.loginToken')}));
 const chat=async(endpoint,body)=>{for(let n=0;n<4;n++){const r=await fetch(settings.urls.chat+'/api/v1/'+endpoint,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-User-Id':rc.id,'X-Auth-Token':rc.token},body:body?JSON.stringify(body):undefined});if(r.status===429&&!body){await new Promise(r=>setTimeout(r,30000));continue}if(!r.ok)throw Error(endpoint+' '+r.status);return r.json()}throw Error('Rate limit')};
 const room=(await chat('im.create',{username:'report-bot'})).room._id;
 await page.goto(settings.urls.chat+'/direct/report-bot');await page.locator('textarea').first().waitFor({timeout:45000});
 async function reply(stamp,pattern,allowError=false){const until=Date.now()+240000;while(Date.now()<until){await new Promise(r=>setTimeout(r,5000));const rows=(await chat('im.history?roomId='+room+'&count=50')).messages;const m=rows.find(m=>m.u?.username==='report-bot'&&m.ts>=stamp&&(pattern.test(m.msg)||m.msg.startsWith('처리 중단:')));if(m){if(m.msg.startsWith('처리 중단:')&&!allowError)throw Error(m.msg);return m}}throw Error('Bot timeout')}
 async function type(text,pattern,allowError=false){const stamp=new Date().toISOString();await page.locator('textarea').first().fill(text);await page.locator('textarea').first().press('Enter');return reply(stamp,pattern,allowError)}
 async function click(label,pattern,allowError=false){const stamp=new Date().toISOString();await page.getByRole('button',{name:label,exact:true}).last().click();return reply(stamp,pattern,allowError)}
 const pid=m=>m.attachments.flatMap(a=>a.actions||[]).find(a=>a.url?.includes('#proposal-')).url.split('#proposal-')[1];
 async function draft(text){const m=await type(text,/이 초안 취소/);const id=pid(m);ids.push(id);assert(m.msg.includes('**[업무목록]**'),'report_format_'+ids.length);return {m,id}}
 async function showProposal(id){await portal.goto(settings.urls.portal+'/?review='+id+'#proposal-'+id);await portal.locator('#cancel-proposal').waitFor({timeout:45000})}
 await type('시작',/보고할 프로젝트/);await click(manifest.project.name,/보고할 업무/);await click(manifest.task.title,/선택한 업무:/);
 portal=await context.newPage();
 // Keep a stale portal preview open, then cancel from Rocket.Chat.
 const first=await draft('요구사항 정리는 진행 중이야.');await showProposal(first.id);
 assert(await portal.locator('#confirm').isEnabled(),'pending_portal_confirm_enabled');
 await page.screenshot({path:path.join(root,'reports/cancellation-chat-buttons.png'),fullPage:true});
 const forbidden=await other.fetch(settings.urls.portal+'/api/proposals/'+first.id+'/cancel',{method:'POST',headers:{'Content-Type':'application/json',Origin:settings.urls.portal,'X-CSRF-Token':other.csrf},body:'{}'});
 assert(forbidden.status===404,'other_worker_cannot_cancel');
 const noCsrf=await s.fetch(settings.urls.portal+'/api/proposals/'+first.id+'/cancel',{method:'POST',headers:{'Content-Type':'application/json',Origin:settings.urls.portal},body:'{}'});
 assert(noCsrf.status===403,'cancel_requires_csrf');
 await click('이 초안 취소',/초안 취소 완료:/);assert((await s.api('/api/proposals/'+first.id)).state==='CANCELLED','chat_button_cancelled');
 await portal.locator('#confirm').click();await portal.waitForFunction(()=>document.querySelector('#proposal').innerText.includes('취소된 초안입니다.'));
 assert(await portal.locator('#confirm').isDisabled()&&await portal.locator('#cancel-proposal').isDisabled(),'stale_portal_confirm_blocked_and_refreshed');
 await portal.reload();await portal.locator('#cancel-proposal').waitFor();assert(await portal.locator('#confirm').isDisabled(),'cancelled_state_survives_reload');
 // Cancel a chat draft in the portal; its old chat confirmation must fail.
 const second=await draft('사용자 안내 작성은 진행 중이야.');await showProposal(second.id);
 await portal.locator('#cancel-proposal').click();await portal.waitForFunction(()=>document.querySelector('#proposal').innerText.includes('취소된 초안입니다.'));
 assert((await s.api('/api/proposals/'+second.id)).state==='CANCELLED','portal_cancels_chat_draft');
 const denied=await click('이 보고 확정',/처리 중단:/,true);assert(denied.msg.includes('취소된 초안'),'old_chat_confirm_after_portal_cancel_denied');
 assert((await s.api('/api/proposals/'+second.id+'/cancel',{})).state==='CANCELLED','cancel_retry_idempotent');
 // The short command cancels the latest draft of this DM and task.
 const third=await draft('요구사항 정리는 진행 중이야.');await type('취소',/초안 취소 완료:/);
 assert((await s.api('/api/proposals/'+third.id)).state==='CANCELLED','short_chat_cancel');
 await type('취소',/초안 취소 완료:/);assert((await s.api('/api/proposals/'+third.id)).state==='CANCELLED','repeated_short_cancel_same_draft');
 await page.screenshot({path:path.join(root,'reports/cancellation-chat-result.png'),fullPage:true});
 // Generate and cancel a report entirely in the assistant screen.
 await portal.goto(settings.urls.portal);await portal.locator('#project-bar').waitFor({state:'visible'});await portal.selectOption('#project-select',manifest.project.id);
 await portal.locator(`[data-report="${manifest.task.id}"]`).click();await portal.locator('#report-text').fill('요구사항 정리는 진행 중이야.');
 await portal.locator('#report-form button').last().click();await portal.locator('#cancel-proposal').waitFor({timeout:240000});
 const responsePromise=portal.waitForResponse(r=>r.url().includes('/api/proposals/')&&r.url().endsWith('/cancel')&&r.request().method()==='POST');
 await portal.locator('#cancel-proposal').click();const cancelled=await (await responsePromise).json();ids.push(cancelled.id);
 await portal.waitForFunction(()=>document.querySelector('#proposal').innerText.includes('취소된 초안입니다.'));
 assert(cancelled.state==='CANCELLED'&&await portal.locator('#confirm').isDisabled(),'portal_report_creation_and_cancellation');
 await portal.screenshot({path:path.join(root,'reports/cancellation-portal.png'),fullPage:true});
 await s.api('/api/sync',{});const after=await current();
 assert(after.text===before.text&&after.revision===before.revision&&after.updatedAt===before.updatedAt,'outline_original_and_revision_unchanged');
 assert(JSON.stringify(after.criteria)===JSON.stringify(before.criteria)&&after.fields.progress===before.fields.progress,'checklist_and_progress_unchanged');
 fs.writeFileSync(path.join(root,'reports/cancellation-verification.json'),JSON.stringify({at:new Date().toISOString(),checks,proposalIds:ids,before:{progress:before.fields.progress,revision:before.revision},after:{progress:after.fields.progress,revision:after.revision},method:'Real Authentik accounts; browser chat input, native cancel/confirm buttons and portal report/cancel UI.'},null,2));
 console.log(JSON.stringify(checks,null,2));
}catch(e){if(page){await page.screenshot({path:path.join(root,'reports/cancellation-failure-chat.png'),fullPage:true});console.log((await page.locator('body').innerText()).slice(-2400))}if(portal){await portal.screenshot({path:path.join(root,'reports/cancellation-failure-portal.png'),fullPage:true});console.log((await portal.locator('body').innerText()).slice(-1000))}throw e}
finally{await browser.close()}
