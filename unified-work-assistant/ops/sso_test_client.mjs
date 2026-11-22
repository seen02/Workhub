import fs from 'node:fs';
import path from 'node:path';
export const root=path.resolve(import.meta.dirname,'..');
export const settings=JSON.parse(fs.readFileSync(path.join(root,'.local/integration.json')));
export const credentials=JSON.parse(fs.readFileSync(path.join(root,'../Outline/authentik/test-credentials.local.json')));
export class Session{
 constructor(){this.jar=new Map()}
 async fetch(url,options={}){
  const headers=new Headers(options.headers||{});
  if(this.jar.size)headers.set('Cookie',[...this.jar].map(([k,v])=>k+'='+v).join('; '));
  const r=await fetch(url,{...options,headers,redirect:'manual'});
  if(process.env.SSO_TRACE)console.log(options.method||'GET',new URL(url).pathname,r.status,r.headers.get('location')?new URL(r.headers.get('location'),url).pathname:'');
  for(const c of r.headers.getSetCookie()){const first=c.split(';')[0],i=first.indexOf('=');this.jar.set(first.slice(0,i),first.slice(i+1));}
  return r;
 }
 async flow(url,account){
  const u=new URL(url),slug=u.pathname.match(/\/if\/flow\/([^/]+)/)?.[1];
  const endpoint=settings.urls.auth+'/api/v3/flows/executor/'+slug+'/?query='+encodeURIComponent(u.search.slice(1));
  let first=await this.fetch(endpoint);
  for(let i=0;i<5&&first.headers.get('location');i++)first=await this.fetch(new URL(first.headers.get('location'),settings.urls.auth).href);
  let d=await first.json();
  for(let i=0;i<8;i++){
   if(d.component==='xak-flow-redirect')return new URL(d.to,settings.urls.auth).href;
   let body;
   if(d.component==='ak-stage-identification')body={uid_field:account.username};
   else if(d.component==='ak-stage-password')body={password:account.password};
   else if(d.component==='ak-stage-consent')body={consent:true};
   else throw Error('SSO stage '+d.component);
   let response=await this.fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
   for(let j=0;j<5&&response.headers.get('location');j++)response=await this.fetch(new URL(response.headers.get('location'),settings.urls.auth).href);
   d=await response.json();
  }throw Error('SSO flow loop');
 }
 async login(start,account=credentials.authentikAdmin){
  let url=start;
  for(let i=0;i<25;i++){
   if(new URL(url).pathname.startsWith('/if/flow/')){url=await this.flow(url,account);continue;}
   const r=await this.fetch(url);
   const location=r.headers.get('location');
   if(location){url=new URL(location,url).href;continue;}
   if(!r.ok)throw Error('SSO '+new URL(url).pathname+' HTTP '+r.status);
   return {url,status:r.status,response:r};
  }throw Error('Redirect loop');
 }
 async api(endpoint,body){
  const r=await this.fetch(settings.urls.portal+endpoint,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','Origin':settings.urls.portal,'X-CSRF-Token':this.csrf||''},body:body===undefined?undefined:JSON.stringify(body)});
  const d=await r.json();if(!r.ok)throw Error(endpoint+' HTTP '+r.status+' '+JSON.stringify(d));return d;
 }
 async portal(){
  for(let i=0;i<15;i++){try{const r=await fetch(settings.urls.portal+'/health');if(r.ok)break;}catch{}await new Promise(r=>setTimeout(r,1000));}
  await this.login(settings.urls.portal+'/auth/login');const me=await this.api('/api/me');this.csrf=me.csrf;return me;
 }
}
