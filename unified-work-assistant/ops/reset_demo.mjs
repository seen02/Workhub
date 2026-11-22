import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {Session,root} from './sso_test_client.mjs';
// Explicitly resets ONLY the three document IDs created by seed_demo; keeps report history and notes.
const manifest=JSON.parse(fs.readFileSync(path.join(root,'reports/demo-manifest.json')));
const session=new Session();await session.portal();
const reset={main:{status:'미착수',progress:'0%'},done:{status:'완료',progress:'100%'},delayed:{status:'지연',progress:'30%'}};
for(const t of manifest.tasks){
 const p=await session.api('/api/tasks/'+t.id+'/proposals',{changes:reset[t.key],idem:'reset-demo-'+crypto.randomUUID()});
 await session.api('/api/proposals/'+p.id+'/confirm',{});
}
await session.api('/api/sync',{});
console.log(JSON.stringify({reset_tasks:manifest.tasks.map(t=>t.code),history_preserved:true,summary:(await session.api('/api/stats?project='+encodeURIComponent('통합 시연'))).summary},null,2));
