"use strict";
const $ = id => document.getElementById(id);
const statusNames = {UNKNOWN:"상태 확인 필요",NOT_STARTED:"예정 / 미착수",IN_PROGRESS:"진행중",DONE:"완료",DELAYED:"지연"};
let session = null, draft = null, busy = false, workspaceContext = null;
const displayTime = value => value.slice(0,16).replace("T"," ");
const comparable = items => JSON.stringify(items.map(i=>[i.task,i.status,i.progress,i.next_action,i.issue,i.project??null]));
function notify(text,error=false){$("notice").textContent=text;$("notice").className=error?"error":"";}
async function request(path,options={}){
  const response=await fetch("/api/review"+path,{...options,headers:{"Content-Type":"application/json","X-Review-Room":new URLSearchParams(location.search).get("room")==="legacy"?"legacy":"personal",...(session?{"X-Rocket-User":session.user_id,"X-Rocket-Token":session.token}:{}),...options.headers}});
  const data=await response.json();
  if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:"입력값을 확인하세요. 진행률은 0~100의 정수입니다.");
  return data;
}
function node(tag,text,cls){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;}
async function withBusy(fn){if(busy)return;busy=true;document.querySelectorAll("button").forEach(b=>b.disabled=true);try{await fn();}catch(e){notify(e.message,true);}finally{busy=false;document.querySelectorAll("button").forEach(b=>b.disabled=false);}}

$("login").addEventListener("submit",event=>{event.preventDefault();withBusy(async()=>{
  session=await request("/login",{method:"POST",body:JSON.stringify({username:$("username").value,password:$("password").value})});$("password").value="";
  sessionStorage.setItem("reportReviewSession",JSON.stringify(session));await openWorkspace();
});});
$("logout").onclick=()=>{session=null;draft=null;sessionStorage.removeItem("reportReviewSession");location.reload();};

async function openWorkspace(){
  workspaceContext=await request("/context");document.querySelectorAll("a[data-personal-chat]").forEach(a=>a.href=workspaceContext.chat_url);
  $("login-panel").hidden=true;$("workspace").hidden=false;$("logout").hidden=false;notify("");
  const list=await refreshList();const id=location.hash.slice(1);if(/^[a-f0-9]{64}$/.test(id))await loadDraft(id);else if(list.length)await loadDraft(list[0].id);
}

async function restoreLogin(){
  const params=new URLSearchParams(location.search);const access=params.get("access");
  try{
    if(access){session=await request("/link-login",{method:"POST",body:JSON.stringify({token:access})});sessionStorage.setItem("reportReviewSession",JSON.stringify(session));params.delete("access");history.replaceState(null,"",location.pathname+(params.size?"?"+params:"")+location.hash);}
    else{const saved=sessionStorage.getItem("reportReviewSession");if(saved)session=JSON.parse(saved);}
    if(session)await openWorkspace();
  }catch(error){session=null;sessionStorage.removeItem("reportReviewSession");notify(error.message,true);}
}
restoreLogin();

async function refreshList(){
  const list=await request("/drafts");list.sort((a,b)=>b.submitted_at.localeCompare(a.submitted_at));$("draft-list").replaceChildren();
  if(!list.length)$("draft-list").append(node("p","수정할 보고가 없습니다. 본인의 개인보고 방에서 '보고 업무내용'을 입력해 주세요."));
  for(const row of list){const btn=node("button",row.title);btn.dataset.draftId=row.id;btn.dataset.time=row.submitted_at;btn.append(node("small",`${row.state==="CONFIRMED"?"저장됨":"저장 전"} · ${displayTime(row.submitted_at)}`),node("span","현재 수정 중","selected-label"));btn.onclick=()=>withBusy(()=>loadDraft(row.id));$("draft-list").append(btn);}
  if(draft)markSelected(draft.id,false);
  return list;
}
$("reload").onclick=()=>withBusy(refreshList);
function markSelected(id,scroll=true){const selected=[...document.querySelectorAll("#draft-list button")].find(button=>button.dataset.draftId===id);document.querySelectorAll("#draft-list button").forEach(button=>{const active=button===selected;button.classList.toggle("selected",active);button.setAttribute("aria-current",active?"true":"false");});if(scroll&&selected)selected.scrollIntoView({behavior:"smooth",block:"nearest",inline:"center"});}
async function loadDraft(id){if(draft&&comparable(readItems())!==comparable(draft.items)&&!window.confirm("저장하지 않은 수정사항을 버리고 다른 보고를 선택할까요?"))return;draft=await request("/drafts/"+id);location.hash=id;render();markSelected(id);}

