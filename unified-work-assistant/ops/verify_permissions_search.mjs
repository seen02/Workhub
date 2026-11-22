import fs from 'node:fs';import path from 'node:path';
import {Session,root,settings,credentials} from './sso_test_client.mjs';
const permissionTarget=process.env.WORKHUB_TEST_TARGET||'unified';
const reportPrefix=permissionTarget==='unified'?'unified-permissions':'permissions';
const permissionConfig=permissionTarget==='unified'?'.local/compose.json':'.local/permissions-compose.json';
const {projects}=JSON.parse(fs.readFileSync(path.join(root,'reports/'+reportPrefix+'-demo-manifest.json'))),admin=new Session();await admin.portal();
const results=[];
for(const [index,account] of [[0,credentials.groupA],[1,credentials.groupB]]){
 const p=projects[index],s=new Session();await s.login(settings.urls.portal+'/auth/login',account);s.csrf=(await s.api('/api/me')).csrf;
 await admin.api('/api/research/refresh',{collection_id:p.id,text:'권한 시연 자료 갱신'});
 const r=await s.api('/api/research',{collection_id:p.id,text:'배포 전에 확인해야 할 항목과 승인 담당자는? 출처도 알려줘.'});
 if(!r.sources?.length||r.sources.some(x=>x.id!==p.document_id&&x.id!==p.task_id)||JSON.stringify(r).includes(projects[1-index].marker))throw Error('RAG scope/source validation failed');
 results.push({user:account.email,project:p.name,status:r.status,mode:r.mode,sources:r.sources.map(x=>({id:x.id,title:x.title,url:x.url})),display:r.display||r.report});
 console.log('PASS RAG sources and answer:',account.email,p.name);
}
fs.writeFileSync(path.join(root,'reports/'+reportPrefix+'-rag-verification.json'),JSON.stringify({at:new Date().toISOString(),results},null,2));
