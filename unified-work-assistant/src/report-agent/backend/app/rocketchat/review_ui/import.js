"use strict";
// Uses the review page's in-memory session; never stores credentials or raw previews locally.
let importRange = null, importRows = new Map(), importNext = null;
if(new URLSearchParams(location.search).get("mode")==="import")$("import-panel").open=true;
const importToday = new Date(Date.now()+9*60*60*1000).toISOString().slice(0,10);
$("import-start").value=importToday;$("import-end").value=importToday;
$("import-start").max=importToday;$("import-end").max=importToday;
function resetImport(){importRange=null;importRows.clear();importNext=null;$("import-messages").replaceChildren();$("import-more").hidden=true;$("import-info").textContent="기간을 선택하고 미리보기를 눌러 주세요.";}
["import-start","import-end"].forEach(id=>$(id).onchange=resetImport);
function importLink(draftId){const link=node("a","내용 확인·수정하기 →");link.href="/#"+draftId;link.onclick=event=>{event.preventDefault();withBusy(async()=>{await loadDraft(draftId);$("editor").scrollIntoView({behavior:"smooth",block:"start"});});};return link;}
function appendImport(row){
  if(importRows.has(row.message_id))return;
  importRows.set(row.message_id,row);
  const card=node("article",undefined,"import-message");const label=node("label");const check=document.createElement("input");check.type="checkbox";check.dataset.messageId=row.message_id;check.disabled=Boolean(row.existing);
  check.onchange=()=>{if(document.querySelectorAll("#import-messages input:checked").length>5){check.checked=false;notify("한 번에 최대 5건만 선택하세요.",true);}};
  label.append(check,node("span",`${row.author} · ${displayTime(row.submitted_at)} KST`));card.append(label,node("pre",row.text));
  const source=node("a","원문 보기 ↗");source.href=row.source_url;source.target="_blank";source.rel="noopener noreferrer";card.append(source);
  if(row.existing){card.append(node("p",row.existing==="CONFIRMED"?"이미 확정한 보고 · 다시 가져오지 않음":"이미 초안이 있음 · 다시 가져오지 않음"),importLink(row.review_url.split("#")[1]));}
  $("import-messages").append(card);
}
async function previewImport(more=false){
  if(!more){const room=await request("/imports/room");resetImport();importRange={room_id:room.id,start:$("import-start").value,end:$("import-end").value,offset:0};}
  if(!importRange)return;
  $("import-fields").disabled=true;
  try{
    $("import-info").textContent="선택 기간의 내 메시지를 조회하고 있어요. 저장·AI 처리는 하지 않습니다.";
    const result=await request("/imports/preview",{method:"POST",body:JSON.stringify({...importRange,offset:more?importNext:0})});
    importRange.as_of=result.as_of;importNext=result.next_offset;result.items.forEach(appendImport);
    $("import-more").hidden=importNext===null;
    $("import-info").textContent=`내 텍스트 메시지 ${importRows.size}건 표시 · 저장된 초안은 선택할 수 없습니다.${result.scan_limit_reached?" 조회 한도에 도달했어요. 기간을 좁혀 주세요.":importNext!==null?" 더 이전 메시지는 아래 '더 보기'로 확인하세요.":" 이 기간의 조회가 끝났습니다."}`;
  }finally{$("import-fields").disabled=false;}
}
$("import-form").onsubmit=event=>{event.preventDefault();withBusy(()=>previewImport());};
$("import-more").onclick=()=>withBusy(()=>previewImport(true));
$("import-create").onclick=()=>withBusy(async()=>{
  const checks=[...document.querySelectorAll("#import-messages input:checked")];
  if(!importRange||!checks.length)return notify("미리보기에서 보고로 사용할 메시지를 먼저 선택하세요.",true);
  if(checks.length>5)return notify("최대 5건만 선택하세요.",true);
  const scope={...importRange,offset:0};$("import-results").replaceChildren();$("import-fields").disabled=true;
  let succeeded=0, failed=0;
  document.querySelectorAll("#import-messages input").forEach(el=>el.disabled=true);
  try{
    for(let i=0;i<checks.length;i++){
      const row=importRows.get(checks[i].dataset.messageId);const line=node("p",`${i+1}/${checks.length} · ${displayTime(row.submitted_at)} 보고를 Gemma로 정리 중…`);$("import-results").append(line);
      try{
        const result=await request("/imports/draft",{method:"POST",body:JSON.stringify({...scope,message_id:row.message_id,fingerprint:row.fingerprint})});
        row.existing=result.draft.state;checks[i].checked=false;
        succeeded++;
        line.textContent=`${i+1}/${checks.length} · ${result.created?"초안 생성 완료 · 아직 최종 저장 전":"기존 초안/보고가 있어 중복 생성하지 않았습니다"} `;
        line.append(importLink(result.draft.id));
      }catch(error){failed++;line.textContent=`${i+1}/${checks.length} · 처리 실패: ${error.message}`;line.className="error";}
    }
    await refreshList();notify(`처리 결과: 초안 확인 가능 ${succeeded}건 · 실패 ${failed}건. ${succeeded?"'내용 확인·수정하기'를 열어 확인한 뒤 저장하세요.":"아래 실패 사유를 확인하고 다시 시도해 주세요."}`,failed>0);
  }finally{
    $("import-fields").disabled=false;
    document.querySelectorAll("#import-messages input").forEach(el=>el.disabled=Boolean(importRows.get(el.dataset.messageId)?.existing));
  }
});
