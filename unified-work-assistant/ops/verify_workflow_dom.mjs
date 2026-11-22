// Build a browser-run integration fixture from the current production markup and UI scripts.
// All API calls are replaced in the generated page; no production data is read or changed.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const root = path.resolve(import.meta.dirname, '..');
const staticDir = path.join(root, 'src/workhub/static');
const index = fs.readFileSync(path.join(staticDir, 'index.html'), 'utf8');
let source = fs.readFileSync(path.join(staticDir, 'projects.js'), 'utf8');
if (!/boot\(\);\s*$/.test(source)) throw Error('Expected final boot() call was not found');
source = source.replace(/boot\(\);\s*$/, '');
const analytics = fs.readFileSync(path.join(staticDir, 'analytics.js'), 'utf8');
const body = index.match(/<body[^>]*>([\s\S]*?)<\/body>/i)?.[1]
  .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');
if (!body) throw Error('Production body was not found');
const css = ['style.css', 'analytics.css', 'workflow.css']
  .filter(name => fs.existsSync(path.join(staticDir, name)))
  .map(name => fs.readFileSync(path.join(staticDir, name), 'utf8')).join('\n');

const fixture = String.raw`
const fixtureChecks=[], fixtureErrors=[], fixtureCalls=[];
let fixtureReportGate=null, fixtureResearchGate=null;
const fixtureProposals=new Map(), deniedProposals=new Set();
let fixtureProjects=[], fixtureTasks=[];
const fixtureMe={sub:'workflow-fixture-only',email:'hong@example.test',name:'홍길동',admin:false,csrf:'fixture',links:{outline:location.origin,chat:location.origin,webui:location.origin}};
const fixtureNames={'hong@example.test':'홍길동','kim@example.test':'김철수','lead@example.test':'팀장'};
const fixturePeople=Object.entries(fixtureNames).map(([email,name],i)=>({id:'person-'+i,email,name,username:name}));
const fixtureToday=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const fixtureDate=offset=>new Date(Date.parse(fixtureToday)+offset*86400000).toISOString().slice(0,10);
const clone=value=>structuredClone(value);
const pause=()=>new Promise(resolve=>setTimeout(resolve,0));
const deferred=()=>{let resolve,reject;const promise=new Promise((ok,fail)=>{resolve=ok;reject=fail});return {promise,resolve,reject}};
const check=(name,condition,detail='')=>{fixtureChecks.push({name,pass:!!condition,...(!condition&&detail?{detail}:{} )})};
const run=async(name,fn)=>{try{await fn()}catch(e){fixtureChecks.push({name,pass:false,error:e.message});fixtureErrors.push({name,message:e.message,stack:e.stack})}};
async function until(predicate,label){for(let i=0;i<80;i++){if(predicate())return;await pause()}throw Error('Timed out: '+label)}
const shown=()=>$$('#task-grid [data-open-task]').map(b=>b.dataset.openTask);
const change=(selector,value)=>{const el=$(selector);el.value=value;el.dispatchEvent(new Event('change',{bubbles:true}))};
const input=(selector,value)=>{const el=$(selector);el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}))};
function makeTask(taskId,title,due,owner=fixtureMe.email,status='진행 중',criterionOwner=owner,collectionId='project-a'){
 const criteria=[{id:'C-'+(taskId==='shared-late'?'00000002':'00000001'),title:title+' 확인',owner:criterionOwner,state:status==='완료'?'완료':'예정'}];
 return {id:taskId,title,collectionId,collectionName:collectionId==='project-a'?'프로젝트 A':'프로젝트 B',url:location.origin+'/fixture-document/'+taskId,updatedAt:'2026-09-23T00:00:00Z',criteria,fields:{owner,status,progress:status==='완료'?'100%':'0%',due,blocker:'없음',next:'검증 항목 확인',result:'없음'},text:'상태: '+status+'\n진행률: '+(status==='완료'?'100%':'0%')+'\n## 완료 기준\n- [ ] '+criteria[0].id+' | '+criteria[0].title+' | 담당자: '+criterionOwner+' | 상태: 예정'};
}
function baseTasks(){return [
 makeTask('own-late','내 지연 업무',fixtureDate(-2)),
 makeTask('shared-late','함께 하는 지연 업무',fixtureDate(-1),'kim@example.test','진행 중',fixtureMe.email),
 makeTask('other-late','다른 사람 지연 업무',fixtureDate(-4),'kim@example.test'),
 makeTask('done-late','유일한 완료 업무',fixtureDate(-5),fixtureMe.email,'완료'),
 makeTask('today','오늘 할 업무',fixtureDate(0)),
 makeTask('day7','7일 뒤 업무',fixtureDate(7)),
 makeTask('day8','8일 뒤 업무',fixtureDate(8)),
 makeTask('no-due','마감일 없는 업무','미정'),
 ...Array.from({length:8},(_,i)=>makeTask('extra-'+i,'추가 업무 '+i,fixtureDate(12+i))),
 makeTask('b-task','B 업무',fixtureDate(4),fixtureMe.email,'진행 중',fixtureMe.email,'project-b')
 ]}
function makeProposal(taskId,proposalId='proposal-'+taskId,state='PENDING'){
 const task=fixtureTasks.find(t=>t.id===taskId);
 if(!task)throw Error('Unknown fixture task '+taskId);
 return {id:proposalId,doc_id:task.id,collectionId:task.collectionId,title:task.title,state,url:task.url,before:task.text,after:task.text.replace('상태: 예정','상태: 완료'),evidence:'모의 보고',formatted_report:'[업무 보고]\n'+task.title+' 진행 상황을 확인했습니다.',result:state==='APPLIED'?{status:'완료',progress:'100%',criteria_total:1,criteria_done:1,criteria:task.criteria.map(i=>({...i,state:'완료'}))}:undefined};
}
api=async function(pathname,body){
 fixtureCalls.push({path:pathname,body:body===undefined?undefined:clone(body)});
 const parsed=new URL(pathname,location.origin),route=parsed.pathname;
 if(route==='/api/projects')return {projects:clone(fixtureProjects)};
 if(route==='/api/assignees')return {people:clone(fixturePeople),names:clone(fixtureNames)};
 if(route==='/api/tasks'&&body===undefined)return {tasks:clone(fixtureTasks.filter(t=>t.collectionId===parsed.searchParams.get('collection_id'))),sync:{ok:true,at:new Date().toISOString()}};
 if(route==='/api/tasks'&&body!==undefined){
  if(!body.fields?.status)throw Object.assign(Error('업무 상태는 필수입니다.'),{status:400});
  const person=fixturePeople.find(p=>p.id===body.assignee_id);if(!person)throw Object.assign(Error('담당자를 선택하세요.'),{status:400});
  const created=makeTask('created-workflow-task',body.title,body.fields.due,person.email,body.fields.status,person.email,body.collection_id);
  created.fields={...created.fields,...clone(body.fields),owner:person.email};
  created.criteria=(body.criteria||[]).map((item,i)=>({id:'C-'+String(10+i).padStart(8,'0'),title:item.title,owner:fixturePeople.find(p=>p.id===item.assignee_id)?.email||item.owner,state:item.state}));
  fixtureTasks.push(created);return clone(created);
 }
 if(route==='/api/research/status')return {state:'ready',documents:2,synced_at:new Date().toISOString()};
 if(route==='/api/research')return fixtureResearchGate?fixtureResearchGate.promise:{report:'현재 프로젝트의 모의 검색 결과',sources:[],retrieval:true};
 if(route==='/api/report'){
  const gate=fixtureReportGate;fixtureReportGate=null;
  const proposal=gate?await gate.promise:makeProposal(body.code,'report-'+fixtureCalls.length);
  fixtureProposals.set(proposal.id,clone(proposal));return clone(proposal);
 }
 const create=route.match(/^\/api\/tasks\/([^/]+)\/proposals$/);
 if(create){const p=makeProposal(create[1],'direct-'+fixtureCalls.length);fixtureProposals.set(p.id,clone(p));return p}
 const proposal=route.match(/^\/api\/proposals\/([^/]+)(?:\/(confirm|cancel))?$/);
 if(proposal){
  if(deniedProposals.has(proposal[1]))throw Object.assign(Error('권한이 없는 초안입니다.'),{status:403});
  const saved=fixtureProposals.get(proposal[1]);if(!saved)throw Object.assign(Error('초안을 찾을 수 없습니다.'),{status:404});
  if(proposal[2]){saved.state=proposal[2]==='cancel'?'CANCELLED':'APPLIED';saved.cancelled_at=new Date().toISOString();if(saved.state==='APPLIED')saved.result=makeProposal(saved.doc_id,saved.id,'APPLIED').result}
  return clone(saved);
 }
 if(route==='/api/sync')return {ok:true};
 throw Error('Unstubbed API call: '+pathname);
};
window.fetch=async()=>{throw Error('Fixture network access is disabled')};
async function refreshAccounts(){}
async function resetFixture(){
 fixtureCalls.length=0;fixtureReportGate=null;fixtureResearchGate=null;fixtureProposals.clear();deniedProposals.clear();
 fixtureProjects=[{id:'project-a',name:'프로젝트 A',manager:'lead@example.test'},{id:'project-b',name:'프로젝트 B',manager:'lead@example.test'}];fixtureTasks=baseTasks();
 me=clone(fixtureMe);names=clone(fixtureNames);people=clone(fixturePeople);tasks=[];projects=[];mine=true;active='tasks';
 selectedTask='';reportTaskId='';reportStage=1;reportMethod='ai';assistantMode='report';currentProposal=null;reportBusy=false;
 boardProject='';boardRenderKey='';boardFocus='open';boardPage=1;boardRequest++;reportDrafts.clear();pendingReports.clear();sessionStorage.removeItem(draftKey());
 $('#search').value='';$('#board-status').value='';$('#board-sort').value='due';$('#report-task').value='';$('#report-text').value='';$('#report-criterion').value='';$('#criterion-state').value='예정';
 $('#proposal').replaceChildren();history.replaceState(null,'',location.pathname+location.search);$('#notice').textContent='';
 await loadProjects('project-a');await load();tab('tasks');setAssistantMode('report');setReportStage(1);setReportMethod('ai');
}

(async()=>{
 await run('업무 보드 프로젝트 버튼 선택',async()=>{
  await resetFixture();check('보드에서는 프로젝트 선택 버튼을 표시하고 드롭다운 숨김',!$('#board-project-picker').hidden&&$('#project-select').closest('label').hidden&&$$('[data-board-project]').length===2);
  $('[data-board-project="project-b"]').click();await until(()=>boardProject==='project-b','프로젝트 버튼 B 선택');check('버튼 선택은 해당 프로젝트 업무를 불러오고 선택 표시',selected()==='project-b'&&tasks.every(t=>t.collectionId==='project-b')&&$('[data-board-project="project-b"]').getAttribute('aria-pressed')==='true');
  check('프로젝트 관리 버튼은 업무 추가와 같은 기본 강조 버튼',!$('#new-project').classList.contains('secondary'));
  tab('assistant');check('AI 비서의 기존 프로젝트 선택 유지',$('#board-project-picker').hidden&&!$('#project-select').closest('label').hidden);
 });
 await run('보드 담당 범위와 마감 경계',async()=>{
  await resetFixture();boardFocus='overdue';draw();
  check('내 업무는 주 담당자와 내 완료 기준이 있는 업무를 포함',JSON.stringify(shown())===JSON.stringify(['own-late','shared-late']),JSON.stringify(shown()));
  check('완료한 과거 마감 업무는 마감 초과에 포함하지 않음',!shown().includes('done-late'));
  $('[data-board-focus="soon"]').click();check('곧 마감은 오늘과 7일째를 포함하고 8일째는 제외',JSON.stringify(shown())===JSON.stringify(['today','day7']),JSON.stringify(shown()));
  $('#all').click();$('[data-board-focus="overdue"]').click();check('팀 전체 전환 시 다른 담당자의 지연 업무도 포함',shown()[0]==='other-late'&&shown().length===3);
  $('#mine').click();$('#board-reset').click();input('#search','김철수');check('내 항목이 있는 업무를 주 담당자 이름으로 검색',JSON.stringify(shown())===JSON.stringify(['shared-late']));
 });
 await run('페이지와 필터 연결',async()=>{
  await resetFixture();check('목록은 한 페이지 8개',shown().length===8&&!$('#board-pagination').hidden);
  $('#board-next').click();check('다음 페이지 이동',boardPage===2&&shown().length>0);
  input('#search','오늘 할 업무');check('검색하면 1페이지로 이동하며 단일 결과 표시',boardPage===1&&JSON.stringify(shown())===JSON.stringify(['today']));
  input('#search','');change('#board-status','완료');check('완료 상태 선택은 미완료 빠른 필터와 충돌하지 않음',boardFocus==='all'&&JSON.stringify(shown())===JSON.stringify(['done-late']));
  $('#board-reset').click();check('필터 초기화는 검색과 상태를 지움',$('#search').value===''&&$('#board-status').value==='');
  input('#search','존재하지 않는 문구');check('검색 빈 상태가 초기화 행동을 제시',$('#board-empty-action')?.textContent==='필터 초기화');$('#board-empty-action').click();check('빈 상태에서 목록 복구',shown().length===8);
 });
 await run('명시적 보고 선택과 입력 보존',async()=>{
  await resetFixture();tab('assistant');check('비서 직접 진입 시 첫 업무 자동 선택 안 함',$('#report-task').value===''&&$('#make-report').disabled&&$('#report-text').disabled);
  startReport('own-late');check('보드에서 진입한 업무를 명시적으로 선택',$('#report-task').value==='own-late'&&!$('#report-text').disabled);
  input('#report-text','검증은 완료했고 배포를 준비하고 있습니다.');const editor=$('#report-text');editor.focus();const detail=$('#report-example');detail.open=true;
  fixtureTasks.find(t=>t.id==='own-late').fields.progress='25%';await loadProjects();await load();
  check('자동 갱신 중 보고 업무·내용·포커스·펼침 보존',$('#report-task').value==='own-late'&&$('#report-text')===editor&&editor.value.includes('검증은 완료')&&document.activeElement===editor&&detail.open);
  change('#report-task','day7');check('다른 업무에 앞 업무 메모가 섞이지 않음',$('#report-text').value==='');change('#report-task','own-late');check('업무를 다시 선택하면 메모 복원',$('#report-text').value.includes('검증은 완료'));
  setReportMethod('direct');change('#report-criterion','C-00000001');change('#criterion-state','완료');fixtureTasks.find(t=>t.id==='own-late').updatedAt='2026-09-23T00:01:00Z';await load();
  check('직접 선택한 완료 상태를 자동 갱신이 덮어쓰지 않음',$('#criterion-state').value==='완료','현재 값: '+$('#criterion-state').value);
 });
 await run('통계에서 업무를 열 때 보드 필터 정리',async()=>{
  await resetFixture();boardFocus='overdue';boardPage=2;const task=fixtureTasks.find(t=>t.id==='today');
  analyticsData={owner:'',horizon:7,actions:[{...clone(task),owner:task.fields.owner,status:task.fields.status,progress:task.fields.progress,due:task.fields.due,days_remaining:0,flags:['due_soon'],remaining:1,next:task.fields.next}]};
  planningFocus='all';planningPage=1;$('#planning-search').value='';drawPlanning();location.hash=taskDetailHref(task).split('#')[1];await openTaskLink();
  check('통계 업무 확인은 이전 보드 필터에 숨지 않고 선택 업무 상세를 표시',active==='tasks'&&boardFocus==='all'&&boardPage===1&&selectedTask==='today'&&!$('#task-detail').hidden&&$('#task-detail').textContent.includes('오늘 할 업무'));
 });
 await run('느린 보고 요청과 화면 이동',async()=>{
  await resetFixture();startReport('own-late');input('#report-text','지연 업무 확인을 끝냈습니다.');const gate=deferred();fixtureReportGate=gate;
  const first=submitReport($('#make-report'));await pause();
  check('보고 요청 동안 프로젝트·업무·완료 기준 선택 잠금',$('#project-select').disabled&&$('#report-task').disabled&&$('#report-criterion').disabled);
  await submitReport($('#make-report'));check('연속 제출 시 보고 API는 한 번만 호출',fixtureCalls.filter(c=>c.path==='/api/report').length===1);
  tab('tasks');gate.resolve(makeProposal('own-late','slow-a'));await first;
  check('다른 화면을 보는 중 응답이 와도 강제로 초안 화면으로 바꾸지 않음',active==='tasks'&&pendingReports.get('own-late')?.id==='slow-a'&&!$('#pending-report-bar').hidden);
  await resumeProposal('own-late');check('초안 계속하기는 원래 프로젝트와 업무 표시',active==='assistant'&&$('#proposal').textContent.includes('프로젝트 A')&&$('#proposal').textContent.includes('내 지연 업무'));
  await loadProjects();await load();check('자동 갱신 후에도 확인 단계 프로젝트 선택기는 숨김',$('#project-bar').hidden&&reportStage===2);
 });
 await run('다른 대상을 반환한 보고 거부',async()=>{
  await resetFixture();startReport('own-late');input('#report-text','지연 업무 확인을 끝냈습니다.');const gate=deferred();fixtureReportGate=gate;const request=submitReport($('#make-report'));gate.resolve(makeProposal('b-task','wrong-b'));await request;
  check('서버 응답 대상이 다르면 초안 표시와 기억을 거부',!pendingReports.size&&currentProposal===null&&$('#proposal').hidden&&$('#notice').textContent.includes('보고 대상이 달라'));
  check('대상 오류 후에도 원래 입력 메모를 유지',$('#report-text').value==='지연 업무 확인을 끝냈습니다.');
 });
 await run('초안 수정과 같은 업무 복귀',async()=>{
  await resetFixture();startReport('own-late');input('#report-text','수정할 원본 메모입니다.');await submitReport($('#make-report'));const proposalId=currentProposal.id;
  check('초안 URL로 복귀 위치를 보관',location.hash==='#proposal-'+proposalId);
  await $('#edit-proposal').onclick({target:$('#edit-proposal')});
  check('입력 수정은 이전 초안만 취소하고 메모를 복원',fixtureProposals.get(proposalId).state==='CANCELLED'&&!pendingReports.has('own-late')&&reportStage===1&&$('#report-task').value==='own-late'&&$('#report-text').value==='수정할 원본 메모입니다.');
  check('수정 과정에는 확정 호출 없음',!fixtureCalls.some(c=>c.path.endsWith('/confirm')));
  await submitReport($('#make-report'));const secondId=currentProposal.id;await $('#cancel-proposal').onclick({target:$('#cancel-proposal')});
  check('초안 취소 결과 표시 및 확정 비활성',currentProposal.state==='CANCELLED'&&$('#proposal').textContent.includes('초안 취소 완료')&&$('#confirm').disabled&&fixtureProposals.get(secondId).state==='CANCELLED');
  await loadProjects('project-b');await load();await $('#back-board').onclick({target:$('#back-board')});
  check('다른 프로젝트에서 돌아가도 처리한 원래 업무 상세로 이동',active==='tasks'&&selected()==='project-a'&&selectedTask==='own-late'&&$('#task-detail').textContent.includes('내 지연 업무'));
 });
 await run('세션 초안 복구와 권한 상실',async()=>{
  await resetFixture();startReport('own-late');input('#report-text','권한 없는 상태에 남으면 안 되는 메모');await submitReport($('#make-report'));const p=clone(currentProposal);
  reportDrafts.clear();pendingReports.clear();recoverDrafts();check('같은 탭 새로고침용 메모·초안 ID 복구',reportDrafts.get('own-late')?.text.includes('권한 없는')&&pendingReports.get('own-late')?.id===p.id);
  deniedProposals.add(p.id);try{await resumeProposal('own-late')}catch(e){check('권한 없는 초안은 서버 403으로 거부',e.status===403)}
  const stored=JSON.parse(sessionStorage.getItem(draftKey())||'{}');
  check('권한 거부 후 초안 ID와 작성 메모 모두 제거',!pendingReports.has('own-late')&&!reportDrafts.has('own-late')&&!JSON.stringify(stored).includes('권한 없는'));
  check('권한 거부 후 이전 초안 DOM과 메모를 계속 표시하지 않음',!$('#report-text').value.includes('권한 없는')&&($('#proposal').hidden||!$('#proposal').textContent.includes(p.title)));
 });
 await run('프로젝트 변경 뒤 메모 소속과 접근 회수',async()=>{
  await resetFixture();startReport('own-late');input('#report-text','프로젝트 A의 비공개 작성 메모');change('#project-select','project-b');await until(()=>boardProject==='project-b','메모 작성 후 B 이동');
  check('프로젝트 변경 시 A 메모를 B 프로젝트 소속으로 덮어쓰지 않음',reportDrafts.get('own-late')?.collectionId==='project-a','저장된 소속: '+reportDrafts.get('own-late')?.collectionId);
  fixtureProjects=fixtureProjects.filter(p=>p.id==='project-b');await loadProjects();
  check('다른 프로젝트를 보는 동안 A 권한 회수 시에도 A 메모 제거',!reportDrafts.has('own-late')&&!sessionStorage.getItem(draftKey()).includes('비공개 작성 메모'));
 });
 await run('확정 중 권한 거부 시 기존 초안 재노출 방지',async()=>{
  await resetFixture();startReport('own-late');input('#report-text','확정 시 접근을 회수할 업무 메모');await submitReport($('#make-report'));const proposalId=currentProposal.id;deniedProposals.add(proposalId);
  await $('#confirm').onclick({target:$('#confirm')});
  check('확정과 재조회 모두 권한 거부되면 이전 초안을 다시 기억하지 않음',!pendingReports.has('own-late')&&!reportDrafts.has('own-late'));
  check('확정 권한 거부 뒤 원래 초안과 입력 메모를 제거',currentProposal===null&&$('#proposal').hidden&&!$('#report-text').value.includes('접근을 회수'));
 });
 await run('보고 처리 도중 프로젝트 권한 회수',async()=>{
  await resetFixture();startReport('own-late');input('#report-text','처리 중 권한이 회수될 메모');const gate=deferred();fixtureReportGate=gate;const request=submitReport($('#make-report'));await pause();
  fixtureProjects=fixtureProjects.filter(p=>p.id==='project-b');await loadProjects('project-b');await load();gate.resolve(makeProposal('own-late','revoked-while-waiting'));await request;
  check('권한 회수 후 도착한 응답은 초안 목록과 메모를 되살리지 않음',!pendingReports.has('own-late')&&!reportDrafts.has('own-late')&&($('#pending-report-bar').hidden||!$('#pending-report-bar').textContent.includes('내 지연 업무')));
 });
 await run('업무 배정 회수 후 작성 화면 정리',async()=>{
  await resetFixture();startReport('own-late');input('#report-text','배정 회수 뒤 남지 않을 메모');await submitReport($('#make-report'));
  const task=fixtureTasks.find(t=>t.id==='own-late');task.fields.owner='kim@example.test';task.criteria.forEach(i=>i.owner='kim@example.test');await load();
  check('다른 담당자로 배정되면 작성 메모·초안 제거',!reportDrafts.has('own-late')&&!pendingReports.has('own-late')&&currentProposal===null);
  check('배정 회수 뒤 다른 업무를 자동 선택하지 않음',$('#report-task').value===''&&$('#make-report').disabled&&$('#report-text').value==='');
 });
 await run('자료 검색의 과거 응답 방지',async()=>{
  await resetFixture();tab('assistant');setAssistantMode('research');input('#research-text','프로젝트 A 요구사항은?');const gate=deferred();fixtureResearchGate=gate;
  $('#research-form').dispatchEvent(new SubmitEvent('submit',{bubbles:true,cancelable:true,submitter:$('#research-form button')}));await pause();
  change('#project-select','project-b');await until(()=>boardProject==='project-b','프로젝트 B 로드');change('#project-select','project-a');await until(()=>boardProject==='project-a','프로젝트 A 복귀');
  gate.resolve({report:'과거 요청 결과 표시는 금지',retrieval:true,sources:[]});await pause();await pause();
  check('프로젝트 A→B→A 뒤 늦은 A 응답을 표시하지 않음',!$('#research-result').textContent.includes('과거 요청 결과 표시는 금지'));
 });
 await run('업무와 담당자 조회를 함께 시작',async()=>{
  await resetFixture();const originalAPI=api,taskGate=deferred(),peopleGate=deferred(),started=[];
  api=async(path,body)=>{if(path.startsWith('/api/tasks?')){started.push('tasks');return taskGate.promise}if(path.startsWith('/api/assignees?')){started.push('people');return peopleGate.promise}return originalAPI(path,body)};
  try{const pending=load();await pause();check('업무 응답을 기다리지 않고 담당자 조회도 시작',started.includes('tasks')&&started.includes('people'));
   peopleGate.resolve({people:clone(fixturePeople),names:clone(fixtureNames)});taskGate.resolve({tasks:clone(fixtureTasks.filter(t=>t.collectionId==='project-a')),sync:{ok:true,at:new Date().toISOString()}});await pending;
   check('동시 조회 완료 후 선택 프로젝트의 업무 표시',boardProject==='project-a'&&tasks.every(t=>t.collectionId==='project-a'));
  }finally{api=originalAPI}
 });
 await run('업무 등록 창 즉시 열기와 취소 보호',async()=>{
  await resetFixture();const originalAPI=api,gate=deferred();api=async(path,body)=>path.startsWith('/api/assignees?')?gate.promise:originalAPI(path,body);
  try{const pending=$('#new-task').onclick({target:$('#new-task')});
   check('담당자 조회 전에도 등록 창 즉시 표시',$('#create-dialog').open&&!$('#create-form').elements.title.disabled);
   check('담당자 조회 중에는 저장과 배정 잠금',!createReady&&$('#create-form').elements.assignee_id.disabled&&$('#create-form').querySelector('button:not([type])').disabled);
   $('#close-create').click();await pause();gate.resolve({people:clone(fixturePeople),names:clone(fixtureNames)});await pending;
   check('닫은 창은 늦은 조회 응답으로 다시 열리지 않음',!$('#create-dialog').open&&!createReady);
  }finally{api=originalAPI}
 });
 await run('등록 담당자 조회 실패 시 저장 차단',async()=>{
  await resetFixture();const originalAPI=api;api=async(path,body)=>{if(path.startsWith('/api/assignees?'))throw Object.assign(Error('접근 권한 없음'),{status:403});return originalAPI(path,body)};
  try{await $('#new-task').onclick({target:$('#new-task')});check('권한 조회 실패는 입력 창에 표시하고 저장 차단',!createReady&&$('#create-form').querySelector('button:not([type])').disabled&&createStatus.textContent.includes('접근 권한 없음'))}finally{api=originalAPI;$('#create-dialog').close();await pause()}
 });
 await run('관리자 업무 등록과 완료 기준 자동 계산',async()=>{
  await resetFixture();me.admin=true;$$('.admin-only').forEach(el=>el.hidden=false);boardRenderKey='';draw();
  await $('#new-task').onclick({target:$('#new-task')});const form=$('#create-form');form.elements.title.value='새로운 시연 업무';form.elements.due.value=fixtureDate(10);
  check('관리자 등록은 실무 담당자를 직접 선택해야 함',$('#create-dialog').open&&form.elements.assignee_id.value===''&&form.elements.assignee_id.validity.valueMissing&&!form.checkValidity());
  change('#create-form [name="assignee_id"]','person-1');$('#create-add-criterion').click();await pause();const row=$('#create-criteria-rows .criterion-row');row.querySelector('.criterion-title').value='신규 업무 검증 완료';
  check('완료 기준 기본 담당자는 선택한 업무 담당자',row.querySelector('.criterion-owner').value==='person-1');
  check('완료 기준이 있으면 상태·진행률 입력은 숨기고 비활성',form.elements.status.disabled&&form.elements.progress.disabled&&form.elements.status.closest('label').hidden&&form.elements.progress.closest('label').hidden);
  check('자동 계산 입력은 FormData에서 실제로 제외됨',!new FormData(form).has('status')&&!new FormData(form).has('progress'));
  form.requestSubmit(form.querySelector('button:not([type])'));await until(()=>selectedTask==='created-workflow-task','신규 업무 상세 표시');
  const posted=fixtureCalls.find(c=>c.path==='/api/tasks'&&c.body!==undefined)?.body;
  check('등록 요청은 숨긴 필드의 기본 상태와 진행률을 포함',posted?.fields.status==='미착수'&&posted.fields.progress==='0%'&&posted.assignee_id==='person-1'&&posted.criteria.length===1);
  check('등록 후 모달을 닫고 새 업무 상세와 성공 결과 표시',!$('#create-dialog').open&&active==='tasks'&&selectedTask==='created-workflow-task'&&$('#task-detail').textContent.includes('새로운 시연 업무')&&$('#task-detail').textContent.includes('김철수')&&$('#board-count').textContent.includes('새로운 시연 업무')&&$('#board-count').textContent.includes('등록 완료'));
 });
 function planningAction(task){
  const f=task.fields,days=/^\d{4}-\d{2}-\d{2}$/.test(f.due)?Math.round((Date.parse(f.due)-Date.parse(fixtureToday))/86400000):null;
  return {id:task.id,title:task.title,collectionId:task.collectionId,collectionName:task.collectionName,owner:f.owner,status:f.status,progress:f.progress,due:f.due,days_remaining:days,flags:days===null?['no_due']:days<0?['overdue']:days<=7?['due_soon']:[],criteria:clone(task.criteria),next:f.next,next_is_suggestion:false,remaining:task.criteria.filter(i=>i.state!=='완료').length,blocker:f.blocker};
 }
 async function resetPlanningFixture(){
  await resetFixture();setPlanningOpen(false);planningFocus='all';planningPage=1;$('#planning-search').value='';
  analyticsData={owner:'',horizon:7,actions:fixtureTasks.filter(t=>t.fields.status!=='완료').map(planningAction)};
  active='stats';$$('.tab').forEach(el=>el.hidden=el.id!=='stats');$('#stats-content').hidden=false;$('#project-bar').hidden=true;drawPlanning();$('#planning-preview').scrollTop=0;
 }
 const planningPreviewText=()=>$$('#planning-preview .plan-preview-row').map(el=>el.textContent.trim());
 const settleLayout=()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
 await run('통계 전체 목록 검색·페이지·입력 포커스 보존',async()=>{
  await resetPlanningFixture();const beforeSearch=planningPreviewText();setPlanningOpen(true);
  input('#planning-search','추가 업무');
  check('확장 패널의 검색어가 기본 목록의 업무에 영향을 주지 않음',JSON.stringify(planningPreviewText())===JSON.stringify(beforeSearch));
  check('전체 목록은 검색 결과를 5개 단위로 표시',$$('#planning-list .plan-row').length===5&&!$('#planning-pages').hidden&&$('#planning-list').textContent.includes('추가 업무'));
  $('#plan-next').click();const search=$('#planning-search');search.focus();search.setSelectionRange(1,3);const opened=$('#planning-list details');if(opened)opened.open=true;
  const openKey=opened?.closest('.plan-row')?.dataset.key,selectedPage=planningPage,visibleTitles=$$('#planning-list h3').map(el=>el.textContent);
  analyticsData=clone(analyticsData);drawPlanning();
  check('자동 재그리기에서 검색·페이지·검색 입력 노드와 포커스 유지',selectedPage===2&&planningPage===2&&$('#planning-search')===search&&search.value==='추가 업무'&&document.activeElement===search&&search.selectionStart===1&&search.selectionEnd===3);
  check('자동 재그리기에서 열린 모달과 현재 페이지 업무 유지',$('#planning-dialog').open&&JSON.stringify($$('#planning-list h3').map(el=>el.textContent))===JSON.stringify(visibleTitles));
  check('현재 페이지에서 펼친 체크리스트도 재그리기 후 유지',!!openKey&&$$('#planning-list details[open]').some(el=>el.closest('.plan-row').dataset.key===openKey));
  input('#planning-search','내 지연 업무');check('검색 변경 시 첫 페이지로 복귀하고 정확한 업무만 표시',planningPage===1&&$$('#planning-list .plan-row').length===1&&$('#planning-list [data-plan-open]')?.dataset.planOpen==='own-late');
  $('#planning-close').click();
 });
 await run('업무 수가 많아져도 통계 목록 높이를 유지하고 내부에서 스크롤',async()=>{
  await resetPlanningFixture();const action=planningAction(fixtureTasks.find(t=>t.id==='own-late'));
  analyticsData.actions=[clone(action)];drawPlanning();await settleLayout();const oneHeight=$('#planning-preview').getBoundingClientRect().height,oneCardHeight=$('#planning-card').getBoundingClientRect().height;
  analyticsData.actions=Array.from({length:100},(_,i)=>({...clone(action),id:'scale-'+i,title:'일정 점검 업무 '+String(i+1).padStart(3,'0')}));drawPlanning();await settleLayout();
  const manyHeight=$('#planning-preview').getBoundingClientRect().height,manyCardHeight=$('#planning-card').getBoundingClientRect().height;
  const preview=$('#planning-preview'),listRect=preview.getBoundingClientRect(),visibleRows=$$('#planning-preview .plan-preview-row').filter(row=>{const rect=row.getBoundingClientRect();return rect.top>=listRect.top-1&&rect.bottom<=listRect.bottom+1});
  check('100개 업무를 확장 버튼 없이 기본 목록에 모두 제공',$$('#planning-preview .plan-preview-row').length===100&&!$('#planning-dialog').open);
  check('목록은 약 세 건 높이로 내부 스크롤을 제공',visibleRows.length===3&&preview.scrollHeight>preview.clientHeight&&['auto','scroll'].includes(getComputedStyle(preview).overflowY),'보이는 행 '+visibleRows.length+'개 / clientHeight '+preview.clientHeight+' / scrollHeight '+preview.scrollHeight);
  check('1개와 100개 업무의 기본 목록 영역 높이가 동일',oneHeight>0&&Math.abs(oneHeight-manyHeight)<=2,'1개 '+oneHeight+'px / 100개 '+manyHeight+'px');
  check('업무 증가로 먼저 점검할 업무 카드가 길어지지 않음',Math.abs(oneCardHeight-manyCardHeight)<=2,'1개 '+oneCardHeight+'px / 100개 '+manyCardHeight+'px');
  preview.scrollTop=240;const savedScroll=preview.scrollTop;analyticsData.actions[60].title='자동 갱신으로 바뀐 업무 제목';drawPlanning();await settleLayout();
  check('백그라운드 갱신은 기본 목록의 스크롤 위치 유지',savedScroll>0&&$('#planning-preview')===preview&&Math.abs(preview.scrollTop-savedScroll)<=1,'갱신 전 '+savedScroll+' / 후 '+preview.scrollTop);
  $('#planning-filters [data-plan-filter="overdue"]').click();check('새 필터를 누르면 기본 목록의 처음부터 확인',planningFocus==='overdue'&&preview.scrollTop===0&&!$('#planning-dialog').open);
  preview.scrollTop=preview.scrollHeight;await settleLayout();const lastRow=$('#planning-preview [data-plan-open="scale-99"]'),lastRect=lastRow.getBoundingClientRect(),bottomRect=preview.getBoundingClientRect();
  check('크게 보기를 열지 않고 스크롤만으로 100번째 업무까지 접근',!$('#planning-dialog').open&&lastRect.bottom<=bottomRect.bottom+1&&lastRect.top>=bottomRect.top-1);
 });
 await run('기본 점검 목록에서 확장 없이 업무 상세로 바로 이동',async()=>{
  await resetPlanningFixture();const preview=$('#planning-preview');preview.scrollTop=preview.scrollHeight;await settleLayout();const button=$('#planning-preview [data-plan-open="b-task"]'),callsBefore=fixtureCalls.length;
  check('상세는 새 탭 링크이며 현재 통계 화면은 유지',button.tagName==='A'&&button.target==='_blank'&&button.rel.includes('noopener')&&active==='stats');
  location.hash=button.hash;await openTaskLink();
  check('기본 목록의 업무 클릭은 정확한 프로젝트와 상세를 표시',!$('#planning-dialog').open&&active==='tasks'&&selected()==='project-b'&&selectedTask==='b-task'&&!$('#task-detail').hidden&&$('#task-detail').textContent.includes('B 업무'));
  check('업무 상세 조회는 저장 API를 호출하지 않음',!fixtureCalls.slice(callsBefore).some(call=>call.body!==undefined));
 });
 await run('통계 패널의 보고 권한과 업무 화면 연결',async()=>{
  await resetPlanningFixture();setPlanningOpen(true);
  check('실무자는 내 항목을 가진 업무에서만 진행 보고 가능',!!$('#planning-list [data-plan-report="own-late"]')&&!!$('#planning-list [data-plan-report="shared-late"]')&&!$('#planning-list [data-plan-report="other-late"]'));
  me.admin=true;drawPlanning();check('관리자는 다른 담당자의 업무에도 보고 버튼 표시',!!$('#planning-list [data-plan-report="other-late"]'));me.admin=false;
  analyticsData.actions=[planningAction(fixtureTasks.find(t=>t.id==='b-task'))];planningPage=1;drawPlanning();
  const detailLink=$('#planning-list [data-plan-open="b-task"]');check('패널의 상세도 새 탭으로 열고 패널 유지',detailLink.target==='_blank'&&$('#planning-dialog').open);setPlanningOpen(false);location.hash=detailLink.hash;await openTaskLink();
  check('전체 목록에서 업무 확인 시 패널을 닫고 올바른 프로젝트의 상세로 이동',!$('#planning-dialog').open&&active==='tasks'&&selected()==='project-b'&&selectedTask==='b-task'&&!$('#task-detail').hidden&&$('#task-detail').textContent.includes('B 업무'));
 });
 await run('완료 업무 목록과 프로젝트 선택 해제',async()=>{
  await resetPlanningFixture();analyticsData.completed_tasks=fixtureTasks.filter(t=>t.fields.status==='완료').map(t=>({...planningAction(t),flags:[]}));
  inspectFocus('completed');check('완료 지표는 본문 완료 목록을 선택하고 패널은 열지 않음',!$('#planning-dialog').open&&$('#planning-title').textContent==='완료한 업무 목록'&&$$('#planning-list .plan-row').length===1&&$('#planning-list').textContent.includes('유일한 완료 업무')&&!$('#planning-list').textContent.includes('진행 보고'));
  setPlanningOpen(true);input('#planning-search','없는 업무');check('완료 목록도 검색 가능',$$('#planning-list .plan-row').length===0);
  setPlanningOpen(false);const originalChanged=statsChanged;statsChanged=()=>{};
  try{renderHTML($('#stats-project'),'<option value="">전체</option>'+options(fixtureProjects));renderHTML($('#project-comparison'),'<button data-stats-project="project-a">A</button>');bindDashboardActions();const card=$('[data-stats-project]');card.click();check('프로젝트 첫 클릭은 선택',$('#stats-project').value==='project-a');card.click();check('같은 프로젝트 다시 클릭은 전체로 복귀',$('#stats-project').value==='');$('#stats-project').value='project-a';$('#stats-all-projects').click();check('전체 복귀 버튼은 프로젝트 영역에 배치하고 선택 해제',$('#stats-project').value===''&&!!$('#stats-all-projects').closest('#project-overview'));}finally{statsChanged=originalChanged}
 });
 await run('담당자 상태 막대 실제 비율',async()=>{
  tab('stats',{refresh:false});$('#stats-content').hidden=false;
  const box=document.createElement('div');box.style.width='400px';$('#owner-comparison').append(box);
  const width=el=>el.getBoundingClientRect().width;
  box.innerHTML=ownerStatusBar(4,0,0);let bar=box.firstElementChild;
  check('전부 완료면 초록색 구간 하나가 전체 폭을 채움',bar.children.length===1&&bar.firstElementChild.classList.contains('done')&&Math.abs(width(bar)-width(bar.firstElementChild))<1&&getComputedStyle(bar.firstElementChild).backgroundColor==='rgb(59, 158, 131)');
  box.innerHTML=ownerStatusBar(0,1,3);bar=box.firstElementChild;
  check('0건 완료 구간은 없고 초과 미완료는 실제 1대3 비율',!bar.querySelector('.done')&&Math.abs(width(bar.children[0])/width(bar)-0.25)<0.01&&Math.abs(width(bar.children[1])/width(bar)-0.75)<0.01);
  box.innerHTML=ownerStatusBar(2,1,1);bar=box.firstElementChild;
  check('세 상태의 막대 합계는 전체 폭과 일치',Math.abs([...bar.children].reduce((n,c)=>n+width(c),0)-width(bar))<1&&Math.abs(width(bar.children[0])/width(bar)-0.5)<0.01);
  box.innerHTML=ownerStatusBar(0,0,0);check('업무 0건이면 막대를 표시하지 않음',box.firstElementChild.children.length===0&&getComputedStyle(box.firstElementChild).display==='none');box.remove();
 });
 await run('담당자 현황에서 점검 업무로 이동',async()=>{
  await resetPlanningFixture();const originalRender=renderAnalytics, saved=clone(analyticsData);let calls=0;
  renderHTML($('#filter-owner'),'<option value="">전체</option><option value="hong@example.test">홍길동</option>');$('#filter-owner').value='';
  renderHTML($('#owner-comparison'),'<button data-stats-owner="hong@example.test">홍길동</button>');
  renderAnalytics=async()=>{calls++;analyticsData={...saved,owner:$('#filter-owner').value,actions:saved.actions.filter(t=>!$('#filter-owner').value||t.owner===$('#filter-owner').value),completed_tasks:[]};drawPlanning()};
  try{bindDashboardActions();planningSchedule={from:'2026-09-28',to:'2026-09-28',owner:null,label:'이전 날짜'};planningFocus='schedule';
   await $('[data-stats-owner]').onclick();
   check('담당자 클릭은 날짜 조건을 해제하고 미완료 목록을 선택',planningFocus==='all'&&planningSchedule===null&&!$('#planning-dialog').open);
   check('담당자 클릭 후 해당 담당자의 업무만 표시',$$('#planning-preview .plan-preview-row').length===saved.actions.filter(t=>t.owner==='hong@example.test').length&&$$('#planning-preview .plan-preview-row').length>0);
   check('점검할 업무의 필터로 키보드 포커스 이동',document.activeElement===$('#planning-filters [data-plan-filter="all"]'));
   await $('[data-stats-owner]').onclick();check('같은 담당자 재클릭은 전체 담당자 업무 복원',$('#filter-owner').value===''&&calls===2&&$$('#planning-preview .plan-preview-row').length===saved.actions.length);
   await $('[data-stats-owner]').onclick();check('담당자 선택 해제 버튼 표시',!$('#planning-owner-clear').hidden);
   await $('#planning-owner-clear').onclick({currentTarget:$('#planning-owner-clear')});check('선택 해제 버튼은 전체 복원 후 숨김',$('#filter-owner').value===''&&$('#planning-owner-clear').hidden&&$$('#planning-preview .plan-preview-row').length===saved.actions.length);
  }finally{renderAnalytics=originalRender;analyticsData=saved;resetPlanning()}
 });
 await run('업무 직접 링크의 접근 검사',async()=>{
  await resetFixture();location.hash='#task?project=forbidden&id=own-late';let denied=false;try{await openTaskLink()}catch{denied=true}check('권한 없는 프로젝트 링크는 다른 프로젝트로 대체하지 않고 거부',denied&&selectedTask==='');
  location.hash='#task?project=project-a&id=missing';denied=false;try{await openTaskLink()}catch{denied=true}check('삭제되거나 접근할 수 없는 업무 링크 거부',denied&&selectedTask==='');history.replaceState(null,'',location.pathname);
 });
 await run('통계 접근 회수 시 열린 패널과 업무 내용 제거',async()=>{
  await resetPlanningFixture();setPlanningOpen(true);const title=analyticsData.actions[0].title;clearAnalyticsAccess();
  check('권한 회수는 열린 전체 목록을 닫고 통계 데이터를 제거',!$('#planning-dialog').open&&analyticsData===null&&$('#stats-content').hidden);
  check('권한 회수 뒤 전체 목록과 미리보기의 업무 DOM 제거',$('#planning-list').children.length===0&&$$('#planning-preview .plan-preview-row').length===0&&!$('#planning-preview').textContent.includes(title)&&!$('#planning-list').textContent.includes(title));
 });
 await run('완료 지표와 프로젝트 화면 렌더링',async()=>{
  await resetPlanningFixture();const actions=analyticsData.actions,completed=fixtureTasks.filter(t=>t.fields.status==='완료').map(t=>({...planningAction(t),flags:[]}));
  const summary={total:fixtureTasks.length,completed:completed.length,open:actions.length,project_progress:50,projects_measured:2,projects_total:2,overdue:3,due_soon:2,blocked:1,no_due:1,invalid:0,no_criteria:0,missing_progress:0,states:{'진행 중':actions.length,'완료':completed.length}};
  const payload={summary,actions,completed_tasks:completed,projects:fixtureProjects.map(p=>({...p,average_progress:50,total:8,completed:1,overdue:1,due_soon:1,criteria_total:8,criteria_done:1,progress_known:8,invalid:0})),owners:[{email:'worker@example.com',tasks:8,tasks_completed:2,tasks_overdue:1,tasks_pending:5}],owner_options:[],schedule:[],invalid_tasks:[],horizon:7,as_of:fixtureToday,sync:{ok:true,at:new Date().toISOString()}};
  const originalAPI=api;api=async(path,body)=>path.startsWith('/api/analytics?')?clone(payload):originalAPI(path,body);
  try{await renderAnalytics();check('완료 옆 미완료 지표 제공', $('#metrics [data-focus=completed]').nextElementSibling.dataset.focus==='all');check('담당자별 업무 상태 3종 표시', $('#owner-comparison').textContent.includes('마감 초과')&&!$('#owner-comparison').textContent.includes('체크리스트'));check('통계에서 진행이 막힌 업무 제거',!$('#metrics [data-focus="blocked"]')&&!$('#signal-actions [data-focus="blocked"]')&&!$('#planning-filters [data-plan-filter="blocked"]'));check('지표와 점검 필터의 공통 항목 순서 일치',JSON.stringify($$('#metrics [data-focus]').map(b=>b.dataset.focus).filter(k=>k!=='projects'))===JSON.stringify($$('#planning-filters [data-plan-filter]').map(b=>b.dataset.planFilter).filter(k=>k!=='no_due')));check('체크리스트 완료 대신 완료한 업무 수를 제공',!!$('#metrics [data-focus="completed"]')&&!$('#metrics').textContent.includes('체크리스트'));$('#metrics [data-focus="completed"]').click();check('완료 지표 클릭으로 본문 완료 업무 목록 표시',!$('#planning-dialog').open&&$('#planning-preview').textContent.includes('유일한 완료 업무')&&document.activeElement===$('#planning-filters [data-plan-filter="completed"]'));setPlanningOpen(false);
  const projectCallsBefore=fixtureCalls.filter(c=>c.path==='/api/projects').length;await renderAnalytics({background:true,availableProjects:fixtureProjects});check('같은 갱신 주기의 프로젝트 재조회 제거',fixtureCalls.filter(c=>c.path==='/api/projects').length===projectCallsBefore);
  check('상단 전체 업무는 완료 앞, 기한 미정은 목록에만 유지',$('#metrics [data-focus=completed]').previousElementSibling.dataset.focus==='total'&&!$('#metrics [data-focus=no_due]')&&!!$('#planning-filters [data-plan-filter=no_due]')&&$('#planning-filters').firstElementChild.dataset.planFilter==='total');
  $('#metrics [data-focus=total]').click();check('전체 업무는 완료와 미완료를 함께 표시',$$('#planning-preview .plan-preview-row').length===actions.length+completed.length&&$('#planning-preview').textContent.includes('유일한 완료 업무')&&document.activeElement.dataset.planFilter==='total');
  check('전체 목록에서 완료 업무에 보고 버튼을 표시하지 않음',!$('#planning-list [data-key="own-done"] [data-plan-report]'));
  }finally{api=originalAPI}
 });
 await run('관리자 일정 조정은 검토 후 확정',async()=>{
  const originalAPI=api;const oldMe=me;me={...me,admin:true};const task=fixtureTasks.find(t=>t.id==='own-late');let sent=null;
  api=async(path,body)=>{if(path==='/api/tasks/'+task.id+'/proposals'){sent=body;return {id:'schedule-fixture',doc_id:task.id,title:task.title,collectionId:task.collectionId,url:task.url,state:'PENDING',changes:body.changes,before:task.text,after:task.text+'\n시작일: '+body.changes.start+'\n마감일: '+body.changes.due}}return originalAPI(path,body)};
  try{openSchedule(task);const form=$('#schedule-form');form.elements.start.value='2026-10-03';form.elements.due.value='2026-10-01';form.requestSubmit(form.querySelector('[type=submit]'));await pause();check('역전된 기간은 요청 전에 차단',!sent&&$('#schedule-error').textContent.includes('늦을 수'));
   form.elements.start.value='2026-09-28';form.requestSubmit(form.querySelector('[type=submit]'));await pause();check('기간 수정은 시작일과 마감일만 제안',sent?.changes.start==='2026-09-28'&&sent?.changes.due==='2026-10-01'&&Object.keys(sent.changes).length===2);
   check('즉시 저장 대신 변경 검토 화면 제공',!$('#schedule-dialog').open&&currentProposal?.state==='PENDING'&&$('#proposal').textContent.includes('시작일')&&!$('#confirm').disabled);
  }finally{api=originalAPI;me=oldMe;$('#schedule-dialog').close();tab('stats',{refresh:false})}
 });
 await run('마감 캘린더와 담당자 분포',async()=>{
  const saved=clone(analyticsData),before=fixtureCalls.length,previousAdmin=me.admin;me.admin=true;
  const base=clone(analyticsData.actions[0]);
  analyticsData={...saved,as_of:'2026-09-28',actions:[
   {...base,id:'cal-a',title:'월말 검증',owner:'a@example.test',start:'2026-09-30',due:'2026-09-30',days_remaining:2,flags:['due_soon']},
   {...base,id:'cal-b',title:'공동 업무 한 건',owner:'b@example.test',start:'2026-09-30',due:'2026-09-30',days_remaining:2,flags:['due_soon'],criteria:[{owner:'a@example.test'},{owner:'b@example.test'}]},
   {...base,id:'cal-c',title:'다음 달 배포',owner:'a@example.test',start:'2026-10-01',due:'2026-10-01',days_remaining:3,flags:['due_soon']},
   {...base,id:'cal-late',title:'지난 업무',owner:'a@example.test',start:'2026-09-27',due:'2026-09-27',days_remaining:-1,flags:['overdue']},
   {...base,id:'cal-none',title:'날짜 없는 업무',owner:'a@example.test',due:null,days_remaining:null,flags:['no_due']}
  ]};calendarAnchor='2026-09-28';calendarMode='week';planningSchedule=null;planningFocus='all';drawCalendar();drawPlanning();
  check('월 경계를 넘는 주간은 월요일부터 일요일까지 7일',calendarBounds(calendarAnchor,'week').end==='2026-10-04'&&$$('.calendar-day').length===7);
  check('캘린더는 해당 주의 미완료 업무만 표시',$$('.calendar-task').length===3&&!$('#deadline-calendar').textContent.includes('유일한 완료 업무'));
  check('캘린더 상세는 새 탭 링크',$$('.calendar-task').every(a=>a.target==='_blank'&&a.rel==='noopener'&&a.href.includes('#task?')));
  check('초과 및 기한 미정 업무는 달력 밖에서도 접근',$('[data-calendar-focus=overdue]').textContent.includes('1')&&$('[data-calendar-focus=unplanned]').textContent.includes('1'));
  $('[data-calendar-date="2026-09-30"]').click();check('날짜 클릭은 2건으로 본문 필터링하고 모달은 열지 않음',planningFocus==='schedule'&&$$('#planning-preview .plan-preview-row').length===2&&!$('#planning-dialog').open&&document.activeElement.dataset.planFilter==='schedule');
  $('[data-deadline-owner="a@example.test"][data-from="2026-09-30"]').click();check('담당자 날짜 셀은 정확한 주 담당자 업무만 선택',$$('#planning-preview .plan-preview-row').length===1&&$('#planning-preview').textContent.includes('월말 검증'));
  check('공동 업무를 다른 참여자의 마감 건수에 중복 집계하지 않음',$$('.heat-total').reduce((sum,b)=>sum+Number(b.textContent),0)===3);
  inspectFocus('all');check('상단 미완료 클릭은 날짜 조건을 해제',planningSchedule===null&&$$('#planning-preview .plan-preview-row').length===5);
  calendarMode='month';drawCalendar();check('월간은 9월 업무만 집계하고 다음 달 제외',$$('.heat-total').reduce((sum,b)=>sum+Number(b.textContent),0)===3&&!$('#deadline-calendar').textContent.includes('다음 달 배포'));
  const bins=calendarBins('2026-09-01','2026-09-30','month');check('월간 분포의 주 구간은 중복 없이 월 전체 포함',bins[0].from==='2026-09-01'&&bins.at(-1).to==='2026-09-30'&&bins.slice(1).every((b,i)=>b.from===calendarAdd(bins[i].to,1)));
  calendarAnchor='2026-01-31';moveCalendar(1);check('월말 다음 달 이동에서 2월을 건너뛰지 않음',calendarAnchor==='2026-02-01');
  check('윤년과 연도 경계 정확',calendarBounds('2028-02-10','month').end==='2028-02-29'&&calendarBounds('2026-01-01','week').start==='2025-12-29');
  calendarAnchor='2026-09-28';drawCalendar();calendarMode='week';drawCalendar();const prior=calendarAnchor;drawCalendar();check('자동 재그리기는 선택 기간과 보기 유지',calendarAnchor===prior&&calendarMode==='week');
  analyticsData.actions=[{...base,id:'late-calendar',title:'지연 업무',start:'2026-09-15',due:'2026-09-22'},{...base,id:'missing-calendar',title:'시작일 미정 지연',start:null,due:'2026-09-25'}];
  calendarMode='month';calendarAnchor='2026-09-28';drawCalendar();const oldFocus=planningFocus;
  $('[data-calendar-focus="overdue"]').click();check('초과 탐색은 월간을 유지하고 해당 캘린더 업무를 강조',calendarMode==='month'&&!!$('.calendar-task.overdue-target')&&planningFocus===oldFocus);
  $('#overdue-next').click();check('시작일이 없어도 마감 날짜에 강조된 업무 표시',!!$('.calendar-task.overdue-target[data-calendar-task="missing-calendar"]'));
  $('#overdue-clear').click();check('강조 해제 시 원래 월과 강조 복원',calendarAnchor==='2026-09-28'&&!$('.overdue-target'));
  calendarMode='week';drawCalendar();check('타임라인 버튼과 컨트롤 제거',!$('[data-calendar-mode="timeline"]')&&!$('#timeline-controls')&&$$('[data-calendar-mode]').length===2);
  calendarAnchor='2026-09-28';moveCalendar(1);check('다음 주 이동은 7일',calendarAnchor==='2026-10-05');
  analyticsData.actions=[];drawCalendar();check('빈 일정도 7일 날짜 표시',$$('.calendar-day').length===7&&$$('.calendar-task').length===0);
  analyticsData=saved;calendarAnchor='';calendarMode='week';planningSchedule=null;planningFocus='all';drawCalendar();drawPlanning();clearAnalyticsAccess();check('권한 회수 시 일정과 담당자 분포 DOM 제거',!$('#deadline-calendar').textContent&&!$('#deadline-distribution').textContent&&!$('#calendar-unplanned').textContent);
  check('일정 탐색은 저장 API를 호출하지 않음',!fixtureCalls.slice(before).some(c=>c.body!==undefined));
  analyticsData=saved;me.admin=previousAdmin;$('#stats-content').hidden=false;drawCalendar();drawPlanning();
 });
 await run('일반 사용자 일정은 본인 배정만 표시',async()=>{
  const saved=clone(analyticsData),admin=me.admin,base=clone(analyticsData.actions[0]);me.admin=false;calendarOverdue=null;calendarMode='week';calendarAnchor='2026-09-28';
  const rows=[{...base,id:'mine',owner:me.email,criteria:[],start:'2026-09-28',due:'2026-09-30'},{...base,id:'shared',owner:'other@example.test',criteria:[{owner:me.email}],start:'2026-09-28',due:'2026-09-30'},{...base,id:'others',owner:'other@example.test',criteria:[],start:'2026-09-28',due:'2026-09-30'}];
  analyticsData={...saved,as_of:'2026-09-28',actions:[rows[2]],calendar_actions:rows};drawCalendar();
  check('다른 담당자 조회 중에도 내 일정과 배정된 공동 업무만 표시',JSON.stringify([...new Set($$('.calendar-task').map(r=>r.dataset.calendarTask))].sort())==='["mine","shared"]');
  check('일반 사용자는 담당자 일정 겹침을 숨기고 내용도 제거',$('#calendar-owner-distribution').hidden&&!$('#deadline-distribution').textContent);
  analyticsData.calendar_actions=[{...rows[0],start:null,due:'2026-09-25'},{...rows[2],start:null,due:'2026-09-24'}];drawCalendar();
  check('기간 미정과 마감 초과도 내 업무만 집계',$$('#calendar-unplanned a').length===1&&overdueCalendarTasks().length===1);
  me.admin=true;analyticsData.actions=rows;drawCalendar();check('관리자 일정과 담당자 겹침은 기존대로 표시',!$('#calendar-owner-distribution').hidden&&new Set($$('.calendar-task').map(r=>r.dataset.calendarTask)).size===3&&!!$('#deadline-distribution table'));
  me.admin=admin;analyticsData=saved;calendarAnchor='';drawCalendar();
 });
 const result={pass:fixtureChecks.every(c=>c.pass),total:fixtureChecks.length,passed:fixtureChecks.filter(c=>c.pass).length,checks:fixtureChecks,errors:fixtureErrors,mockOnly:true};
 $('#workflow-results').textContent=JSON.stringify(result,null,2);document.body.dataset.pass=String(result.pass);document.title=(result.pass?'PASS':'FAIL')+' · Workhub workflow integration';window.scrollTo(0,0);
})().catch(error=>{const result={pass:false,error:error.message,stack:error.stack,checks:fixtureChecks};$('#workflow-results').textContent=JSON.stringify(result,null,2);document.body.dataset.pass='false'});
`;

const combined = `${source}\n${analytics}\n${fixture}`;
new vm.Script(combined, { filename: 'workhub-workflow-fixture.js' });
const escapeScript = value => value.replace(/<\/script/gi, '<\\/script');
const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; img-src data:"><title>Workhub workflow integration</title><style>${css}\n#workflow-fixture-result{position:relative;z-index:1000;background:#fff;margin:0 0 24px 220px;padding:24px;border-bottom:3px solid #285dd4}#workflow-results{white-space:pre-wrap;overflow-wrap:anywhere;max-height:70vh;overflow:auto;font-size:14px}#workflow-fixture-result h1{font-size:22px}</style></head><body><section id="workflow-fixture-result"><h1>Workhub 흐름 통합 회귀 검증</h1><p>실제 화면 코드 + 모의 API. 운영 데이터를 읽거나 변경하지 않습니다.</p><pre id="workflow-results">검증 중…</pre></section>${body}<script>${escapeScript(combined)}</script></body></html>`;
const folder = path.join(root, '.ui-review/workflow');
fs.mkdirSync(folder, { recursive: true });
fs.writeFileSync(path.join(folder, 'index.html'), html);
console.log(path.join(folder, 'index.html'));
