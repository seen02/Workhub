import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {Session,root,settings} from './sso_test_client.mjs';
const s=new Session(),me=await s.portal(),checks={},stamp=new Date().toISOString();
const assert=(condition,name)=>{if(!condition)throw Error(name);checks[name]=true;console.log('PASS',name)};
const cfg=JSON.parse(fs.readFileSync(path.join(root,'.local/compose.json'))),env=cfg.services['document-agent'].environment;
async function outline(endpoint,body){const r=await fetch(settings.urls.outline+'/api/'+endpoint,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+env.OUTLINE_API_KEY},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(endpoint+' '+r.status);return d.data;}
async function project(name){const ps=(await s.api('/api/projects')).projects;return ps.find(p=>p.name===name)||await s.api('/api/projects',{name,idem:'demo-'+crypto.randomUUID()})}
const a=await project('시연 · 고객 포털'),b=await project('시연 · 문서 자동화');
const base={owner:me.email,status:'미착수',progress:'0%',due:'2026-09-30',blocker:'없음',next:'완료 기준별 진행 보고',result:'없음'};
async function create(p,title,items,key){
  const old=(await s.api('/api/tasks?collection_id='+p.id)).tasks.find(t=>t.title===title);
  if(old)return old;
  return s.api('/api/tasks',{collection_id:p.id,title,fields:base,criteria:items.map(title=>({title,owner:me.email,state:'예정'})),notes:'프로젝트별 완료 기준 시연용입니다. 기존 자료를 변경하지 않습니다.',idem:'project-demo-'+key});
}
let t=await create(a,'고객 포털 출시',['요구사항 승인','화면 검증','배포 확인'],'portal'),other=await create(b,'문서 자동화 출시',['문서 수집','검색 검증'],'docs');
const reset=await s.api('/api/tasks/'+t.id+'/proposals',{changes:{criteria:t.criteria.map(i=>({...i,state:'예정'}))},idem:crypto.randomUUID()});await s.api('/api/proposals/'+reset.id+'/confirm',{});
t=(await s.api('/api/tasks?collection_id='+a.id)).tasks.find(x=>x.id===t.id);
assert(t.fields.progress==='0%','checklist_initial_zero');
assert(t.collectionId===a.id&&other.collectionId===b.id,'create_in_two_outline_collections');
assert(!(await s.api('/api/tasks?collection_id='+a.id)).tasks.some(x=>x.id===other.id),'project_task_filter');
const p=await s.api('/api/tasks/'+t.id+'/proposals',{changes:{criterion_states:{[t.criteria[0].id]:'완료',[t.criteria[1].id]:'진행 중'}},idem:crypto.randomUUID()});
assert((await outline('documents.info',{id:t.id})).text.includes('진행률: 0%'),'draft_does_not_modify_outline');
await s.api('/api/proposals/'+p.id+'/confirm',{});await s.api('/api/proposals/'+p.id+'/confirm',{});
let doc=await outline('documents.info',{id:t.id});
assert(doc.text.includes('진행률: 33.3%')&&doc.text.includes('- [x] '+t.criteria[0].id),'confirmation_checks_item_and_rolls_up');
assert(doc.text.includes(t.criteria[2].id+' | 배포 확인 | 담당자: '+me.email+' | 상태: 예정'),'unmentioned_item_preserved');
assert((await s.api('/api/tasks?collection_id='+a.id)).tasks.filter(x=>x.id===t.id).length===1,'repeat_confirm_no_duplicate');
const conflict=await s.api('/api/tasks/'+t.id+'/proposals',{changes:{criterion_states:{[t.criteria[2].id]:'완료'}},idem:crypto.randomUUID()});
await outline('documents.update',{id:t.id,text:doc.text.replace('- [ ] '+t.criteria[1].id,'- [x] '+t.criteria[1].id),lastRevision:doc.revision});
await s.api('/api/sync',{});doc=await outline('documents.info',{id:t.id});
assert(doc.text.includes('진행률: 66.7%'),'native_outline_checkbox_updates_progress');
let rejected=false;try{await s.api('/api/proposals/'+conflict.id+'/confirm',{})}catch(e){rejected=e.message.includes('409')}
assert(rejected,'stale_proposal_rejected');
await outline('documents.update',{id:t.id,text:doc.text.replace('- [x] '+t.criteria[1].id,'- [ ] '+t.criteria[1].id),lastRevision:doc.revision});await s.api('/api/sync',{});
assert((await outline('documents.info',{id:t.id})).text.includes('진행률: 33.3%'),'native_outline_uncheck_reopens');
for(const state of ['완료','진행 중','예정']){
  const next=await s.api('/api/tasks/'+t.id+'/proposals',{changes:{criterion_states:{[t.criteria[2].id]:state}},idem:crypto.randomUUID()});await s.api('/api/proposals/'+next.id+'/confirm',{});
  assert((await s.api('/api/tasks?collection_id='+a.id)).tasks.find(x=>x.id===t.id).criteria[2].state===state,'state_transition_'+state);
}
const stats=await s.api('/api/stats?collection_id='+a.id);
assert(stats.summary.total===1&&stats.criteria.total===3&&stats.criteria.completed===1&&stats.criteria.progress===33.3,'project_statistics_and_criterion_denominator');
assert((await s.api('/api/stats?collection_id='+b.id)).criteria.completed===0,'other_project_unchanged');
const weekly=await s.api('/api/weekly?collection_id='+a.id),pub=await s.api('/api/weekly/'+weekly.id+'/publish',{});
const published=await outline('documents.info',{id:pub.doc_id});assert(published.collectionId===a.id,'summary_published_in_selected_collection');
await s.api('/api/sync',{});assert((await s.api('/api/stats?collection_id='+a.id)).summary.total===1,'summary_not_counted_as_task');
// Leave a deterministic reusable demo; the live AI/bot test will take it from 0 to 33.3 to 100.
const current=(await s.api('/api/tasks?collection_id='+a.id)).tasks.find(x=>x.id===t.id);
const back=await s.api('/api/tasks/'+t.id+'/proposals',{changes:{criteria:current.criteria.map(i=>({...i,state:'예정'}))},idem:crypto.randomUUID()});await s.api('/api/proposals/'+back.id+'/confirm',{});
const manifest={at:stamp,projects:[a,b],tasks:[{...t,project:a},{...other,project:b}]};
fs.writeFileSync(path.join(root,'reports/project-demo-manifest.json'),JSON.stringify(manifest,null,2));
fs.writeFileSync(path.join(root,'reports/project-verification.json'),JSON.stringify({at:stamp,checks},null,2));
console.log(JSON.stringify({checks,projects:[a,b],task_code:t.code},null,2));
