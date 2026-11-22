import fs from 'node:fs';import path from 'node:path';import {createRequire} from 'node:module';
import {Session,root,settings,credentials} from './sso_test_client.mjs';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE||'playwright');
const s=new Session();await s.login(settings.urls.portal+'/auth/login',credentials.groupA);const me=await s.api('/api/me');
const browser=await chromium.launch({headless:true,channel:'msedge'});
try{
 const context=await browser.newContext();await context.addCookies([...s.jar].filter(([k])=>k.startsWith('workhub_')).map(([name,value])=>({name,value,domain:'localhost',path:'/',httpOnly:true,sameSite:'Lax'})));
 const page=await context.newPage();await page.goto(settings.urls.portal);await page.locator('#tasks').waitFor({state:'visible'});await page.getByRole('button',{name:'진행 통계',exact:true}).click();
 const ready=()=>page.waitForFunction(()=>document.querySelector('#stats-content').getAttribute('aria-busy')==='false'&&document.querySelector('#stats-status').textContent.includes('기준일'));
 await ready();const other=(await page.locator('#filter-owner option').evaluateAll(opts=>opts.map(o=>o.value))).find(v=>v&&v!==me.email);
 await page.selectOption('#filter-owner',other);await ready();if(!(await page.locator('#metrics').innerText()).includes('선택 담당 기준 달성'))throw Error('Other owner label');
 await page.locator('#stats-reset').click();await ready();const detail=page.locator('#planning-list details').first();await detail.locator('summary').click();const href=await detail.locator('xpath=..').locator('h3 a').getAttribute('href');
 await page.locator('#stats-refresh').click();await ready();const expanded=await page.locator('#planning-list details[open]').evaluateAll(ds=>ds.map(d=>d.closest('.plan-row').querySelector('h3 a').getAttribute('href')));if(!expanded.includes(href))throw Error('Expanded checklist lost on refresh');
 fs.writeFileSync(path.join(root,'reports/analytics-refresh-verification.json'),JSON.stringify({at:new Date().toISOString(),other_owner_label:true,expanded_checklist_survives_refresh:true},null,2));console.log('PASS other owner label; expanded checklist survives refresh');
}finally{await browser.close()}
