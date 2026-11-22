import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {root,settings} from './sso_test_client.mjs';

const rc=JSON.parse(fs.readFileSync(path.join(root,'src/report-agent/rocketchat/.local/credentials.json')));
const base=settings.urls.chat+'/api/v1/';
const login=await fetch(base+'login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user:rc.admin.username,password:rc.admin.password})});
if(!login.ok)throw Error('Rocket administrator login failed');
const {data}=await login.json();
const headers={'Content-Type':'application/json','X-User-Id':data.userId,'X-Auth-Token':data.authToken,'X-2fa-Method':'password','X-2fa-Code':crypto.createHash('sha256').update(rc.admin.password).digest('hex')};
try{
 const endpoint=base+'settings/theme-custom-css';
 const current=await fetch(endpoint,{headers});
 if(!current.ok)throw Error('Read custom CSS HTTP '+current.status);
 const existing=(await current.json()).value;
 if(typeof existing!=='string')throw Error('Unexpected custom CSS response');
 const start='/* WORKHUB_BUTTONS_START */',end='/* WORKHUB_BUTTONS_END */';
 const css=fs.readFileSync(path.join(root,'ops/workhub-chat-buttons.css'),'utf8');
 const block=start+'\n'+css.trim()+'\n'+end;
 let value;
 if(existing.includes(start)){
  const a=existing.indexOf(start),b=existing.indexOf(end,a);
  if(b<0)throw Error('Incomplete Workhub CSS marker');
  value=existing.slice(0,a)+block+existing.slice(b+end.length);
 }else value=existing+(existing?'\n\n':'')+block;
 if(existing!==value){
  fs.mkdirSync(path.join(root,'.local'),{recursive:true});
  fs.writeFileSync(path.join(root,'.local/chat-css-before-'+Date.now()+'.txt'),existing);
  const update=await fetch(endpoint,{method:'POST',headers,body:JSON.stringify({value})});
  if(!update.ok)throw Error('Update custom CSS HTTP '+update.status);
 }
 const check=await fetch(endpoint,{headers});
 if(!check.ok||(await check.json()).value!==value)throw Error('Custom CSS verification failed');
 console.log('Workhub button styles applied and verified; other custom CSS preserved.');
}finally{
 await fetch(base+'logout',{method:'POST',headers,body:'{}'});
}
