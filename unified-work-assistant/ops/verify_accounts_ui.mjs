import fs from 'node:fs';import path from 'node:path';import {createRequire} from 'node:module';
import {Session,root,settings} from './sso_test_client.mjs';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE||'playwright');
const admin=new Session();await admin.portal();const checks=[];
const assert=(ok,name)=>{if(!ok)throw Error(name);checks.push(name);console.log('PASS',name)};
const cfg=JSON.parse(fs.readFileSync(path.join(root,'.local/compose.json'))),m=JSON.parse(fs.readFileSync(path.join(root,'reports/accounts-live-verification.json')));
const rr=await fetch(settings.urls.auth+'/api/v3/core/users/'+m.employee.pk+'/',{method:'PATCH',headers:{Authorization:'Bearer '+cfg.services.workhub.environment.AUTHENTIK_DIRECTORY_TOKEN.replaceAll('$$','$'),'Content-Type':'application/json'},body:JSON.stringify({name:'박지민'})});
assert(rr.status===403,'directory service credential cannot edit employee accounts');
const browser=await chromium.launch({headless:true,channel:'msedge'});
try{
 const context=await browser.newContext({viewport:{width:1440,height:1100}});
 await context.addCookies([...admin.jar].filter(([k])=>k==='workhub_session').map(([name,value])=>({name,value,domain:'localhost',path:'/',httpOnly:true,sameSite:'Lax'})));
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(settings.urls.portal);await page.getByRole('button',{name:'계정 · 인수인계',exact:true}).click();await page.locator('#account-handover [data-handover]').waitFor({timeout:30000});
 assert((await page.locator('#account-handover').innerText()).includes('박지민'),'inactive assignee shown by name in handover');
 await page.screenshot({path:path.join(root,'reports/accounts-ui.png'),fullPage:true});
 await page.locator('#account-handover [data-handover]').first().click();await page.locator('#detail-criteria').waitFor({timeout:30000});
 assert((await page.locator('#task-detail').innerText()).includes('신규 직원 인수인계 점검'),'handover button opens the correct project and task');
 await page.locator('#detail-criteria').click();await page.locator('#criteria-dialog[open]').waitFor();
 const options=await page.locator('#criteria-dialog .criterion-owner').first().locator('option').allTextContents();
 assert(options.some(x=>x.includes('팀장')),'manager can choose an active project member for reassignment');
 await page.locator('[data-close="criteria-dialog"]').click();assert(!errors.length,'handover navigation has no JavaScript errors');
}finally{await browser.close();fs.writeFileSync(path.join(root,'reports/accounts-ui-verification.json'),JSON.stringify({at:new Date().toISOString(),checks},null,2));}
