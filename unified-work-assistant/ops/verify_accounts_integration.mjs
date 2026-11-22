import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {Session,root,settings,credentials} from './sso_test_client.mjs';
const checks=[],timings={};
const assert=(ok,name)=>{if(!ok)throw Error(name);checks.push(name);console.log('PASS',name)};
const docker=(...args)=>execFileSync('docker',['compose',...args],{cwd:root,encoding:'utf8',stdio:['ignore','pipe','pipe']});
const sessions=[];
for(const c of [credentials.authentikAdmin,credentials.groupA,credentials.groupB]){const s=new Session();await s.login(settings.urls.portal+'/auth/login',c);s.csrf=(await s.api('/api/me')).csrf;sessions.push(s)}
const [admin,hong,kim]=sessions;
// Respect current user-adjusted permissions: Hong still belongs to the common
// project; do not silently restore a removed development collection grant.
const [,ops,dev]=JSON.parse(fs.readFileSync(path.join(root,'reports/unified-permissions-demo-manifest.json'))).projects;
const statuses=async(s,p,body)=>{const r=await s.fetch(settings.urls.portal+p,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json',Origin:settings.urls.portal,'X-CSRF-Token':s.csrf},body:body===undefined?undefined:JSON.stringify(body)});return r.status};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
async function ready(url){for(let i=0;i<50;i++){try{const r=await fetch(url);if(r.ok)return}catch{}await wait(1000)}throw Error('service recovery timeout')}
let original,task,pending;
try{
 assert(await statuses(hong,'/api/accounts')===403&&await statuses(hong,'/api/accounts/sync',{})===403,'worker cannot read or trigger account administration');
 const forged=await admin.fetch(settings.urls.portal+'/api/accounts/sync',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
 assert(forged.status===403,'account changes reject missing CSRF');
 const start=Date.now();
 const responses=await Promise.all(Array.from({length:10},(_,i)=>sessions[i%3].api(i%2?'/api/projects':'/api/tasks')));
 timings.concurrent_reads_ms=Date.now()-start;assert(responses.length===10,'10 simultaneous authenticated reads across three users');
 task=(await hong.api('/api/tasks?collection_id='+dev.id)).tasks.find(t=>t.id===dev.task_id);
 const saved=path.join(root,'.local/integration-original-criteria.json');
 original=fs.existsSync(saved)?JSON.parse(fs.readFileSync(saved,'utf8').replace(/^\uFEFF/,'')):task.criteria;
 if(!fs.existsSync(saved))fs.writeFileSync(saved,JSON.stringify(original));
 const cid=task.criteria[0].id;
 const drafts=await Promise.all(['진행 중','완료'].map(state=>hong.api('/api/tasks/'+task.id+'/proposals',{changes:{criterion_states:{[cid]:state}},idem:crypto.randomUUID()})));
 const results=await Promise.all(drafts.map(p=>statuses(hong,'/api/proposals/'+p.id+'/confirm',{})));
 assert(results.filter(s=>s===200).length===1&&results.some(s=>s===409),'simultaneous confirmations apply once and reject stale revision');
 pending=await hong.api('/api/tasks/'+task.id+'/proposals',{changes:{criterion_states:{[cid]:'예정'}},idem:crypto.randomUUID()});
 docker('restart','workhub');await ready(settings.urls.portal+'/health');
 assert((await hong.api('/api/proposals/'+pending.id)).state==='PENDING','pending draft and login survive Workhub restart');
 for(const [service,probe,restore] of [
   ['outline',()=>statuses(hong,'/api/projects'),settings.urls.outline+'/_health'],
   ['authentik-server',()=>statuses(hong,'/api/projects'),settings.urls.auth+'/-/health/ready/'],
   ['document-agent',()=>statuses(hong,'/api/research',{collection_id:dev.id,text:'배포 전에 무엇을 확인해야 하나요?'}),'http://localhost:3002/health']]){
   try{docker('stop','--timeout','15',service);const code=await probe();assert(code>=500&&code<600,service+' outage fails closed with explicit error');}
   finally{docker('start',service);await ready(restore);}
   assert((await hong.api('/api/projects')).projects.some(p=>p.id===dev.id),service+' recovery preserves access and data');
 }
 const aiStart=Date.now();
 const answers=await Promise.all([[hong,dev],[kim,ops]].map(async([s,p])=>{
   const d=await s.api('/api/research',{collection_id:p.id,text:'배포 전 확인 사항과 승인 담당자를 출처와 함께 알려줘.'});
   assert(d.sources?.length&&d.sources.every(x=>[p.document_id,p.task_id].includes(x.id)),'concurrent RAG answer scoped to '+p.name);
   return {project:p.name,status:d.status,mode:d.mode,sources:d.sources};
 }));timings.concurrent_ai_ms=Date.now()-aiStart;
 fs.writeFileSync(path.join(root,'reports/accounts-concurrent-ai.json'),JSON.stringify(answers,null,2));
 const invalidLogout=await fetch(settings.urls.webui+'/oauth/backchannel-logout',{method:'POST',body:new URLSearchParams({logout_token:'forged'})});
 assert(invalidLogout.status===400,'forged OIDC logout rejected');
}catch(e){console.error('INTEGRATION FAILURE:',e.message);throw e;}finally{
 if(pending)await hong.api('/api/proposals/'+pending.id+'/cancel',{}).catch(()=>{});
 try{
  if(task&&original){
   const idem=crypto.randomUUID();
   for(let i=0;i<4;i++){try{const p=await admin.api('/api/tasks/'+task.id+'/proposals',{changes:{criteria:original},idem});await admin.api('/api/proposals/'+p.id+'/confirm',{});break}catch(e){if(i===3)throw e;await wait(15000)}}
  }
 }finally{fs.writeFileSync(path.join(root,'reports/accounts-integration-verification.json'),JSON.stringify({at:new Date().toISOString(),checks,timings},null,2));}
}
console.log('Integration verification finished',JSON.stringify(timings));
