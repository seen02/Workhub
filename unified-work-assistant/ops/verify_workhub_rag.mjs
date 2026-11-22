import fs from 'node:fs';
import assert from 'node:assert/strict';
import {Session,root,settings,credentials} from './sso_test_client.mjs';
const s=new Session();await s.portal();
const projects=(await s.api('/api/projects')).projects;
const report={at:new Date().toISOString(),cases:[]};
for(const [name,question,expect] of [
 ['팀 협업 시연','고객 포털의 요구사항에서 배포 전에 확인할 항목을 찾아줘. 출처도 알려줘.','sources'],
 ['팀 협업 시연','출시 전에 어떤 점검을 해야 하는지 알려줘.','sources'],
 ['팀 협업 시연','이 프로젝트의 확정된 예산 총액과 계약 금액은 얼마인가요?','no_amount'],
 ['시연 · 고객 포털','고객 포털 배포 전 확인할 사항과 담당자를 알려줘.','sources'],
 ['시연 · 문서 자동화','DEMO-RELEASE-0921 점검표를 찾아줘.','none'],
 ]){
 const p=projects.find(p=>p.name===name);assert(p,name);
 const start=Date.now();const result=await s.api('/api/research',{collection_id:p.id,text:question});
 assert.notEqual(result.status,'failed',JSON.stringify(result));
 if(expect==='sources')assert(result.sources?.length>0,JSON.stringify(result));
 if(expect==='none')assert.equal(result.sources?.length||0,0);
 if(expect==='no_amount')assert(!/\d[\d,.]*\s*(만원|억원|원)/.test(result.report||result.display));
 const entry={project:name,collection_id:p.id,question,seconds:(Date.now()-start)/1000,result};
 report.cases.push(entry);fs.writeFileSync(root+'/reports/workhub-rag-live-2026-09-21.json',JSON.stringify(report,null,2));
 console.log(JSON.stringify({project:name,question,seconds:entry.seconds,sources:result.sources?.length,metrics:result.metrics,answer:result.report||result.display}));
}
const employee=new Session();await employee.login(settings.urls.portal+'/auth/login',credentials.groupA);
const me=await employee.api('/api/me');employee.csrf=me.csrf;
const p=projects.find(p=>p.name==='팀 협업 시연');
const result=await employee.api('/api/research',{collection_id:p.id,text:'사용자 안내와 배포 점검 준비는 누가 맡나요?'});
assert(result.sources.length>0);
report.employee={name:me.name,result};
let denied=false;try{await employee.api('/api/research/refresh',{collection_id:p.id,text:'자료 새로고침'})}catch(e){denied=/403/.test(e.message)}assert(denied);
report.employee.refresh_denied=denied;
fs.writeFileSync(root+'/reports/workhub-rag-live-2026-09-21.json',JSON.stringify(report,null,2));
console.log(JSON.stringify({employee:me.name,sources:result.sources.length,refresh_denied:denied}));
