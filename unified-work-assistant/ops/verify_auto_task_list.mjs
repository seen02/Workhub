import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {Session,settings,root} from './sso_test_client.mjs';

for(let i=0;i<30;i++) {
  try {if((await fetch(settings.urls.outline+'/_health')).ok)break;}catch{}
  await new Promise(resolve=>setTimeout(resolve,1000));
}
const session=new Session();
await session.login(settings.urls.outline+'/auth/oidc');
async function api(method,body={}) {
  const response=await session.fetch(settings.urls.outline+'/api/'+method,{
    method:'POST',headers:{'Content-Type':'application/json',Origin:settings.urls.outline,
      'X-CSRF-Token':decodeURIComponent(session.jar.get('csrfToken')||'')},body:JSON.stringify(body)});
  const result=await response.json();
  if(!response.ok)throw Error(method+' '+response.status+' '+result.message);
  return result.data;
}
const checks={};
function check(ok,name){if(!ok)throw Error(name);checks[name]=true;console.log('PASS',name)}
const created=[];
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE);
const browser=await chromium.launch({headless:true,channel:'msedge'});
try {
  const context=await browser.newContext();
  await context.addCookies([...session.jar].filter(([name])=>!name.startsWith('authentik')).map(([name,value])=>({name,value,domain:new URL(settings.urls.outline).hostname,path:'/',httpOnly:!name.includes('csrf'),sameSite:'Lax'})));
  const page=await context.newPage();
  const collection=await api('collections.create',{name:'[검증] 업무 목록 자동 생성 '+Date.now(),permission:null});created.push(collection.id);
  check((await api('documents.list',{collectionId:collection.id})).length===0,'ordinary_collection_has_no_automatic_document');
  await page.goto(settings.urls.outline+'/workhub/projects/'+collection.id);
  await page.getByTestId('workhub-link').waitFor({timeout:45000});
  await page.getByTestId('workhub-link').click();
  await page.getByTestId('workhub-unlink').waitFor({timeout:45000});
  const documents=await api('documents.list',{collectionId:collection.id});
  console.log('New root comparison',JSON.stringify(documents.map(d=>({id:d.id,title:d.title,parentDocumentId:d.parentDocumentId,publishedAt:d.publishedAt,collectionId:d.collectionId}))));
  check(documents.length===1&&documents[0].title==='업무 목록'&&!documents[0].parentDocumentId&&!!documents[0].publishedAt,'browser_link_creates_one_published_root');
  const parent=documents[0];
  const state=await api('workhub.projectInfo',{collectionId:collection.id});
  await api('workhub.projectUnlink',{collectionId:collection.id,requestId:crypto.randomUUID(),expectedRevision:state.revision});
  const link={collectionId:collection.id,requestId:crypto.randomUUID(),expectedRevision:state.revision+1,managerSubject:null};
  await api('workhub.projectLink',link);await api('workhub.projectLink',link);
  const after=await api('documents.list',{collectionId:collection.id});
  check(after.length===1&&after[0].id===parent.id,'relink_and_duplicate_request_reuse_same_root');

  const existing=await api('collections.create',{name:'[검증] 기존 업무 목록 재사용 '+Date.now(),permission:null});created.push(existing.id);
  const original=await api('documents.create',{collectionId:existing.id,title:'업무 목록',text:'사람이 작성한 업무 안내를 보존합니다.',publish:true});
  const before=await api('documents.info',{id:original.id});
  await api('workhub.projectLink',{collectionId:existing.id,requestId:crypto.randomUUID(),expectedRevision:0,managerSubject:null});
  const reused=await api('documents.info',{id:original.id});
  const roots=await api('documents.list',{collectionId:existing.id});
  console.log('Existing root comparison',JSON.stringify({count:roots.length,ids:roots.map(d=>d.id),before:{id:before.id,revision:before.revision,text:before.text},after:{id:reused.id,revision:reused.revision,text:reused.text}}));
  check(roots.length===1&&before.text===reused.text&&before.revision===reused.revision,'existing_root_content_and_revision_preserved');
} finally {
  await browser.close();
  // Only collections created by this execution are cleaned up.
  for(const collectionId of created) {
    const state=await api('workhub.projectInfo',{collectionId});
    if(state.linked)await api('workhub.projectUnlink',{collectionId,requestId:crypto.randomUUID(),expectedRevision:state.revision});
    await api('collections.delete',{id:collectionId});
  }
}
fs.writeFileSync(path.join(root,'reports/outline-auto-task-list-live.json'),JSON.stringify({at:new Date().toISOString(),checks,temporaryCollectionsRemoved:created},null,2));
