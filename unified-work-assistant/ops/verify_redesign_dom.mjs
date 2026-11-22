// Generate a browser-run regression fixture from the shipped UI functions.
import fs from 'node:fs';
import path from 'node:path';
const root=path.resolve(import.meta.dirname,'..');
const source=fs.readFileSync(path.join(root,'src/workhub/static/projects.js'),'utf8');
const patcher=source.slice(source.indexOf('const renderedHTML='),source.indexOf("let boardRenderKey="));
const summary=source.slice(source.indexOf('function proposalSummary('),source.indexOf('function showProposal('));
const drafts=source.slice(source.indexOf('function saveReportDraft('),source.indexOf('function rememberProposal('));
const html=`<!doctype html><html lang="ko"><meta charset="utf-8"><title>Workhub DOM regression</title><h1>Workhub 화면 회귀 검증</h1><pre id="results"></pre><div id="test"></div><select id="report-task"><option>A</option><option>B</option></select><textarea id="report-text"></textarea><select id="report-criterion"><option>x</option><option>y</option></select><select id="criterion-state"><option>예정</option><option>진행 중</option><option>완료</option></select><script>
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),personName=s=>s;
${patcher}
${summary}
const tasks=[],selected=()=> 'fixture';function persistDrafts(){}
let reportTaskId='A';const reportDrafts=new Map();function drawReportItems(previous){$('#report-criterion').value=previous||'x'}
${drafts}
const checks=[];function check(name,condition){if(!condition)throw Error(name);checks.push(name)}
try{
const target=$('#test');renderHTML(target,'<section data-key="A"><input value="original"><details><summary>보기</summary><b>0%</b></details></section><section data-key="B">다음 업무</section>');
const row=target.firstChild,input=row.querySelector('input'),detail=row.querySelector('details');input.value='작성 중';input.focus();detail.open=true;
renderHTML(target,'<section data-key="A"><input value="original"><details><summary>보기</summary><b>50%</b></details></section><section data-key="B">다음 업무</section>');
check('변경 수치 반영 + 동일 행·입력 노드 유지',target.firstChild===row&&row.querySelector('input')===input&&row.querySelector('b').textContent==='50%');
check('입력값·포커스·펼친 상세 유지',input.value==='작성 중'&&document.activeElement===input&&detail.open);
renderHTML(target,'<section data-key="B">다음 업무</section><section data-key="A"><input value="original"><details><summary>보기</summary><b>75%</b></details></section>');
check('업무 순서가 바뀌어도 동일 키의 노드 재사용',target.lastChild===row&&detail.open&&input.value==='작성 중');
renderHTML(target,'<section data-key="A"><input value="original"><details><summary>보기</summary><b>100%</b></details></section>');
check('사라진 행 제거 및 남은 행 유지',target.children.length===1&&target.firstChild===row);
renderHTML(target,'<p>업무 없음</p>');check('빈 상태 전환',target.textContent==='업무 없음');
$('#report-text').value='A 보고';$('#report-criterion').value='y';$('#criterion-state').value='진행 중';$('#report-task').value='B';restoreReportDraft();check('새 업무에 이전 업무 메모가 섞이지 않음',$('#report-text').value==='');$('#report-text').value='B 보고';$('#report-task').value='A';restoreReportDraft();check('업무 재선택 시 입력·항목·직접 상태 복원',$('#report-text').value==='A 보고'&&$('#report-criterion').value==='y'&&$('#criterion-state').value==='진행 중');
const before='상태: 미착수\\n진행률: 0%\\n## 완료 기준\\n- [ ] C-12345678 | 승인 확인 | 담당자: a@example.com | 상태: 예정';const after=before.replace('미착수','완료').replace('0%','100%').replace('[ ]','[x]').replace('상태: 예정','상태: 완료');const output=proposalSummary({before,after:after+'\\n\\n### 보고 기록\\n상태: 지연\\n진행률: 66%'});check('현재 완료 기준과 진행률만 요약, 과거 보고 필드 제외',output.includes('승인 확인')&&output.includes('100%')&&!output.includes('66%'));
check('변경 요약의 HTML 이스케이프',proposalSummary({before:'다음 행동: 없음',after:'다음 행동: <img src=x onerror=alert(1)>'}).includes('&lt;img'));
$('#results').textContent=JSON.stringify({pass:true,checks},null,2);document.body.dataset.pass='true';
}catch(e){$('#results').textContent=JSON.stringify({pass:false,checks,error:e.message},null,2);document.body.dataset.pass='false'}
</script></html>`;
const folder=path.join(root,'.ui-review/redesign-dom');fs.mkdirSync(folder,{recursive:true});fs.writeFileSync(path.join(folder,'index.html'),html);console.log(path.join(folder,'index.html'));
