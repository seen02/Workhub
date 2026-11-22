import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {Session,root,settings,credentials} from './sso_test_client.mjs';
const checks={},assert=(v,k)=>{if(!v)throw Error(k);checks[k]=true;console.log('PASS',k)};
const config=JSON.parse(fs.readFileSync(path.join(root,'.local/compose.json')));
const key=config.services.workhub.environment.OUTLINE_API_KEY;
for(let attempt=0;attempt<45;attempt++){try{const response=await fetch(settings.urls.outline+'/_health');if(response.ok)break}catch{}await new Promise(r=>setTimeout(r,1000))}
async function source(method,body={}){const r=await fetch(settings.urls.outline+'/api/'+method,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+key},body:JSON.stringify(body)});if(!r.ok)throw Error(method+' '+r.status);return (await r.json()).data}
const admin=new Session();await admin.login(settings.urls.outline+'/auth/oidc');
async function api(session,method,body={},raw=false){const r=await session.fetch(settings.urls.outline+'/api/'+method,{method:'POST',headers:{'Content-Type':'application/json',Origin:settings.urls.outline,'X-CSRF-Token':decodeURIComponent(session.jar.get('csrfToken')||'')},body:JSON.stringify(body)});const d=await r.json();if(raw)return {status:r.status,body:d};if(!r.ok)throw Error(method+' '+r.status+' '+d.message);return d.data}
const cap=await api(admin,'workhub.capabilities');assert(cap.manage,'outline_login_without_workhub_session');
assert(!admin.jar.has('workhub_session'),'workhub_cookie_not_required');
assert((await fetch(settings.urls.portal+'/internal/outline-projects/info',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).status===404,'internal_api_not_public');
const baseline=JSON.parse(fs.readFileSync(path.join(root,'reports/outline-project-baseline.json')));
for(const p of baseline.projects){const i=await api(admin,'workhub.projectInfo',{collectionId:p.id});assert(i.linked,'existing_link_'+p.id.slice(0,8))}
if(process.argv.includes('--smoke')){console.log('Smoke passed');process.exit(0)}
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE);
const browser=await chromium.launch({headless:true,channel:'msedge'});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
await context.addCookies([...admin.jar].filter(([name])=>!name.startsWith('authentik')).map(([name,value])=>({name,value,domain:new URL(settings.urls.outline).hostname,path:'/',httpOnly:!name.includes('csrf'),sameSite:'Lax'})));
let page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
page.on('response',async r=>{if(r.url().includes('/api/workhub.')&&!r.ok())console.log('BRIDGE_UI_ERROR',r.status(),r.url(),await r.text())});
const statePath=path.join(root,'reports/outline-project-live-fixture.json');
let fixture=fs.existsSync(statePath)?JSON.parse(fs.readFileSync(statePath)):null;
try{
  await page.goto(settings.urls.outline+'/home');
  await page.waitForTimeout(2500);
  if(!fixture){
    // Exercise the real native collection modal using Outline's keyboard shortcut menu.
    await page.keyboard.press('Control+Alt+n').catch(()=>{});
    const newCollection=page.getByText(/^(새 컬렉션|New collection|컬렉션 추가)$/).first();
    if(await newCollection.count()){await newCollection.click()}
    else {await page.keyboard.press('Escape');await page.getByRole('button',{name:/New collection|새 컬렉션|컬렉션 추가/}).first().click()}
    const checkbox=page.getByTestId('workhub-register-project');await checkbox.waitFor({timeout:30000});
    await checkbox.check({timeout:30000});
    const dialog=page.getByRole('dialog');
    const name='[검증] Outline 프로젝트 관리 '+Date.now();
    await dialog.locator('input[name="name"]').fill(name);
    const created=page.waitForResponse(r=>r.url().includes('/api/collections.create')&&r.request().method()==='POST');
    await dialog.locator('button[type="submit"]').click();
    const response=await created;const result=await response.json();assert(response.ok(),'native_collection_create');
    fixture={id:result.data.id,name};fs.writeFileSync(statePath,JSON.stringify(fixture,null,2));
    await page.getByTestId('workhub-project').waitFor({timeout:30000});
    assert(!(await api(admin,'workhub.projectInfo',{collectionId:fixture.id})).linked,'creation_does_not_link_before_confirm');
  }else{await page.goto(settings.urls.outline+'/workhub/projects/'+fixture.id)}
  await page.getByTestId('workhub-project').waitFor({timeout:45000});
  const info=()=>api(admin,'workhub.projectInfo',{collectionId:fixture.id});
  if(!(await info()).linked){
    await page.getByTestId('workhub-link').click();
    await page.getByTestId('workhub-unlink').waitFor({timeout:45000});
  }
  assert((await info()).linked,'native_project_link');
  await page.screenshot({path:path.join(root,'reports/outline-project-linked.png'),fullPage:true});
  const portal=new Session();const me=await portal.portal();
  if(!fixture.task){
    const ref=await source('documents.create',{collectionId:fixture.id,title:'PRD · 보존 확인',text:'프로젝트 연결 해제 후에도 보존되어야 하는 참고 문서입니다.',publish:true});
    const task=await portal.api('/api/tasks',{collection_id:fixture.id,title:'새 프로젝트 기존 업무 흐름 확인',fields:{owner:me.email,status:'미착수',progress:'0%'},idem:crypto.randomUUID()});
    fixture={...fixture,ref:ref.id,task:task.id,parent:task.parentDocumentId};fs.writeFileSync(statePath,JSON.stringify(fixture,null,2));
  }
  assert((await portal.api('/api/tasks?collection_id='+fixture.id)).tasks.some(t=>t.id===fixture.task),'existing_task_creation');
  const original=await source('documents.info',{id:fixture.task});
  const proposal=await portal.api('/api/tasks/'+fixture.task+'/proposals',{changes:{status:'진행 중'},idem:crypto.randomUUID()});
  const confirmed=await portal.api('/api/proposals/'+proposal.id+'/confirm',{});
  assert(confirmed.state==='APPLIED','existing_report_confirmation');
  assert((await source('documents.info',{id:fixture.task})).text!==original.text,'report_updates_outline_original');
  assert((await portal.api('/api/analytics?collection_id='+fixture.id)).projects!==undefined,'existing_statistics');
  await page.getByTestId('workhub-unlink').click();
  await page.getByTestId('workhub-unlink-submit').waitFor();
  assert(!(await page.getByTestId('workhub-delete').isChecked()),'unlink_preserves_documents_default');
  await page.screenshot({path:path.join(root,'reports/outline-project-unlink.png'),fullPage:true});
  const unlinkResponse=page.waitForResponse(r=>r.url().includes('workhub.projectUnlink')&&!r.url().includes('Preview'));
  await page.getByTestId('workhub-unlink-submit').click();const unlinked=await unlinkResponse;const oldRequest=JSON.parse(unlinked.request().postData());
  await page.getByTestId('workhub-link').waitFor();await page.waitForTimeout(1000);
  assert(!(await info()).linked,'native_unlink');
  assert((await source('documents.info',{id:fixture.task})).id===fixture.task,'task_document_preserved');
  assert((await source('documents.info',{id:fixture.parent})).id===fixture.parent,'task_parent_preserved');
  assert((await source('documents.info',{id:fixture.ref})).id===fixture.ref,'reference_document_preserved');
  assert(!(await portal.api('/api/tasks')).tasks.some(t=>t.collectionId===fixture.id),'unlinked_excluded_from_tasks');
  await page.getByTestId('workhub-link').click();await page.getByTestId('workhub-unlink').waitFor({timeout:45000});
  assert((await info()).linked,'native_reconnect');
  await api(admin,'workhub.projectUnlink',oldRequest);assert((await info()).linked,'old_unlink_cannot_remove_reconnection');
  await portal.api('/api/sync',{});assert((await portal.api('/api/tasks?collection_id='+fixture.id)).tasks.some(t=>t.id===fixture.task&&t.parentDocumentId===fixture.parent),'reconnect_keeps_task_ids');
  await page.getByTestId('workhub-unlink').click();await page.locator('summary').filter({hasText:'고급 옵션'}).click();
  await page.getByTestId('workhub-delete').check();
  await page.screenshot({path:path.join(root,'reports/outline-project-unlink-delete.png'),fullPage:true});
  await page.getByTestId('workhub-unlink-submit').click();await page.waitForTimeout(1500);
  assert(!(await info()).linked,'native_optional_delete_unlink');
  const trash=await source('documents.deleted',{collectionId:fixture.id,limit:100});
  assert(trash.some(d=>d.id===fixture.task)&&trash.some(d=>d.id===fixture.parent),'only_task_subtree_in_trash');
  assert((await source('collections.info',{id:fixture.id})).id===fixture.id&&(await source('documents.info',{id:fixture.ref})).id===fixture.ref,'collection_and_reference_survive');
  const employee=new Session();await employee.login(settings.urls.outline+'/auth/oidc',credentials.groupA);
  const employeeCap=await api(employee,'workhub.capabilities');assert(!employeeCap.manage,'employee_cannot_manage');
  const denied=await api(employee,'workhub.projectLink',{collectionId:fixture.id,requestId:crypto.randomUUID(),expectedRevision:(await info()).revision},true);
  assert(denied.status===403,'employee_mutation_denied');
  const spoof=await api(admin,'workhub.projectInfo',{collectionId:fixture.id,actor:{outlineUserId:'other'}},true);assert(spoof.status===400,'browser_actor_spoof_rejected');
  assert(errors.length===0,'no_browser_javascript_errors');
  await portal.api('/api/sync',{});
  const after=(await portal.api('/api/projects')).projects;
  assert(JSON.stringify(after.map(p=>p.id).sort())===JSON.stringify(baseline.projects.map(p=>p.id).sort()),'original_project_registry_unchanged');
  for(const d of baseline.documents){const current=await source('documents.info',{id:d.id});assert(crypto.createHash('sha256').update(current.text||'').digest('hex')===d.hash,'original_document_'+d.id.slice(0,8))}
  fs.writeFileSync(path.join(root,'reports/outline-project-live-results.json'),JSON.stringify({at:new Date().toISOString(),checks,fixture,browserErrors:errors},null,2));
  console.log('Live verification complete:',Object.keys(checks).length,'checks');
}catch(error){await page.screenshot({path:path.join(root,'reports/outline-project-failure.png'),fullPage:true});console.log((await page.locator('body').innerText()).slice(-3500));throw error}
finally{await browser.close()}