function field(label,key,value,type="text"){
  const wrap=node("label",label);const input=document.createElement(type==="select"?"select":"input");input.dataset.key=key;
  if(type==="select"){for(const [code,name] of Object.entries(statusNames)){const opt=node("option",name);opt.value=code;input.append(opt);}input.value=value??"UNKNOWN";}else{input.type=type;input.value=value??"";}
  if(key==="progress"){input.min="0";input.max="100";input.step="1";}if(key==="task"){input.required=true;input.minLength=2;input.maxLength=160;}if(key==="next_action")input.maxLength=240;if(key==="issue")input.maxLength=1000;
  input.oninput=input.onchange=preview;wrap.append(input);return wrap;
}
function addProject(card,value){const label=node("label","프로젝트");const select=node("select");select.dataset.key="project";select.append(new Option("프로젝트 선택",""));for(const [key,title] of Object.entries(workspaceContext.projects))select.append(new Option(title,key));select.value=value||"";select.onchange=preview;label.append(select);card.append(label);}
function itemCard(item,index){
  const card=node("section",undefined,"card item");const head=node("div",undefined,"item-head");head.append(node("h3",`업무 ${index+1}`));const del=node("button","삭제");del.type="button";del.className="quiet";del.onclick=()=>{if(document.querySelectorAll(".item").length<=1)return notify("업무는 한 개 이상 있어야 합니다.",true);card.remove();renumber();preview();};head.append(del);card.append(head);
  if(workspaceContext?.private_mode)addProject(card,item.project);
  const fields=node("div",undefined,"fields");fields.append(field("업무 내용","task",item.task),field("상태","status",item.status,"select"),field("진행률 (%)","progress",item.progress,"number"));card.append(fields);
  const optional=node("details");optional.open=Boolean(item.next_action||item.issue);optional.append(node("summary","다음 작업·이슈 추가 (선택)"));const extras=node("div",undefined,"extras");extras.append(field("다음 작업","next_action",item.next_action),field("이슈","issue",item.issue));optional.append(extras);card.append(optional);return card;
}
function renumber(){document.querySelectorAll(".item h3").forEach((h,n)=>h.textContent=`업무 ${n+1}`);}
function readItems(){if(!draft)return null;return [...document.querySelectorAll(".item")].map(card=>{const item={};card.querySelectorAll("[data-key]").forEach(el=>item[el.dataset.key]=el.dataset.key==="progress"?(el.value===""?null:Number(el.value)):(el.value.trim()||null));return item;});}
function isDirty(){return draft&&comparable(readItems())!==comparable(draft.items);}
function preview(){if(!draft)return;$("preview").textContent=formatCompanyReport(readItems(),draft.submitted_at);updateActionState();}
function updateActionState(){
  const sent=(draft.publications||[]).some(p=>p.state==="SENT"&&p.version===draft.version);
  $("confirm").textContent=draft.state==="CONFIRMED"?(isDirty()?"수정 내용 저장":"내용 저장됨"):"내용 저장";
  $("publication-confirm").hidden=draft.state!=="CONFIRMED"||sent;
  $("publication-confirm").textContent=(draft.publications||[]).some(p=>p.state==="SENT")?"수정본 업무보고방에 보내기":"업무보고방에 보내기";
  $("publication-status").textContent=isDirty()?"수정한 내용을 먼저 저장해 주세요.":sent?"이 내용은 업무보고방에 보냈습니다.":draft.state==="CONFIRMED"?"내용이 저장되었습니다. 위 미리보기가 맞으면 업무보고방에 보내세요.":"위 미리보기를 확인한 뒤 내용을 저장하세요.";
}
function render(){$("editor").hidden=false;$("items").replaceChildren(...draft.items.map(itemCard));preview();}
$("add").onclick=()=>{const count=document.querySelectorAll(".item").length;if(count>=8)return notify("업무는 최대 8개까지 가능합니다.",true);$("items").append(itemCard({task:"",status:"UNKNOWN",progress:null,project:null},count));preview();};
$("edit-form").onsubmit=event=>{event.preventDefault();persist();};
async function persist(){if(!draft||!$("edit-form").reportValidity())return;await withBusy(async()=>{draft=await request(`/drafts/${draft.id}/confirm`,{method:"POST",body:JSON.stringify({version:draft.version,items:readItems(),reason:$("reason").value})});render();await refreshList();notify("내용을 저장했습니다. 업무보고방에 보내려면 아래 보내기 버튼을 누르세요.");});}

$("publication-confirm").onclick=()=>withBusy(async()=>{
  if(isDirty())throw new Error("수정한 내용을 먼저 저장해 주세요.");
  const view=await request(`/drafts/${draft.id}/publication-preview`);
  const result=await request(`/drafts/${draft.id}/publish`,{method:"POST",body:JSON.stringify({version:view.version,preview_hash:view.preview_hash})});
  draft=await request("/drafts/"+draft.id);render();notify(result.already_sent?"이미 보낸 보고입니다. 중복으로 보내지 않았습니다.":"업무보고방에 보냈습니다.");
});
