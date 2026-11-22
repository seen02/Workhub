import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';
import {Session,root,settings} from './sso_test_client.mjs';
const fixture=JSON.parse(fs.readFileSync(path.join(root,'reports/search-live-fixture.json')));
const config=JSON.parse(fs.readFileSync(path.join(root,'.local/compose.json')));
const token=config.services.workhub.environment.OUTLINE_API_KEY;
const admin=new Session();await admin.login(settings.urls.outline+'/auth/oidc');
async function source(method,body){const r=await fetch(settings.urls.outline+'/api/'+method,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(method+' '+r.status);return d.data;}
async function api(method,body){const r=await admin.fetch(settings.urls.outline+'/api/workhub.search.'+method,{method:'POST',headers:{'Content-Type':'application/json',Origin:settings.urls.outline,'X-CSRF-Token':decodeURIComponent(admin.jar.get('csrfToken')||'')},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(method+' '+r.status);return d.data;}
const original=await source('documents.info',{id:fixture.other.id});
if(original.title!=='작업 메모')throw Error('Fixture changed; do not overwrite');
const at=Date.now(),marker='AUTOSYNC930';let written,result;
try{
  written=await source('documents.update',{id:original.id,title:'자동 갱신 '+marker,text:original.text+'\n\n'+marker+' 자동 갱신 확인.',lastRevision:original.revision});
  console.log('Waiting for automatic index update (no refresh request)');
  for(let n=0;n<35;n++){
    await new Promise(r=>setTimeout(r,12000));const request_id=crypto.randomUUID();
    await api('submit',{request_id,query:marker+' 문서 링크 줘',mode:'links',collection_id:fixture.b.id});
    for(let p=0;p<20;p++){await new Promise(r=>setTimeout(r,1500));result=await api('result',{request_id});if(!['queued','running'].includes(result.status))break;}
    if(result.documents?.some(d=>d.id===original.id&&d.title.includes(marker)))break;
  }
  if(!result.documents?.some(d=>d.id===original.id&&d.title.includes(marker)))throw Error('automatic update timeout');
  const seconds=(Date.now()-at)/1000;
  fs.writeFileSync(path.join(root,'reports/search-auto-update-results.json'),JSON.stringify({at:new Date().toISOString(),automatic_update:true,refresh_used_before_success:false,seconds},null,2));
  console.log('PASS automatic_outline_edit_reindexed',seconds);
}finally{
  if(written){const current=await source('documents.info',{id:original.id});if(current.revision!==written.revision)throw Error('Fixture changed by another writer; guarded restore stopped');
    await source('documents.update',{id:original.id,title:original.title,text:original.text,lastRevision:current.revision});
    await api('refresh',{collection_id:fixture.b.id});
    console.log('PASS demo_document_restored');}
}
