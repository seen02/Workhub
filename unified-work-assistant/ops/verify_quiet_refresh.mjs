import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {Session,root,settings} from './sso_test_client.mjs';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE||'playwright');
const s=new Session();await s.portal();
const browser=await chromium.launch({headless:true,channel:'msedge'}),checks=[];
try{
 const context=await browser.newContext({viewport:{width:1440,height:1050}});
 await context.addCookies([...s.jar].filter(([k])=>k.startsWith('workhub_')).map(([name,value])=>({name,value,domain:'localhost',path:'/',httpOnly:true,sameSite:'Lax'})));
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(settings.urls.portal);await page.locator('#tasks').waitFor({state:'visible'});
 await page.click('#all');
 const projects=(await s.api('/api/projects')).projects,project=projects.find(p=>p.name==='팀 협업 시연')||projects[0];
 const selected=page.waitForResponse(r=>r.url().includes('/api/tasks?')&&r.url().includes(project.id));await page.selectOption('#project-select',project.id);await selected;await page.locator('#project-progress').waitFor({state:'visible'});
 await page.evaluate(()=>{
  window.boardNode=document.querySelector('#task-grid .task');window.barHidden=0;
  window.boardWatcher=new MutationObserver(records=>{for(const r of records)if(r.attributeName==='hidden')window.barHidden++});
  window.boardWatcher.observe(document.querySelector('#project-progress'),{attributes:true});
 });
 await page.waitForResponse(r=>r.url().includes('/api/tasks?'),{timeout:26000});
 await page.waitForFunction(()=>!refreshing);
 assert.equal(await page.evaluate(()=>window.boardNode===document.querySelector('#task-grid .task')&&window.barHidden===0),true);
 checks.push('20초 업무 보드 갱신: 기존 카드 유지, 진행률 숨김 없음');
 await page.getByRole('button',{name:'진행 통계',exact:true}).click();
 const ready=()=>page.waitForFunction(()=>document.querySelector('#stats-content').getAttribute('aria-busy')==='false'&&document.querySelector('#stats-status').textContent.includes('기준일'));
 await ready();const actual=await s.api('/api/analytics');
 assert.match(await page.locator('#metrics').innerText(),/전체 프로젝트 진행률/);
 assert.equal(await page.locator('#metrics .stat-tile strong').first().innerText(),actual.summary.project_progress+'%');
 for(const p of actual.projects){const row=page.locator(`[data-stats-project="${p.id}"]`).locator('xpath=../..');assert.equal(await row.locator('.project-cell b').innerText(),p.average_progress===null?'—':p.average_progress+'%')}
 checks.push('관리자 전체·프로젝트별 진행률이 실제 집계와 일치');
 await page.screenshot({path:path.join(root,'reports/admin-project-progress.png'),fullPage:true});
 await page.locator('#planning-list details summary').first().click();await page.locator('#planning-list details summary').first().focus();
 await page.evaluate(()=>{
  window.stableNodes=['#metrics button','#project-comparison tr','#planning-list details','#stats-project option'].map(s=>document.querySelector(s));
  window.savedFocus=document.activeElement;window.savedScroll=scrollY;window.faded=false;window.loadingMessage=false;
  window.refreshWatch=setInterval(()=>{const el=document.querySelector('#stats-content');window.faded ||= getComputedStyle(el).opacity!=='1'||el.hidden;window.loadingMessage ||= document.querySelector('#stats-status').textContent.includes('불러오고 있습니다');},20);
 });
 await page.route('**/api/analytics?*',async route=>{await new Promise(r=>setTimeout(r,400));await route.continue()});
 await page.waitForResponse(r=>r.url().includes('/api/analytics?'),{timeout:26000});await ready();
 const stable=await page.evaluate(()=>{
  clearInterval(window.refreshWatch);
  return {nodes:window.stableNodes.every((node,i)=>node===document.querySelector(['#metrics button','#project-comparison tr','#planning-list details','#stats-project option'][i])),focus:document.activeElement===window.savedFocus,scroll:Math.abs(scrollY-window.savedScroll)<2,expanded:document.querySelector('#planning-list details').open,faded:window.faded,loading:window.loadingMessage};
 });
 assert.deepEqual(stable,{nodes:true,focus:true,scroll:true,expanded:true,faded:false,loading:false});
 checks.push('20초 통계 갱신: 밝기·DOM·포커스·스크롤·펼친 기준 유지');
 await page.unroute('**/api/analytics?*');
 await page.route('**/api/analytics?*',r=>r.fulfill({status:503,json:{detail:'검증용 일시 오류'}}));
 await page.evaluate(()=>renderAnalytics({background:true}).catch(()=>{}));
 assert.equal(await page.locator('#stats-content').isVisible(),true);assert.match(await page.locator('#stats-status').innerText(),/마지막으로 확인한 통계/);
 await page.unroute('**/api/analytics?*');await page.evaluate(()=>renderAnalytics({background:true}));await ready();
 checks.push('자동 갱신 실패 시 기존 화면 유지·오류 안내·재조회 복구');
 const fixture=structuredClone(actual);fixture.summary.project_progress=62.5;fixture.projects[0].average_progress=62.5;
 await page.route('**/api/analytics?*',r=>r.fulfill({json:fixture}));await page.evaluate(()=>renderAnalytics({background:true}));await ready();
 assert.equal(await page.locator('#metrics .stat-tile strong').first().innerText(),'62.5%');assert.equal(await page.locator('#project-comparison .project-cell b').first().innerText(),'62.5%');assert.equal(await page.locator('#planning-list details').first().getAttribute('open'),'');
 await page.unroute('**/api/analytics?*');await page.evaluate(()=>renderAnalytics({background:true}));await ready();
 checks.push('변경된 집계 수치 반영 확인 (읽기 응답 모의 데이터)');
 await page.selectOption('#stats-project',project.id);await ready();assert.match(await page.locator('#metrics').innerText(),/선택 프로젝트 진행률/);
 await page.click('#stats-reset');await ready();await page.setViewportSize({width:390,height:844});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 await page.screenshot({path:path.join(root,'reports/admin-project-progress-mobile.png'),fullPage:true});checks.push('프로젝트 필터·모바일 화면 정상');
 assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(root,'reports/quiet-refresh-verification.json'),JSON.stringify({at:new Date().toISOString(),checks,stable,page_errors:errors},null,2));
 console.log(JSON.stringify({pass:true,checks},null,2));
}finally{await browser.close()}
