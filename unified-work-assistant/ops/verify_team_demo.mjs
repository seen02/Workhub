import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {Session,root,settings,credentials} from './sso_test_client.mjs';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const manifest=JSON.parse(fs.readFileSync(path.join(root,'reports/team-demo-manifest.json'))),checks={},steps=[],actors=[],errors=[];
const browser=await chromium.launch({headless:true,channel:'msedge'});
const assert=(v,key)=>{if(!v)throw Error(key);checks[key]=true;console.log('PASS',key)};
const cfg=JSON.parse(fs.readFileSync(path.join(root,'.local/compose.json')));
async function outline(endpoint,body){const r=await fetch(settings.urls.outline+'/api/'+endpoint,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+cfg.services['document-agent'].environment.OUTLINE_API_KEY},body:JSON.stringify(body)});if(!r.ok)throw Error(endpoint+' '+r.status);return (await r.json()).data}
let temporary;
try{
 for(const [n,account] of [credentials.authentikAdmin,credentials.groupA,credentials.groupB].entries()){
  const s=new Session();await s.login(settings.urls.portal+'/auth/login',account);const me=await s.api('/api/me');s.csrf=me.csrf;
  const context=await browser.newContext({viewport:{width:1440,height:1050}});
  await context.addCookies([...s.jar].filter(([k])=>k.startsWith('workhub_')||k.startsWith('authentik_')).map(([name,value])=>({name,value,domain:name.startsWith('workhub_')?'localhost':new URL(settings.urls.auth).hostname,path:'/',httpOnly:true,sameSite:'Lax'})));
  const page=await context.newPage();page.on('pageerror',e=>errors.push({actor:me.name,origin:new URL(page.url()).origin,error:e.message}));
  await page.goto(settings.urls.portal);await page.locator('#project-bar').waitFor({state:'visible'});await page.selectOption('#project-select',manifest.project.id);await page.locator(`[data-task="${manifest.task.id}"]`).waitFor();
  assert((await page.locator('#account').innerText()).includes(manifest.accounts[n].name),'portal_name_'+n);
  if(n){assert(await page.locator('[data-tab=stats]').isHidden(),'worker_stats_hidden_'+n);assert(await page.locator('[data-criteria]').count()===0,'worker_assignment_editor_hidden_'+n)}
  actors.push({s,me,context,page});
 }
 const [admin,hong,kim]=actors;
 const current=async()=>(await admin.s.api('/api/tasks?collection_id='+manifest.project.id)).tasks.find(t=>t.id===manifest.task.id);
 // Reset only this dedicated team demonstration; preserve assignment IDs and report history.
 let task=await current();const reset=await admin.s.api('/api/tasks/'+task.id+'/proposals',{changes:{criteria:task.criteria.map(i=>({...i,state:'예정'}))},idem:crypto.randomUUID()});await admin.s.api('/api/proposals/'+reset.id+'/confirm',{});
 await admin.page.locator('#sync').click();await admin.page.locator(`[data-criteria="${task.id}"]`).click();await admin.page.locator('#criteria-dialog').waitFor({state:'visible'});
 assert(await admin.page.locator('#criteria-rows input[type=email]').count()===0,'no_email_typing_for_assignment');
 const selects=admin.page.locator('#criteria-rows .criterion-owner');
 await selects.nth(0).selectOption({label:'홍길동'});await selects.nth(1).selectOption({label:'홍길동'});await selects.nth(2).selectOption({label:'김철수'});await selects.nth(3).selectOption({label:'김철수'});
 await admin.page.screenshot({path:path.join(root,'reports/team-name-assignment.png'),fullPage:true});
 await admin.page.locator('#criteria-form > button').last().click();await admin.page.locator('#confirm').click();await admin.page.waitForFunction(()=>document.querySelector('#proposal').innerText.includes('반영되었습니다'));
 task=await current();assert(JSON.stringify(task.criteria.map(i=>i.owner))===JSON.stringify([hong.me.email,hong.me.email,kim.me.email,kim.me.email]),'ui_name_selection_maps_to_correct_accounts');
 // Name selection also works when creating a new task, not only when editing a checklist.
 await admin.page.locator('[data-tab=tasks]').click();await admin.page.locator('#new-task').click();await admin.page.locator('#create-dialog').waitFor({state:'visible'});
 const tempName='[이름 선택 검증] '+crypto.randomUUID().slice(0,6);await admin.page.locator('#create-form [name=title]').fill(tempName);await admin.page.selectOption('#create-form [name=assignee_id]',{label:'홍길동'});
 await admin.page.locator('#create-add-criterion').click();await admin.page.locator('#create-criteria-rows .criterion-title').fill('이름 배정 확인');await admin.page.selectOption('#create-criteria-rows .criterion-owner',{label:'김철수'});
 await admin.page.locator('#create-form > button').last().click();await admin.page.locator('#create-dialog').waitFor({state:'hidden'});
 temporary=(await admin.s.api('/api/tasks?collection_id='+manifest.project.id)).tasks.find(t=>t.title===tempName);
 assert(temporary.fields.owner===hong.me.email&&temporary.criteria[0].owner===kim.me.email,'ui_create_with_different_named_assignees');
 await outline('documents.archive',{id:temporary.id});temporary=null;await admin.s.api('/api/sync',{});
 for(const actor of [hong,kim]){
  const {page,s}=actor;await page.goto(settings.urls.chat);await page.getByRole('button',{name:/Authentik/}).waitFor({timeout:45000});await page.getByRole('button',{name:/Authentik/}).click();
  await page.waitForURL(u=>u.origin===settings.urls.chat,{timeout:45000});await page.waitForFunction(()=>localStorage.getItem('Meteor.loginToken'),{timeout:45000});
  const rc=await page.evaluate(()=>({id:localStorage.getItem('Meteor.userId'),token:localStorage.getItem('Meteor.loginToken')}));
  await s.api('/api/me');
  actor.chat=async(endpoint,body)=>{
   for(let attempt=0;attempt<4;attempt++){
    const r=await fetch(settings.urls.chat+'/api/v1/'+endpoint,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-User-Id':rc.id,'X-Auth-Token':rc.token},body:body?JSON.stringify(body):undefined});
    if(r.status===429&&!body){await new Promise(resolve=>setTimeout(resolve,Math.min(60000,Math.max(10000,Number(r.headers.get('retry-after')||30)*1000))));continue}
    const d=await r.json();if(!r.ok)throw Error('Rocket '+endpoint+' '+r.status);return d;
   }throw Error('Rocket history rate limit did not clear');
  };
  const user=await actor.chat('me');assert(user.name===actor.me.name&&!user.roles.includes('admin'),'rocketchat_name_and_worker_role_'+actor.me.preferred_username);
  actor.room=(await actor.chat('im.create',{username:'report-bot'})).room._id;
  actor.send=async(text,pattern,allowError=false)=>{
   const stamp=new Date().toISOString(),start=Date.now();await actor.chat('chat.postMessage',{roomId:actor.room,text});
   while(Date.now()-start<240000){await new Promise(r=>setTimeout(r,5000));const msgs=(await actor.chat('im.history?roomId='+actor.room+'&count=50')).messages,m=msgs.find(m=>m.u?.username==='report-bot'&&m.ts>=stamp&&(pattern.test(m.msg)||m.msg.startsWith('처리 중단:')));if(m){if(m.msg.startsWith('처리 중단:')&&!allowError)throw Error(actor.me.name+': '+m.msg);actor.lastReply=m;return m.msg}}throw Error('Bot timeout '+actor.me.name);
  };
  await actor.send('프로젝트 '+manifest.project.code,/선택한 프로젝트/);const listing=await actor.send('항목 '+manifest.task.code,/완료 기준/);
  assert(listing.includes('홍길동')&&listing.includes('김철수')&&listing.includes('(내 항목)'),'bot_names_and_own_items_'+actor.me.preferred_username);
 }
 const report=async(actor,raw,expected,progress)=>{
  const before=await current(),started=Date.now(),draft=await actor.send(raw,/이 보고 확정/);
  assert(draft.includes('**[업무목록]**'),'company_format_'+steps.length);
  assert(JSON.stringify((await current()).criteria)===JSON.stringify(before.criteria),'private_draft_'+steps.length);
  const pid=actor.lastReply.attachments.flatMap(a=>a.actions||[]).find(a=>a.url?.includes('#proposal-')).url.split('#proposal-')[1];
  if(!steps.length){const r=await kim.s.fetch(settings.urls.portal+'/api/proposals/'+pid);assert(r.status===404,'coworker_cannot_read_private_proposal')}
  await actor.send('확정 '+pid,/Outline 반영 완료/);
  const after=await current();assert(JSON.stringify(after.criteria.map(i=>i.state))===JSON.stringify(expected),'item_states_'+steps.length);assert(after.fields.progress===progress,'progress_'+steps.length);
  steps.push({actor:actor.me.name,input:raw,states:expected,progress,seconds:Math.round((Date.now()-started)/100)/10});console.log('STEP',actor.me.name,progress);
 };
 await report(hong,'요구사항 정리는 진행 중이고 사용자 안내 작성은 아직 시작 안 했어.',['진행 중','예정','예정','예정'],'0%');
 await report(kim,'화면 검증은 끝냈고 배포 점검은 진행 중이야.',['진행 중','예정','완료','진행 중'],'25%');
 // Server must reject another worker's item even if the AI can understand the sentence.
 const blocked=await hong.send('화면 검증은 아직 진행 중이야.',/처리 중단:/,true);assert(blocked.includes('배정된 완료 기준만'),'chat_other_worker_item_denied');assert((await current()).criteria[2].state==='완료','denied_chat_preserves_other_worker_item');
 await report(hong,'요구사항 정리와 사용자 안내 작성 둘 다 끝냈어.',['완료','완료','완료','진행 중'],'75%');
 await report(kim,'배포 점검도 끝났어.',['완료','완료','완료','완료'],'100%');
 const statistics=await admin.s.api('/api/stats?collection_id='+manifest.project.id);
 assert(statistics.criteria.owners[hong.me.email]['완료']===2&&statistics.criteria.owners[kim.me.email]['완료']===2,'manager_sees_each_worker_two_completed');
 const personal=await admin.s.api('/api/stats?'+new URLSearchParams({collection_id:manifest.project.id,owner:hong.me.email}));
 assert(personal.criteria.total===2&&personal.criteria.completed===2&&Object.keys(personal.criteria.owners).length===1,'manager_person_filter_counts_only_assigned_items');
 assert((await current()).fields.status==='완료','task_completed_after_all_four_items');
 for(const actor of [hong,kim]){await actor.page.goto(settings.urls.chat+'/direct/report-bot');await actor.page.getByText('Outline 반영 완료:',{exact:false}).last().waitFor({timeout:30000});await actor.page.screenshot({path:path.join(root,'reports/team-chat-'+actor.me.preferred_username+'.png'),fullPage:true})}
 await admin.page.locator('[data-tab=stats]').click();await admin.page.locator('#filter').click();await admin.page.waitForFunction(()=>document.querySelector('#metrics').innerText.includes('100%'));await admin.page.screenshot({path:path.join(root,'reports/team-completed-stats.png'),fullPage:true});
 assert(errors.length===0,'browser_no_javascript_errors');
 fs.writeFileSync(path.join(root,'reports/team-verification.json'),JSON.stringify({at:new Date().toISOString(),checks,steps,errors,accounts:manifest.accounts,task:manifest.task,project:manifest.project},null,2));
 console.log(JSON.stringify({checks,steps},null,2));
}catch(e){console.log('Browser errors:',JSON.stringify(errors));for(const [n,a] of actors.entries()){await a.page.screenshot({path:path.join(root,'reports/team-failure-'+n+'.png'),fullPage:true});console.log(a.me.name,(await a.page.locator('body').innerText()).slice(-1800))}throw e}
finally{if(temporary)await outline('documents.archive',{id:temporary.id});await browser.close()}
