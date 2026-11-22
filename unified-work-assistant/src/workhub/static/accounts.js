async function loadAccounts(){
  if(!me?.admin)return;
  const d=await api('/api/accounts');
  const accountNames=Object.fromEntries(d.accounts.map(a=>[a.email,a.name]));
  $('#accounts-state').textContent=(d.sync.at?'최근 계정 반영: '+new Date(d.sync.at).toLocaleString()+' · '+(d.sync.ok?'완료':'확인 필요 — 아래 서비스별 결과를 확인하세요'):'아직 계정 변경사항을 반영하지 않았습니다.')+(d.sync.message?' · '+d.sync.message:'')+(d.security_sync.at?'\n자동 이용 상태 확인: '+new Date(d.security_sync.at).toLocaleString()+' · '+(d.security_sync.ok?'완료':'확인 필요 — 아래 자동 처리 결과를 확인하세요'):'');
  renderHTML($('#account-list'),d.accounts.map(a=>`<tr><td><strong>${esc(a.name)}</strong><br><small>${esc(a.email)}</small></td><td>${a.review?esc(a.review):a.active?'사용 중':'이용 중지'}</td><td>${Object.entries(a.services||{}).map(([key,s])=>`<div class="${s.ok?'muted':'error'}">${esc({outline:'Outline',chat:'Rocket.Chat',groups:'자동 연결 그룹',sso:'통합 로그인'}[key]||key)}: ${esc(s.message)}</div>`).join('')}${Object.entries(a.security_services||{}).map(([key,s])=>`<div class="${s.ok?'muted':'error'}">자동 처리 / ${esc({outline:'Outline',chat:'Rocket.Chat',groups:'자동 연결 그룹',sso:'통합 로그인'}[key]||key)}: ${esc(s.message)}</div>`).join('')}</td></tr>`).join('')||'<tr><td colspan="3">등록된 업무 사용자가 없습니다.</td></tr>');
  renderHTML($('#account-handover'),d.handover.map(t=>`<div class="card"><strong>${esc(t.title)}</strong><p>${t.items.length?t.items.map(i=>`${esc(i.title)} · ${esc(accountNames[i.owner]||personName(i.owner))} · ${esc(i.state)}`).join('<br>'):esc(accountNames[t.owner]||personName(t.owner))+' · 미완료 업무'}</p><button class="secondary" data-handover="${esc(t.id)}" data-project="${esc(t.collectionId)}">업무 상세 보기 →</button></div>`).join('')||'<p class="muted">현재 볼 수 있는 프로젝트에는 인수인계할 미완료 업무가 없습니다.</p>');
  $$('[data-handover]').forEach(b=>b.onclick=()=>work(b,async()=>{await loadProjects(b.dataset.project);await load();const t=tasks.find(t=>t.id===b.dataset.handover);if(!t)throw Error('업무가 변경되었거나 접근할 수 없습니다. 계정 목록을 다시 확인하세요.');showBoardTask(t.id);}));
  renderHTML($('#account-mappings'),d.mappings.map(m=>`<li>${esc(m.name)} → <strong>${esc(m.outline_name)}</strong></li>`).join('')||'<li>연결한 그룹 없음</li>');
  $('#account-audit').textContent=d.audit.slice().reverse().map(a=>`${new Date(a.at).toLocaleString()} · ${{account_changed:'계정 변경',manual_sync:'계정 반영 요청',group_mapping_created:'그룹 연결',service_failed:'서비스 처리 실패',service_recovered:'서비스 처리 완료'}[a.action]||a.action} · ${a.email||a.actor||a.name||''}${a.service?' · '+a.service:''}${a.message?' · '+a.message:''}`).join('\n')||'아직 계정 처리 기록이 없습니다.';
}
let accountsRefreshing=false;
async function refreshAccounts(){
  if(accountsRefreshing||!me?.admin)return;
  accountsRefreshing=true;
  try{await work($('#accounts-sync'),async()=>{
    $('#accounts-state').textContent='직원 이름과 이용 상태를 연결된 서비스에 반영하고 있습니다…';
    let d;
    try{d=await api('/api/accounts/sync',{})}finally{await loadAccounts()}
    if(!d.ok)$('#accounts-state').textContent+='\n일부 항목을 처리하지 못했습니다. 아래 결과를 확인한 뒤 ‘계정 변경사항 반영’을 다시 눌러주세요. 이용 상태·권한 처리 실패는 자동으로도 재시도합니다.';
  })}finally{accountsRefreshing=false}
}
$('#accounts-sync').onclick=refreshAccounts;
let accountGroupsLoaded=false;
function setAccountGroupOpen(open){const button=$('#account-group-load');$('#account-group-form').hidden=!open;button.setAttribute('aria-expanded',String(open));button.textContent=open?'그룹 선택 접기':'＋ 자동 연결할 그룹 선택';}
$('#account-group-load').onclick=e=>{if(!$('#account-group-form').hidden){setAccountGroupOpen(false);return}return work(e.currentTarget,async()=>{if(!accountGroupsLoaded){const d=await api('/api/accounts/groups');$('#account-group-select').innerHTML=d.groups.map(g=>`<option value="${esc(g.id)}">${esc(g.name)}</option>`).join('');accountGroupsLoaded=true;}setAccountGroupOpen(true);$('#account-group-select').focus();});};
$('#account-group-form').onsubmit=e=>{e.preventDefault();work(e.submitter,async()=>{await api('/api/accounts/groups',{authentik_id:$('#account-group-select').value});await api('/api/accounts/sync',{});await loadAccounts();setAccountGroupOpen(false);$('#account-group-load').focus();});};
