import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';
import {Session,root,settings,credentials} from './sso_test_client.mjs';
const checks={},assert=(v,k)=>{if(!v)throw Error(k);checks[k]=true;console.log('PASS',k)};
const config=JSON.parse(fs.readFileSync(path.join(root,'.local/compose.json')));
const key=config.services.workhub.environment.OUTLINE_API_KEY;
async function source(method,body={}){const r=await fetch(settings.urls.outline+'/api/'+method,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+key},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(method+' '+r.status+' '+d.message);return d.data;}
const admin=new Session();await admin.login(settings.urls.outline+'/auth/oidc');
const worker=new Session();await worker.login(settings.urls.outline+'/auth/oidc',credentials.groupA);
async function api(session,method,body={},raw=false){const r=await session.fetch(settings.urls.outline+'/api/workhub.search.'+method,{method:'POST',headers:{'Content-Type':'application/json',Origin:settings.urls.outline,'X-CSRF-Token':decodeURIComponent(session.jar.get('csrfToken')||'')},body:JSON.stringify(body)});const d=await r.json();if(raw)return {status:r.status,data:d};if(!r.ok)throw Error(method+' '+r.status+' '+d.message);return d.data;}
async function query(session,text,cid,mode='links'){const request_id=crypto.randomUUID();await api(session,'submit',{request_id,query:text,mode,collection_id:cid});for(let n=0;n<70;n++){await new Promise(r=>setTimeout(r,2500));const r=await api(session,'result',{request_id});if(!['queued','running'].includes(r.status))return {request_id,...r};}throw Error('query timeout')}
async function project(method,body={}){const r=await admin.fetch(settings.urls.outline+'/api/workhub.'+method,{method:'POST',headers:{'Content-Type':'application/json',Origin:settings.urls.outline,'X-CSRF-Token':decodeURIComponent(admin.jar.get('csrfToken')||'')},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(method+' '+r.status);return d.data;}
const statePath=path.join(root,'reports/search-edge-fixture.json');
let f=fs.existsSync(statePath)?JSON.parse(fs.readFileSync(statePath)):{};
if(f.cleaned)f={};
const save=()=>fs.writeFileSync(statePath,JSON.stringify(f,null,2));
if(!f.collection){f.collection=await source('collections.create',{name:'[검증] 검색 권한과 갱신',permission:null});save();}
if(!f.doc){f.doc=await source('documents.create',{collectionId:f.collection.id,title:'비공개 검증 설계서',text:'검증용 기록입니다. 공개하면 안 되는 토큰은 SECRETMARK314입니다.',publish:true});save();}
if(!f.report){f.report=await source('documents.create',{collectionId:f.collection.id,title:'로그인 화면 점검 기록',text:'# 현재 상태\n\n로그인 화면 만들기는 완료했습니다.\n\n# 보고 기록\n\n[9월 29일 화요일 : 9시]\n\n로그인 화면 만들기는 진행 중입니다.\n\n[9월 29일 화요일 : 13시]\n\n로그인 화면 만들기는 완료했습니다.\n\n# 템플릿 예시\n\n로그인 화면 만들기는 예정입니다. 이 문장은 보고 작성 예시입니다.',publish:true});save();}
const person=(await source('users.list',{limit:100})).find(p=>p.email===credentials.groupA.email);
assert(person,'worker_outline_identity');
await source('collections.add_user',{id:f.collection.id,userId:person.id,permission:'read'});
try {
  await project('projectLink',{collectionId:f.collection.id,requestId:crypto.randomUUID(),expectedRevision:0});
  assert((await api(admin,'catalog')).collections.some(c=>c.id===f.collection.id&&c.project&&c.included),'project_link_auto_includes_search');
  await api(admin,'include',{collection_id:f.collection.id,included:true});
  const pi=await project('projectInfo',{collectionId:f.collection.id});
  await project('projectUnlink',{collectionId:f.collection.id,requestId:crypto.randomUUID(),expectedRevision:pi.revision,deleteTaskList:false});
  assert((await api(admin,'catalog')).collections.some(c=>c.id===f.collection.id&&!c.project&&c.knowledge&&c.included),'unlink_keeps_independent_knowledge');
  assert((await source('documents.info',{id:f.doc.id})).id===f.doc.id,'unlink_preserves_original_document');
  const cat=await api(worker,'catalog');assert(cat.collections.some(c=>c.id===f.collection.id),'granted_collection_discovered');
  for(let n=0;n<70;n++){const c=(await api(admin,'catalog')).collections.find(c=>c.id===f.collection.id);if(c?.documents>=1&&['ready','syncing'].includes(c.state))break;await new Promise(r=>setTimeout(r,2500));}
  const r=await query(worker,'비공개 검증 설계서 링크 줘',f.collection.id);assert(r.documents?.some(d=>d.id===f.doc.id),'granted_private_document_found');
  const morning=await query(worker,'9월 29일 9시 보고에서 로그인 화면 만들기는 어떤 상태였어?',f.collection.id,'answer');
  fs.writeFileSync(path.join(root,'reports/search-time-result.json'),JSON.stringify(morning,null,2));
  assert(morning.documents?.some(d=>d.id===f.report.id)&&morning.answer.includes('진행')&&!morning.answer.includes('완료')&&!morning.answer.includes('예정'),'morning_report_not_afternoon_or_template');
  assert((await api(admin,'result',{request_id:r.request_id},true)).status===404,'job_cannot_be_read_by_other_user');
  await source('collections.remove_user',{id:f.collection.id,userId:person.id});
  const revoked=await api(worker,'result',{request_id:r.request_id},true);
  assert(revoked.status===403,'revocation_blocks_saved_answer');
  assert(!JSON.stringify(revoked).includes('비공개 검증 설계서'),'revocation_no_title_leak');
  const hidden=await api(worker,'catalog');assert(!hidden.collections.some(c=>c.id===f.collection.id),'private_collection_hidden_after_revocation');
  const a=await query(admin,'비공개 검증 설계서 링크 줘',f.collection.id);
  await source('documents.update',{id:f.doc.id,title:'변경된 검증 설계서',text:'갱신 검증 기록입니다. SECRETMARK315로 변경되었습니다.'});
  assert((await api(admin,'result',{request_id:a.request_id},true)).status===409,'revision_change_blocks_saved_answer');
  await api(admin,'refresh',{collection_id:f.collection.id});
  let latest;
  for(let n=0;n<20;n++){latest=await query(admin,'변경된 검증 설계서 링크 줘',f.collection.id);if(latest.documents?.some(d=>d.id===f.doc.id))break;await new Promise(r=>setTimeout(r,3000));}
  assert(latest.documents?.some(d=>d.title==='변경된 검증 설계서'),'updated_document_reindexed');
  await api(admin,'include',{collection_id:f.collection.id,included:false});
  assert((await api(admin,'result',{request_id:latest.request_id},true)).status===409,'last_inclusion_removal_blocks_saved_result');
  await api(admin,'include',{collection_id:f.collection.id,included:true});
  await source('documents.archive',{id:f.doc.id});
  const archived=await api(admin,'result',{request_id:latest.request_id},true);
  assert([403,409].includes(archived.status)&&!JSON.stringify(archived).includes('SECRETMARK315'),'archive_blocks_saved_result');
  await source('documents.restore',{id:f.doc.id});
  await source('documents.delete',{id:f.doc.id});
  const deleted=await api(admin,'result',{request_id:latest.request_id},true);
  assert([403,409].includes(deleted.status)&&!JSON.stringify(deleted).includes('SECRETMARK315'),'delete_blocks_saved_result');
  const request_id=crypto.randomUUID();await api(admin,'submit',{request_id,query:'설계',mode:'links',collection_id:f.collection.id});
  assert((await api(admin,'cancel',{request_id})).status==='cancelled','cancel_job');
  assert((await api(admin,'result',{request_id})).status==='cancelled','cancelled_result_not_restored');
}finally {
  try{const pi=await project('projectInfo',{collectionId:f.collection.id});if(pi.linked)await project('projectUnlink',{collectionId:f.collection.id,requestId:crypto.randomUUID(),expectedRevision:pi.revision,deleteTaskList:false});}catch{}
  await api(admin,'include',{collection_id:f.collection.id,included:false}).catch(()=>{});
  await source('collections.delete',{id:f.collection.id}).catch(()=>{});
  f.cleaned=true;save();
  fs.writeFileSync(path.join(root,'reports/search-edge-results.json'),JSON.stringify({at:new Date().toISOString(),checks,cleaned:true},null,2));
}
