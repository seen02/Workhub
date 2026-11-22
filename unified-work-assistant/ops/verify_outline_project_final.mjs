import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {Session,root,settings} from './sso_test_client.mjs';
const session=new Session();await session.portal();
const baseline=JSON.parse(fs.readFileSync(path.join(root,'reports/outline-project-baseline.json')));
const config=JSON.parse(fs.readFileSync(path.join(root,'.local/compose.json')));
const key=config.services.workhub.environment.OUTLINE_API_KEY;
const projects=(await session.api('/api/projects')).projects;
if(JSON.stringify(projects.map(p=>p.id).sort())!==JSON.stringify(baseline.projects.map(p=>p.id).sort()))throw Error('Original project registry changed');
let verified=0;
for(const d of baseline.documents){
 const r=await fetch(settings.urls.outline+'/api/documents.info',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+key},body:JSON.stringify({id:d.id})});
 if(!r.ok)throw Error('Original document unreadable '+r.status);
 const value=(await r.json()).data;
 if(crypto.createHash('sha256').update(value.text||'').digest('hex')!==d.hash)throw Error('Original document changed '+d.id);
 verified++;
}
const tasks=(await session.api('/api/tasks')).tasks;
if(tasks.length!==baseline.tasks.length||!baseline.tasks.every(t=>tasks.some(c=>c.id===t.id&&c.collectionId===t.collectionId)))throw Error('Original task inventory changed');
const target=projects.find(p=>p.name==='팀 협업 시연')||projects[0];
const rag=await session.api('/api/research/status?collection_id='+target.id);
const operations=await session.api('/api/operations');
const stats=await session.api('/api/analytics');
const result={at:new Date().toISOString(),originalProjects:projects.length,originalDocumentsVerified:verified,originalTasks:tasks.length,originalDataPreserved:true,
 rag:{state:rag.state,documents:rag.documents,failed:rag.failed},bot:operations.bot,sync:operations.sync?{ok:operations.sync.ok,at:operations.sync.at}:null,analyticsAvailable:!!stats.summary};
if(result.sync?.ok!==true)throw Error('Workhub document synchronization is not healthy');
fs.writeFileSync(path.join(root,'reports/outline-project-final-health.json'),JSON.stringify(result,null,2));
console.log(JSON.stringify(result,null,2));
