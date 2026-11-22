const assert=require('node:assert/strict');
require('../backend/app/rocketchat/review_ui/report-format.js');
const items=[
 {project:'ai-assistant',task:'환경 구성 및 연동',status:'DONE',progress:100},
 {project:'ai-assistant',task:'업무보고 테스트',status:'IN_PROGRESS',progress:60},
 {project:'ai-assistant',task:'RAG 도입',status:'NOT_STARTED',progress:0},
 {project:'spatial-agent',task:'검색 품질 개선',status:'IN_PROGRESS',progress:30},
 {project:'spatial-agent',task:'검색 테스트',status:'IN_PROGRESS',progress:50},
];
const text=formatCompanyReport(items,'2026-09-09T09:00:00');
assert(text.startsWith('[업무목록]\n- 로켓챗 기반 업무 비서 AI Agent 개발\n- 자연어 기반 GIS 분석 프로젝트 진행 방향 정리'));
assert(text.includes('[9월 9일 수요일 : 9시]'));
assert(text.includes('1. 환경 구성 및 연동(✅ 완료)'));
assert(text.includes('2. 업무보고 테스트(🔄 진행중 60%)'));
assert(text.includes('3. RAG 도입(⏳ 예정)'));
assert(text.includes('1. 검색 품질 개선(🔄 진행중 30%)'));
assert(text.includes('2. 검색 테스트(🔄 진행중 50%)'));
assert(!text.includes('100%'));
assert(!text.includes('미기재'));
assert(formatCompanyReport([{task:'확인',status:'IN_PROGRESS',progress:null}],'2026-09-09T00:05:00').includes('[9월 9일 수요일 : 0시 5분]'));
console.log('PASS: report layout, project grouping, per-project numbering, status icons, progress, Korean date');
