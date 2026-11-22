import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {Session,root,settings} from './sso_test_client.mjs';
const s=new Session();await s.portal();
const manifest=JSON.parse(fs.readFileSync(path.join(root,'reports/team-demo-manifest.json')));
const current=async()=>(await s.api('/api/tasks?collection_id='+manifest.project.id)).tasks.find(t=>t.id===manifest.task.id);
let task=await current();if(!task)throw Error('팀 시연 업무를 찾을 수 없습니다.');
if(process.argv.includes('--reset')){
 const p=await s.api('/api/tasks/'+task.id+'/proposals',{changes:{criteria:task.criteria.map(i=>({...i,state:'예정'}))},idem:crypto.randomUUID(),notes:'팀 시연 초기화: 담당자와 기존 보고 이력을 보존하고 모든 완료 기준을 예정으로 되돌렸습니다.'});
 await s.api('/api/proposals/'+p.id+'/confirm',{});task=await current();
 if(task.fields.progress!=='0%'||task.criteria.some(i=>i.state!=='예정'))throw Error('초기화 확인 실패');
}
const names=Object.fromEntries(manifest.accounts.map(a=>[a.email,a.name]));
const ready={at:new Date().toISOString(),project:manifest.project.name,project_code:manifest.project.code,task:task.title,task_code:task.code,progress:task.fields.progress,criteria:task.criteria.map(i=>({...i,name:names[i.owner]||i.owner})),url:task.url};
fs.writeFileSync(path.join(root,'reports/team-demo-current.json'),JSON.stringify(ready,null,2));
console.log(JSON.stringify(ready,null,2));
console.log('포털: '+settings.urls.portal+' · Rocket.Chat: '+settings.urls.chat);
