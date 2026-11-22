import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {Session,root,settings} from './sso_test_client.mjs';
const s=new Session();await s.portal();
const manifest=JSON.parse(fs.readFileSync(path.join(root,'reports/project-demo-manifest.json'))),reset=process.argv.includes('--reset');
for(const entry of manifest.tasks){
 let t=(await s.api('/api/tasks?collection_id='+entry.project.id)).tasks.find(t=>t.id===entry.id);
 if(!t)throw Error('시연 업무를 찾을 수 없습니다: '+entry.id);
 if(reset){
   const p=await s.api('/api/tasks/'+t.id+'/proposals',{changes:{criteria:t.criteria.map(i=>({...i,state:'예정'}))},idem:crypto.randomUUID(),notes:'시연 초기화: 완료 기준을 예정으로 되돌렸습니다. 이전 보고와 이력은 보존합니다.'});
   await s.api('/api/proposals/'+p.id+'/confirm',{});t=(await s.api('/api/tasks?collection_id='+entry.project.id)).tasks.find(t=>t.id===entry.id);
 }
 console.log(JSON.stringify({project:entry.project.name,project_code:entry.project.code,task:t.title,task_code:t.code,progress:t.fields.progress,criteria:t.criteria,url:t.url},null,2));
}
console.log('포털: '+settings.urls.portal+' · Rocket.Chat: '+settings.urls.chat);
if(reset)console.log('시연 두 업무의 항목만 예정으로 초기화했습니다. 원문 메모·배정·보고 이력은 보존했습니다.');
