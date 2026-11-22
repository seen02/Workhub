import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {Session,root,settings} from './sso_test_client.mjs';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const session=new Session(),me=await session.portal(),manifest=JSON.parse(fs.readFileSync(path.join(root,'reports/project-demo-manifest.json')));
const [projectA,projectB]=manifest.projects,task=manifest.tasks[0],checks={},errors=[];
const assert=(v,name)=>{if(!v)throw Error(name);checks[name]=true;console.log('PASS',name)};
const browser=await chromium.launch({headless:true,channel:'msedge'});let page,temporaryTask;
const cfg=JSON.parse(fs.readFileSync(path.join(root,'.local/compose.json')));
async function outline(endpoint,body){const r=await fetch(settings.urls.outline+'/api/'+endpoint,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+cfg.services['document-agent'].environment.OUTLINE_API_KEY},body:JSON.stringify(body)});if(!r.ok)throw Error(endpoint+' '+r.status);return (await r.json()).data;}
try{
 const context=await browser.newContext({viewport:{width:1500,height:1060}});
 await context.addCookies([...session.jar].filter(([name])=>name.startsWith('workhub_')||name.startsWith('authentik_')).map(([name,value])=>({name,value,domain:name.startsWith('workhub_')?'localhost':new URL(settings.urls.auth).hostname,path:'/',httpOnly:true,sameSite:'Lax'})));
 page=await context.newPage();page.on('pageerror',e=>errors.push({origin:new URL(page.url()).origin,message:e.message}));
 await page.goto(settings.urls.portal);await page.locator('#project-bar').waitFor({state:'visible'});
 await page.selectOption('#project-select',projectA.id);await page.locator(`[data-task="${task.id}"]`).waitFor();
 assert(await page.locator('.checklist li').count()===3,'project_board_checklist_rendered');
 await page.screenshot({path:path.join(root,'reports/project-board.png'),fullPage:true});
 await page.locator(`[data-criteria="${task.id}"]`).click();await page.locator('#criteria-dialog').waitFor({state:'visible'});
 assert(await page.locator('#criteria-rows .criterion-owner').count()===3,'manager_assignment_editor');
 await page.screenshot({path:path.join(root,'reports/project-assignment.png'),fullPage:true});
 await page.locator('[data-close=criteria-dialog]').click();
 await page.selectOption('#project-select',projectB.id);await page.locator(`[data-task="${manifest.tasks[1].id}"]`).waitFor();
 assert(await page.locator(`[data-task="${task.id}"]`).count()===0,'browser_project_switch_isolates_tasks');
 // Use real UI fields to create, assign, preview and save a task, then archive only this test task.
 await page.locator('#new-task').click();const name='[화면 검증] 프로젝트 업무 '+crypto.randomUUID().slice(0,6);
 await page.locator('#create-form [name=title]').fill(name);await page.locator('#create-add-criterion').click();
 await page.locator('#create-criteria-rows .criterion-title').fill('시연 화면 승인');
 await page.locator('#create-form button[type=submit], #create-form > button').last().click();
 await page.locator('#create-dialog').waitFor({state:'hidden'});
 temporaryTask=(await session.api('/api/tasks?collection_id='+projectB.id)).tasks.find(t=>t.title===name);
 assert(temporaryTask?.collectionId===projectB.id&&temporaryTask.criteria[0].owner===me.email,'ui_create_and_assign_to_selected_project');
 await page.locator(`[data-criteria="${temporaryTask.id}"]`).click();
 await page.locator('#criteria-rows .criterion-title').fill('최종 시연 화면 승인');
 await page.locator('#criteria-form > button').last().click();await page.locator('#proposal').waitFor({state:'visible'});
 assert((await outline('documents.info',{id:temporaryTask.id})).text.includes('| 시연 화면 승인 |'),'ui_assignment_is_private_until_confirm');
 await page.locator('#confirm').click();await page.waitForFunction(()=>document.querySelector('#confirm')?.disabled&&document.querySelector('#proposal').innerText.includes('반영되었습니다'));
 assert((await outline('documents.info',{id:temporaryTask.id})).text.includes('| 최종 시연 화면 승인 |'),'ui_assignment_confirm_saved');
 await page.selectOption('#report-task',temporaryTask.id);await page.selectOption('#report-criterion',temporaryTask.criteria[0].id);await page.selectOption('#criterion-state','완료');
 await page.locator('#apply-state').click();await page.locator('#confirm').waitFor({state:'visible'});await page.locator('#confirm').click();
 await page.waitForFunction(()=>document.querySelector('#proposal').innerText.includes('반영되었습니다'));
 assert((await outline('documents.info',{id:temporaryTask.id})).text.includes('진행률: 100%'),'ui_direct_item_state_and_rollup');
 await outline('documents.archive',{id:temporaryTask.id});temporaryTask=null;await session.api('/api/sync',{});
 await page.selectOption('#project-select',projectA.id);await page.locator('[data-tab=stats]').click();await page.locator('.metric').first().waitFor();
 await page.screenshot({path:path.join(root,'reports/project-statistics.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'mobile_no_overflow');
 await page.screenshot({path:path.join(root,'reports/project-mobile.png'),fullPage:true});await page.setViewportSize({width:1500,height:1060});
 // Actual Authentik -> Rocket.Chat login, then real DM transport.
 await page.goto(settings.urls.chat);await page.getByRole('button',{name:/Authentik/}).waitFor({timeout:45000});await page.getByRole('button',{name:/Authentik/}).click();
 await page.waitForURL(u=>u.origin===settings.urls.chat,{timeout:45000});await page.waitForFunction(()=>localStorage.getItem('Meteor.loginToken'),{timeout:45000});
 const rc=await page.evaluate(()=>({id:localStorage.getItem('Meteor.userId'),token:localStorage.getItem('Meteor.loginToken')}));
 async function chat(endpoint,body){const r=await fetch(settings.urls.chat+'/api/v1/'+endpoint,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-User-Id':rc.id,'X-Auth-Token':rc.token},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error('chat '+endpoint+' '+r.status);return d;}
 const room=(await chat('im.create',{username:'report-bot'})).room;
 async function send(text,pattern,seconds=180){
   const stamp=new Date().toISOString();await chat('chat.postMessage',{roomId:room._id,text});const start=Date.now();
   while(Date.now()-start<seconds*1000){const messages=(await chat('im.history?roomId='+room._id+'&count=50')).messages;const match=messages.find(m=>m.u?.username==='report-bot'&&m.ts>=stamp&&(pattern.test(m.msg)||m.msg.startsWith('처리 중단:')));if(match){if(match.msg.startsWith('처리 중단:'))throw Error(match.msg);return match.msg;}await new Promise(r=>setTimeout(r,1500))}throw Error('Bot timeout '+text);
 }
 await send('프로젝트 '+projectA.code,/선택한 프로젝트/);await send('항목 '+task.code,/완료 기준/);
 const answer=await send('요구사항은 다 끝냈어. 화면 검증은 아직 손보는 중이고 배포 확인은 내일 할 거야.',/확정 [a-f0-9]{8}/,240);
 assert(answer.includes('**[업무목록]**')&&answer.includes('✅ 완료')&&answer.includes('🔄 진행중')&&answer.includes('⏳ 예정'),'real_chat_rough_report_original_format');
 const pid=answer.match(/확정 ([a-f0-9]{8})/)[1];await send('확정 '+pid,/Outline 반영 완료/);
 let latest=(await session.api('/api/tasks?collection_id='+projectA.id)).tasks.find(t=>t.id===task.id);
 assert(latest.fields.progress==='33.3%'&&JSON.stringify(latest.criteria.map(i=>i.state))===JSON.stringify(['완료','진행 중','예정']),'real_chat_confirm_updates_outline');
 await send('프로젝트 '+projectB.code,/선택한 프로젝트/);const other=await send('업무',/문서 자동화 출시/);
 assert(!other.includes('고객 포털 출시'),'real_chat_project_scope');
 await send('프로젝트 '+projectA.code,/선택한 프로젝트/);await send('항목 '+task.code,/완료 기준/);
 await page.goto(settings.urls.chat+'/direct/report-bot');await page.getByText('전체 진행률: 33.3%',{exact:false}).last().waitFor({timeout:30000});
 await page.screenshot({path:path.join(root,'reports/project-rocketchat.png'),fullPage:true});
 assert(errors.filter(e=>e.origin===settings.urls.portal).length===0,'no_portal_javascript_errors');
 fs.writeFileSync(path.join(root,'reports/project-browser-verification.json'),JSON.stringify({at:new Date().toISOString(),checks,errors,bot_room:room._id,task_code:task.code},null,2));
 console.log(JSON.stringify({checks,errors},null,2));
}catch(e){console.log('Browser errors:',JSON.stringify(errors));if(page){await page.screenshot({path:path.join(root,'reports/project-browser-failure.png'),fullPage:true});console.log((await page.locator('body').innerText()).slice(-4500))}throw e}
finally{if(temporaryTask)await outline('documents.archive',{id:temporaryTask.id});await browser.close()}
