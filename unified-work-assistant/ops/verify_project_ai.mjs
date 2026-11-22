import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {Session,root} from './sso_test_client.mjs';
const s=new Session();await s.portal();
const manifest=JSON.parse(fs.readFileSync(path.join(root,'reports/project-demo-manifest.json'))),task=manifest.tasks[0],p=task.project;
const results=[],checks={};
const assert=(v,name)=>{if(!v)throw Error(name);checks[name]=true;console.log('PASS',name)};
const current=async()=>(await s.api('/api/tasks?collection_id='+p.id)).tasks.find(t=>t.id===task.id);
let t=await current();const reset=await s.api('/api/tasks/'+t.id+'/proposals',{changes:{criteria:t.criteria.map(i=>({...i,state:'예정'}))},idem:crypto.randomUUID()});await s.api('/api/proposals/'+reset.id+'/confirm',{});
const cases=[
  {raw:'요구사항은 다 끝냈어. 화면 검증은 아직 손보는 중이고 배포 확인은 내일 할 거야.',states:['완료','진행 중','예정'],progress:'33.3%'},
  {raw:'화면 검증도 끝났고 배포 확인도 끝났어.',states:['완료','완료','완료'],progress:'100%'},
  {raw:'배포 확인은 완료한 게 아니라 아직 진행 중이야.',states:['완료','완료','진행 중'],progress:'66.7%'}
];
for(const [index,c] of cases.entries()){
  const before=await current(),started=Date.now(),draft=await s.api('/api/report',{code:task.id,collection_id:p.id,text:c.raw,idem:crypto.randomUUID()});
  assert(draft.formatted_report.startsWith('**[업무목록]**')&&draft.formatted_report.includes(p.name),'original_format_'+index);
  assert((await current()).fields.progress===before.fields.progress,'ai_draft_private_'+index);
  await s.api('/api/proposals/'+draft.id+'/confirm',{});const after=await current();
  assert(JSON.stringify(after.criteria.map(i=>i.state))===JSON.stringify(c.states),'natural_language_states_'+index);
  assert(after.fields.progress===c.progress,'rollup_'+c.progress);
  results.push({input:c.raw,seconds:Math.round((Date.now()-started)/100)/10,formatted_report:draft.formatted_report,interpretation:draft.interpretation,progress:after.fields.progress});
  fs.writeFileSync(path.join(root,'reports/project-ai-verification.json'),JSON.stringify({at:new Date().toISOString(),model:draft.model,checks,results},null,2));
}
const before=await current();let clarified=false;
try{await s.api('/api/report',{code:task.id,collection_id:p.id,text:'고생은 했는데 어디까지 됐는지는 모르겠어.',idem:crypto.randomUUID()})}catch(e){clarified=e.message.includes('422')}
assert(clarified,'unclear_report_requests_clarification');assert((await current()).fields.progress===before.fields.progress,'unclear_report_does_not_change_source');
fs.writeFileSync(path.join(root,'reports/project-ai-verification.json'),JSON.stringify({at:new Date().toISOString(),checks,results},null,2));
console.log(JSON.stringify({checks,results},null,2));
