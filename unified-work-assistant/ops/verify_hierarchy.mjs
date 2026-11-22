import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {Session,root,settings,credentials} from './sso_test_client.mjs';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE||'playwright');
const env=JSON.parse(fs.readFileSync(path.join(root,'.local/compose.json'))).services['document-agent'].environment;
async function outline(endpoint,body){const r=await fetch(settings.urls.outline+'/api/'+endpoint,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+env.OUTLINE_API_KEY},body:JSON.stringify(body)});if(!r.ok)throw Error(endpoint+' '+r.status);return (await r.json()).data}
const checks={},assert=(v,key)=>{if(!v)throw Error(key);checks[key]=true;console.log('PASS',key)};
const admin=new Session();await admin.portal();await admin.api('/api/sync',{});
const baseline=(await admin.api('/api/tasks')).tasks;
const migrations=JSON.parse(fs.readFileSync(path.join(root,'reports/hierarchy-migration.json'),'utf8').replace(/^\uFEFF/,''));
assert(migrations.verified&&migrations.moved===9,'existing_nine_tasks_migrated');
for(const p of migrations.projects){const ts=baseline.filter(t=>t.collectionId===p.collectionId);assert(ts.length===p.tasks.length&&ts.every(t=>t.parentDocumentId===p.parentId),'migrated_parent_'+p.name)}
assert(new Set(migrations.projects.map(p=>p.parentId)).size===5,'separate_parent_for_each_project');
const s=new Session();await s.login(settings.urls.portal+'/auth/login',credentials.groupA);const me=await s.api('/api/me');s.csrf=me.csrf;
let project,browser,page;
try{
 project=await admin.api('/api/projects',{name:'[검증] 업무 계층 '+Date.now(),idem:crypto.randomUUID()});
 const reference=await outline('documents.create',{collectionId:project.id,title:'PRD',text:'일반 프로젝트 문서는 최상위에 유지합니다.',publish:true});
 const body={title:'하위 업무 보고 검증',collection_id:project.id,fields:{owner:me.email,status:'미착수',progress:'0%'},criteria:[{id:'C-12345678',title:'화면 검증',owner:me.email,state:'예정'}],idem:crypto.randomUUID()};
 const task=await admin.api('/api/tasks',body);
 const doc=await outline('documents.info',{id:task.id}),parent=await outline('documents.info',{id:doc.parentDocumentId});
 assert(parent.title==='업무 목록'&&!parent.parentDocumentId&&parent.collectionId===project.id,'new_task_under_auto_created_root');
 assert((await admin.api('/api/tasks',body)).id===task.id,'create_retry_no_duplicate_task');
 await outline('documents.update',{id:parent.id,title:'업무 목록 · 이름 변경 검증'});
 await s.api('/api/me');
 browser=await chromium.launch({headless:true,channel:'msedge'});const context=await browser.newContext({viewport:{width:1440,height:1050}});
 await context.addCookies([...s.jar].filter(([k])=>k.startsWith('workhub_')||k.startsWith('authentik_')).map(([name,value])=>({name,value,domain:name.startsWith('workhub_')?'localhost':new URL(settings.urls.auth).hostname,path:'/',httpOnly:true,sameSite:'Lax'})));
 const portal=await context.newPage();await portal.goto(settings.urls.portal);await portal.locator('#project-bar').waitFor({state:'visible',timeout:45000});await portal.selectOption('#project-select',project.id);
 await portal.locator('#new-task').click();await portal.locator('#create-dialog [name=title]').fill('포털에서 등록한 업무');
 const created=portal.waitForResponse(r=>r.url().endsWith('/api/tasks')&&r.request().method()==='POST');await portal.locator('#create-form button').last().click();const uiTask=await(await created).json();
 if(uiTask.parentDocumentId!==parent.id)console.log('Portal creation result',JSON.stringify({id:uiTask.id,parent:uiTask.parentDocumentId,collection:uiTask.collectionId,detail:uiTask.detail,request:JSON.parse((await created).request().postData()),docs:(await outline('documents.list',{collectionId:project.id,limit:100})).map(d=>({id:d.id,parent:d.parentDocumentId,published:d.publishedAt,title:d.title}))}));
 assert(uiTask.parentDocumentId===parent.id,'portal_creation_uses_renamed_parent');
 await portal.locator('#create-dialog').waitFor({state:'hidden'});await portal.screenshot({path:path.join(root,'reports/hierarchy-portal.png'),fullPage:true});
 page=await context.newPage();await page.goto(settings.urls.chat);await page.getByRole('button',{name:/Authentik/}).waitFor({timeout:45000});await page.getByRole('button',{name:/Authentik/}).click();
 await page.waitForURL(u=>u.origin===settings.urls.chat,{timeout:45000});await page.waitForFunction(()=>localStorage.getItem('Meteor.loginToken'),{timeout:45000});
 const rc=await page.evaluate(()=>({id:localStorage.getItem('Meteor.userId'),token:localStorage.getItem('Meteor.loginToken')}));
 const chat=async(endpoint,body)=>{for(let n=0;n<4;n++){const r=await fetch(settings.urls.chat+'/api/v1/'+endpoint,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-User-Id':rc.id,'X-Auth-Token':rc.token},body:body?JSON.stringify(body):undefined});if(r.status===429&&!body){await new Promise(r=>setTimeout(r,30000));continue}if(!r.ok)throw Error(endpoint+' '+r.status);return r.json()}throw Error('Rate limit')};
 const room=(await chat('im.create',{username:'report-bot'})).room._id;
 await page.goto(settings.urls.chat+'/direct/report-bot');await page.locator('textarea').first().waitFor({timeout:45000});
 async function reply(stamp,pattern){const until=Date.now()+240000;while(Date.now()<until){await new Promise(r=>setTimeout(r,5000));const rows=(await chat('im.history?roomId='+room+'&count=50')).messages;const m=rows.find(m=>m.u?.username==='report-bot'&&m.ts>=stamp&&(pattern.test(m.msg)||m.msg.startsWith('처리 중단:')));if(m){if(m.msg.startsWith('처리 중단:'))throw Error(m.msg);return m}}throw Error('Bot timeout')}
 async function type(text,pattern){const stamp=new Date().toISOString();await page.locator('textarea').first().fill(text);await page.locator('textarea').first().press('Enter');return reply(stamp,pattern)}
 async function click(label,pattern){const stamp=new Date().toISOString();await page.getByRole('button',{name:label,exact:true}).last().click();return reply(stamp,pattern)}
 await type('시작',/보고할 프로젝트/);await click(project.name,/보고할 업무/);const selected=await click(task.title,/선택한 업무:/);assert(selected.msg.includes('화면 검증'),'nested_task_selectable_in_chat');
 const draft=await type('화면 검증은 다 끝냈어.',/이 보고 확정/);assert(draft.msg.includes('**[업무목록]**'),'original_report_format_retained');
 assert((await outline('documents.info',{id:task.id})).text===doc.text,'draft_does_not_modify_nested_task');
 await click('이 보고 확정',/Outline 반영 완료/);
 const updated=(await s.api('/api/tasks?collection_id='+project.id)).tasks.find(t=>t.id===task.id);
 assert(updated.parentDocumentId===parent.id&&updated.criteria[0].state==='완료'&&updated.fields.progress==='100%','chat_confirm_updates_nested_task_and_checklist');
 const stat=await admin.api('/api/stats?collection_id='+project.id);
 assert(stat.summary.total===2&&stat.criteria.total===1&&stat.criteria.completed===1&&stat.criteria.progress===100,'statistics_exclude_parent_and_reference');
 const after=await outline('documents.info',{id:task.id});await type('화면 검증은 다시 진행 중이야.',/이 보고 확정/);await click('이 초안 취소',/초안 취소 완료/);
 assert((await outline('documents.info',{id:task.id})).text===after.text,'chat_cancel_preserves_nested_source');
 await type('작성 채팅에서 등록한 업무',/업무 등록 완료/);
 const tasks=(await s.api('/api/tasks?collection_id='+project.id)).tasks;
 assert(tasks.length===3&&tasks.every(t=>t.parentDocumentId===parent.id),'chat_creation_uses_same_parent');
 const docs=await outline('documents.list',{collectionId:project.id,limit:100});assert(docs.length===5,'no_duplicate_parent_after_rename_and_retries');
 const refAfter=await outline('documents.info',{id:reference.id});assert(!refAfter.parentDocumentId&&refAfter.text===reference.text,'reference_document_unchanged');
 await page.screenshot({path:path.join(root,'reports/hierarchy-chat.png'),fullPage:true});
 // Keep the user's next chat interaction on the real demonstration project.
 const real=JSON.parse(fs.readFileSync(path.join(root,'reports/team-demo-manifest.json')));
 await type('시작',/보고할 프로젝트/);await click(real.project.name,/보고할 업무/);await click(real.task.title,/선택한 업무:/);
}finally{
 if(browser)await browser.close();
 if(project){await outline('collections.delete',{id:project.id});await new Promise(r=>setTimeout(r,5500));await admin.api('/api/sync',{});checks.test_project_removed=true;}
}
const final=(await admin.api('/api/tasks')).tasks;
assert(final.length===baseline.length&&baseline.every(t=>final.some(f=>f.id===t.id&&f.text===t.text&&f.parentDocumentId===t.parentDocumentId)),'existing_tasks_unchanged_after_live_tests');
fs.writeFileSync(path.join(root,'reports/hierarchy-verification.json'),JSON.stringify({at:new Date().toISOString(),checks,originalTasks:baseline.length,method:'Authentik admin and worker; real portal creation and Rocket.Chat selection/report/confirm/cancel/create; temporary project removed.'},null,2));
console.log(JSON.stringify(checks,null,2));
