"use strict";
// Mirrors report_format.py; deterministic display only, never changes saved values.
globalThis.formatCompanyReport = function(items, stamp) {
  const projects={"ai-assistant":"로켓챗 기반 업무 비서 AI Agent 개발","spatial-agent":"자연어 기반 GIS 분석 프로젝트 진행 방향 정리"};
  const states={DONE:"✅ 완료",IN_PROGRESS:"🔄 진행중",NOT_STARTED:"⏳ 예정",DELAYED:"⚠️ 지연",UNKNOWN:"❔ 상태 확인 필요"};
  const when=new Date(stamp.slice(0,19)+"+09:00");
  const parts=Object.fromEntries(new Intl.DateTimeFormat("en-US",{timeZone:"Asia/Seoul",month:"numeric",day:"numeric",weekday:"short",hour:"numeric",minute:"numeric",hourCycle:"h23"}).formatToParts(when).map(p=>[p.type,p.value]));
  const weekday={Mon:"월",Tue:"화",Wed:"수",Thu:"목",Fri:"금",Sat:"토",Sun:"일"}[parts.weekday];
  const clock=`${Number(parts.hour)}시${Number(parts.minute)?` ${Number(parts.minute)}분`:""}`;
  const groups=Object.entries(projects).map(([key,title])=>[title,items.filter(i=>i.project===key)]);
  const unknown=items.filter(i=>!projects[i.project]);if(unknown.length)groups.push(["프로젝트 미선택",unknown]);
  const visible=groups.filter(([,rows])=>rows.length);
  const lines=["[업무목록]",...visible.map(([title])=>"- "+title),"",`[${Number(parts.month)}월 ${Number(parts.day)}일 ${weekday}요일 : ${clock}]`];
  for(const [title,rows] of visible){
    lines.push("",title);
    rows.forEach((item,n)=>{
      const progress=item.status==="IN_PROGRESS"&&item.progress!==null&&item.progress!==undefined?` ${item.progress}%`:"";
      lines.push(`${n+1}. ${item.task||"업무명 입력"}(${states[item.status]}${progress})`);
      if(item.next_action)lines.push("   다음 작업: "+item.next_action);
      if(item.issue)lines.push("   이슈: "+item.issue);
    });
  }
  return lines.join("\n");
};
