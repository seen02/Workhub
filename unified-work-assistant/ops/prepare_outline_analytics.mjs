import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {Session,root,settings} from './sso_test_client.mjs';
const backup=path.join(root,'backups/pre-outline-analytics-20261001');
if(fs.existsSync(backup))throw Error('Backup already exists; do not overwrite');
fs.mkdirSync(backup,{recursive:true});
for(const name of ['.local/compose.json','src/workhub','integrations/outline/patches','integrations/outline/export_patch.py','integrations/outline/upstream.lock.json','config/nginx-local/default.conf']) {
 const dest=path.join(backup,name);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.cpSync(path.join(root,name),dest,{recursive:true});
}
const session=new Session();await session.portal();
const config=JSON.parse(fs.readFileSync(path.join(root,'.local/compose.json')));
const projects=(await session.api('/api/projects')).projects;
const tasks=(await session.api('/api/tasks')).tasks;
const documents=[];const key=config.services.workhub.environment.OUTLINE_API_KEY;
for(const p of projects){
 for(let offset=0;;offset+=100){
  const response=await fetch(settings.urls.outline+'/api/documents.list',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+key},body:JSON.stringify({collectionId:p.id,limit:100,offset})});
  if(!response.ok)throw Error('Baseline inventory failed '+response.status);
  const rows=(await response.json()).data;
  for(const d of rows){const r=await fetch(settings.urls.outline+'/api/documents.info',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+key},body:JSON.stringify({id:d.id})});if(!r.ok)throw Error('Baseline document failed');const doc=(await r.json()).data;documents.push({id:doc.id,revision:doc.revision,hash:crypto.createHash('sha256').update(doc.text||'').digest('hex')});}
  if(rows.length<100)break;
 }
}
fs.writeFileSync(path.join(root,'reports/outline-analytics-baseline.json'),JSON.stringify({at:new Date().toISOString(),projects,tasks:tasks.map(t=>({id:t.id,collectionId:t.collectionId})),documents},null,2));
console.log(JSON.stringify({backup:path.relative(root,backup),projects:projects.length,tasks:tasks.length,documents:documents.length}));
