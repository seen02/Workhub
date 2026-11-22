// Code-drawn circle, matching the 64px/24px EmojiOne circle presentation.
// Rocket.Chat's bundled EmojiOne does not include the Unicode orange circle.
// API: https://developer.rocket.chat/apidocs/create-an-emoji
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import {root,settings} from './sso_test_client.mjs';

const name='workhub_orange_circle', size=64;
const crc=buffer=>{
 let c=0xffffffff;
 for(const v of buffer){c^=v;for(let j=0;j<8;j++)c=(c>>>1)^((c&1)?0xedb88320:0)}
 return (c^0xffffffff)>>>0;
};
const chunk=(type,data)=>{
 const label=Buffer.from(type), length=Buffer.alloc(4), checksum=Buffer.alloc(4);
 length.writeUInt32BE(data.length);checksum.writeUInt32BE(crc(Buffer.concat([label,data])));
 return Buffer.concat([length,label,data,checksum]);
};
const raw=Buffer.alloc(size*(size*4+1));
for(let y=0;y<size;y++)for(let x=0;x<size;x++){
 const t=y/(size-1), k=y*(size*4+1)+1+x*4;
 let coverage=0;
 for(let sy=0;sy<4;sy++)for(let sx=0;sx<4;sx++)
  if(Math.hypot(x+(sx+.5)/4-32,y+(sy+.5)/4-32)<30)coverage++;
 raw[k]=Math.round(255*(1-t)+237*t);raw[k+1]=Math.round(177*(1-t)+126*t);
 raw[k+2]=Math.round(71*(1-t));raw[k+3]=Math.round(255*coverage/16);
}
const ihdr=Buffer.alloc(13);ihdr.writeUInt32BE(size);ihdr.writeUInt32BE(size,4);ihdr[8]=8;ihdr[9]=6;
const png=Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',ihdr),chunk('IDAT',zlib.deflateSync(raw)),chunk('IEND',Buffer.alloc(0))]);
fs.writeFileSync(path.join(root,'src/workhub/static/workhub-orange-circle.png'),png);
const credentials=JSON.parse(fs.readFileSync(path.join(root,'src/report-agent/rocketchat/.local/credentials.json')));
const base=settings.urls.chat+'/api/v1/';
const login=await fetch(base+'login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user:credentials.admin.username,password:credentials.admin.password})});
if(!login.ok)throw Error('Emoji setup login failed');
const {data}=await login.json();
const headers={'X-User-Id':data.userId,'X-Auth-Token':data.authToken};
try{
 const listing=await fetch(base+'emoji-custom.all',{headers});
 if(!listing.ok)throw Error('Cannot list custom emoji');
 const body=await listing.json();
 const emojis=body.emojis?.update ?? body.emojis;
 if(!Array.isArray(emojis))throw Error('Unexpected emoji list response');
 const existing=emojis.find(e=>e.name===name);
 if(!existing){
  const form=new FormData();form.set('name',name);form.set('emoji',new Blob([png],{type:'image/png'}),name+'.png');
  const result=await fetch(base+'emoji-custom.create',{method:'POST',headers,body:form});
  if(!result.ok||!(await result.json()).success)throw Error('Emoji creation failed: '+result.status);
 }
 console.log('Orange circle emoji ready: '+name);
}finally{await fetch(base+'logout',{method:'POST',headers})}
