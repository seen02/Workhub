import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {Session,root,settings} from './sso_test_client.mjs';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const session=new Session();const me=await session.portal();
const browser=await chromium.launch({headless:true,channel:'msedge'});
let page;
try{
const context=await browser.newContext({viewport:{width:1440,height:1000}});
context.on('page',p=>{p.on('framenavigated',f=>{if(f===p.mainFrame())console.log('Navigate',new URL(f.url()).origin,new URL(f.url()).pathname)});p.on('console',m=>{if(m.type()==='error')console.log('Console error',m.text().replace(/code=[^&\s]+/g,'code=[redacted]').slice(0,400))});});
await context.addCookies([...session.jar].filter(([name])=>name.startsWith('workhub_')||name.startsWith('authentik_')).map(([name,value])=>({name,value,domain:name.startsWith('workhub_')?'localhost':new URL(settings.urls.auth).hostname,path:'/',httpOnly:true,sameSite:'Lax'})));
page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto(settings.urls.portal);await page.locator('#tasks').waitFor({state:'visible'});
await page.screenshot({path:path.join(root,'reports/portal-board.png'),fullPage:true});
await page.locator('[data-tab=stats]').click();await page.locator('.metric').first().waitFor();
await page.screenshot({path:path.join(root,'reports/portal-stats.png'),fullPage:true});
await page.setViewportSize({width:390,height:844});
if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Mobile overflow');
await page.screenshot({path:path.join(root,'reports/portal-mobile.png'),fullPage:true});
await page.setViewportSize({width:1440,height:1000});
await page.goto(settings.urls.chat);await page.getByRole('button',{name:/Authentik/}).waitFor({timeout:45000});
await page.getByRole('button',{name:/Authentik/}).click();
await page.waitForURL(u=>u.origin===settings.urls.chat,{timeout:45000});
await page.waitForFunction(()=>localStorage.getItem('Meteor.loginToken'),{timeout:45000});
const rc=await page.evaluate(()=>({id:localStorage.getItem('Meteor.userId'),token:localStorage.getItem('Meteor.loginToken')}));
const response=await fetch(settings.urls.chat+'/api/v1/me',{headers:{'X-User-Id':rc.id,'X-Auth-Token':rc.token}});
const user=await response.json();if(!response.ok||!user.emails?.some(e=>e.address===me.email))throw Error('Rocket.Chat SSO user mismatch');
if(!user.roles?.includes('admin'))throw Error('Rocket.Chat administrator group mapping failed');
await page.screenshot({path:path.join(root,'reports/rocketchat-sso.png'),fullPage:true});
const result={portal_ui:true,mobile_no_overflow:true,rocket_sso:true,rocket_user:{id:rc.id,username:user.username,email:me.email,roles:user.roles},page_errors:errors};
if(process.env.VERIFY_BOT==='1'){
 const rh={'Content-Type':'application/json','X-User-Id':rc.id,'X-Auth-Token':rc.token};
 async function chat(endpoint,body){const r=await fetch(settings.urls.chat+'/api/v1/'+endpoint,{method:body?'POST':'GET',headers:rh,body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error('Chat '+endpoint+' '+r.status);return d;}
 const room=(await chat('im.create',{username:'report-bot'})).room;
 const after=new Date().toISOString();
 await chat('chat.postMessage',{roomId:room._id,text:'업무'});
 async function answer(pattern,afterStamp,seconds=100){const start=Date.now();while(Date.now()-start<seconds*1000){const messages=(await chat('im.history?roomId='+room._id+'&count=50')).messages;const found=messages.find(m=>m.u?.username==='report-bot'&&m.ts>=afterStamp&&pattern.test(m.msg));if(found)return found;await new Promise(r=>setTimeout(r,2000));}throw Error('Bot response timed out: '+pattern);}
 await answer(/고객용 업무 화면 검증/,after);
 const manifest=JSON.parse(fs.readFileSync(path.join(root,'reports/demo-manifest.json')));const task=manifest.tasks.find(t=>t.key==='main');
 const reportAt=new Date().toISOString();
 await chat('chat.postMessage',{roomId:room._id,text:`보고 ${task.code} 고객용 업무 화면 검증은 현재 진행 중이며 전체 진행률은 60%입니다.`});
 const draft=await answer(/확정 [a-f0-9]{8}/,reportAt,240);
 const pid=draft.msg.match(/확정 ([a-f0-9]{8})/)[1];
 const confirmedAt=new Date().toISOString();
 await chat('chat.postMessage',{roomId:room._id,text:'확정 '+pid});
 await answer(/Outline 반영 완료/,confirmedAt);
 await session.api('/api/sync',{});const current=(await session.api('/api/tasks')).tasks.find(t=>t.id===task.id);
 if(current.fields.progress!=='60%')throw Error('Chat confirmation did not update Outline');
 result.bot={room:room._id,list:true,ai_draft:true,confirmation:true,outline_progress:current.fields.progress,task_id:task.id};
 await page.goto(settings.urls.chat+'/direct/report-bot');await page.getByText('Outline 반영 완료:',{exact:false}).last().waitFor({timeout:30000});
 await page.screenshot({path:path.join(root,'reports/rocketchat-demo.png'),fullPage:true});
}
fs.writeFileSync(path.join(root,'reports/browser-verification.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
}catch(ex){if(page){await page.screenshot({path:path.join(root,'reports/browser-failure.png'),fullPage:true});console.log('Visible page:',new URL(page.url()).pathname,(await page.locator('body').innerText()).slice(0,2500));}console.error('Browser verification:',ex.message);throw ex;}finally{await browser.close()}
