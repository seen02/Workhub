import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';import {createRequire} from 'node:module';
import {Session,root,settings,credentials} from './sso_test_client.mjs';
const fixture=JSON.parse(fs.readFileSync(path.join(root,'reports/search-live-fixture.json')));
const rooms=JSON.parse(fs.readFileSync(path.join(root,'reports/search-chat-fixture.json')));
const checks={},results=[];const assert=(v,k)=>{if(!v)throw Error(k);checks[k]=true;console.log('PASS',k)};
const admin=new Session();await admin.login(settings.urls.outline+'/auth/oidc');
async function searchApi(action,body={}){const r=await admin.fetch(settings.urls.outline+'/api/workhub.search.'+action,{method:'POST',headers:{'Content-Type':'application/json',Origin:settings.urls.outline,'X-CSRF-Token':decodeURIComponent(admin.jar.get('csrfToken')||'')},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(action+' '+r.status+' '+d.message);return d.data;}
for(const room of [rooms.room,rooms.discussion])await searchApi('sharing',{room_id:room.id,collection_ids:[fixture.a.id]});
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE);
const browser=await chromium.launch({headless:true,channel:'msedge'});
async function actor(account){
  const s=new Session();await s.login(settings.urls.portal+'/auth/login',account);await s.api('/api/me');
  const context=await browser.newContext({viewport:{width:1400,height:960}});
  await context.addCookies([...s.jar].filter(([k])=>k.startsWith('authentik_')).map(([name,value])=>({name,value,domain:new URL(settings.urls.auth).hostname,path:'/',httpOnly:true,sameSite:'Lax'})));
  const page=await context.newPage();await page.goto(settings.urls.chat);
  await page.getByRole('button',{name:/Authentik/}).click({timeout:45000});
  await page.waitForFunction(()=>localStorage.getItem('Meteor.loginToken'),{timeout:60000});
  const rc=await page.evaluate(()=>({id:localStorage.getItem('Meteor.userId'),token:localStorage.getItem('Meteor.loginToken')}));
  async function api(endpoint,body){for(let n=0;n<3;n++){const r=await fetch(settings.urls.chat+'/api/v1/'+endpoint,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-User-Id':rc.id,'X-Auth-Token':rc.token},body:body?JSON.stringify(body):undefined});const d=await r.json();if(r.status===429&&!body){await new Promise(resolve=>setTimeout(resolve,Math.min(60,Number(d.error?.match(/wait (\d+)/)?.[1]||10))*1000));continue;}if(!r.ok)throw Error(endpoint+' '+r.status+' '+d.error);return d;}throw Error('Chat read rate limited');}
  return {page,context,api,rc};
}
try {
  const employee=await actor(credentials.groupA);
  for(const [room,kind] of [[rooms.room,'channel'],[rooms.discussion,'discussion']]) {
    const message='@report-bot 검색 시연 A 설계 문서 링크 제공해줘';
    const at=Date.now(),sent=(await employee.api('chat.sendMessage',{message:{_id:'demo'+crypto.randomBytes(10).toString('hex'),rid:room.id,msg:message}})).message;
    assert(sent.mentions?.some(m=>m._id===rooms.bot),kind+'_actual_mention');
    let reply;
    for(let n=0;n<35;n++){
      await new Promise(r=>setTimeout(r,5000));
      const rows=(await employee.api('chat.getThreadMessages?tmid='+sent._id+'&count=30')).messages||[];
      reply=rows.find(m=>m.u?._id===rooms.bot&&m.msg.includes(fixture.design.url.split('/').pop()));
      if(reply)break;
    }
    assert(reply,kind+'_link_in_thread');
    assert(reply.msg.includes('http://outline.workhub.test/'),'canonical_outline_link');
    results.push({kind,seconds:(Date.now()-at)/1000,request:sent._id,response:reply._id,rid:room.id});
    await employee.page.goto(settings.urls.chat+'/channel/'+room.name+'?msg='+sent._id);
    await employee.page.waitForTimeout(2500);
    await employee.page.screenshot({path:path.join(root,'reports/search-chat-'+kind+'.png'),fullPage:true});
    await employee.page.reload();
    const after=await employee.api('chat.getMessage?msgId='+reply._id);
    assert(after.message._id===reply._id,kind+'_reply_persisted');
  }
  const other=await actor(credentials.groupB);
  for(const entry of results){const value=await other.api('chat.getMessage?msgId='+entry.response);assert(value.message._id===entry.response,entry.kind+'_other_user_sees_reply');}
  // Unapproved collection stays private even though this user can read it in Outline.
  const sent=(await employee.api('chat.sendMessage',{message:{_id:'demo'+crypto.randomBytes(10).toString('hex'),rid:rooms.room.id,msg:'@report-bot 검색 시연 B 작업 메모 링크 줘'}})).message;
  let notice;
  for(let n=0;n<20;n++){await new Promise(r=>setTimeout(r,5000));notice=(await employee.api('chat.getThreadMessages?tmid='+sent._id+'&count=30')).messages.find(m=>m.u?._id===rooms.bot);if(notice)break;}
  assert(notice?.msg==='검색 결과는 개인 대화방으로 안내했어요.','unapproved_scope_dm_notice_only');
  const dm=(await employee.api('im.create',{username:'report-bot'})).room;
  const direct=(await employee.api('im.history?roomId='+(dm._id||dm.rid)+'&count=30')).messages;
  assert(direct.some(m=>m.u?._id===rooms.bot&&m.msg.includes(fixture.other.url.split('/').pop())),'private_result_delivered');
  const plain=(await employee.api('chat.sendMessage',{message:{_id:'demo'+crypto.randomBytes(10).toString('hex'),rid:rooms.room.id,msg:'검색 시연 A 설계 문서 링크 줘 (멘션 없음 검증)'}})).message;
  await new Promise(r=>setTimeout(r,4000));
  assert(!(await employee.api('chat.getThreadMessages?tmid='+plain._id+'&count=30')).messages.some(m=>m.u?._id===rooms.bot),'no_response_without_mention');
  fs.writeFileSync(path.join(root,'reports/search-chat-results.json'),JSON.stringify({at:new Date().toISOString(),checks,results},null,2));
}finally{await browser.close();}
