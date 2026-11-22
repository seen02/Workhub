import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {Session,root,settings,credentials} from './sso_test_client.mjs';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE||'playwright');
const env=JSON.parse(fs.readFileSync(path.join(root,'.local/compose.json'))).services['document-agent'].environment;
async function outline(endpoint,body){if(endpoint==='collections.delete')throw Error('Collection deletion is forbidden in this test');const r=await fetch(settings.urls.outline+'/api/'+endpoint,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+env.OUTLINE_API_KEY},body:JSON.stringify(body)});if(!r.ok)throw Error(endpoint+' '+r.status);return (await r.json()).data}
const checks={},assert=(v,k)=>{if(!v)throw Error(k);checks[k]=true;console.log('PASS',k)};
const admin=new Session();const me=await admin.portal();const baseline=(await admin.api('/api/tasks')).tasks,baseProjects=(await admin.api('/api/projects')).projects;
const worker=new Session();await worker.login(settings.urls.portal+'/auth/login',credentials.groupA);worker.csrf=(await worker.api('/api/me')).csrf;
const project=await admin.api('/api/projects',{name:'[검증] 연결 해제 '+Date.now(),idem:crypto.randomUUID()});
const ref=await outline('documents.create',{collectionId:project.id,title:'PRD · 연결 해제 보존 확인',text:'이 컬렉션은 연결 해제 검증용입니다. 업무 목록 삭제 후에도 이 문서와 컬렉션은 보존합니다.',publish:true});
const task=await admin.api('/api/tasks',{collection_id:project.id,title:'연결 해제 검증 업무',fields:{owner:me.email,status:'미착수',progress:'0%'},idem:crypto.randomUUID()});
const nested=await outline('documents.create',{collectionId:project.id,parentDocumentId:task.id,title:'하위 검증 자료',text:'업무 목록의 하위 자료 삭제 범위 확인',publish:true});
const original=await outline('documents.info',{id:task.id}),parent=await outline('documents.info',{id:task.parentDocumentId});
const pending=await admin.api('/api/tasks/'+task.id+'/proposals',{changes:{status:'진행 중'},idem:crypto.randomUUID()});
async function status(session,endpoint,body,csrf=true){const r=await session.fetch(settings.urls.portal+endpoint,{method:'POST',headers:{'Content-Type':'application/json',Origin:settings.urls.portal,...(csrf?{'X-CSRF-Token':session.csrf}:{})},body:JSON.stringify(body)});return r.status}
assert(await status(worker,'/api/projects/'+project.id+'/unlink',{idem:crypto.randomUUID()})===403,'worker_cannot_unlink');
assert(await status(admin,'/api/projects/'+project.id+'/unlink',{idem:crypto.randomUUID()},false)===403,'csrf_required');
assert(await status(admin,'/api/projects/'+project.id+'/unlink',{idem:crypto.randomUUID(),delete_collection:true})===422,'collection_delete_option_rejected');
const browser=await chromium.launch({headless:true,channel:'msedge'});let page;
try{
 const context=await browser.newContext({viewport:{width:1440,height:1050}});await context.addCookies([...admin.jar].filter(([k])=>k.startsWith('workhub_')||k.startsWith('authentik_')).map(([name,value])=>({name,value,domain:name.startsWith('workhub_')?'localhost':new URL(settings.urls.auth).hostname,path:'/',httpOnly:true,sameSite:'Lax'})));
 page=await context.newPage();await page.goto(settings.urls.portal);await page.locator('#project-bar').waitFor({state:'visible',timeout:45000});await page.selectOption('#project-select',project.id);
 async function openUnlink(){await page.locator('#new-project').click();await page.locator(`[data-unlink="${project.id}"]`).click();await page.locator('#unlink-dialog').waitFor({state:'visible'})}
 await openUnlink();assert(!(await page.locator('#delete-task-list').isChecked()),'delete_checkbox_off_by_default');assert(await page.locator('#submit-unlink').innerText()==='연결만 해제','default_button_is_unlink_only');
 await page.screenshot({path:path.join(root,'reports/unlink-default.png'),fullPage:true});
 let response=page.waitForResponse(r=>r.url().endsWith('/unlink')&&r.request().method()==='POST');await page.locator('#submit-unlink').click();const firstResponse=await response,firstBody=await firstResponse.json(),firstRequest=JSON.parse(firstResponse.request().postData());
 assert(firstBody.unlinked&&!firstBody.taskListDeleted&&!firstBody.collectionDeleted,'ui_default_unlink_success');await page.locator('#unlink-dialog').waitFor({state:'hidden'});
 assert(!(await admin.api('/api/projects')).projects.some(p=>p.id===project.id),'removed_from_project_registry');
 assert(!(await admin.api('/api/tasks')).tasks.some(t=>t.collectionId===project.id),'removed_from_task_board');
 assert(!(await admin.api('/api/stats')).events.some(e=>e.body.collectionId===project.id),'removed_from_statistics_history');
 assert((await outline('documents.info',{id:task.id})).text===original.text&&(await outline('documents.info',{id:parent.id})).id===parent.id,'default_preserves_parent_and_task');
 assert((await outline('documents.info',{id:nested.id})).text===nested.text&&(await outline('documents.info',{id:ref.id})).text===ref.text,'default_preserves_nested_and_reference_documents');
 assert(await status(admin,'/api/proposals/'+pending.id+'/confirm',{})===404,'old_pending_confirmation_blocked');
 await admin.api('/api/proposals/'+pending.id+'/cancel',{});
 // Reconnect through the actual project management dialog.
 await page.locator('#new-project').click();await page.selectOption('#existing-collection',project.id);await page.locator('#project-form button').last().click();await page.locator('#project-dialog').waitFor({state:'hidden'});
 assert((await admin.api('/api/tasks?collection_id='+project.id)).tasks.some(t=>t.id===task.id&&t.parentDocumentId===parent.id),'reconnect_restores_same_task_and_parent');
 await admin.api('/api/projects/'+project.id+'/unlink',firstRequest);assert((await admin.api('/api/projects')).projects.some(p=>p.id===project.id),'old_unlink_retry_does_not_remove_reconnected_project');
 await openUnlink();assert(!(await page.locator('#delete-task-list').isChecked()),'delete_option_resets_on_reopen');await page.locator('#delete-task-list').check();
 assert((await page.locator('#unlink-dialog').innerText()).includes('그 아래 모든 문서'),'subtree_delete_scope_visible');await page.screenshot({path:path.join(root,'reports/unlink-delete-option.png'),fullPage:true});
 response=page.waitForResponse(r=>r.url().endsWith('/unlink')&&r.request().method()==='POST');await page.locator('#submit-unlink').click();const removed=await(await response).json();assert(removed.unlinked&&removed.taskListDeleted&&!removed.collectionDeleted,'optional_document_delete_unlink_success');
 await page.locator('#unlink-dialog').waitFor({state:'hidden'});
 const deleted=await outline('documents.deleted',{collectionId:project.id,limit:100});
 assert([parent.id,task.id,nested.id].every(id=>deleted.some(d=>d.id===id)),'parent_and_descendants_in_outline_trash');
 assert((await outline('collections.info',{id:project.id})).id===project.id,'collection_survives_optional_delete');
 const afterRef=await outline('documents.info',{id:ref.id});assert(afterRef.text===ref.text&&afterRef.updatedAt===ref.updatedAt,'reference_document_untouched_after_delete');
 // The same collection can be linked again and receive a fresh task container.
 await admin.api('/api/projects',{existing_id:project.id,idem:crypto.randomUUID()});
 const fresh=await admin.api('/api/tasks',{collection_id:project.id,title:'재연결 후 업무',fields:{owner:me.email,status:'미착수'},idem:crypto.randomUUID()});
 assert(fresh.parentDocumentId!==parent.id,'reconnect_after_delete_creates_new_parent');
 const preview=await admin.api('/api/projects/'+project.id+'/unlink-preview');await admin.api('/api/projects/'+project.id+'/unlink',{idem:crypto.randomUUID(),delete_task_list:true,expected_parent_id:preview.parent.id});
 // Verify the real bot project menu after unlink. No collection-delete operation is used.
 const chatPage=await context.newPage();await chatPage.goto(settings.urls.chat);await chatPage.getByRole('button',{name:/Authentik/}).waitFor({timeout:45000});await chatPage.getByRole('button',{name:/Authentik/}).click();await chatPage.waitForFunction(()=>localStorage.getItem('Meteor.loginToken'),{timeout:45000});
 const rc=await chatPage.evaluate(()=>({id:localStorage.getItem('Meteor.userId'),token:localStorage.getItem('Meteor.loginToken')}));
 async function chat(endpoint,body){const r=await fetch(settings.urls.chat+'/api/v1/'+endpoint,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-User-Id':rc.id,'X-Auth-Token':rc.token},body:body?JSON.stringify(body):undefined});if(r.status===429){await new Promise(r=>setTimeout(r,30000));return chat(endpoint,body)}if(!r.ok)throw Error('chat '+r.status);return r.json()}
 const room=(await chat('im.create',{username:'report-bot'})).room._id;await chatPage.goto(settings.urls.chat+'/direct/report-bot');await chatPage.locator('textarea').first().waitFor({timeout:45000});const stamp=new Date().toISOString();await chatPage.locator('textarea').first().fill('시작');await chatPage.locator('textarea').first().press('Enter');let reply;
 for(let i=0;i<18;i++){await new Promise(r=>setTimeout(r,5000));reply=(await chat('im.history?roomId='+room+'&count=30')).messages.find(m=>m.u?.username==='report-bot'&&m.ts>=stamp&&m.msg.includes('보고할 프로젝트'));if(reply)break}
 assert(reply&&!reply.attachments.flatMap(a=>a.actions||[]).some(a=>a.text===project.name),'bot_menu_excludes_unlinked_project');
 // Empty-registry rendering without disconnecting any real project.
 await page.route('**/api/projects',route=>route.request().method()==='GET'?route.fulfill({json:{projects:[]}}):route.continue());await page.goto(settings.urls.portal);await page.locator('#task-grid').getByText('연결된 프로젝트가 없습니다.',{exact:false}).waitFor();assert(await page.locator('#new-task').isDisabled()&&await page.locator('#new-project').isVisible(),'empty_registry_keeps_management_available');await page.unroute('**/api/projects');
 await page.goto(settings.urls.portal);await page.locator('#new-project').click();await page.locator('#project-dialog').waitFor({state:'visible'});await page.screenshot({path:path.join(root,'reports/project-management-unlink.png'),fullPage:true});
}catch(error){if(page)await page.screenshot({path:path.join(root,'reports/unlink-failure.png'),fullPage:true});throw error}
finally{await browser.close()}
await admin.api('/api/sync',{});const final=(await admin.api('/api/tasks')).tasks;
assert(final.length===baseline.length&&baseline.every(t=>final.some(f=>f.id===t.id&&f.text===t.text)),'existing_user_tasks_unchanged');
assert(JSON.stringify((await admin.api('/api/projects')).projects.map(p=>p.id).sort())===JSON.stringify(baseProjects.map(p=>p.id).sort()),'existing_project_links_unchanged');
fs.writeFileSync(path.join(root,'reports/unlink-verification.json'),JSON.stringify({at:new Date().toISOString(),checks,preservedTestCollection:{id:project.id,name:project.name,referenceUrl:settings.urls.outline+ref.url},note:'Test collection and PRD deliberately preserved. Only test task-list documents were soft-deleted; original project links and tasks were unchanged.'},null,2));
console.log(JSON.stringify(checks,null,2));
