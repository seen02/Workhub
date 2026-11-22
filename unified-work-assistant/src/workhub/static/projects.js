const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Preserve DOM nodes, focus and expanded controls when a poll has no new content.
const renderedHTML=new WeakMap();
function renderHTML(element,html){
  if(renderedHTML.get(element)===html)return;
  const template=document.createElement('template');template.innerHTML=html;
  // Patch existing nodes so background updates preserve focus and expanded details.
  const key=n=>n.nodeType===1?(n.id||n.getAttribute('data-key')||''):'';
  function patch(parent,source){
    let cursor=parent.firstChild;
    const keyed=new Map([...parent.childNodes].filter(n=>key(n)).map(n=>[key(n),n]));
    for(const next of [...source.childNodes]){
      let current=cursor;
      if(key(next)){const match=keyed.get(key(next));if(match){if(match!==cursor)parent.insertBefore(match,cursor);current=match}}
      if(!current){parent.append(next.cloneNode(true));continue}
      if(current.nodeType!==next.nodeType||current.nodeName!==next.nodeName||(key(next)&&key(current)!==key(next))){const node=next.cloneNode(true);parent.insertBefore(node,current);continue}
      if(current.nodeType===3){if(current.data!==next.data)current.data=next.data}
      else if(current.nodeType===1){
        for(const a of [...current.attributes])if(!next.hasAttribute(a.name)&&!(current.tagName==='DETAILS'&&a.name==='open'))current.removeAttribute(a.name);
        for(const a of [...next.attributes])if(current.getAttribute(a.name)!==a.value)current.setAttribute(a.name,a.value);
        patch(current,next);
      }
      cursor=current.nextSibling;
    }
    while(cursor){const next=cursor.nextSibling;cursor.remove();cursor=next}
  }
  patch(element,template.content);renderedHTML.set(element,html);
}
let boardRenderKey='',boardProject='',boardRequest=0,refreshing=false;
let selectedTask='',assistantMode='report',reportStage=1,reportTaskId='',reportBusy=false;
const reportDrafts=new Map(),pendingReports=new Map();
let boardFocus='open',boardPage=1,reportMethod='ai',currentProposal=null,researchRequest=0;
const boardPageSize=8;
const belongsToMe=t=>t.fields.owner?.toLowerCase()===me.email.toLowerCase()||t.criteria?.some(i=>i.owner===me.email.toLowerCase());
let me,tasks=[],projects=[],people=[],names={},mine=true,active='stats',pendingCreate,editingTask,statsOwnerInitialized=false;
const personName=email=>names[email?.toLowerCase()]||email;
function personOptions(email,onlySelf=false){
  const candidates=people.filter(p=>!onlySelf||p.email===me.email.toLowerCase());
  return (email&&!candidates.some(p=>p.email===email.toLowerCase())?`<option value="legacy:${esc(email)}" selected>${esc(personName(email))} · 기존 배정</option>`:'')+
    candidates.map(p=>`<option value="${esc(p.id)}" ${p.email===email?.toLowerCase()?'selected':''}>${esc(p.name)}${people.filter(x=>x.name===p.name).length>1?' · '+esc(p.username||p.email):''}</option>`).join('');
}
async function loadPeople(){
  const cid=selected();const d=await api('/api/assignees?'+new URLSearchParams({collection_id:cid}));applyPeople(cid,d);
}
function applyPeople(cid,d){
  const filter=$('#filter-owner');if(cid!==selected())return;people=d.people;names=d.names;
  const owner=me.admin&&statsOwnerInitialized?filter.value:me.email.toLowerCase();
  // Refreshing the directory must preserve an explicitly selected owner or all.
  filter.innerHTML='<option value="">전체 담당자</option>'+people.map(p=>`<option value="${esc(p.email)}">${esc(p.name)}${people.filter(x=>x.name===p.name).length>1?' · '+esc(p.username||p.email):''}</option>`).join('')+(owner&&!people.some(p=>p.email===owner)?`<option value="${esc(owner)}">${esc(owner===me.email.toLowerCase()?(me.name||me.email):personName(owner))}</option>`:'');
  filter.value=owner;statsOwnerInitialized=true;
}
function namedText(text){let result=text;Object.entries(names).sort((a,b)=>b[0].length-a[0].length).forEach(([email,name])=>{result=result.split(email).join(name)});return result}
const id=()=>crypto.randomUUID?crypto.randomUUID():Date.now()+'-'+Math.random().toString(36).slice(2);
const selected=()=>$('#project-select').value,states=['예정','진행 중','완료'];
const writable=t=>!t.error&&(me.admin||(t.criteria?.length?t.criteria.some(i=>i.owner===me.email.toLowerCase()):t.fields.owner?.toLowerCase()===me.email.toLowerCase()));
function notice(t=''){$('#notice').textContent=t}
async function api(path,body){
  const r=await fetch(path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':me?.csrf||''},body:body===undefined?undefined:JSON.stringify(body)});
  const d=await r.json();if(!r.ok){if(r.status===401)$('#login').hidden=false;const error=Error(typeof d.detail==='string'?d.detail:'입력 내용을 확인하세요.');error.status=r.status;throw error}return d;
}
async function work(button,fn){button.disabled=true;notice('처리 중입니다…');const dialog=button.closest('dialog');dialog?.querySelector('.dialog-error')?.remove();try{await fn();notice()}catch(e){notice(e.message);if(dialog?.open){const p=document.createElement('p');p.className='error dialog-error';p.setAttribute('role','alert');p.textContent=e.message;button.before(p)}}finally{button.disabled=false}}
function tab(name,{refresh=true}={}){
  if(active!==name)window.scrollTo({top:0,behavior:'instant'});
  active=name;$$('.tab').forEach(x=>x.hidden=x.id!==name);$$('[data-tab]').forEach(x=>{x.classList.toggle('selected',x.dataset.tab===name);if(x.dataset.tab===name)x.setAttribute('aria-current','page');else x.removeAttribute('aria-current')});
  $('#heading').textContent={tasks:'업무 보드',assistant:'AI 업무 비서',stats:'진행 통계',guide:'시연 가이드',accounts:'계정 · 인수인계'}[name];
  syncProjectBar();updatePendingBar();
  if(name==='accounts'){history.replaceState(null,'','#accounts');refreshAccounts().catch(e=>notice(e.message));}
  else if(location.hash==='#accounts')history.replaceState(null,'',location.pathname+location.search);

  if(name==='stats'&&refresh){$('#filter-owner').value=me.email.toLowerCase();$('#stats-portfolio').value=me.admin?'managed':'all';$('#stats-project').value='';loadStats().catch(e=>notice(e.message));}
  if(name==='guide'&&me?.admin)api('/api/operations').then(d=>$('#operations').textContent=JSON.stringify(d,null,2)).catch(e=>notice(e.message));
}
$$('[data-tab]').forEach(b=>b.onclick=()=>{if(me)tab(b.dataset.tab)});
$$('[data-close]').forEach(b=>b.onclick=()=>$('#'+b.dataset.close).close());
function options(ps){return ps.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}
async function loadProjects(preferred){
  projects=(await api('/api/projects')).projects;const allowed=new Set(projects.map(p=>p.id));for(const [taskId,p] of pendingReports)if(!allowed.has(p.collectionId)){forgetTaskDraft(taskId)}for(const [taskId,draft] of reportDrafts)if(draft.collectionId&&!allowed.has(draft.collectionId))forgetTaskDraft(taskId);persistDrafts();updatePendingBar();const old=preferred||selected()||localStorage.getItem('workhub-project');
  renderHTML($('#project-select'),options(projects));if(projects.some(p=>p.id===old))$('#project-select').value=old;else if(old)clearAccessDisplays();syncProjectBar();
  $('#new-task').disabled=!projects.length;
}
function syncProjectBar(){const reviewing=active==='assistant'&&assistantMode==='report'&&reportStage!==1;$('#project-bar').hidden=['stats','guide','accounts'].includes(active)||reviewing||!me;$('#project-select').disabled=reportBusy;
 const board=active==='tasks';$('#project-bar').classList.toggle('board-project-mode',board);$('#project-select').closest('label').hidden=board;$('#board-project-picker').hidden=!board;
 if(board){renderHTML($('#board-project-buttons'),[...projects].sort((a,b)=>a.name.localeCompare(b.name,'ko')).map(p=>`<button type="button" class="project-choice" data-board-project="${esc(p.id)}" aria-pressed="${p.id===selected()}" ${reportBusy?'disabled':''}><span>${esc(p.name)}</span><span aria-hidden="true">${p.id===selected()?'✓':'→'}</span></button>`).join('')||'<p class="muted">접근 가능한 프로젝트가 없습니다.</p>');$$('[data-board-project]').forEach(b=>b.onclick=()=>{if(b.dataset.boardProject===selected())return;$('#project-select').value=b.dataset.boardProject;$('#project-select').dispatchEvent(new Event('change',{bubbles:true}))})}
}
function clearAccessDisplays(){
  tasks=[];people=[];names={};selectedTask='';boardRenderKey='';reportDrafts.clear();pendingReports.clear();currentProposal=null;persistDrafts();updatePendingBar();
  $('#task-detail').hidden=true;$('#task-detail').replaceChildren();$('#proposal').hidden=true;$('#proposal').replaceChildren();
  $('#weekly-preview').hidden=true;$('#weekly-preview').replaceChildren();$('#research-result').replaceChildren();
  $('#report-text').value='';$('#report-context').replaceChildren();$$('dialog[open]').forEach(d=>d.close());draw();
  if(typeof clearAnalyticsAccess==='function')clearAnalyticsAccess();
}
$('#project-select').onchange=()=>{saveReportDraft();boardPage=1;researchRequest++;selectedTask='';$('#report-task').value='';reportTaskId='';$('#report-text').value='';setReportStage(1);localStorage.setItem('workhub-project',selected());$('#weekly-preview').hidden=true;$('#research-result').textContent='';loadResearchStatus();load().then(()=>active==='stats'?loadStats():null).catch(e=>notice(e.message))};
$('#project-dialog h2').textContent='프로젝트 관리';
const linkedArea=document.createElement('section');linkedArea.className='linked-projects';linkedArea.innerHTML='<h3>연결된 프로젝트</h3><div id="linked-project-list"></div>';$('#project-dialog').append(linkedArea);
const unlinkDialog=document.createElement('dialog');unlinkDialog.id='unlink-dialog';unlinkDialog.innerHTML='<form id="unlink-form"><div class="dialog-head"><h2>프로젝트 연결 해제</h2><button type="button" id="close-unlink" class="secondary">닫기</button></div><h3 id="unlink-project-name"></h3><p>허브의 프로젝트·업무·통계와 봇 선택 목록에서 제외합니다. 기본은 연결 해제만 하며, Outline 문서와 접근 권한은 유지합니다. 나중에 기존 컬렉션으로 다시 연결할 수 있습니다.</p><label class="unlink-option"><input type="checkbox" id="delete-task-list"> 업무 목록과 그 아래 모든 문서도 휴지통으로 이동</label><p id="unlink-document-note"></p><p><strong>컬렉션 자체는 삭제하지 않습니다.</strong> 업무 목록 밖의 요구사항·PRD 등 다른 문서는 유지합니다.</p><button id="submit-unlink">연결만 해제</button></form>';document.body.append(unlinkDialog);
const managerDialog=document.createElement('dialog');managerDialog.id='manager-dialog';managerDialog.innerHTML='<form id="manager-form"><div class="dialog-head"><h2>프로젝트 책임자</h2><button type="button" id="close-manager" class="secondary">닫기</button></div><h3 id="manager-project"></h3><p>일정과 진행 상황을 관리할 팀장입니다. 업무 담당자·접근 권한은 바뀌지 않습니다.</p><label>책임자 이름<select id="project-manager"></select></label><button>저장</button></form>';document.body.append(managerDialog);
$('#close-manager').onclick=()=>managerDialog.close();
$('#manager-form').onsubmit=e=>{e.preventDefault();work(e.submitter,async()=>{await api('/api/projects/'+e.target.dataset.project+'/manager',{manager:$('#project-manager').value});managerDialog.close();await loadProjects();await load();if(active==='stats')await loadStats()})};
let unlinkTarget;
$('#close-unlink').onclick=()=>unlinkDialog.close();
$('#delete-task-list').onchange=()=>{$('#submit-unlink').textContent=$('#delete-task-list').checked?'문서 삭제 후 연결 해제':'연결만 해제'};
$('#new-project').onclick=e=>work(e.target,async()=>{
  if(me.project_management_outline){window.location.href=me.links.outline+'/workhub/projects'+(selected()?'/'+encodeURIComponent(selected()):'');return}
  const [,d]=await Promise.all([loadProjects(),api('/api/project-candidates')]);$('#existing-collection').innerHTML='<option value="">새 컬렉션 만들기</option>'+options(d.collections);
  $('#linked-project-list').innerHTML=projects.length?projects.map(p=>`<div class="linked-project-row"><span>${esc(p.name)}<small>프로젝트 책임자: ${esc(p.manager?personName(p.manager):'미지정')}</small></span><button type="button" class="secondary" data-manager="${esc(p.id)}">책임자 변경</button><button type="button" class="secondary" data-unlink="${esc(p.id)}">연결 해제</button></div>`).join(''):'<p>현재 연결된 프로젝트가 없습니다.</p>';
  $$('[data-manager]').forEach(b=>b.onclick=()=>work(b,async()=>{const p=projects.find(p=>p.id===b.dataset.manager),d=await api('/api/projects/'+p.id+'/managers');$('#manager-project').textContent=p.name;$('#manager-form').dataset.project=p.id;$('#project-manager').innerHTML='<option value="">미지정</option>'+d.people.map(x=>`<option value="${esc(x.email)}">${esc(x.name)}</option>`).join('');$('#project-manager').value=p.manager||'';$('#project-dialog').close();$('#manager-dialog').showModal()}));
  $$('[data-unlink]').forEach(button=>button.onclick=()=>work(button,async()=>{
    const preview=await api('/api/projects/'+button.dataset.unlink+'/unlink-preview');unlinkTarget={...preview,idem:id()};$('#unlink-project-name').textContent=preview.project.name;
    $('#delete-task-list').checked=false;$('#delete-task-list').disabled=!preview.parent;$('#submit-unlink').textContent='연결만 해제';
    $('#unlink-document-note').textContent=preview.parent?`삭제 옵션 대상: ${preview.parent.title}. 하위 업무·첨부 자료 등 이 문서 아래의 모든 문서가 함께 휴지통으로 이동합니다.`:'삭제할 업무 목록을 확인할 수 없습니다. 문서를 건드리지 않고 연결만 해제할 수 있습니다.';
    unlinkDialog.querySelector('.dialog-error')?.remove();$('#project-dialog').close();unlinkDialog.showModal();
  }));$('#project-dialog').showModal();
});
$('#unlink-form').onsubmit=e=>{e.preventDefault();work(e.submitter,async()=>{
  await api('/api/projects/'+unlinkTarget.project.id+'/unlink',{idem:unlinkTarget.idem,delete_task_list:$('#delete-task-list').checked,expected_parent_id:$('#delete-task-list').checked?unlinkTarget.parent.id:''});
  unlinkDialog.close();$('#proposal').hidden=true;$('#weekly-preview').hidden=true;$('#research-result').textContent='';await loadProjects();await load();if(active==='stats')await loadStats();
})};
$('#project-form').onsubmit=e=>{e.preventDefault();work(e.submitter,async()=>{const p=await api('/api/projects',{...Object.fromEntries(new FormData(e.target)),idem:id()});$('#project-dialog').close();e.target.reset();await loadProjects(p.id);await load()})};
function criterionLines(t){
  const items=t.criteria||[];if(!items.length)return '<p class="muted">등록된 완료 기준이 없습니다.</p>';
  return `<p class="muted">완료 ${items.filter(i=>i.state==='완료').length} / ${items.length}개</p><ul class="checklist">`+items.map((i,n)=>`<li class="${i.state==='완료'?'done':''}"><span>${i.state==='완료'?'☑':'☐'}</span><div><b>${n+1}. ${esc(i.title)}</b><small>${i.owner===me.email.toLowerCase()?'내가 맡은 항목 · ':''}${esc(personName(i.owner))} · ${esc(i.state)}</small></div></li>`).join('')+'</ul>';
}
const projectProgress=document.createElement('div');
projectProgress.id='project-progress';projectProgress.className='project-progress';projectProgress.hidden=true;
projectProgress.innerHTML='<div class="project-progress-heading"><strong>프로젝트 진행률</strong><span id="project-progress-value"></span></div><progress id="project-progress-bar" max="100" value="0" aria-label="프로젝트 전체 진행률" title="전체 업무 진행률의 평균" aria-describedby="project-progress-note"></progress><p id="project-progress-note"></p>';
$('#tasks .toolbar').before(projectProgress);
function drawProjectProgress(){
  projectProgress.hidden=!selected();
  // Use the whole project, independently of the board's assignee/search filters.
  const valid=[...new Map(tasks.map(t=>[t.id,t])).values()].filter(t=>!t.error);
  const progress=valid.map(t=>{
    const raw=t.fields.progress;
    if(typeof raw!=='string'||!raw.replace(/%+$/,'').trim())return NaN;
    return Number(raw.replace(/%+$/,''));
  }).filter(n=>Number.isFinite(n)&&n>=0&&n<=100);
  const average=progress.length?Math.round((progress.reduce((a,b)=>a+b,0)/progress.length+Number.EPSILON)*10)/10:null;
  $('#project-progress-value').textContent=average===null?'—':`${average}%`;
  $('#project-progress-bar').hidden=average===null;
  $('#project-progress-bar').value=average??0;
  const excluded=tasks.length-valid.length;
  const manager=projects.find(p=>p.id===selected())?.manager;
  $('#project-progress-note').textContent=valid.length?
    `책임자 ${manager?personName(manager):'미지정'} · 업무 ${valid.length}개 · 완료 ${valid.filter(t=>t.fields.status==='완료').length}개${progress.length<valid.length?` · 진행률 미기재 ${valid.length-progress.length}개 제외`:''}${excluded?` · 형식 오류 ${excluded}건 제외`:''}`:
    (tasks.length?'집계 가능한 업무가 없습니다. 업무 문서 형식을 확인하세요.':'등록된 업무가 없습니다.');
}
function deadlineInfo(t){
 const raw=t.fields.due;if(!/^\d{4}-\d{2}-\d{2}$/.test(raw||''))return {days:Infinity,label:'마감일 미정',tone:''};
 const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
 const days=Math.round((Date.parse(raw)-Date.parse(today))/86400000);
 return {days,label:t.fields.status==='완료'?'완료':days<0?`${-days}일 지남`:days===0?'오늘 마감':days<=7?`${days}일 후 마감`:raw,tone:t.fields.status==='완료'?'done':days<0?'overdue':days<=7?'soon':''};
}
function resetBoard(){boardFocus='all';boardPage=1;$('#search').value='';$('#board-status').value='';draw()}
function showBoardTask(taskId){selectedTask=taskId;mine=false;boardFocus='all';boardPage=1;$('#search').value='';$('#board-status').value='';boardRenderKey='';tab('tasks');draw();$('#task-detail').scrollIntoView({behavior:'instant',block:'start'})}
function draw(){
 updateBoardFilterState();
 $('#board-title').textContent=mine?'내 업무':'팀 업무';
 const key=JSON.stringify([selected(),tasks,mine,boardFocus,boardPage,$('#board-sort').value,$('#search').value,$('#board-status').value,names,selectedTask]);
 if(key===boardRenderKey)return;boardRenderKey=key;drawProjectProgress();
 const previous=$('#report-task').value,previousCriterion=$('#report-criterion')?.value,q=$('#search').value.trim().toLowerCase();
 const scope=tasks.filter(t=>!mine||belongsToMe(t)),open=t=>t.fields.status!=='완료';
 const match=(t,focus)=>focus==='all'||focus==='open'&&open(t)||focus==='overdue'&&open(t)&&deadlineInfo(t).days<0||focus==='soon'&&open(t)&&deadlineInfo(t).days>=0&&deadlineInfo(t).days<=7;
 const groups=[['all','전체 업무'],['open','미완료'],['overdue','마감 지남'],['soon','7일 안에 마감']];
 renderHTML($('#board-summary'),groups.map(([focus,label])=>`<button class="board-summary-item ${focus}" data-board-focus="${focus}" aria-pressed="${boardFocus===focus}"><span>${label}</span><strong>${scope.filter(t=>match(t,focus)).length}<small>개</small></strong></button>`).join(''));
 $$('[data-board-focus]').forEach(b=>b.onclick=()=>{boardFocus=b.dataset.boardFocus;boardPage=1;$('#board-status').value='';draw()});
 let list=scope.filter(t=>match(t,boardFocus)&&(!$('#board-status').value||t.fields.status===$('#board-status').value)&&(t.title+' '+personName(t.fields.owner)+' '+(t.criteria||[]).map(i=>personName(i.owner)).join(' ')).toLowerCase().includes(q));
 list.sort((a,b)=>deadlineInfo(a).days-deadlineInfo(b).days||a.title.localeCompare(b.title,'ko'));
 const pages=Math.max(1,Math.ceil(list.length/boardPageSize));boardPage=Math.min(boardPage,pages);
 const rows=list.slice((boardPage-1)*boardPageSize,boardPage*boardPageSize);
 $('#board-list-title').textContent=(mine?'내 업무':'팀 전체')+' · '+(groups.find(g=>g[0]===boardFocus)?.[1]||'전체 업무');
 $('#board-count').textContent=list.length?`${list.length}개 중 ${(boardPage-1)*boardPageSize+1}–${Math.min(boardPage*boardPageSize,list.length)}개 표시`:'현재 조건에 맞는 업무가 없습니다.';
 renderHTML($('#task-grid'),rows.length?`<div class="work-list">${rows.map(t=>{const f=t.fields,own=(t.criteria||[]).filter(i=>i.owner===me.email.toLowerCase()),n=Number.parseFloat(f.progress),due=deadlineInfo(t);return `<article data-key="${esc(t.id)}" class="work-row ${selectedTask===t.id?'selected':''}"><button class="work-open" data-open-task="${esc(t.id)}" aria-expanded="${selectedTask===t.id}" aria-controls="task-detail"><div class="work-row-title"><h3>${esc(t.title)}</h3><span class="status-badge ${f.status==='완료'?'done':f.status==='미착수'?'planned':''}">${esc(t.error?'문서 확인 필요':f.status)}</span></div><p class="work-row-meta">${esc(personName(f.owner)||'미확인')}</p><div class="work-row-progress">${Number.isFinite(n)?`<progress max="100" value="${n}" aria-label="${esc(t.title)} 전체 진행률"></progress>`:''}<b>${esc(f.progress||'—')}</b></div><div class="work-row-bottom"><span class="due-badge ${due.tone}">${esc(due.label)}</span><span class="work-detail-hint">${selectedTask===t.id?'선택됨':'상세 →'}</span></div></button>${writable(t)&&f.status!=='완료'?`<button class="row-report secondary" data-row-report="${esc(t.id)}">진행 보고 →</button>`:''}</article>`}).join('')}</div>`:`<div class="empty-state"><h3>${!tasks.length?'아직 등록된 업무가 없습니다':!scope.length&&mine?'아직 나에게 배정된 업무가 없습니다':'조건에 맞는 업무가 없습니다'}</h3><p>${!tasks.length?'업무를 등록해 시작하세요.':!scope.length&&mine?'팀 업무를 보거나 배정을 요청하세요.':'검색어나 필터를 바꿔보세요.'}</p><button class="secondary" id="board-empty-action">${!tasks.length?'업무 등록':!scope.length&&mine?'팀 전체 보기':'필터 초기화'}</button></div>`);
 if($('#board-empty-action'))$('#board-empty-action').onclick=()=>{if(!tasks.length)$('#new-task').click();else{if(!scope.length)mine=false;resetBoard()}};
 renderHTML($('#board-pagination'),`<button id="board-prev" class="secondary" ${boardPage<=1?'disabled':''}>이전</button><span>${boardPage} / ${pages}쪽</span><button id="board-next" class="secondary" ${boardPage>=pages?'disabled':''}>다음</button>`);$('#board-pagination').hidden=pages<=1;
 $('#board-prev').onclick=()=>{boardPage--;draw();$('#board-list-heading').scrollIntoView({behavior:'smooth'})};$('#board-next').onclick=()=>{boardPage++;draw();$('#board-list-heading').scrollIntoView({behavior:'smooth'})};
 if(selectedTask&&!list.some(t=>t.id===selectedTask))selectedTask='';drawTaskDetail();
 $$('[data-open-task]').forEach(b=>b.onclick=()=>{selectedTask=b.dataset.openTask;boardRenderKey='';draw();if(matchMedia('(max-width:1240px)').matches)$('#task-detail').scrollIntoView({behavior:'smooth',block:'start'})});
 $$('[data-row-report]').forEach(b=>b.onclick=()=>startReport(b.dataset.rowReport));
 if(!reportBusy){renderHTML($('#report-task'),'<option value="">업무를 선택하세요</option>'+tasks.filter(writable).map(t=>`<option value="${esc(t.id)}">${esc(t.title)} · ${esc(t.fields.progress)}</option>`).join(''));$('#report-task').value=tasks.some(t=>t.id===previous&&writable(t))?previous:'';
 if(reportTaskId!==$('#report-task').value)restoreReportDraft();else drawReportItems(previousCriterion);}
}
function safeUrl(value){try{const u=new URL(value);return ['http:','https:'].includes(u.protocol)?u.href:''}catch{return ''}}
function drawTaskDetail(){
  const t=tasks.find(t=>t.id===selectedTask),panel=$('#task-detail');panel.hidden=!t;$('#board-detail-empty').hidden=!!t;$('#board-layout').classList.toggle('has-detail',!!t);if(!t)return;
  const f=t.fields,reports=(t.text||'').split(/^### 보고 기록\s*$/m).slice(1).reverse(),result=safeUrl(f.result);
  renderHTML(panel,`<div class="detail-heading"><div><small>${esc(t.collectionName)}</small><h2>${esc(t.title)}</h2></div><button class="secondary" id="close-task-detail" aria-label="업무 상세 닫기">닫기</button></div><p class="detail-meta">담당 · ${esc(personName(f.owner))}<br>${esc(f.status)} · 진행률 ${esc(f.progress)} · 계획 ${esc(f.start||'미정')} ~ ${esc(f.due)}</p><div class="detail-action-bar">${writable(t)?'<button id="detail-report">이 업무 진행 보고 →</button>':'<p>이 업무에 배정된 항목만 보고할 수 있습니다.</p>'}${me.admin&&!t.error?'<button id="detail-schedule" class="secondary">일정 조정</button><button id="detail-criteria" class="secondary">완료 기준 · 담당자 배정</button>':''}</div><h3 class="detail-section">완료 기준</h3>${t.error?`<p class="error">${esc(t.error)}</p>`:criterionLines(t)}<dl class="task-facts"><dt>다음 할 일</dt><dd>${esc(f.next||'미기재')}</dd><dt>장애 요인</dt><dd>${esc(f.blocker||'없음')}</dd><dt>결과물</dt><dd>${result?`<a href="${esc(result)}" target="_blank" rel="noopener">결과물 열기 ↗</a>`:esc(f.result||'미등록')}</dd></dl><div class="detail-actions"><a href="${esc(t.url)}" target="_blank" rel="noopener">Outline 원본 ↗</a></div><details class="recent-reports"><summary>최근 보고 기록 ${reports.length}건</summary>${reports.length?reports.slice(0,3).map(r=>`<pre>${esc(namedText(r.trim()))}</pre>`).join(''):'<p>아직 반영된 보고 기록이 없습니다.</p>'}${reports.length>3?'<p>이전 기록은 Outline 원본에서 확인하세요.</p>':''}</details><small>수정 · ${esc(new Date(t.updatedAt).toLocaleString('ko-KR'))}</small>`);
  $('#close-task-detail').onclick=()=>{const button=$$('[data-open-task]').find(b=>b.dataset.openTask===selectedTask);selectedTask='';boardRenderKey='';draw();button?.focus()};
  if($('#detail-report'))$('#detail-report').onclick=()=>startReport(t.id);
  if($('#detail-schedule'))$('#detail-schedule').onclick=()=>openSchedule(t);
  if($('#detail-criteria'))$('#detail-criteria').onclick=e=>work(e.target,async()=>{await loadPeople();openCriteria(t.id)});
}
let scheduleTask=null;
function openSchedule(task){scheduleTask=task;const form=$('#schedule-form');form.elements.start.value=/^\d{4}-\d{2}-\d{2}$/.test(task.fields.start||'')?task.fields.start:'';form.elements.due.value=/^\d{4}-\d{2}-\d{2}$/.test(task.fields.due||'')?task.fields.due:'';$('#schedule-task-name').textContent=task.title;$('#schedule-error').textContent='';$('#schedule-dialog').showModal()}
$('#schedule-close').onclick=()=>$('#schedule-dialog').close();
$('#schedule-form').onsubmit=async e=>{e.preventDefault();const f=e.target,button=e.submitter;$('#schedule-error').textContent='';if(f.elements.start.value&&f.elements.due.value&&f.elements.start.value>f.elements.due.value){$('#schedule-error').textContent='시작일은 마감일보다 늦을 수 없습니다.';return}button.disabled=true;try{const p=await api('/api/tasks/'+scheduleTask.id+'/proposals',{changes:{start:f.elements.start.value||'미정',due:f.elements.due.value||'미정'},idem:id()});$('#schedule-dialog').close();showProposal(p)}catch(error){$('#schedule-error').textContent=error.message}finally{button.disabled=false}};
function forgetTaskDraft(taskId){pendingReports.delete(taskId);reportDrafts.delete(taskId);if(reportTaskId===taskId){reportTaskId='';$('#report-text').value='';$('#report-task').value=''}if(currentProposal?.doc_id===taskId){currentProposal=null;$('#proposal').replaceChildren();setReportStage(1);history.replaceState(null,'',location.pathname)}}
function draftKey(){return 'workhub-drafts:'+me?.sub}
function persistDrafts(){if(!me)return;try{sessionStorage.setItem(draftKey(),JSON.stringify({drafts:[...reportDrafts].slice(-40),pending:[...pendingReports].slice(-20)}))}catch{}}
function recoverDrafts(){try{const data=JSON.parse(sessionStorage.getItem(draftKey())||'{}');for(const [key,value] of data.drafts||[])reportDrafts.set(key,value);for(const [key,value] of data.pending||[])pendingReports.set(key,value)}catch{}updatePendingBar()}
function saveReportDraft(){if(reportTaskId){reportDrafts.set(reportTaskId,{collectionId:tasks.find(t=>t.id===reportTaskId)?.collectionId||reportDrafts.get(reportTaskId)?.collectionId||selected(),text:$('#report-text').value,criterion:$('#report-criterion').value,state:$('#criterion-state').value});persistDrafts()}}
function restoreReportDraft(){saveReportDraft();reportTaskId=$('#report-task').value;const draft=reportDrafts.get(reportTaskId);$('#report-text').value=draft?.text||'';drawReportItems(draft?.criterion);if(draft?.state)$('#criterion-state').value=draft.state}
function rememberProposal(p){if(['PENDING','APPLYING','CONFLICT'].includes(p.state))pendingReports.set(p.doc_id,{id:p.id,title:p.title,collectionId:p.collectionId,state:p.state});else{pendingReports.delete(p.doc_id);if(p.state==='APPLIED'){reportDrafts.delete(p.doc_id);if(reportTaskId===p.doc_id){reportTaskId='';$('#report-text').value=''}}}persistDrafts();updatePendingBar()}
function updatePendingBar(){const bar=$('#pending-report-bar');if(!bar)return;const entries=[...pendingReports.entries()];bar.hidden=!entries.length||(active==='assistant'&&assistantMode==='report'&&reportStage!==1);if(!bar.hidden){renderHTML(bar,`<div><b>미확정 초안 ${entries.length}개</b><p>확정 전에는 반영되지 않습니다.</p></div><div>${entries.map(([task,p])=>`<button class="secondary" data-resume-draft="${esc(task)}">${esc(p.title)} · 초안 계속하기</button>`).join('')}</div>`);$$('[data-resume-draft]').forEach(b=>b.onclick=()=>work(b,()=>resumeProposal(b.dataset.resumeDraft)))}}
async function resumeProposal(taskId){const saved=pendingReports.get(taskId);if(!saved)return;try{showProposal(await api('/api/proposals/'+saved.id))}catch(e){if([403,404].includes(e.status)){forgetTaskDraft(taskId);persistDrafts();updatePendingBar()}throw e}}
function setAssistantMode(mode){assistantMode=mode;$('#report-panel').hidden=mode!=='report';$('#research-panel').hidden=mode!=='research';$('#report-tab').setAttribute('aria-selected',String(mode==='report'));$('#research-tab').setAttribute('aria-selected',String(mode==='research'));$('#report-tab').tabIndex=mode==='report'?0:-1;$('#research-tab').tabIndex=mode==='research'?0:-1;syncProjectBar();updatePendingBar();if(mode==='research')loadResearchStatus()}
function setReportStage(stage){reportStage=stage;syncProjectBar();$('#report-editor').hidden=stage!==1;$('#proposal').hidden=stage===1;$$('#report-steps li').forEach((li,i)=>{if(i===stage-1)li.setAttribute('aria-current','step');else li.removeAttribute('aria-current')});updatePendingBar()}
function startReport(taskId){saveReportDraft();tab('assistant');setAssistantMode('report');$('#report-task').value=taskId;restoreReportDraft();setReportStage(1);if(pendingReports.has(taskId)){resumeProposal(taskId).catch(e=>notice(e.message));return}$('#report-text').focus()}
async function returnToTask(p){saveReportDraft();await loadProjects(p.collectionId);await load();history.replaceState(null,'',location.pathname);showBoardTask(p.doc_id);}
function setReportMethod(method){reportMethod=method;$$('[data-report-method]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.reportMethod===method)));$('#ai-report-fields').hidden=method!=='ai';$('#report-text').required=method==='ai';$('#quick-state').hidden=method!=='direct';drawReportItems($('#report-criterion').value)}
$('#report-tab').onclick=()=>setAssistantMode('report');$('#research-tab').onclick=()=>setAssistantMode('research');
for(const [i,b] of [$('#report-tab'),$('#research-tab')].entries()){b.tabIndex=i===0?0:-1;b.onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const next=e.key==='Home'?$('#report-tab'):e.key==='End'?$('#research-tab'):i===0?$('#research-tab'):$('#report-tab');next.click();next.focus()}};}
$$('[data-workflow-entry]').forEach(b=>b.onclick=()=>{if(b.dataset.workflowEntry==='tasks')tab('tasks');else{tab('assistant');setAssistantMode(b.dataset.workflowEntry==='research'?'research':'report');if(b.dataset.workflowEntry==='report')setReportStage(1)}});
$('#report-back-board').onclick=()=>{const taskId=$('#report-task').value;if(taskId)showBoardTask(taskId);else tab('tasks')};
$$('[data-report-method]').forEach(b=>b.onclick=()=>setReportMethod(b.dataset.reportMethod));
$$('[data-report-prompt]').forEach(b=>{b.textContent=b.dataset.reportPrompt.replace(/:\s*$/,'')+' 넣기';b.title='작성 중인 보고 끝에 이 문구를 추가합니다.';b.onclick=()=>{const input=$('#report-text');input.value+=(input.value.trim()?'\n':'')+b.dataset.reportPrompt;saveReportDraft();input.focus()}});
$('#report-text').oninput=saveReportDraft;
window.addEventListener('pagehide',saveReportDraft);
async function load(){
  const request=++boardRequest;
  const cid=selected();if(!cid){clearAccessDisplays();$('#task-grid').innerHTML='<div class="empty">접근 가능한 프로젝트가 없습니다. 관리자에게 Outline 프로젝트 구성원·그룹 권한을 요청하세요.</div>';$('#sync-state').textContent='';return}
  if(boardProject!==cid){tasks=[];boardRenderKey='';selectedTask='';projectProgress.hidden=true;$('#task-grid').textContent='업무를 불러오고 있습니다…'}
  let d,roster;try{[d,roster]=await Promise.all([api('/api/tasks?'+new URLSearchParams({collection_id:cid})),api('/api/assignees?'+new URLSearchParams({collection_id:cid}))])}catch(e){if(request!==boardRequest)return;if(![401,403,404].includes(e.status)){$('#sync-state').textContent='동기화 실패 · 다시 동기화하세요.';throw e}clearAccessDisplays();setReportStage(1);if(e.status===401)throw e;await loadProjects();return load()}if(request!==boardRequest||cid!==selected())return;
  applyPeople(cid,roster);
  boardProject=cid;
  tasks=d.tasks;for(const [taskId,draft] of reportDrafts){if(draft.collectionId===cid&&!tasks.some(t=>t.id===taskId&&writable(t))){forgetTaskDraft(taskId)}}persistDrafts();updatePendingBar();draw();$('#sync-state').textContent=d.sync?.ok?`동기화 ${new Date(d.sync.at).toLocaleTimeString('ko-KR')}`:'Outline 확인 중…';
}
function updateBoardFilterState(){
  [[$('#mine'),mine],[$('#all'),!mine]].forEach(([button,selected])=>{
    button.classList.toggle('is-active',selected);
    button.setAttribute('aria-pressed',String(selected));
  });
}
$('#mine').onclick=()=>{mine=true;boardPage=1;draw()};$('#all').onclick=()=>{mine=false;boardPage=1;draw()};$('#search').oninput=()=>{boardPage=1;draw()};
$('#board-sort').onchange=()=>{boardPage=1;draw()};$('#board-reset').onclick=resetBoard;
$('#board-status').onchange=()=>{boardFocus='all';boardPage=1;draw()};
$('#sync').onclick=e=>work(e.target,async()=>{await api('/api/sync',{});await load()});
function addRow(container,item={}){
  const row=document.createElement('div');row.className='criterion-row';row.dataset.id=item.id||'';
  row.innerHTML=`<label>완료 기준<input class="criterion-title" required minlength="2" maxlength="160" value="${esc(item.title||'')}" placeholder="예: 요구사항 승인"></label><label>배정할 담당자<select class="criterion-owner" required>${personOptions(item.owner||(container.id==='create-criteria-rows'?people.find(p=>p.id===$('#create-form').elements.assignee_id.value)?.email:editingTask?.fields.owner)||me.email)}</select></label><label>상태<select class="criterion-state">${states.map(s=>`<option ${s===(item.state||'예정')?'selected':''}>${s}</option>`).join('')}</select></label><button type="button" class="secondary remove-criterion" aria-label="완료 기준 삭제">삭제</button>`;
  row.querySelector('button').onclick=()=>row.remove();container.append(row);
}
function readRows(container){return [...container.querySelectorAll('.criterion-row')].map(r=>{const value=r.querySelector('.criterion-owner').value;return {...(r.dataset.id?{id:r.dataset.id}:{}),title:r.querySelector('.criterion-title').value,...(value.startsWith('legacy:')?{owner:value.slice(7)}:{assignee_id:value}),state:r.querySelector('.criterion-state').value}})}
function openCriteria(taskId){editingTask=tasks.find(t=>t.id===taskId);$('#criteria-task-title').textContent=editingTask.title;$('#criteria-rows').innerHTML='';(editingTask.criteria?.length?editingTask.criteria:[{}]).forEach(i=>addRow($('#criteria-rows'),i));$('#criteria-dialog').showModal()}
$('#add-criterion').onclick=()=>addRow($('#criteria-rows'));
$('#criteria-form').onsubmit=e=>{e.preventDefault();work(e.submitter,async()=>{const p=await api('/api/tasks/'+editingTask.id+'/proposals',{changes:{criteria:readRows($('#criteria-rows'))},idem:id()});$('#criteria-dialog').close();showProposal(p)})};
$('#create-form').elements.project.readOnly=true;
const ownerInput=$('#create-form').elements.owner,ownerSelect=document.createElement('select');ownerSelect.name='assignee_id';ownerSelect.required=true;ownerInput.closest('label').firstChild.textContent='업무 담당자';ownerInput.replaceWith(ownerSelect);
const ownerFilter=document.createElement('select');ownerFilter.id='filter-owner';$('#filter-owner').closest('label').firstChild.textContent='담당자';$('#filter-owner').replaceWith(ownerFilter);
const createCriteria=document.createElement('div');createCriteria.id='create-criteria';createCriteria.className='admin-only';createCriteria.hidden=true;
createCriteria.innerHTML='<h3>완료 기준과 담당자 배정</h3><p>완료 기준에 따라 상태·진행률을 자동 계산합니다.</p><div id="create-criteria-rows"></div><button type="button" class="secondary" id="create-add-criterion">＋ 완료 기준 추가</button>';
$('#create-form').elements.notes.closest('label').before(createCriteria);
const extraFields=document.createElement('details');extraFields.className='create-extra';extraFields.innerHTML='<summary>추가 정보 · 선택 사항</summary>';$('#create-form').elements.notes.closest('label').before(extraFields);for(const name of ['blocker','next','result','notes'])extraFields.append($('#create-form').elements[name].closest('label'));
function updateCreateMode(){const automatic=!!$('#create-criteria-rows').children.length;for(const name of ['status','progress']){$('#create-form').elements[name].closest('label').hidden=automatic;$('#create-form').elements[name].disabled=automatic}}
new MutationObserver(updateCreateMode).observe($('#create-criteria-rows'),{childList:true});
$('#create-add-criterion').onclick=()=>addRow($('#create-criteria-rows'));
let createOpenRequest=0,createReady=false;
const createStatus=document.createElement('p');createStatus.className='muted';createStatus.setAttribute('role','status');$('#create-form').querySelector('.dialog-head').after(createStatus);
$('#create-dialog').addEventListener('close',()=>{createOpenRequest++;createReady=false});
$('#new-task').onclick=e=>work(e.target,async()=>{
 const request=++createOpenRequest,cid=selected(),f=$('#create-form'),submit=f.querySelector('button:not([type])');createReady=false;
 if(!f.elements.start.value)f.elements.start.value=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
 f.elements.project.value=projects.find(p=>p.id===cid)?.name||'';f.elements.assignee_id.innerHTML='<option value="">담당자 확인 중…</option>';f.elements.assignee_id.disabled=true;submit.disabled=true;$('#create-add-criterion').disabled=true;createStatus.textContent='담당자를 확인하고 있습니다. 업무 내용은 먼저 입력할 수 있습니다.';createStatus.className='muted';$('#create-dialog').showModal();
 try{await loadPeople();if(request!==createOpenRequest||cid!==selected()||!$('#create-dialog').open)return;
  f.elements.assignee_id.innerHTML=(me.admin?'<option value="">실무 담당자를 선택하세요</option>':'')+personOptions(me.admin?'':me.email,!me.admin);f.elements.assignee_id.disabled=false;submit.disabled=false;$('#create-add-criterion').disabled=false;createStatus.textContent='';createReady=true;
 }catch(error){if(request===createOpenRequest&&$('#create-dialog').open){createStatus.className='error';createStatus.textContent=error.message+' 창을 닫고 다시 열어 주세요.'}throw error}
});
$('#close-create').onclick=()=>$('#create-dialog').close();
$('#create-form').onsubmit=e=>{e.preventDefault();if(!createReady)return;work(e.submitter,async()=>{
  const f=Object.fromEntries(new FormData(e.target)),{title,notes,assignee_id,...fields}=f,payload={title,notes,assignee_id,fields:{status:'미착수',progress:'0%',...fields},collection_id:selected(),criteria:readRows($('#create-criteria-rows'))},fingerprint=JSON.stringify(payload);
  if(pendingCreate?.fingerprint!==fingerprint)pendingCreate={fingerprint,idem:id()};const created=await api('/api/tasks',{...payload,idem:pendingCreate.idem});pendingCreate=null;$('#create-dialog').close();e.target.reset();$('#create-criteria-rows').innerHTML='';await load();showBoardTask(created.id);$('#board-count').textContent='✓ '+created.title+' · 등록 완료';
})};
function proposalOutcome(p){
  if(!['APPLIED','CANCELLED','APPLYING'].includes(p.state))return '';
  const applied=p.state==='APPLIED',cancelled=p.state==='CANCELLED',r=p.result;
  const time=p.applied_at||p.cancelled_at;
  return `<div class="proposal-outcome ${applied?'saved':cancelled?'cancelled':'pending'}" role="status" aria-live="polite" tabindex="-1"><h2>${applied?'✓ Outline 반영 완료':cancelled?'초안 취소 완료':'반영 결과 확인 필요'}</h2><p><strong>${esc(p.title)}</strong></p><p>${applied?(r?('start' in (p.changes||{})?'업무 일정을 저장했습니다. 변경 내용을 아래에서 확인할 수 있습니다.':'완료 체크와 업무 진행률을 저장했습니다. 아래는 이 보고를 반영한 시점의 결과입니다.'):'반영된 이전 보고입니다. 저장 당시의 상세 결과가 없는 기록이므로 아래 변경 내용과 Outline 원본을 확인하세요.'):cancelled?'이 초안으로는 Outline 원본·완료 체크·진행률을 변경하지 않았습니다. 새 보고를 작성할 수 있습니다.':'저장 요청을 보낸 상태입니다. 아직 실패나 성공으로 확정하지 않았습니다. 아래 버튼으로 저장 결과를 다시 확인하세요.'}</p>${applied&&r?`<div class="outcome-metrics"><span>업무 상태 <b>${esc(r.status)}</b></span><span>업무 진행률 <b>${esc(r.progress)}</b></span><span>완료 체크 <b>${r.criteria_done} / ${r.criteria_total}개</b></span></div>${r.criteria?.length?`<ul class="outcome-checklist">${r.criteria.map(i=>`<li><span>${i.state==='완료'?'☑':'☐'}</span><span>${esc(i.title)}</span><b>${esc(i.state)}</b><small>${esc(personName(i.owner))}</small></li>`).join('')}</ul>`:''}`:''}${time?`<small>${p.verification==='subsequent_snapshot'?'저장 이력으로 반영 확인':'처리 시각'} · ${esc(new Date(time).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}))}</small>`:''}</div>`;
}
function proposalSummary(p){
  const live=text=>String(text||'').split(/^### 보고 기록\s*$/m)[0];
  const items=text=>[...live(text).matchAll(/^\s*[-*] \[[ xX]\] (C-[a-f0-9]{8}) \| (.+?) \| 담당자: ([^|]+?) \| 상태: (예정|진행 중|완료)\s*$/gm)].map(m=>({id:m[1],title:m[2],owner:m[3],state:m[4]}));
  const before=items(p.before),after=items(p.after),rows=[];
  for(const i of after){const old=before.find(o=>o.id===i.id);if(!old||old.title!==i.title||old.owner!==i.owner||old.state!==i.state)rows.push([i.title,old?`${personName(old.owner)} · ${old.state}`:'새 항목',`${personName(i.owner)} · ${i.state}`])}
  for(const i of before)if(!after.some(a=>a.id===i.id))rows.push([i.title,`${personName(i.owner)} · ${i.state}`,'항목 삭제']);
  for(const label of ['프로젝트','담당자','시작일','마감일','상태','진행률','장애요인','다음 행동','결과물']){
    const re=new RegExp('^'+label+':\\s*([^\\n]*)','m'),old=live(p.before).match(re)?.[1]||'—',next=live(p.after).match(re)?.[1]||'—';
    if(old!==next)rows.push([label,label==='담당자'?personName(old):old,label==='담당자'?personName(next):next]);
  }
  return `<section class="change-summary"><h3>변경 사항</h3>${rows.length?`<div class="table-wrap"><table><thead><tr><th>항목</th><th>변경 전</th><th>변경 후</th></tr></thead><tbody>${rows.map(r=>`<tr>${r.map(v=>`<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:'<p>상태·진행률 변경 없이 보고 기록을 추가합니다.</p>'}</section>`;
}
function showProposal(p){
  const messages={APPLIED:'Outline에 반영되었습니다.',CANCELLED:'취소된 초안입니다. Outline 원본·완료 체크·진행률은 변경하지 않았습니다. 새 보고를 작성할 수 있습니다.',CONFLICT:'원본이 바뀐 초안입니다. 취소하거나 새 보고를 작성하세요.',APPLYING:'반영 결과를 확인 중입니다. 원본과 확정 결과를 먼저 확인하세요.'};
  const canConfirm=['PENDING','APPLYING'].includes(p.state),canCancel=['PENDING','CONFLICT'].includes(p.state);
  const terminal=['APPLIED','CANCELLED'].includes(p.state);
  saveReportDraft();currentProposal=p;rememberProposal(p);tab('assistant');setAssistantMode('report');setReportStage(terminal?3:2);
  history.replaceState(null,'','#proposal-'+p.id);
  $('#proposal').innerHTML=`<p class="proposal-project">${esc(projects.find(project=>project.id===p.collectionId)?.name||'프로젝트 업무 보고')}</p>${proposalOutcome(p)}${terminal?'<details class="proposal-details"><summary>처리한 보고와 변경 내용 보기</summary>':''}<h2>${esc(p.title)} · 변경 확인</h2><p role="status">${esc(messages[p.state]||'변경 내용을 확인하세요. 확정 전에는 반영되지 않습니다.')}</p>${proposalSummary(p)}${p.formatted_report?`<h3>보고문</h3><pre class="report-preview">${esc(p.formatted_report)}</pre>`:''}<details class="source-diff"><summary>Outline 문서 전체 변경 내용</summary><div class="split"><div><h3>변경 전</h3><pre class="diff">${esc(namedText(p.before))}</pre></div><div><h3>${p.state==='CANCELLED'?'취소된 변경안':'변경 후'}</h3><pre class="diff">${esc(namedText(p.after))}</pre></div></div></details><p>보고 근거: ${esc(p.evidence||'관리자 또는 담당자 직접 입력')}</p>${terminal?'</details>':''}<div class="proposal-actions">${p.state==='PENDING'?'<button id="edit-proposal" class="secondary">초안 취소 후 수정</button>':''}<button id="cancel-proposal" class="secondary" ${canCancel?'':'disabled'} ${terminal?'hidden':''}>초안 취소</button><button id="confirm" ${canConfirm?'':'disabled'} ${terminal?'hidden':''}>${p.state==='APPLYING'?'반영 결과 다시 확인':'확정하고 Outline에 반영'}</button>${terminal?'<button id="new-report">새 보고 작성</button><button id="back-board" class="secondary">이 업무로 돌아가기</button>':''}<a href="${esc(p.url)}" target="_blank" rel="noopener">Outline 원본 열기 ↗</a></div>`;
  const act=async(button,action)=>{
    $('#confirm').disabled=true;$('#cancel-proposal').disabled=true;if($('#edit-proposal'))$('#edit-proposal').disabled=true;
    notice(action==='cancel'?'초안을 취소하고 있습니다…':'Outline 저장 결과를 확인하고 있습니다…');
    let result;
    try{result=await api('/api/proposals/'+p.id+'/'+action,{})}
    catch(error){
      if([403,404].includes(error.status)){forgetTaskDraft(p.doc_id);persistDrafts();updatePendingBar();notice(error.message);return}
      let latest;try{latest=await api('/api/proposals/'+p.id)}catch{}
      if(latest?.state===(action==='cancel'?'CANCELLED':'APPLIED'))result=latest;
      else{showProposal(latest||p);notice(error.message);return}
    }
    showProposal(result);notice();
    try{await load()}catch{notice('처리는 완료되었습니다. 업무 목록 새로고침이 지연되어 아래 처리 결과를 유지합니다.')}
  };
  $('#confirm').onclick=e=>act(e.target,'confirm');$('#cancel-proposal').onclick=e=>act(e.target,'cancel');
  if($('#edit-proposal'))$('#edit-proposal').onclick=e=>work(e.target,async()=>{const result=await api('/api/proposals/'+p.id+'/cancel',{});rememberProposal(result);await loadProjects(p.collectionId);await load();$('#report-task').value=p.doc_id;restoreReportDraft();setReportStage(1);history.replaceState(null,'',location.pathname);$('#report-feedback').textContent='이전 초안을 취소했습니다. 내용을 고쳐 새 초안을 만드세요.';$('#report-text').focus()});
  if(terminal){$('#new-report').onclick=e=>work(e.target,async()=>{await loadProjects(p.collectionId);await load();reportDrafts.delete(p.doc_id);if(reportTaskId===p.doc_id){reportTaskId='';$('#report-text').value=''}startReport(p.doc_id);history.replaceState(null,'',location.pathname)});$('#back-board').onclick=e=>work(e.target,()=>returnToTask(p))}
  $('#proposal').scrollIntoView({behavior:'smooth'});
  $('#proposal .proposal-outcome')?.focus({preventScroll:true});
}
const itemSelector=document.createElement('label');itemSelector.innerHTML='報告할 완료 기준<select id="report-criterion"><option value="">내 항목을 함께 보고</option></select>';itemSelector.firstChild.textContent='보고할 완료 기준';$('#report-context').after(itemSelector);
const itemStatus=document.createElement('div');itemStatus.id='quick-state';itemStatus.hidden=true;itemStatus.innerHTML='<h3>항목 상태</h3><p>완료 기준과 상태를 선택한 뒤 변경안을 확인하세요.</p><label>변경할 상태<select id="criterion-state"><option>예정</option><option>진행 중</option><option>완료</option></select></label><button type="button" id="apply-state">상태 변경안 확인</button>';$('#report-form').after(itemStatus);
function drawReportItems(previous){
 const t=tasks.find(t=>t.id===$('#report-task').value),items=t?.criteria||[],own=items.filter(i=>me.admin||i.owner===me.email.toLowerCase()),pending=t&&pendingReports.has(t.id);
 renderHTML($('#report-criterion'),'<option value="">'+(!t?'업무 선택 후 표시됩니다':reportMethod==='direct'?'변경할 항목을 선택하세요':items.length?(me.admin?'여러 항목을 함께 보고':'내 담당 항목을 함께 보고'):'완료 기준 없음 · 업무 전체 보고')+'</option>'+own.map((i,n)=>`<option value="${esc(i.id)}">${n+1}. ${esc(i.title)} · ${esc(personName(i.owner))} · ${esc(i.state)}</option>`).join(''));
 $('#report-criterion').value=own.some(i=>i.id===previous)?previous:'';
 $('#report-criterion').closest('label').hidden=!t||!items.length;$('#report-criterion').disabled=!t||reportBusy;$('#report-task').disabled=reportBusy;
 const selectedItem=own.find(i=>i.id===$('#report-criterion').value);
 $('#report-scope').textContent=projects.find(p=>p.id===selected())?.name||'프로젝트를 선택하세요';
 renderHTML($('#report-context'),t?`<b>${esc(t.title)}</b><p class="context-facts">담당 ${esc(personName(t.fields.owner))} · 마감 ${esc(t.fields.due)} · 진행률 ${esc(t.fields.progress)}</p>${!items.length?'<p class="context-note">완료 기준 없이 업무 전체를 보고합니다.</p>':''}${selectedItem?`<p class="context-note">보고 대상 · <strong>${esc(selectedItem.title)}</strong></p>`:''}${own.length?`<ul class="context-items">${own.map(i=>`<li>${esc(i.title)} <b>${esc(i.state)}</b></li>`).join('')}</ul>`:''}`:'');
 if(t&&!own.length&&reportMethod==='direct'){reportMethod='ai';$$('[data-report-method]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.reportMethod==='ai')));$('#ai-report-fields').hidden=false;$('#report-text').required=true;$('#quick-state').hidden=true}const available=tasks.filter(writable);$('#report-empty').hidden=available.length>0;
 renderHTML($('#report-empty'),`<h3>${selected()?'보고할 업무가 없습니다':'참여 중인 프로젝트가 없습니다'}</h3><p>${selected()?'프로젝트를 바꾸거나 업무 배정을 요청하세요.':'관리자에게 프로젝트 참여 권한을 요청하세요.'}</p><button type="button" class="secondary" id="report-empty-board">업무 보드 보기</button>`);$('#report-empty-board').onclick=()=>tab('tasks');
 $('#make-report').disabled=!t||reportBusy||!!pending;$('#report-text').disabled=!t||reportBusy||!!pending;
 $('#apply-state').disabled=!t||!selectedItem||reportBusy||!!pending;$('#criterion-state').disabled=!selectedItem||reportBusy||!!pending;
 $('#report-feedback').textContent=reportBusy?'보고 초안 작성 중…':pending?'미확정 초안이 있습니다. ‘초안 계속하기’를 눌러주세요.':!t?'보고할 업무를 선택하세요.':'확정 전에는 업무 기록이 바뀌지 않습니다.';
 $$('[data-report-method],[data-report-prompt]').forEach(b=>b.disabled=!t||reportBusy||!!pending||(b.dataset.reportMethod==='direct'&&!own.length));syncProjectBar();
}
$('#report-task').onchange=()=>{restoreReportDraft();setReportStage(1)};
$('#report-criterion').onchange=()=>{const item=tasks.find(t=>t.id===$('#report-task').value)?.criteria?.find(i=>i.id===$('#report-criterion').value);if(item)$('#criterion-state').value=item.state;drawReportItems($('#report-criterion').value);saveReportDraft()};$('#criterion-state').onchange=saveReportDraft;
async function submitReport(button,direct=false){
 if(reportBusy)return;const taskId=$('#report-task').value,cid=selected(),criterionId=$('#report-criterion').value;
 if(!taskId||!tasks.some(t=>t.id===taskId&&writable(t)))return notice('보고할 업무를 먼저 선택하세요.');
 if(pendingReports.has(taskId))return resumeProposal(taskId);
 if(direct&&!criterionId)return notice('변경할 완료 기준을 선택하세요.');
 notice();saveReportDraft();const text=$('#report-text').value,state=$('#criterion-state').value;reportBusy=true;drawReportItems(criterionId);let failureMessage='';
 try{
  const p=direct?await api('/api/tasks/'+taskId+'/proposals',{changes:{criterion_states:{[criterionId]:state}},idem:id()}):await api('/api/report',{code:taskId,text,idem:id(),collection_id:cid,criterion_id:criterionId});
  if(p.doc_id!==taskId||p.collectionId!==cid)throw Error('보고 대상이 달라 초안을 표시하지 않았습니다. 업무를 다시 확인하세요.');
  if(!projects.some(project=>project.id===cid)||(boardProject===cid&&!tasks.some(t=>t.id===taskId&&writable(t)))){forgetTaskDraft(taskId);persistDrafts();updatePendingBar();throw Error('보고 대상의 접근 권한 또는 배정이 바뀌었습니다. 업무 목록을 다시 확인하세요.')}
  rememberProposal(p);
  if(active==='assistant'&&assistantMode==='report'&&selected()===cid&&$('#report-task').value===taskId)showProposal(p);
  else notice('보고 초안이 준비되었습니다. 상단의 초안 계속하기를 눌러 확인하세요.');
 }catch(error){failureMessage=error.message;notice(error.message);}
 finally{reportBusy=false;drawReportItems(criterionId);syncProjectBar();if(failureMessage)$('#report-feedback').textContent=failureMessage+' · 입력 내용은 그대로 남아 있습니다.';}
}
$('#apply-state').onclick=e=>submitReport(e.currentTarget,true);
$('#report-form').onsubmit=e=>{e.preventDefault();submitReport(e.submitter)};
async function loadResearchStatus(){
  const cid=selected();$('#research-scope').textContent=projects.find(p=>p.id===cid)?.name||'프로젝트를 선택하세요';$('#research-form button').disabled=!cid;$('#research-refresh').disabled=!cid;if(!cid){$('#research-status').textContent='참여할 프로젝트가 필요합니다.';return;}
  try{const d=await api('/api/research/status?'+new URLSearchParams({collection_id:cid}));if(cid!==selected())return;
    $('#research-status').textContent=({ready:'검색 가능',preparing:'자료 준비 중',syncing:'자료 갱신 중',partial:'일부 자료 갱신 실패',disabled:'자료 검색 비활성화'}[d.state]||d.state)+` · 문서 ${d.documents}개`;$('#research-status').title=d.synced_at?'최근 확인 '+new Date(d.synced_at).toLocaleString('ko-KR'):'';
  }catch(err){if(cid===selected())$('#research-status').textContent=err.message}
}
$$('[data-research-example]').forEach(b=>{const question=b.dataset.researchExample;b.textContent=question.includes('주요 요구사항')?'요구사항 질문 넣기':question.includes('배포 전에')?'배포 점검 질문 넣기':'결정 사항 질문 넣기';b.title='질문 입력란에 예시를 넣습니다. 검색은 아래 버튼으로 실행하세요.';b.onclick=()=>{$('#research-text').value=b.dataset.researchExample;$('#research-text').focus()}});
function renderResearch(d){
  const el=$('#research-result');el.replaceChildren();
  const text=document.createElement('p');text.className='research-answer';
  text.textContent=d.report||d.display||String(d);el.append(text);
  if(d.retrieval){const scope=document.createElement('p');scope.className='muted';scope.textContent=`근거 문서 ${d.sources?.length||0}개 · 원문 확인 완료`+(d.failed?.length?' · 변경되거나 접근할 수 없는 자료 일부 제외':'');el.append(scope)}
  if(d.sources?.length){const h=document.createElement('h3');h.textContent='근거 문서';el.append(h)}
  if(!d.sources?.length){const help=document.createElement('p');help.className='context-note';help.textContent='근거 문서를 찾지 못했습니다. 프로젝트나 검색어를 바꿔보세요.';el.append(help)}
  for(const [i,s] of (d.sources||[]).entries()){
    const card=document.createElement('div');card.className='research-source';
    const title=document.createElement('strong');title.textContent=`[${s.number||i+1}] ${s.title}`;card.append(title);
    const quotes=s.excerpts?.map(quote=>({quote}))||d.findings?.find(f=>f.number===s.number)?.evidence||[];
    if(quotes.length){const quote=document.createElement('p');quote.textContent=quotes.map(e=>e.quote).join('\n');card.append(quote)}
    try{const url=new URL(s.url);if(url.origin===new URL(me.links.outline).origin&&['http:','https:'].includes(url.protocol)){
      const a=document.createElement('a');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';a.textContent='Outline 원문 열기 ↗';card.append(a)
    }}catch{}
    el.append(card);
  }
}
$('#research-refresh').onclick=e=>work(e.target,async()=>{
  $('#research-status').textContent='자료 갱신 중…';
  await api('/api/research/refresh',{collection_id:selected(),text:'자료 새로고침'});await loadResearchStatus();
});
$('#research-form').onsubmit=e=>{e.preventDefault();const cid=selected(),request=++researchRequest;work(e.submitter,async()=>{
  $('#research-result').textContent='자료 검색 중…';
  try{const d=await api('/api/research',{text:$('#research-text').value,collection_id:cid});if(cid===selected()&&request===researchRequest)renderResearch(d)}
  catch(err){if(cid===selected()&&request===researchRequest)$('#research-result').textContent=err.message;throw err}
  finally{await loadResearchStatus()}
})};
$('#filter-project').closest('label').hidden=true;
async function loadStats(options){return renderAnalytics(options)}
$('#filter').onclick=e=>work(e.target,loadStats);
$('#logout').onclick=e=>work(e.target,async()=>{await api('/auth/logout',{});reportTaskId='';reportDrafts.clear();pendingReports.clear();sessionStorage.removeItem(draftKey());location.reload()});
function taskDetailHref(task){return '/#task?'+new URLSearchParams({project:task.collectionId,id:task.id})}
async function openTaskLink(){
 const params=new URLSearchParams(location.hash.slice(6)),cid=params.get('project'),taskId=params.get('id');
 if(!cid||!taskId)throw Error('업무 링크가 올바르지 않습니다.');
 await loadProjects(cid);
 if(!projects.some(p=>p.id===cid))throw Error('이 프로젝트에 접근할 수 없습니다.');
 await load();
 if(!tasks.some(t=>t.id===taskId))throw Error('업무를 찾을 수 없거나 접근할 수 없습니다.');
 showBoardTask(taskId);
}
async function boot(){try{
  me=await api('/api/me');recoverDrafts();mine=!me.admin;$('#login').hidden=true;$('#account').textContent=(me.name||me.email)+(me.admin?' · 관리자':' · 실무자');$('#logout').hidden=false;$$('.admin-only').forEach(x=>x.hidden=!me.admin);
  if(me.project_management_outline)$('#new-project').textContent='Outline에서 프로젝트 관리 ↗';
  $('#links').innerHTML=`<a href="${esc(me.links.outline)}" target="_blank" rel="noopener">Outline ↗</a><a href="${esc(me.links.chat)}" target="_blank" rel="noopener">Rocket.Chat ↗</a>${me.admin?`<a href="${esc(me.links.webui)}" target="_blank" rel="noopener">문서 비서 ↗</a>`:''}`;
  if(location.hash.startsWith('#task?')){tab('tasks');try{await openTaskLink()}catch(error){selectedTask='';boardRenderKey='';draw();notice(error.message)}}
  else{await loadProjects();await load();tab(me.admin&&location.hash==='#accounts'?'accounts':'stats');if(location.hash.startsWith('#proposal-'))showProposal(await api('/api/proposals/'+location.hash.slice(10)));}
  setInterval(async()=>{
    if(refreshing||document.hidden)return;refreshing=true;
    try{await loadProjects();if(active==='stats')await loadStats({background:true,availableProjects:projects});else await load();if(active==='assistant'&&assistantMode==='research')await loadResearchStatus()}
    catch(error){if([401,403].includes(error.status)){clearAccessDisplays();notice(error.message)}}finally{refreshing=false}
  },20000);
}catch(e){$('#login').hidden=false;notice(e.message)}}boot();
