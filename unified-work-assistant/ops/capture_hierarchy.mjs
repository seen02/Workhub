import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {Session,root,settings} from './sso_test_client.mjs';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE||'playwright');
const s=new Session();await s.portal();await s.login(settings.urls.outline+'/auth/oidc');
const migration=JSON.parse(fs.readFileSync(path.join(root,'reports/hierarchy-migration.json'),'utf8').replace(/^\uFEFF/,''));
const project=migration.projects.find(p=>p.name==='프로젝트 A');
const browser=await chromium.launch({headless:true,channel:'msedge'});
try{
 const context=await browser.newContext({viewport:{width:1440,height:1050}});
 await context.addCookies([...s.jar].map(([name,value])=>({name,value,domain:name.startsWith('workhub_')?'localhost':new URL(settings.urls.outline).hostname,path:'/',httpOnly:true,sameSite:'Lax'})));
 const page=await context.newPage();await page.goto(project.parentUrl);
 await page.getByRole('link',{name:'A-1',exact:true}).first().waitFor({timeout:45000});
 await page.screenshot({path:path.join(root,'reports/hierarchy-outline.png'),fullPage:true});
 console.log('PASS Outline parent and child visible');
}finally{await browser.close()}
