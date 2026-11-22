import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {Session,root,settings,credentials} from './sso_test_client.mjs';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE||'playwright');
const manifest=JSON.parse(fs.readFileSync(path.join(root,'reports/team-demo-manifest.json')));
const browser=await chromium.launch({headless:true,channel:'msedge'}),checks={};
try{
 for(const [n,account] of [credentials.authentikAdmin,credentials.groupB].entries()){
  const s=new Session();await s.login(settings.urls.portal+'/auth/login',account);const me=await s.api('/api/me');
  const context=await browser.newContext({viewport:{width:1440,height:1050}});
  await context.addCookies([...s.jar].filter(([k])=>k.startsWith('workhub_')||k.startsWith('authentik_')).map(([name,value])=>({name,value,domain:name.startsWith('workhub_')?'localhost':new URL(settings.urls.auth).hostname,path:'/',httpOnly:true,sameSite:'Lax'})));
  const page=await context.newPage();
  if(n===0){
   await page.goto(settings.urls.portal);await page.locator('#project-bar').waitFor({state:'visible'});await page.selectOption('#project-select',manifest.project.id);
   const card=page.locator(`[data-task="${manifest.task.id}"]`);await card.waitFor();const text=await card.innerText();
   checks.ready_zero=text.includes('완료 0 / 4개')&&text.includes('홍길동')&&text.includes('김철수');
   await page.screenshot({path:path.join(root,'reports/team-ready-board.png'),fullPage:true});
   await page.locator('[data-tab=guide]').click();checks.team_guide_visible=await page.getByRole('heading',{name:'팀장 · 홍길동 · 김철수 시연'}).isVisible();
  }else{
   await page.goto(settings.urls.chat);await page.getByRole('button',{name:/Authentik/}).waitFor({timeout:45000});await page.getByRole('button',{name:/Authentik/}).click();
   await page.waitForURL(u=>u.origin===settings.urls.chat,{timeout:45000});await page.waitForFunction(()=>localStorage.getItem('Meteor.loginToken'),{timeout:45000});
   await page.goto(settings.urls.chat+'/direct/report-bot');await page.getByText('Outline 반영 완료:',{exact:false}).last().waitFor({timeout:30000});
   checks.chat_author_is_real_name=(await page.getByText('김철수',{exact:true}).count())>0;
   await page.screenshot({path:path.join(root,'reports/team-chat-names.png'),fullPage:true});
  }
 }
 if(Object.values(checks).some(v=>!v))throw Error(JSON.stringify(checks));
 fs.writeFileSync(path.join(root,'reports/team-ready-verification.json'),JSON.stringify({at:new Date().toISOString(),checks},null,2));console.log(JSON.stringify(checks,null,2));
}finally{await browser.close()}
