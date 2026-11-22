import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {Session,root,settings,credentials} from './sso_test_client.mjs';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE||'playwright');
const checks={},assert=(v,k)=>{if(!v)throw Error(k);checks[k]=true;console.log('PASS',k)};
const admin=new Session();await admin.portal();await admin.api('/api/sync',{});const before=(await admin.api('/api/tasks')).tasks;
const data=await admin.api('/api/analytics'),valid=before.filter(t=>!t.error),open=valid.filter(t=>t.fields.status!=='완료');
const criteria=valid.flatMap(t=>t.criteria||[]),done=criteria.filter(i=>i.state==='완료').length;
assert(data.summary.total===valid.length&&data.summary.completed===valid.length-open.length,'counts_match_current_outline_tasks');
assert(data.summary.criteria_total===criteria.length&&data.summary.criteria_done===done&&data.summary.criteria_progress===(criteria.length?Math.round(1000*done/criteria.length)/10:null),'weighted_criteria_match_actual_data');
const dated=t=>/^\d{4}-\d{2}-\d{2}$/.test(t.fields.due);
assert(data.summary.overdue===open.filter(t=>dated(t)&&t.fields.due<data.as_of).length,'overdue_matches_korean_calendar');
assert(data.summary.due_soon===open.filter(t=>dated(t)&&t.fields.due>=data.as_of&&t.fields.due<=data.until).length,'upcoming_deadline_boundary_matches');
const known=valid.map(t=>Number.parseFloat(t.fields.progress)).filter(n=>Number.isFinite(n));
assert(data.summary.average_progress===(known.length?Math.round(10*known.reduce((a,b)=>a+b,0)/known.length)/10:null),'average_excludes_unreported_progress');
assert(data.schedule.reduce((n,b)=>n+b.count,0)===open.length,'deadline_buckets_cover_each_open_task_once');
const browser=await chromium.launch({headless:true,channel:'msedge'});const errors=[];
try{
 for(const [account,key] of [[credentials.authentikAdmin,'admin'],[credentials.groupA,'hong'],[credentials.groupB,'kim']]){
  const s=new Session();await s.login(settings.urls.portal+'/auth/login',account);const me=await s.api('/api/me');s.csrf=me.csrf;
  assert((await s.api('/api/analytics')).summary.total===data.summary.total,'analytics_access_'+key);
  const context=await browser.newContext({viewport:{width:1600,height:1080}});await context.addCookies([...s.jar].filter(([k])=>k.startsWith('workhub_')).map(([name,value])=>({name,value,domain:'localhost',path:'/',httpOnly:true,sameSite:'Lax'})));
  const page=await context.newPage();page.on('pageerror',e=>errors.push(key+': '+e.message));await page.goto(settings.urls.portal);await page.locator('#tasks').waitFor({state:'visible',timeout:45000});
  await page.getByRole('button',{name:'진행 통계',exact:true}).click();
  const ready=()=>page.waitForFunction(()=>document.querySelector('#stats-content').getAttribute('aria-busy')==='false'&&document.querySelector('#stats-status').textContent.includes('기준일'));
  await ready();assert(await page.locator('#metrics .stat-tile').count()===6,'six_metric_cards_'+key);assert(await page.locator('#project-bar').isHidden(),'independent_statistics_scope_'+key);
  assert(await page.locator('#stats-project').inputValue()==='','all_projects_default_'+key);
  if(!me.admin){assert(await page.locator('#weekly').isHidden(),'worker_has_no_publish_action_'+key);const r=await s.fetch(settings.urls.portal+'/api/weekly');assert(r.status===403,'worker_publish_api_still_denied_'+key)}
  if(key==='admin'){
   assert(await page.locator('#weekly').isDisabled(),'all_projects_cannot_publish_wrong_project');
   await page.screenshot({path:path.join(root,'reports/analytics-overview.png'),fullPage:true});
   await page.locator('#metrics [data-focus=overdue]').click();assert(await page.locator('#planning-list .plan-row').count()===data.summary.overdue,'metric_drills_into_matching_actions');
   await page.locator('#planning-search').fill('없는 업무 검증 zzz999');assert(await page.locator('#planning-list .empty').count()===1,'action_search_empty_state');
   await page.locator('#stats-reset').click();await ready();
   const projectId=data.projects.find(p=>p.total)?.id;await page.locator(`[data-stats-project="${projectId}"]`).click();await ready();
   assert(await page.locator('#stats-project').inputValue()===projectId&&await page.locator('#project-comparison tr').count()===1,'project_comparison_drilldown');
   assert(await page.locator('#weekly').isEnabled(),'single_project_admin_report_available');
   await page.selectOption('#stats-horizon','30');await ready();assert((await page.locator('#metrics').innerText()).includes('30일'),'horizon_control_updates_cards');
  }
  await page.locator('#stats-reset').click();await ready();await page.locator('#stats-mine').click();await ready();
  const mine=await s.api('/api/analytics?owner='+encodeURIComponent(me.email)),mineItems=criteria.filter(i=>i.owner===me.email);
  assert(mine.summary.criteria_total===mineItems.length,'my_criteria_denominator_'+key);assert(await page.locator('#filter-owner').inputValue()===me.email,'my_filter_selected_'+key);
  if(key==='hong'){
   await page.screenshot({path:path.join(root,'reports/analytics-my-work.png'),fullPage:true});
   const report=page.locator('[data-plan-report]').first();if(await report.count()){
    const target=await report.getAttribute('data-plan-report');await report.click();await page.locator('#assistant').waitFor({state:'visible'});assert(await page.locator('#report-task').inputValue()===target,'planning_action_opens_correct_report_task');
    await page.getByRole('button',{name:'진행 통계',exact:true}).click();await ready();
   }
   await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(root,'reports/analytics-mobile.png'),fullPage:true});
   assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)),'mobile_no_page_overflow');
   await page.setViewportSize({width:1600,height:1080});
   const empty=structuredClone(data);empty.summary={...empty.summary,total:0,completed:0,open:0,completion_rate:null,criteria_total:0,criteria_done:0,criteria_remaining:0,criteria_progress:null,overdue:0,due_soon:0,blocked:0,no_due:0,invalid:0,no_criteria:0,missing_progress:0,states:Object.fromEntries(Object.keys(empty.summary.states).map(k=>[k,0]))};empty.projects=[];empty.owners=[];empty.actions=[];empty.invalid_tasks=[];empty.schedule=empty.schedule.map(b=>({...b,count:0}));
   await page.route('**/api/analytics?**',r=>r.fulfill({json:empty}));await page.locator('#stats-reset').click();await ready();assert((await page.locator('#metrics').innerText()).includes('—')&&await page.locator('#planning-list .empty').count()===1,'empty_data_not_presented_as_zero_achievement');await page.unroute('**/api/analytics?**');
   await page.route('**/api/analytics?**',r=>r.fulfill({status:503,json:{detail:'검증용 일시 오류'}}));await page.locator('#stats-reset').click();await page.waitForFunction(()=>document.querySelector('#stats-status').textContent.includes('통계를 불러오지 못했습니다.'));assert(await page.locator('#stats-content').isHidden(),'failed_refresh_does_not_show_stale_totals');await page.unroute('**/api/analytics?**');await page.locator('#stats-reset').click();await ready();
   await page.locator('#stats-refresh').click();await ready();assert((await page.locator('#stats-status').innerText()).includes('마지막 동기화'),'manual_refresh_displays_freshness');
  }
  await context.close();
 }
}finally{await browser.close()}
assert(errors.length===0,'no_browser_javascript_errors');
const after=(await admin.api('/api/tasks')).tasks;assert(before.length===after.length&&before.every(t=>after.some(a=>a.id===t.id&&a.text===t.text)),'statistics_did_not_modify_user_tasks');
fs.writeFileSync(path.join(root,'reports/analytics-verification.json'),JSON.stringify({at:new Date().toISOString(),checks,summary:data.summary,projects:data.projects.map(p=>({id:p.id,name:p.name,total:p.total,criteria_progress:p.criteria_progress,average_progress:p.average_progress})),method:'Actual Authentik admin/Hong/Kim accounts; browser filters, drilldown, report shortcut and responsive UI. Empty/error displays use isolated mocked read responses.'},null,2));
console.log(JSON.stringify(checks,null,2));
