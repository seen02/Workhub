import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';
import {Session,root,settings,credentials} from './sso_test_client.mjs';
const session=new Session();await session.login(settings.urls.outline+'/auth/oidc',credentials.groupA);
async function api(method,body){const r=await session.fetch(settings.urls.outline+'/api/workhub.search.'+method,{method:'POST',headers:{'Content-Type':'application/json',Origin:settings.urls.outline,'X-CSRF-Token':decodeURIComponent(session.jar.get('csrfToken')||'')},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(method+' '+r.status);return d.data;}
async function run(){const start=Date.now(),request_id=crypto.randomUUID();await api('submit',{request_id,query:'검색 시연 A 설계 문서 링크 줘',mode:'links'});for(let n=0;n<60;n++){await new Promise(r=>setTimeout(r,1500));const d=await api('result',{request_id});if(['queued','running'].includes(d.status))continue;if(d.status!=='succeeded'||d.generation_calls!==0)throw Error('link regression');return {seconds:(Date.now()-start)/1000,backend_seconds:d.timings.total,generation_calls:d.generation_calls};}throw Error('timeout')}
const serial=[];for(let i=0;i<5;i++){serial.push(await run());console.log('PASS serial_link',i+1,serial.at(-1).seconds)}
const concurrent=await Promise.all([run(),run()]);console.log('PASS two_concurrent_links');
const values=serial.map(r=>r.seconds).sort((a,b)=>a-b),percentile=p=>values[Math.ceil(values.length*p)-1];
fs.writeFileSync(path.join(root,'reports/search-latency-results.json'),JSON.stringify({at:new Date().toISOString(),samples:5,p50:percentile(.5),p95:percentile(.95),max:values.at(-1),serial,concurrent,scope:'small local smoke measurement; not production capacity guarantee'},null,2));
