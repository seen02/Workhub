import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {Session,root,settings,credentials} from './sso_test_client.mjs';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE||'playwright');
const admin=new Session();await admin.portal();
const s=new Session();await s.login(settings.urls.portal+'/auth/login',credentials.groupA);
const browser=await chromium.launch({headless:true,channel:'msedge'});
const checks=[];
try{
  const context=await browser.newContext({viewport:{width:1440,height:1050}});
  await context.addCookies([...s.jar].filter(([k])=>k.startsWith('workhub_')).map(([name,value])=>({name,value,domain:'localhost',path:'/',httpOnly:true,sameSite:'Lax'})));
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(settings.urls.portal);await page.locator('#tasks').waitFor({state:'visible'});
  const projects=(await s.api('/api/projects')).projects;
  const ready=()=>page.locator('#project-progress').waitFor({state:'visible'});
  for(const project of projects){
    const response=page.waitForResponse(r=>r.url().includes('/api/tasks?')&&r.url().includes(project.id));
    await page.selectOption('#project-select',project.id);await response;await ready();
    const {summary}=await s.api('/api/analytics?collection_id='+project.id);
    const value=summary.average_progress===null?'—':summary.average_progress+'%';
    assert.equal(await page.locator('#project-progress-value').innerText(),value);
    for(const button of ['#all','#mine']){await page.click(button);assert.equal(await page.locator('#project-progress-value').innerText(),value)}
    await page.fill('#search','no-matching-task-for-verification');assert.equal(await page.locator('#project-progress-value').innerText(),value);await page.fill('#search','');
    checks.push({project:project.name,progress:value,analytics_match:true,independent_of_filters:true});
  }
  const demo=projects.find(p=>p.name==='팀 협업 시연')||projects[0];
  await page.selectOption('#project-select',demo.id);await ready();
  await page.screenshot({path:path.join(root,'reports/project-progress-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:path.join(root,'reports/project-progress-mobile.png'),fullPage:true});
  checks.push({mobile_no_overflow:true});
  // Edge cases are read-only browser response fixtures, never Outline mutations.
  const original=await s.api('/api/tasks?collection_id='+demo.id);const base=original.tasks[0];assert.ok(base);
  let fixture={...original,tasks:[{...base,id:'fixture-1',fields:{...base.fields,progress:'25%'}},{...base,id:'fixture-2',fields:{...base.fields,progress:'미기재'}},{...base,id:'fixture-3',error:'invalid',fields:{...base.fields,progress:'100%'}}]};
  await page.route('**/api/tasks?*',route=>route.fulfill({json:fixture}));
  const reload=async()=>{await page.reload();await page.locator('#tasks').waitFor({state:'visible'});await ready()};
  await reload();assert.equal(await page.locator('#project-progress-value').innerText(),'25%');assert.match(await page.locator('#project-progress-note').innerText(),/미기재 1건 제외.*형식 오류 1건 제외/);
  fixture.tasks=[fixture.tasks[1]];await reload();assert.equal(await page.locator('#project-progress-value').innerText(),'—');assert.equal(await page.locator('#project-progress-bar').isVisible(),false);
  fixture.tasks=[];await reload();assert.match(await page.locator('#project-progress-note').innerText(),/등록된 업무가 없습니다/);
  checks.push({missing_and_invalid_excluded:true,unknown_not_shown_as_zero:true,empty_project:true});
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(root,'reports/project-progress-verification.json'),JSON.stringify({at:new Date().toISOString(),checks,page_errors:errors},null,2));
  console.log(JSON.stringify({pass:true,checks},null,2));
}finally{await browser.close()}
