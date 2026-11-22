let analyticsData,analyticsRequest=0,planningFocus='all',analyticsInitialized=false,planningPage=1,planningScroll;
const planningPageSize=5;
const planningVisibleRows=3;
const projectPalette=[['#285dd4','#eff4ff'],['#8b4eb0','#f8f0ff'],['#16846b','#edf9f4'],['#b76b14','#fff7e9'],['#b84e71','#fff0f5'],['#367f99','#eff9fc'],['#6965b8','#f3f2ff'],['#8b704f','#f8f4ef']];
let projectColors=new Map();
let calendarMode='week',calendarAnchor='',planningSchedule=null,calendarOverdue=null;
function projectStyle(id){const [ink,tint]=projectColors.get(id)||projectPalette[0];return `--project-color:${ink};--project-tint:${tint}`;}
function restorePlanningPosition(){if(planningScroll){window.scrollTo(planningScroll.x,planningScroll.y);planningScroll=null}}
function resetPlanningListScroll(){for(const selector of ['#planning-list','#planning-body'])$(selector).scrollTop=0}
function setPlanningOpen(open){const dialog=$('#planning-dialog');if(open&&!dialog.open){planningScroll={x:window.scrollX,y:window.scrollY};dialog.showModal();$('#planning-title').focus({preventScroll:true});window.scrollTo(planningScroll.x,planningScroll.y)}else if(!open&&dialog.open){dialog.close();restorePlanningPosition()}}
$('#planning-close').onclick=()=>setPlanningOpen(false);
// Dismiss only a click that both starts and ends on the backdrop, not a drag out of the list.
const planningDialog=$('#planning-dialog');
let planningBackdropPressed=false;
function outsidePlanningPanel(event){const r=planningDialog.getBoundingClientRect();return event.clientX<r.left||event.clientX>=r.right||event.clientY<r.top||event.clientY>=r.bottom}
planningDialog.addEventListener('pointerdown',event=>{planningBackdropPressed=event.isPrimary&&event.button===0&&event.target===planningDialog&&outsidePlanningPanel(event)});
planningDialog.addEventListener('pointercancel',()=>{planningBackdropPressed=false});
planningDialog.addEventListener('click',event=>{const dismiss=planningBackdropPressed&&event.button===0&&event.target===planningDialog&&outsidePlanningPanel(event);planningBackdropPressed=false;if(dismiss)setPlanningOpen(false)});
planningDialog.addEventListener('close',()=>{planningBackdropPressed=false});
$('#planning-dialog').addEventListener('close',()=>{const open=$('#planning-dialog').open;if(!open)restorePlanningPosition()});
$$('[data-jump]').forEach(b=>b.onclick=()=>$('#'+b.dataset.jump).scrollIntoView({behavior:'smooth',block:'start'}));
function clearPlanningContent(){$('#planning-owner-clear').hidden=true;calendarOverdue=null;planningSchedule=null;for(const id of ['deadline-calendar','deadline-distribution','calendar-exceptions','calendar-unplanned','calendar-alert']){const el=$('#'+id);el.replaceChildren();renderedHTML.delete(el)}setPlanningOpen(false);for(const selector of ['#planning-list','#planning-preview','#planning-filters','#planning-dialog-filters','#planning-pages']){const element=$(selector);element.replaceChildren();renderedHTML.delete(element)}$('#planning-search').value='';$('#planning-count').textContent='';$('#planning-preview-count').textContent='';$('#planning-scope').textContent='';}
function clearAnalyticsAccess(){analyticsData=null;analyticsRequest++;$('#stats-content').hidden=true;clearPlanningContent();$('#stats-project').replaceChildren();}
const pct=value=>value==null?'—':value+'%';
const flagNames={overdue:'마감 지남',due_soon:'마감 임박',no_due:'마감일 없음'};
const stateClass={'미착수':'planned','진행 중':'working','지연':'late','완료':'done','보류':'paused'};
function resetPlanning(){calendarOverdue=null;planningSchedule=null;planningFocus='all';planningPage=1;$('#planning-preview').scrollTop=0;setPlanningOpen(false);$('#planning-search').value='';$('#weekly-preview').hidden=true}
function statsChanged(){resetPlanning();renderAnalytics().catch(e=>notice(e.message))}
$('#stats-portfolio').onchange=()=>{$('#stats-project').value='';statsChanged()};
$('#stats-project').onchange=statsChanged;$('#filter-owner').onchange=statsChanged;
$$('[data-horizon]').forEach(b=>b.onclick=()=>{$('#stats-horizon').value=b.dataset.horizon;$$('[data-horizon]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));statsChanged()});
$('#stats-mine').onclick=()=>{$('#filter-owner').value=me.email.toLowerCase();statsChanged()};
$('#stats-reset').onclick=()=>{$('#filter-owner').value='';statsChanged()};
$('#stats-all-projects').onclick=()=>{$('#stats-project').value='';statsChanged()};
$('#stats-change-scope').onclick=()=>$('#stats-settings').scrollIntoView({behavior:'smooth',block:'start'});
$('#planning-search').oninput=()=>{planningPage=1;drawPlanning();resetPlanningListScroll()};
$('#stats-refresh').onclick=async e=>{const b=e.currentTarget;b.disabled=true;b.textContent='확인 중…';try{await api('/api/sync',{});await renderAnalytics()}catch(error){notice(error.message)}finally{b.disabled=false;b.textContent='새로고침'}};
new ResizeObserver(entries=>{const height=entries[0].target.getBoundingClientRect().height;if(height)document.documentElement.style.setProperty('--stats-dock-height',Math.ceil(height)+'px')}).observe($('#stats-dock'));
function inspectFocus(focus){
 setPlanningOpen(false);
 const behavior=window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth';
 if(focus==='projects'){$('#project-overview').scrollIntoView({behavior,block:'start'});return}
 if(focus!=='schedule')planningSchedule=null;
 planningFocus=focus;planningPage=1;$('#planning-search').value='';drawPlanning();
 $('#planning-preview').scrollTop=0;resetPlanningListScroll();
 $('#planning-filters [data-plan-filter="'+focus+'"]').focus({preventScroll:true});
 $('#planning-card').scrollIntoView({behavior,block:'start'});
}
async function selectPlanningOwner(owner){if(!me.admin&&owner!==me.email.toLowerCase())return;$('#filter-owner').value=owner;resetPlanning();await renderAnalytics();if($('#filter-owner').value===owner&&analyticsData?.owner===owner)inspectFocus('all')}
$('#planning-owner-clear').onclick=e=>work(e.currentTarget,()=>selectPlanningOwner(''));
function ownerStatusBar(done,late,pending){
 const parts=[['done',done],['late',late],['pending',pending]].filter(([,count])=>count>0);
 return `<span class="owner-status-bar" aria-hidden="true" ${parts.length?'':'hidden'}>${parts.map(([state,count])=>`<span class="owner-status-segment ${state}" style="flex:${count} 1 0%"></span>`).join('')}</span>`;
}
function bindDashboardActions(){
 $$('[data-focus]').forEach(b=>b.onclick=()=>work(b,async()=>{if(me.admin&&$('#filter-owner').value&&b.dataset.focus!=='projects'){$('#filter-owner').value='';resetPlanning();await renderAnalytics()}inspectFocus(b.dataset.focus)}));
 $$('[data-stats-project]').forEach(b=>b.onclick=()=>{$('#stats-project').value=$('#stats-project').value===b.dataset.statsProject?'':b.dataset.statsProject;statsChanged()});
 $$('[data-stats-owner]').forEach(b=>b.onclick=()=>work(b,()=>selectPlanningOwner($('#filter-owner').value===b.dataset.statsOwner?'':b.dataset.statsOwner)));
}
async function renderAnalytics({background=false,availableProjects=null}={}){
 if(background&&$('#stats-content').getAttribute('aria-busy')==='true')return;
 const request=++analyticsRequest,projectValue=$('#stats-project').value,ownerValue=me.admin?$('#filter-owner').value:me.email.toLowerCase();
 $('#stats-content').setAttribute('aria-busy','true');if(!analyticsInitialized)$('#stats-status').textContent='현황 불러오는 중…';
 try{
  const managed=me.admin&&$('#stats-portfolio').value==='managed';$('#stats-portfolio-label').hidden=!me.admin;
  const allProjects=availableProjects??(await api('/api/projects')).projects;if(request!==analyticsRequest)return;
  const registry=allProjects.filter(p=>!managed||p.manager===me.email.toLowerCase());
  projectColors=new Map([...allProjects].sort((a,b)=>a.id.localeCompare(b.id)).map((p,i)=>[p.id,projectPalette[i%projectPalette.length]]));
  renderHTML($('#stats-project'),`<option value="">${managed?'내가 관리하는 모든 프로젝트':'전체 프로젝트'}</option>`+options(registry));
  $('#stats-project').value=registry.some(p=>p.id===projectValue)?projectValue:'';
  const data=await api('/api/analytics?'+new URLSearchParams({collection_id:$('#stats-project').value,owner:ownerValue,managed:String(managed),horizon:$('#stats-horizon').value}));
  if(request!==analyticsRequest)return;analyticsData=data;analyticsInitialized=true;
  for(const person of data.owner_options||[])names[person.email]=person.name;
  const selectedOwner=data.owner,owners=new Set([me.email.toLowerCase(),...(data.owner_options||[]).map(p=>p.email),...(ownerValue?[ownerValue]:[])]);
  renderHTML($('#filter-owner'),(me.admin?'<option value="">전체 담당자</option>':'')+[...owners].sort((a,b)=>personName(a).localeCompare(personName(b),'ko')).map(email=>`<option value="${esc(email)}">${esc(personName(email))}</option>`).join(''));$('#filter-owner').value=selectedOwner;
  $('#filter-owner').closest('label').hidden=!me.admin;$('#stats-reset').closest('[role="group"]').hidden=!me.admin;
  $('#owners-overview').hidden=!me.admin;$('[data-jump="owners-overview"]').hidden=!me.admin;
  $('.dashboard-workspace').style.gridTemplateColumns=me.admin?'':'minmax(0,1fr)';
  const isMine=selectedOwner===me.email.toLowerCase(),projectName=registry.find(p=>p.id===$('#stats-project').value)?.name||(managed?'내가 관리하는 프로젝트':'전체 프로젝트');
  $('#stats-scope').textContent=`${projectName} · ${me.admin?'전체 집계 / 업무 목록: ':''}${selectedOwner?personName(selectedOwner):'팀 전체'}`;
  $('#stats-mine').setAttribute('aria-pressed',String(isMine));$('#stats-reset').setAttribute('aria-pressed',String(!selectedOwner));
  $('#stats-all-projects').hidden=!$('#stats-project').value;
  const s=me.admin?(data.portfolio?.summary||data.summary):data.summary,projectRows=me.admin?(data.portfolio?.projects||data.projects):data.projects,synced=data.sync?.at?new Date(data.sync.at).toLocaleTimeString('ko-KR',{timeZone:'Asia/Seoul',hour:'2-digit',minute:'2-digit',hour12:false}):'확인 전';
  const stale=!data.sync?.ok||!data.sync.at||(Date.now()-Date.parse(data.sync.at))/1000>120;
  $('#stats-status').textContent=stale?`업데이트가 지연되고 있습니다. 마지막 확인 ${synced} · 이전 수치를 표시합니다.`:`최근 업데이트 ${synced}`;
  $('#stats-status').classList.toggle('error',stale);
  const progressLabel=me.admin?($('#stats-project').value?'프로젝트 진행률':'전체 진행률'):(selectedOwner?'업무 진행률':'전체 진행률');
  const progressNote=me.admin?'선택 프로젝트 범위의 전체 업무 기준':selectedOwner?`${personName(selectedOwner)}의 참여 업무`:`${s.projects_measured}개 프로젝트 현황`;
  
  const cards=[
   [progressLabel,pct(s.project_progress),progressNote,'projects','blue'],
   ['전체 업무',s.total+'건','완료와 미완료 업무 모두 보기','total','gray'],
   ['완료 업무',s.completed+'건','완료된 업무 목록 보기','completed','teal'],
   ['미완료',s.open+'건','남은 업무 전체 보기','all','purple'],
   ['마감 초과',s.overdue+'건','일정 재확인이 필요해요','overdue','red'],
   ['마감 임박',s.due_soon+'건',`오늘부터 ${data.horizon}일 후까지`,'due_soon','amber']];
  renderHTML($('#metrics'),cards.map(([label,value,desc,focus,tone])=>`<button class="stat-tile ${tone}" data-focus="${focus}" aria-label="${esc(label)} ${esc(value)} · ${focus==='projects'?'프로젝트별 현황으로 이동':'해당 업무 목록으로 이동'}" ${focus!=='projects'?'aria-controls="planning-card"':''} title="${esc(desc)} · ${focus==='projects'?'프로젝트별 진행 상황 보기':'관련 업무 보기'}"><span>${esc(label)}</span><strong>${esc(value)}<span class="tile-action">${focus==='projects'?'현황 ↓':'목록 ›'}</span></strong><small>${esc(desc)}</small></button>`).join(''));
  $('#stats-empty').hidden=s.total>0;$('#stats-empty').textContent=!me.admin?'본인 참여 업무가 없습니다. 다른 프로젝트를 확인하세요.':selectedOwner?'이 담당자에게 배정된 업무가 없습니다. 팀 전체를 선택하거나 다른 프로젝트를 확인하세요.':'표시할 업무가 없습니다. 업무 보드에서 프로젝트를 연결하고 업무를 등록하세요.';
  $('#project-progress-column').textContent=me.admin?'담당자 선택과 무관한 프로젝트 전체 업무 기준':selectedOwner?`${personName(selectedOwner)} 참여 업무`:'';$('#project-progress-column').hidden=!me.admin&&!selectedOwner;
  renderHTML($('#project-comparison'),projectRows.map(p=>`<button class="project-summary project-line" style="${projectStyle(p.id)}" data-key="${esc(p.id)}" data-stats-project="${esc(p.id)}" aria-pressed="${$('#stats-project').value===p.id}"><span class="project-identity"><span class="project-mark" aria-hidden="true">${esc(p.name.slice(0,1))}</span><span><b>${esc(p.name)}</b><small>책임자 · ${esc(p.manager?personName(p.manager):'미지정')}</small></span></span><span class="project-line-progress"><b>${pct(p.average_progress)}</b><progress max="100" value="${p.average_progress??0}" aria-label="${esc(p.name)} 진행률"></progress></span><span class="project-line-count"><b>${p.completed} / ${p.total}</b><small>완료 업무</small></span><span class="project-line-count ${p.overdue?'risk-text':''}"><b>${p.overdue}건</b><small>마감 초과</small></span><span class="project-line-action">${$('#stats-project').value===p.id?'전체 보기 ↩':'상세 보기 →'}</span></button>`).join('')||'<div class="empty">표시할 프로젝트가 없습니다.</div>');
  $('#owners-caption').textContent=`${data.owners.length}명`;
  renderHTML($('#owner-comparison'),data.owners.map(o=>{
    const done=o.tasks_completed??0,late=o.tasks_overdue??0,pending=o.tasks_pending??0;
    return `<button class="owner-card" data-key="${esc(o.email)}" data-stats-owner="${esc(o.email)}" aria-controls="planning-card" title="담당 업무 목록 보기" aria-pressed="${selectedOwner===o.email}"><span class="owner-avatar" aria-hidden="true">${esc(personName(o.email).slice(0,1))}</span><span class="owner-work"><b>${esc(personName(o.email))}<small>전체 ${o.tasks}건</small></b>${ownerStatusBar(done,late,pending)}<span class="owner-status-counts"><span class="done">완료 <b>${done}</b></span><span class="late">마감 초과 <b>${late}</b></span><span class="pending" title="마감 초과를 제외한 미완료 업무">미완료(초과 제외) <b>${pending}</b></span></span></span><span class="owner-drilldown">${selectedOwner===o.email?'선택 해제 ×':'→'}</span></button>`;
  }).join('')||'<div class="empty">표시할 담당자가 없습니다.</div>');
  drawCalendar();
  renderHTML($('#state-bars'),Object.entries(s.states).map(([name,count])=>`<span class="state-key ${stateClass[name]}"><i></i>${esc(name)} <b>${count}</b></span>`).join(''));
  renderHTML($('#stats-quality'),`<p>문서 확인 필요 ${s.invalid}건 · 체크리스트 없는 업무 ${s.no_criteria}건 · 진행률 없는 업무 ${s.missing_progress}건</p>`+data.invalid_tasks.map(t=>`<p><a href="${esc(t.url)}" target="_blank" rel="noopener">${esc(t.title)}</a> · ${esc(t.error)}</p>`).join(''));
  bindDashboardActions();drawPlanning();
 }catch(error){if(request===analyticsRequest){if([401,403,404].includes(error.status)){analyticsData=null;$('#stats-content').hidden=true;clearPlanningContent();$('#weekly-preview').hidden=true;await loadProjects();renderHTML($('#stats-project'),'<option value="">전체 프로젝트</option>'+options(projects))}$('#stats-status').textContent=(background&&analyticsData?'자동 업데이트 실패 · 이전 수치를 표시합니다. ':'통계를 불러오지 못했습니다. ')+error.message;$('#stats-status').classList.add('error');$('#stats-content').hidden=!(background&&analyticsData)}throw error}
 finally{if(request===analyticsRequest){$('#stats-content').setAttribute('aria-busy','false');if(analyticsData&&$('#stats-status').textContent.indexOf('통계를 불러오지 못했습니다.')!==0)$('#stats-content').hidden=false}}
}

function drawPlanning(){
  if(!analyticsData)return;$('#planning-owner-clear').hidden=!me.admin||!analyticsData.owner;$('#planning-owner-clear').textContent=analyticsData.owner?personName(analyticsData.owner)+' 선택 해제 ×':'담당자 선택 해제 ×';const completed=planningFocus==='completed',pending=!me.admin&&['schedule','unplanned'].includes(planningFocus)?calendarActions():analyticsData.actions,all=planningFocus==='total'?[...pending,...(analyticsData.completed_tasks||[])]:completed?(analyticsData.completed_tasks||[]):pending,q=$('#planning-search').value.trim().toLowerCase();
  const expanded=new Set($$('#planning-list details[open]').map(d=>d.closest('.plan-row').dataset.key));
  const filters=[['total','전체 업무'],['completed','완료'],['all','미완료'],['overdue','마감 초과'],['due_soon','마감 임박'],['no_due','기한 미정']];
  if(planningSchedule)filters.push(['schedule',planningSchedule.label]);
  const extra={unplanned:'일정 미설정',today:'오늘 마감',upcoming:'내일부터 '+analyticsData.horizon+'일 안에',later:'그 이후 마감'};if(extra[planningFocus])filters.push([planningFocus,extra[planningFocus]]);
  const matches=(t,key)=>key==='unplanned'?!hasTaskPeriod(t):key==='schedule'?matchesSchedule(t):key==='total'||key==='all'||key==='completed'&&t.status==='완료'||(key==='today'?t.days_remaining===0:key==='upcoming'?t.days_remaining>0&&t.days_remaining<=analyticsData.horizon:key==='later'?t.days_remaining>analyticsData.horizon:t.flags.includes(key));
  const filterHTML=filters.map(([key,label])=>`<button class="${planningFocus===key?'selected':''}" data-plan-filter="${key}" aria-pressed="${planningFocus===key}">${label} <b>${key==='total'?pending.length+(analyticsData.completed_tasks||[]).length:key==='completed'?(analyticsData.completed_tasks||[]).length:key==='all'?pending.length:pending.filter(t=>matches(t,key)).length}</b></button>`).join('');
  renderHTML($('#planning-filters'),filterHTML);renderHTML($('#planning-dialog-filters'),filterHTML);
  $$('[data-plan-filter]').forEach(b=>b.onclick=()=>{planningFocus=b.dataset.planFilter;if(planningFocus!=='schedule')planningSchedule=null;planningPage=1;$('#planning-preview').scrollTop=0;drawPlanning();resetPlanningListScroll()});
  const filtered=all.filter(t=>matches(t,planningFocus));
  const focusLabel=filters.find(([key])=>key===planningFocus)?.[1]||'미완료';
  const dateLabel=t=>t.status==='완료'?'완료':t.days_remaining===null?'마감일 없음':t.days_remaining<0?`${Math.abs(t.days_remaining)}일 지남`:t.days_remaining===0?'오늘 마감':`D-${t.days_remaining}`;
  renderHTML($('#planning-preview'),filtered.map(t=>`<a target="_blank" rel="noopener" href="${esc(taskDetailHref(t))}" title="업무 상세 새 탭에서 열기" class="plan-preview-row" style="${projectStyle(t.collectionId)}" data-key="${esc(t.id)}" data-plan-open="${esc(t.id)}"><span class="plan-preview-main"><strong class="preview-title" title="${esc(t.title)}"><span>${esc(t.title)}</span><span class="new-tab-mark" aria-hidden="true">↗</span><span class="sr-only">새 탭에서 열기</span></strong><span class="plan-preview-meta"><span class="preview-project" title="${esc(t.collectionName)}">${esc(t.collectionName)}</span><span>${esc(personName(t.owner))}</span></span></span><span class="plan-preview-progress" aria-label="진행률 ${esc(t.progress)}"><b>${esc(t.progress)}</b></span><span title="${esc(t.due?'마감일 '+t.due:'마감일 미정')}" class="plan-preview-due ${t.flags.includes('overdue')?'overdue':t.flags.includes('due_soon')?'due_soon':''}"><b>${esc(dateLabel(t))}</b></span><span class="preview-arrow" aria-hidden="true">상세 <b>↗</b></span></a>`).join('')||'<div class="planning-preview-empty"><strong>조건에 맞는 업무 없음</strong></div>');
  $('#planning-preview-count').textContent=`${filtered.length}개${filtered.length>planningVisibleRows?' · 스크롤로 더 보기':''}`;
  $('#planning-scope').textContent=$('#stats-scope').textContent;$('#planning-card h2').textContent=completed?'완료한 업무':'점검할 업무';$('#planning-title').textContent=completed?'완료한 업무 목록':'점검할 업무 목록';
  const rows=filtered.filter(t=>!q||(t.title+' '+t.collectionName+' '+personName(t.owner)).toLowerCase().includes(q));
  const pageCount=Math.max(1,Math.ceil(rows.length/planningPageSize));planningPage=Math.min(planningPage,pageCount);
  const start=(planningPage-1)*planningPageSize,visible=rows.slice(start,start+planningPageSize);
  $('#planning-count').textContent=rows.length?`${start+1}–${start+visible.length} / 전체 ${rows.length}개`:'검색 결과 없음';
  renderHTML($('#planning-pages'),`<button class="secondary" id="plan-prev" ${planningPage===1?'disabled':''}>← 이전</button><span>${planningPage} / ${pageCount}쪽</span><button class="secondary" id="plan-next" ${planningPage===pageCount?'disabled':''}>다음 →</button>`);
  $('#planning-pages').hidden=pageCount<=1;
  $('#plan-prev').onclick=()=>{planningPage--;drawPlanning();resetPlanningListScroll()};
  $('#plan-next').onclick=()=>{planningPage++;drawPlanning();resetPlanningListScroll()};
  renderHTML($('#planning-list'),visible.map(t=>{
    const completed=t.status==='완료';
    const canReport=me.admin||(t.criteria.length?t.criteria.some(i=>i.owner===me.email.toLowerCase()):t.owner===me.email.toLowerCase());
    const dateLabel=completed?'완료':t.days_remaining===null?'마감일 미정':t.days_remaining<0?`${Math.abs(t.days_remaining)}일 초과`:t.days_remaining===0?'오늘 마감':`D-${t.days_remaining}`;
    const ownItems=t.criteria.filter(i=>!analyticsData.owner||i.owner===analyticsData.owner);
    return `<article class="plan-row" style="${projectStyle(t.collectionId)}" data-key="${esc(t.id)}"><div><div class="plan-meta"><span class="project-badge">${esc(t.collectionName)}</span>${t.flags.filter(f=>f!=='blocked').map(f=>`<span class="plan-flag ${f}">${flagNames[f]}</span>`).join('')}</div><h3><a class="table-link" target="_blank" rel="noopener" href="${esc(taskDetailHref(t))}" data-plan-open="${esc(t.id)}">${esc(t.title)} ↗</a></h3><p>${esc(personName(t.owner))} · ${esc(t.status)} · ${esc(t.progress)}${ownItems.length?` · 체크리스트 ${ownItems.length}개 중 ${t.remaining}개 남음`:''}</p>${completed?'':`<p class="next-step"><b>${t.next_is_suggestion?'점검 제안':'다음 행동'}</b> ${esc(t.next)}</p>`}${ownItems.length?`<details><summary>체크리스트 항목 ${ownItems.length}개 보기</summary><ul>${ownItems.map(i=>`<li>${i.state==='완료'?'☑':'☐'} ${esc(i.title)} · ${esc(i.state)} · ${esc(personName(i.owner))}</li>`).join('')}</ul></details>`:''}</div><div class="plan-action"><strong>${esc(dateLabel)}</strong><small>${esc(t.due?'마감 '+t.due:completed?'':'일정 확인 필요')}</small><a class="button secondary" target="_blank" rel="noopener" href="${esc(taskDetailHref(t))}" data-plan-open="${esc(t.id)}">업무 상세 ↗</a>${!completed&&canReport?`<button class="secondary" data-plan-report="${esc(t.id)}">진행 보고</button>`:completed?'':'<span class="muted">담당자 보고 대기</span>'}</div></article>`;
  }).join('')||'<div class="empty">이 조건에 맞는 업무가 없습니다.</div>');
  $$('#planning-list details').forEach(d=>{d.open=expanded.has(d.closest('.plan-row').dataset.key)});
  async function reportPlanning(b){const t=analyticsData?.actions.find(t=>t.id===b.dataset.planReport);if(!t)throw Error('업무가 변경되었습니다. 통계를 새로고침하세요.');saveReportDraft();await loadProjects(t.collectionId);await load();if(!tasks.some(v=>v.id===t.id))throw Error('업무가 변경되었습니다. 통계를 새로고침하세요.');setPlanningOpen(false);startReport(t.id)}
  $$('[data-plan-report]').forEach(b=>b.onclick=()=>work(b,()=>reportPlanning(b)));

}

// Calendar dates are date-only UTC values; browser time zones cannot shift a deadline.
function calendarDate(key){return new Date(key+'T00:00:00Z')}
function calendarKey(date){return date.toISOString().slice(0,10)}
function calendarAdd(key,days){const d=calendarDate(key);d.setUTCDate(d.getUTCDate()+days);return calendarKey(d)}
function calendarMonday(key){const d=calendarDate(key);return calendarAdd(key,-((d.getUTCDay()+6)%7))}
function calendarShort(key){return Number(key.slice(5,7))+'/'+Number(key.slice(8,10))}
function calendarBounds(anchor,mode){
 const start=mode!=='month'?calendarMonday(anchor):anchor.slice(0,7)+'-01';
 const end=mode!=='month'?calendarAdd(start,6):calendarKey(new Date(Date.UTC(Number(start.slice(0,4)),Number(start.slice(5,7)),0)));
 return {start,end};
}
function calendarBins(start,end,mode){
 const bins=[];
 for(let from=start;from<=end;){const to=mode==='week'?from:[calendarAdd(calendarMonday(from),6),end].sort()[0];bins.push({from,to});from=calendarAdd(to,1)}
 return bins;
}
function hasTaskPeriod(t){return /^\d{4}-\d{2}-\d{2}$/.test(t.start||'')&&/^\d{4}-\d{2}-\d{2}$/.test(t.due||'')&&t.start<=t.due}
function taskOverlaps(t,from,to){return hasTaskPeriod(t)&&t.start<=to&&t.due>=from}
function matchesSchedule(task){const s=planningSchedule;return !!s&&taskOverlaps(task,s.from,s.to)&&(s.owner===null||(task.owner||'').toLowerCase()===s.owner)}
function inspectSchedule(from,to,owner=null){
 const label=(from===to?calendarShort(from):calendarShort(from)+'–'+calendarShort(to))+' 일정'+(owner!==null?' · '+(owner?personName(owner):'미지정'):'');
 planningSchedule={from,to,owner,label};inspectFocus('schedule');
}
function compareCalendarTasks(a,b){return (a.collectionName||'').localeCompare(b.collectionName||'','ko')||(a.start||a.due||'9999').localeCompare(b.start||b.due||'9999')||personName(a.owner).localeCompare(personName(b.owner),'ko')||a.title.localeCompare(b.title,'ko')||a.id.localeCompare(b.id)}
function calendarActions(){const rows=me.admin?(analyticsData?.actions||[]):(analyticsData?.calendar_actions||analyticsData?.actions||[]),email=me.email.toLowerCase();return me.admin?rows:rows.filter(t=>(t.owner||'').toLowerCase()===email||(t.criteria||[]).some(i=>(i.owner||'').toLowerCase()===email))}
function overdueCalendarTasks(){return calendarActions().filter(t=>t.due&&t.due<analyticsData.as_of).sort(compareCalendarTasks)}
function clearCalendarOverdue(){if(calendarOverdue){calendarMode=calendarOverdue.mode;calendarAnchor=calendarOverdue.anchor;calendarOverdue=null}drawCalendar()}
function focusCalendarOverdue(direction=0){
 const rows=overdueCalendarTasks();if(!rows.length)return;
 const navigationFocus=document.activeElement?.id;
 const old=calendarOverdue,at=old?Math.max(0,rows.findIndex(t=>t.id===old.id)):0,index=Math.max(0,Math.min(rows.length-1,at+direction));
 calendarOverdue={id:rows[index].id,mode:old?.mode||calendarMode,anchor:old?old.anchor:calendarAnchor};
 calendarAnchor=rows[index].due;drawCalendar();
 const target=$$('#deadline-calendar .calendar-task').find(r=>r.dataset.calendarTask===rows[index].id&&r.closest('.calendar-day').dataset.key===rows[index].due);
 if(target){
  const toolbar=$('#calendar-alert'),list=$('#deadline-calendar').closest('.calendar-scroll'),dock=$('#stats-dock');
  const top=Math.max(0,dock.getBoundingClientRect().bottom)+8,area=toolbar.getBoundingClientRect();
  if(area.top<top||area.bottom+list.clientHeight>innerHeight-16)window.scrollBy({top:area.top-top,behavior:'instant'});
  const listBox=list.getBoundingClientRect(),box=target.getBoundingClientRect(),header=list.querySelector('.calendar-weekdays').getBoundingClientRect().height;
  if(box.top<listBox.top+header||box.bottom>listBox.bottom)list.scrollTo({top:list.scrollTop+box.top-listBox.top-header,behavior:'instant'});
  const nav=['overdue-prev','overdue-next'].includes(navigationFocus)?$('#'+navigationFocus):null;
  if(nav)(nav.disabled?$('#'+(navigationFocus==='overdue-next'?'overdue-prev':'overdue-next')):nav).focus({preventScroll:true});else target.focus({preventScroll:true});
 }

}
$('#calendar-prev').onclick=()=>moveCalendar(-1);
$('#calendar-next').onclick=()=>moveCalendar(1);
$('#calendar-today').onclick=()=>{calendarOverdue=null;calendarAnchor=analyticsData?.as_of||'';drawCalendar()};
$$('[data-calendar-mode]').forEach(b=>b.onclick=()=>{calendarOverdue=null;calendarMode=b.dataset.calendarMode;drawCalendar()});
function moveCalendar(direction){
 if(!analyticsData)return;calendarOverdue=null;
 const key=calendarAnchor||analyticsData.as_of;
 calendarAnchor=calendarMode!=='month'?calendarAdd(key,7*direction):calendarKey(new Date(Date.UTC(Number(key.slice(0,4)),Number(key.slice(5,7))-1+direction,1)));
 drawCalendar();
}
function drawCalendar(){
 if(!analyticsData)return;
 const today=analyticsData.as_of,anchor=calendarAnchor||today,{start,end}=calendarBounds(anchor,calendarMode);
 const actions=calendarActions(),inRange=actions.filter(t=>taskOverlaps(t,start,end));
 const overdueRows=overdueCalendarTasks();if(calendarOverdue&&!overdueRows.some(t=>t.id===calendarOverdue.id))calendarOverdue=null;
 $('#deadlines-overview').classList.toggle('overdue-browsing',!!calendarOverdue);
 const overdueIndex=calendarOverdue?overdueRows.findIndex(t=>t.id===calendarOverdue.id):-1;
 renderHTML($('#calendar-alert'),calendarOverdue?`<div class="calendar-alert-toolbar"><strong>마감 초과 업무</strong><span>강조된 업무를 확인하세요</span><button class="secondary" id="overdue-prev" ${overdueIndex===0?'disabled':''}>이전 업무</button><button class="secondary" id="overdue-next" ${overdueIndex===overdueRows.length-1?'disabled':''}>다음 업무</button><button class="secondary" id="overdue-clear">강조 해제 ×</button></div>`:'');
 if(calendarOverdue){$('#overdue-prev').onclick=()=>focusCalendarOverdue(-1);$('#overdue-next').onclick=()=>focusCalendarOverdue(1);$('#overdue-clear').onclick=clearCalendarOverdue}
 const unplanned=actions.filter(t=>!hasTaskPeriod(t)).sort((a,b)=>(a.due||'9999').localeCompare(b.due||'9999')||a.title.localeCompare(b.title,'ko'));
 renderHTML($('#calendar-unplanned'),unplanned.length?`<section class="unplanned-section" aria-label="기간을 정할 업무"><div class="distribution-heading"><h3>기간을 정할 업무 <span>${unplanned.length}</span></h3><p>시작일 또는 마감일 미설정 · 날짜 범위와 관계없이 표시</p></div><div class="unplanned-list">${unplanned.map(t=>`<a class="unplanned-task" style="${projectStyle(t.collectionId)}" href="${esc(taskDetailHref(t))}" target="_blank" rel="noopener"><div><small>${esc(t.collectionName)} · ${esc(personName(t.owner)||'미지정')}</small><strong>${esc(t.title)} ↗</strong></div><span>${t.due?'마감 '+esc(t.due):'마감일 미정'}<small>${t.start?'시작 '+esc(t.start):'시작일 미정'}</small></span></a>`).join('')}</div><p class="calendar-note">업무를 열어 일정을 설정하면 ${me.admin?'캘린더와 담당자별 일정 겹침에':'내 업무 일정에'} 반영됩니다.</p></section>`:'');
 const byDay=new Map();for(let day=start;day<=end;day=calendarAdd(day,1))byDay.set(day,inRange.filter(t=>taskOverlaps(t,day,day)));
 for(const rows of byDay.values())rows.sort((a,b)=>a.collectionName.localeCompare(b.collectionName,'ko')||a.title.localeCompare(b.title,'ko'));
 $('#deadline-caption').textContent=me.admin?`${$('#stats-scope').textContent} · 계획된 작업 기간`:`${$('#stats-project').value?$('#stats-project').selectedOptions[0].textContent:'전체 프로젝트'} · 내 업무`;
 $('#calendar-range').textContent=calendarMode==='month'?`${start.slice(0,4)}년 ${Number(start.slice(5,7))}월`:`${start.slice(0,4)}. ${calendarShort(start)} — ${end.slice(0,4)!==start.slice(0,4)?end.slice(0,4)+'. ':''}${calendarShort(end)}`;
 $$('[data-calendar-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.calendarMode===calendarMode)));
 const overdue=actions.filter(t=>t.due&&t.due<today).length,undated=actions.filter(t=>!t.due).length;
 renderHTML($('#calendar-exceptions'),`<button class="calendar-exception late" data-calendar-focus="overdue" aria-pressed="${!!calendarOverdue}" ${overdue?'':'disabled'}>마감 초과 <b>${overdue}</b></button><button class="calendar-exception" data-calendar-focus="unplanned">일정 미설정 <b>${actions.filter(t=>!hasTaskPeriod(t)).length}</b></button>`);
 $$('[data-calendar-focus]').forEach(b=>b.onclick=()=>{if(b.dataset.calendarFocus==='overdue'){if(calendarOverdue)clearCalendarOverdue();else focusCalendarOverdue()}else inspectFocus(b.dataset.calendarFocus)});
 const gridStart=calendarMode!=='month'?start:calendarMonday(start),gridEnd=calendarMode!=='month'?end:calendarAdd(calendarMonday(end),6),days=[];
 for(let key=gridStart;key<=gridEnd;key=calendarAdd(key,1))days.push(key);
 const weekday=['월','화','수','목','금','토','일'];
 renderHTML($('#deadline-calendar'),`<div class="calendar-weekdays">${weekday.map(d=>`<span>${d}</span>`).join('')}</div><div class="calendar-grid ${calendarMode}">${days.map(key=>{
 const outside=key<start||key>end,rows=[...(byDay.get(key)||[])],limit=calendarMode==='week'?3:2;
 const overdueTarget=calendarOverdue&&overdueRows.find(t=>t.id===calendarOverdue.id&&t.due===key);
 if(overdueTarget){const at=rows.findIndex(t=>t.id===overdueTarget.id);if(at>=0)rows.splice(at,1);rows.unshift(overdueTarget)}
 return `<div class="calendar-day ${outside?'outside':''} ${key===today?'today':''}" data-key="${key}">${outside?`<span class="calendar-day-muted">${Number(key.slice(8))}</span>`:`<button class="calendar-day-number" data-calendar-date="${key}" aria-label="${key} 배정 업무 ${rows.length}건" ${key===today?'aria-current="date"':''}><span>${calendarMode==='week'?calendarShort(key):Number(key.slice(8))}</span><small>${rows.length?rows.length+'건':''}</small></button>${rows.slice(0,limit).map(t=>`<a data-calendar-task="${esc(t.id)}" class="calendar-task ${calendarOverdue?.id===t.id?'overdue-target':''}" style="${projectStyle(t.collectionId)}" href="${esc(taskDetailHref(t))}" target="_blank" rel="noopener" title="${esc(t.collectionName+' · '+t.title+' · '+personName(t.owner))}" aria-label="${esc(t.title+' · '+t.collectionName+' · '+personName(t.owner))} · 새 탭에서 열기"><span>${esc(t.title)} <i aria-hidden="true">↗</i></span><small>${esc(personName(t.owner)||'미지정')}</small></a>`).join('')}${rows.length>limit?`<button class="calendar-more" data-calendar-date="${key}">+${rows.length-limit}건 보기</button>`:''}`}</div>`;
 }).join('')}</div>`);
 $$('[data-calendar-date]').forEach(b=>b.onclick=()=>inspectSchedule(b.dataset.calendarDate,b.dataset.calendarDate));
 $('#calendar-owner-distribution').hidden=!me.admin;
 if(!me.admin){renderHTML($('#deadline-distribution'),'');return}
 const bins=calendarBins(start,end,calendarMode),ownerMap=new Map();
 for(const t of inRange){const email=(t.owner||'').toLowerCase();if(!ownerMap.has(email))ownerMap.set(email,[]);ownerMap.get(email).push(t)}
 const people=[...ownerMap].sort((a,b)=>b[1].length-a[1].length||(a[0]||'').localeCompare(b[0]));
 renderHTML($('#deadline-distribution'),people.length?`<table class="distribution-table"><caption class="sr-only">${esc($('#calendar-range').textContent)} 담당자별 동시 배정 업무 수</caption><thead><tr><th scope="col">담당자</th>${bins.map(b=>`<th scope="col">${b.from===b.to?calendarShort(b.from):calendarShort(b.from)+'–'+calendarShort(b.to)}</th>`).join('')}<th scope="col">기간 업무</th></tr></thead><tbody>${people.map(([email,rows])=>`<tr data-key="${esc(email||'unassigned')}"><th scope="row">${esc(email?personName(email):'미지정')}</th>${bins.map(b=>{const n=peakConcurrent(rows,b.from,b.to);return `<td>${n?`<button class="heat-cell level-${n>=4?3:n>=2?2:1}" data-deadline-owner="${esc(email)}" data-from="${b.from}" data-to="${b.to}" aria-label="${esc(email?personName(email):'미지정')} ${calendarShort(b.from)}${b.from===b.to?'':'부터 '+calendarShort(b.to)+'까지'} 동시 배정 최대 ${n}건">${n}</button>`:'<span class="heat-zero">—</span>'}</td>`}).join('')}<td><button class="heat-total" data-deadline-owner="${esc(email)}" data-from="${start}" data-to="${end}" aria-label="${esc(email?personName(email):'미지정')} 기간 내 업무 ${rows.length}건">${rows.length}</button></td></tr>`).join('')}</tbody></table>`:'<div class="calendar-empty">이 기간에 시작일과 마감일이 설정된 미완료 업무가 없습니다.</div>');
 $$('[data-deadline-owner]').forEach(b=>b.onclick=()=>inspectSchedule(b.dataset.from,b.dataset.to,b.dataset.deadlineOwner));
}

function peakConcurrent(rows,from,to){let peak=0;for(let day=from;day<=to;day=calendarAdd(day,1))peak=Math.max(peak,rows.filter(t=>taskOverlaps(t,day,day)).length);return peak}
