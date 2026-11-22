import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {Session,root,settings,credentials} from './sso_test_client.mjs';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE||'playwright');
const manifest=JSON.parse(fs.readFileSync(path.join(root,'reports/team-demo-manifest.json'))),checks={},steps=[],actors=[];
const assert=(v,key)=>{if(!v)throw Error(key);checks[key]=true;console.log('PASS',key)};
const admin=new Session();await admin.portal();
const current=async()=>(await admin.api('/api/tasks?collection_id='+manifest.project.id)).tasks.find(t=>t.id===manifest.task.id);
let task=await current();
const reset=await admin.api('/api/tasks/'+task.id+'/proposals',{changes:{criteria:task.criteria.map(i=>({...i,state:'예정'}))},idem:crypto.randomUUID()});await admin.api('/api/proposals/'+reset.id+'/confirm',{});
const browser=await chromium.launch({headless:true,channel:'msedge'});
try{
 for(const account of [credentials.groupA,credentials.groupB]){
  const s=new Session();await s.login(settings.urls.portal+'/auth/login',account);const me=await s.api('/api/me');s.csrf=me.csrf;
  const context=await browser.newContext({viewport:{width:1440,height:1050}});
  await context.addCookies([...s.jar].filter(([k])=>k.startsWith('workhub_')||k.startsWith('authentik_')).map(([name,value])=>({name,value,domain:name.startsWith('workhub_')?'localhost':new URL(settings.urls.auth).hostname,path:'/',httpOnly:true,sameSite:'Lax'})));
  const page=await context.newPage();await page.goto(settings.urls.chat);await page.getByRole('button',{name:/Authentik/}).waitFor({timeout:45000});await page.getByRole('button',{name:/Authentik/}).click();
  await page.waitForURL(u=>u.origin===settings.urls.chat,{timeout:45000});await page.waitForFunction(()=>localStorage.getItem('Meteor.loginToken'),{timeout:45000});
  const rc=await page.evaluate(()=>({id:localStorage.getItem('Meteor.userId'),token:localStorage.getItem('Meteor.loginToken')}));
  const chat=async(endpoint,body)=>{for(let n=0;n<4;n++){const r=await fetch(settings.urls.chat+'/api/v1/'+endpoint,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-User-Id':rc.id,'X-Auth-Token':rc.token},body:body?JSON.stringify(body):undefined});if(r.status===429&&!body){await new Promise(r=>setTimeout(r,30000));continue}if(!r.ok)throw Error(endpoint+' '+r.status);return r.json()}throw Error('Rate limit')};
  const room=(await chat('im.create',{username:'report-bot'})).room._id;
  await page.goto(settings.urls.chat+'/direct/report-bot');
  await page.locator('textarea, [contenteditable=true]').first().waitFor({timeout:45000});
  console.log('Editor',JSON.stringify(await page.locator('textarea, [contenteditable=true]').evaluateAll(es=>es.map(e=>({tag:e.tagName,qa:e.getAttribute('data-qa'),placeholder:e.getAttribute('placeholder'),role:e.getAttribute('role')})))));
  const actor={s,me,page,context,chat,room};actors.push(actor);
  actor.reply=async(since,pattern)=>{const until=Date.now()+240000;while(Date.now()<until){await new Promise(r=>setTimeout(r,5000));const rows=(await chat('im.history?roomId='+room+'&count=50')).messages;const m=rows.find(m=>m.u?.username==='report-bot'&&m.ts>=since&&(pattern.test(m.msg)||m.msg.startsWith('처리 중단:')));if(m){if(m.msg.startsWith('처리 중단:'))throw Error(m.msg);return m}}throw Error('Bot timeout')};
  actor.type=async(text,pattern)=>{const stamp=new Date().toISOString();const editor=page.locator('textarea, [contenteditable=true]').first();await editor.fill(text);await editor.press('Enter');return actor.reply(stamp,pattern)};
  actor.click=async(label,pattern)=>{const stamp=new Date().toISOString();await page.getByRole('button',{name:label,exact:true}).last().click();return actor.reply(stamp,pattern)};
  const menu=await actor.type('시작',/보고할 프로젝트를 선택/);
  assert(menu.attachments?.flatMap(a=>a.actions||[]).some(a=>a.text===manifest.project.name),'project_button_'+me.preferred_username);
  await page.screenshot({path:path.join(root,'reports/chat-project-buttons-'+me.preferred_username+'.png'),fullPage:true});
  await actor.click(manifest.project.name,/보고할 업무를 선택/);
  await page.screenshot({path:path.join(root,'reports/chat-task-buttons-'+me.preferred_username+'.png'),fullPage:true});
  const selected=await actor.click(manifest.task.title,/선택한 업무:/);
  assert(selected.msg.includes('(내 항목)')&&selected.msg.includes(me.name),'task_click_selects_own_context_'+me.preferred_username);
 }
 const [hong,kim]=actors;
 async function report(actor,text,expected,progress){
  const before=await current(),started=Date.now();const draft=await actor.type(text,/이 보고 확정/);
  assert(draft.msg.includes('**[업무목록]**'),'original_format_'+steps.length);
  assert(JSON.stringify((await current()).criteria)===JSON.stringify(before.criteria),'draft_does_not_write_'+steps.length);
  const action=draft.attachments?.[0]?.actions.find(a=>a.text.startsWith('이 보고 확정'));
  assert(!!action&&!/확정 [a-f0-9]{8}/.test(action.msg),'no_code_copy_'+steps.length);
  if(steps.length===0)await actor.page.screenshot({path:path.join(root,'reports/chat-confirm-button.png'),fullPage:true});
  await actor.click(action.text,/Outline 반영 완료:/);const after=await current();
  assert(JSON.stringify(after.criteria.map(i=>i.state))===JSON.stringify(expected),'states_'+steps.length);assert(after.fields.progress===progress,'progress_'+steps.length);
  steps.push({name:actor.me.name,input:text,progress,seconds:Math.round((Date.now()-started)/100)/10});
 }
 await report(hong,'요구사항 정리는 진행 중이고 사용자 안내 작성은 아직 시작 안 했어.',['진행 중','예정','예정','예정'],'0%');
 await report(kim,'화면 검증은 끝냈고 배포 점검은 진행 중이야.',['진행 중','예정','완료','진행 중'],'25%');
 await report(hong,'요구사항 정리와 사용자 안내 작성 둘 다 끝냈어.',['완료','완료','완료','진행 중'],'75%');
 await report(kim,'배포 점검도 끝났어.',['완료','완료','완료','완료'],'100%');
 // Navigation controls and numeric fallback work without changing document state.
 await hong.click('↖ 프로젝트 변경',/보고할 프로젝트를 선택/);
 const menu=await hong.type('프로젝트',/보고할 프로젝트를 선택/);
 const index=menu.attachments.flatMap(a=>a.actions||[]).findIndex(a=>a.text===manifest.project.name)+1;
 await hong.type(String(index),/보고할 업무를 선택/);await hong.type('1',/선택한 업무:/);
 assert((await current()).fields.progress==='100%','numeric_fallback_does_not_change_work');
 await kim.click('현재 업무 · 완료 기준',/선택한 업무:/);
 await kim.page.screenshot({path:path.join(root,'reports/chat-selection-completed.png'),fullPage:true});
 const stats=await admin.api('/api/stats?collection_id='+manifest.project.id);assert(stats.criteria.completed===4&&stats.criteria.owners[hong.me.email]['완료']===2&&stats.criteria.owners[kim.me.email]['완료']===2,'manager_counts_match');
 fs.writeFileSync(path.join(root,'reports/chat-selection-verification.json'),JSON.stringify({at:new Date().toISOString(),checks,steps,method:'Real browser input and native attachment button clicks; real Authentik worker sessions, Rocket.Chat bot, Ollama and Outline.'},null,2));
 console.log(JSON.stringify({checks,steps},null,2));
}catch(e){for(const a of actors){await a.page.screenshot({path:path.join(root,'reports/chat-selection-failure-'+a.me.preferred_username+'.png'),fullPage:true});console.log(a.me.name,(await a.page.locator('body').innerText()).slice(-3500))}throw e}
finally{await browser.close()}
