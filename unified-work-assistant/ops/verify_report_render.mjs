// Read-only verification using the installed Rocket.Chat parser and React renderer.
// Mounts a browser-local preview; never sends or changes a chat message.
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {Session,settings,root} from './sso_test_client.mjs';
const fixtures=JSON.parse(fs.readFileSync(path.join(root,'reports/report-render-fixtures.json'),'utf8').replace(/^\uFEFF/,''));
const session=new Session();await session.portal();
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE);
const browser=await chromium.launch({headless:true,channel:'msedge'});
try {
  const context=await browser.newContext({viewport:{width:1200,height:1000}});
  await context.addCookies([...session.jar].filter(([name])=>name.startsWith('authentik')).map(([name,value])=>({name,value,domain:new URL(settings.urls.auth).hostname,path:'/',httpOnly:true,sameSite:'Lax'})));
  const page=await context.newPage();
  await page.goto(settings.urls.chat);await page.getByRole('button',{name:/Authentik/}).click();
  await page.waitForFunction(()=>localStorage.getItem('Meteor.loginToken'),{timeout:60000});
  await page.goto(settings.urls.chat+'/direct/report-bot');
  await page.locator('textarea').first().waitFor({timeout:45000});
  await page.waitForFunction(()=>{
    try{return typeof require('@rocket.chat/message-parser').parse==='function'&&!!require('@rocket.chat/gazzodown').Markup;}catch{return false;}
  },{timeout:45000});
  const parsed=await page.evaluate(fixtures=>{
    const React=require('react');const {createRoot}=require('react-dom/client');
    const {parse}=require('@rocket.chat/message-parser');
    const {Markup,MarkupInteractionContext}=require('@rocket.chat/gazzodown');
    const {MessageBody,MessageContainer}=require('@rocket.chat/fuselage');
    const roots=Object.fromEntries(Object.entries(fixtures).map(([key,text])=>[key,parse(text)]));
    if(roots.broken[0].value[1]?.type!=='LINK')throw Error('Original bug was not reproduced');
    for(const key of ['single','multiple']){
      if(roots[key][0].value[0].type!=='BOLD')throw Error('Heading is not bold');
      const list=roots[key].find(n=>n.type==='UNORDERED_LIST');
      if(list?.value.length!==(key==='single'?1:2))throw Error('Incorrect task list');
      for(const item of list.value){
        const link=item.value[0];
        if(link.type!=='LINK'||link.value.label.some(n=>n.value.includes('업무목록')||n.value.includes('\n')))throw Error('Heading swallowed by link');
      }
    }
    const host=document.createElement('div');host.id='report-render-verification';
    Object.assign(host.style,{position:'fixed',inset:'0',zIndex:'2147483647',background:'#f4f5f7',overflow:'auto',padding:'24px',color:'#1f2937'});
    document.body.append(host);
    const card=(key,label)=>React.createElement('section',{id:'preview-'+key,style:{background:'white',padding:'22px',border:'1px solid #ddd',borderRadius:'8px',minWidth:0}},
      React.createElement('h2',{style:{fontSize:'16px',marginBottom:'18px'}},label),
      React.createElement(MarkupInteractionContext.Provider,{value:{}},
        React.createElement(MessageContainer,null,React.createElement(MessageBody,null,React.createElement(Markup,{tokens:roots[key]})))));
    createRoot(host).render(React.createElement(React.Fragment,null,
      React.createElement('p',{style:{marginBottom:'18px'}},'Rocket.Chat 실제 메시지 렌더러 · 브라우저 내부 검증 (전송하지 않음)'),
      React.createElement('div',{style:{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'20px'}},card('single','업무 1개 보고'),card('multiple','여러 업무 보고'))));
    return {originalBugReproduced:true,singleHeadingAndLink:true,multipleHeadingAndLinks:true};
  },fixtures);
  await page.locator('#preview-multiple a').nth(1).waitFor();
  const verification=await page.locator('#report-render-verification').evaluate(el=>{
    const cards=[...el.querySelectorAll('section')];
    return cards.map(card=>({text:card.innerText,links:[...card.querySelectorAll('a')].map(a=>({text:a.textContent,url:a.getAttribute('href')}))}));
  });
  for(const card of verification){
    if(card.text.includes('**')||card.links.some(a=>a.text.includes('업무목록'))||!card.text.includes('────────────────────────'))throw Error('Broken rendered output');
  }
  if(verification[0].links[0].text!=='도구 선정'||verification[1].links[1].text!=='자료 정리')throw Error('Wrong rendered link label');
  await page.screenshot({path:path.join(root,'reports/report-render-fixed.png'),fullPage:true});
  fs.writeFileSync(path.join(root,'reports/report-render-browser-results.json'),JSON.stringify({at:new Date().toISOString(),...parsed,verification,messagesSent:0},null,2));
  console.log('PASS: original bug reproduced; actual Rocket.Chat parser + renderer verified for one and multiple task links, bold headings and dividers. No messages sent.');
}finally{await browser.close()}
