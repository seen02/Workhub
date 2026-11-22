import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {Session,root,settings} from './sso_test_client.mjs';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE||'playwright');
const manifest=JSON.parse(fs.readFileSync(path.join(root,'reports/team-demo-manifest.json'))),s=new Session();await s.portal();
const current=async()=>(await s.api('/api/tasks?collection_id='+manifest.project.id)).tasks.find(t=>t.id===manifest.task.id);
const before=await current(),browser=await chromium.launch({headless:true,channel:'msedge'});
try{
 const context=await browser.newContext({viewport:{width:1440,height:1050}});
 await context.addCookies([...s.jar].filter(([k])=>k.startsWith('workhub_')||k.startsWith('authentik_')).map(([name,value])=>({name,value,domain:name.startsWith('workhub_')?'localhost':new URL(settings.urls.auth).hostname,path:'/',httpOnly:true,sameSite:'Lax'})));
 const page=await context.newPage();await page.goto(settings.urls.portal);await page.locator('#project-bar').waitFor({state:'visible'});await page.selectOption('#project-select',manifest.project.id);
 await page.locator(`[data-criteria="${manifest.task.id}"]`).click();await page.locator('#criteria-dialog').waitFor({state:'visible'});
 const states=page.locator('#criteria-rows .criterion-state');for(let n=0;n<await states.count();n++)await states.nth(n).selectOption('예정');
 await page.locator('#criteria-form > button').last().click();await page.locator('#confirm').click();await page.waitForFunction(()=>document.querySelector('#proposal').innerText.includes('반영되었습니다'));
 const after=await current();const checks={reset_zero:after.fields.progress==='0%'&&after.fields.status==='미착수'&&after.criteria.every(i=>i.state==='예정'),assignments_preserved:JSON.stringify(after.criteria.map(i=>[i.id,i.owner]))===JSON.stringify(before.criteria.map(i=>[i.id,i.owner])),report_history_preserved:after.text.includes('보고 기록')&&after.text.includes('배포 점검도 끝났어.')};
 await page.locator('[data-tab=tasks]').click();await page.locator('#sync').click();await page.screenshot({path:path.join(root,'reports/chat-selection-ready-board.png'),fullPage:true});
 await page.locator('[data-tab=guide]').click();const guide=await page.locator('#guide').innerText();checks.guide_has_buttons_and_reset=guide.includes('이 보고 확정')&&guide.includes('다시 처음부터 시연하기')&&!guide.includes('efc39435');
 if(Object.values(checks).some(v=>!v))throw Error(JSON.stringify(checks));
 fs.writeFileSync(path.join(root,'reports/chat-reset-verification.json'),JSON.stringify({at:new Date().toISOString(),checks,progress:after.fields.progress},null,2));console.log(JSON.stringify(checks,null,2));
}finally{await browser.close()}
