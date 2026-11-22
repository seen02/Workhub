import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {Session,root,settings,credentials} from './sso_test_client.mjs';
const admin=new Session(),worker=new Session(),checks={};
await admin.login(settings.urls.outline+'/auth/oidc',credentials.authentikAdmin);
await worker.login(settings.urls.outline+'/auth/oidc',credentials.groupA);
async function api(session,method,body={},raw=false){
 const r=await session.fetch(settings.urls.outline+'/api/'+method,{method:'POST',headers:{'Content-Type':'application/json',Origin:settings.urls.outline,'X-CSRF-Token':decodeURIComponent(session.jar.get('csrfToken')||'')},body:JSON.stringify(body)});
 const result=await r.json();if(raw)return {status:r.status,data:result};
 if(!r.ok)throw Error(method+' '+r.status+' '+result.message);return result.data;
}
const assert=(v,key)=>{if(!v)throw Error(key);checks[key]=true;console.log('PASS',key)};
const caps=await api(admin,'workhub.capabilities');
const workerInfo=await api(worker,'auth.info');
let collection,linked=false;
try{
 collection=await api(admin,'collections.create',{name:'[검증] 진행 통계 권한 회수 '+Date.now(),permission:null});
 await api(admin,'workhub.projectLink',{collectionId:collection.id,requestId:crypto.randomUUID(),managerSubject:caps.subject});linked=true;
 await api(admin,'collections.add_user',{id:collection.id,userId:workerInfo.user.id,permission:'read'});
 const before=await api(worker,'workhub.analyticsQuery',{collectionId:collection.id,managed:false});
 assert(before.filter_options.projects.some(p=>p.id===collection.id),'live_granted_project_visible');
 await api(admin,'collections.remove_user',{id:collection.id,userId:workerInfo.user.id});
 assert([403,404].includes((await api(worker,'workhub.analyticsQuery',{collectionId:collection.id,managed:false},true)).status),'same_session_revoked_project_denied');
 const after=await api(worker,'workhub.analyticsQuery',{managed:false});
 assert(!after.linked_ids.includes(collection.id)&&!after.filter_options.projects.some(p=>p.id===collection.id),'revoked_project_removed_from_all_range');
}finally{
 if(collection){
  if(linked){const info=await api(admin,'workhub.projectInfo',{collectionId:collection.id});await api(admin,'workhub.projectUnlink',{collectionId:collection.id,requestId:crypto.randomUUID(),expectedRevision:info.revision});}
  await api(admin,'collections.delete',{id:collection.id});
  checks.fixture_unlinked_and_trashed=true;
 }
 fs.writeFileSync(path.join(root,'reports/outline-analytics-revocation.json'),JSON.stringify({at:new Date().toISOString(),checks,fixture:collection?.id},null,2));
}
