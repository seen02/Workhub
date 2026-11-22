import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {Session,root,settings} from './sso_test_client.mjs';
const configPath=path.join(root,'.local/compose.json');
const config=JSON.parse(fs.readFileSync(configPath));
const env=config.services.workhub.environment;
const session=new Session();await session.portal();
const baselinePath=path.join(root,'reports/outline-project-baseline.json');
async function outline(method,body={}){const r=await fetch(settings.urls.outline+'/api/'+method,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+env.OUTLINE_API_KEY},body:JSON.stringify(body)});if(!r.ok)throw Error(method+' '+r.status);return (await r.json()).data}
if(!fs.existsSync(baselinePath)){
 const projects=(await session.api('/api/projects')).projects,tasks=(await session.api('/api/tasks')).tasks;
 const docs=[];
 for(const p of projects){for(let offset=0;;offset+=100){const page=await outline('documents.list',{collectionId:p.id,offset,limit:100});for(const d of page){const full=await outline('documents.info',{id:d.id});docs.push({id:d.id,collectionId:p.id,hash:crypto.createHash('sha256').update(full.text||'').digest('hex')})}if(page.length<100)break}}
 fs.writeFileSync(baselinePath,JSON.stringify({at:new Date().toISOString(),projects,tasks:tasks.map(t=>({id:t.id,collectionId:t.collectionId})),documents:docs},null,2));
 console.log('Baseline saved:',projects.length,'projects,',docs.length,'documents');
}
const auth=await outline('auth.info');
const secret=env.OUTLINE_WORKHUB_BRIDGE_SECRET||crypto.randomBytes(48).toString('hex');
Object.assign(env,{OUTLINE_PROJECT_MANAGEMENT_ENABLED:'true',OUTLINE_WORKHUB_BRIDGE_SECRET:secret,OUTLINE_WORKHUB_TEAM_ID:auth.team.id});
Object.assign(config.services.outline.environment,{OUTLINE_PROJECT_MANAGEMENT_ENABLED:'true',OUTLINE_WORKHUB_BRIDGE_SECRET:secret,WORKHUB_INTERNAL_URL:'http://workhub:8000'});
config.services.outline.image='unified-work-assistant/outline:project-management-20260930';
config.services.workhub.image='unified-work-assistant/workhub:project-management-20260930';
fs.writeFileSync(configPath,JSON.stringify(config,null,2)+'\n');
console.log('Prepared local Outline and Workhub settings. No credentials printed.');
