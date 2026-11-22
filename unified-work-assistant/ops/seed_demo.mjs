import fs from 'node:fs';
import path from 'node:path';
import {Session,root,settings} from './sso_test_client.mjs';
const s=new Session();const me=await s.portal();
const day=(n)=>new Date(Date.now()+n*86400000).toISOString().slice(0,10);
const rows=[
 {key:'main',title:'[시연] 고객용 업무 화면 검증',status:'미착수',progress:'0%',due:day(5),blocker:'없음',next:'10개 검증 항목 중 담당 항목 확인',notes:'완료 기준: 로그인, 업무 등록, 문서 직접 수정, 채팅 보고, 변경 미리보기, 확정 저장, 중복 방지, 권한 차단, 관리자 통계, 주간 보고의 10개 검증 항목을 모두 통과합니다.\n\n시연 중 진행률 40% → 60% → 100%로 변경합니다. 현재 상태는 위의 관리 항목을 기준으로 확인하세요.'},
 {key:'done',title:'[시연] 통합 로그인 사용 안내 작성',status:'완료',progress:'100%',due:day(-1),blocker:'없음',next:'신규 구성원에게 안내',notes:'Authentik 로그인과 Outline 업무 관리 방법을 설명하는 안내문을 작성했습니다.'},
 {key:'delayed',title:'[시연] 외부 검증 자료 수집',status:'지연',progress:'30%',due:day(-2),blocker:'협력사 검증 자료 회신 대기',next:'회신 일정 재확인',notes:'관리자 현황의 기한 초과와 장애요인 집계를 보여주는 시연용 업무입니다.'}
];
const manifest={created:new Date().toISOString(),portal:settings.urls.portal,chat:settings.urls.chat,outline:settings.urls.outline,tasks:[]};
for(const row of rows){
 const t=await s.api('/api/tasks',{title:row.title,fields:{project:'통합 시연',owner:me.email,due:row.due,status:row.status,progress:row.progress,blocker:row.blocker,next:row.next,result:'없음'},notes:row.notes,idem:'seed-demo-v1-'+row.key});
 manifest.tasks.push({key:row.key,id:t.id,code:t.code,title:t.title,url:t.url});
}
await s.api('/api/sync',{});
fs.writeFileSync(path.join(root,'reports/demo-manifest.json'),JSON.stringify(manifest,null,2));
console.log(JSON.stringify(manifest,null,2));
