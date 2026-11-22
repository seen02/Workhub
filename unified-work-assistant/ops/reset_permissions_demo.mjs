import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';
import {Session,root} from './sso_test_client.mjs';
const permissionTarget=process.env.WORKHUB_TEST_TARGET||'unified';
const reportPrefix=permissionTarget==='unified'?'unified-permissions':'permissions';
const permissionConfig=permissionTarget==='unified'?'.local/compose.json':'.local/permissions-compose.json';
const s=new Session();await s.portal();
const {projects}=JSON.parse(fs.readFileSync(path.join(root,'reports/'+reportPrefix+'-demo-manifest.json')));
for(const p of projects){
 const task=(await s.api('/api/tasks?collection_id='+p.id)).tasks.find(t=>t.id===p.task_id);
 if(!task)throw Error('Missing demo task: '+p.name);
 const states=Object.fromEntries(task.criteria.filter(i=>i.state!=='예정').map(i=>[i.id,'예정']));
 if(Object.keys(states).length){const draft=await s.api('/api/tasks/'+task.id+'/proposals',{changes:{criterion_states:states},idem:crypto.randomUUID()});await s.api('/api/proposals/'+draft.id+'/confirm',{});}
 console.log('RESET to 예정:',p.name);
}
console.log('Only the three demo task states were reset. Documents, permissions and audit history were retained.');
