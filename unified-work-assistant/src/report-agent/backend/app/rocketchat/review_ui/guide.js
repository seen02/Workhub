"use strict";
const panels=[...document.querySelectorAll(".manual-panel")];
const aliases={write:"new-report",confirm:"new-report",edit:"search-help",search:"search-help"};
function showPanel(){
  const requested=location.hash.slice(1)||"map";
  const id=aliases[requested]||requested;
  const active=panels.find(panel=>panel.id===id)||panels[0];
  panels.forEach(panel=>panel.hidden=panel!==active);
  document.querySelectorAll("[data-panel]").forEach(link=>{
    if(link.dataset.panel===active.id)link.setAttribute("aria-current","page");else link.removeAttribute("aria-current");
  });
  document.getElementById("copy-status").textContent="";
  document.title=active.querySelector("h1").textContent+" · 업무비서 매뉴얼";
}
showPanel();
document.body.classList.add("js-manual");
window.addEventListener("hashchange",()=>{
  showPanel();
  const target=document.getElementById(location.hash.slice(1));
  if(target && !target.classList.contains("manual-panel"))target.scrollIntoView({block:"start"});
  else window.scrollTo(0,0);
});
document.querySelectorAll("[data-copy]").forEach(button=>button.addEventListener("click",async()=>{
  const status=document.getElementById("copy-status");
  try{await navigator.clipboard.writeText(document.getElementById(button.dataset.copy).textContent);status.textContent="복사했습니다. 로켓챗에 붙여 넣고 직접 보내세요.";}
  catch{status.textContent="예시 글을 직접 선택해 복사해 주세요.";}
}));
let previousDetails=[];
window.addEventListener("beforeprint",()=>{previousDetails=[...document.querySelectorAll("details")].map(el=>[el,el.open]);previousDetails.forEach(([el])=>el.open=true);});
window.addEventListener("afterprint",()=>{previousDetails.forEach(([el,open])=>el.open=open);previousDetails=[];});
document.getElementById("print-guide").onclick=()=>window.print();
