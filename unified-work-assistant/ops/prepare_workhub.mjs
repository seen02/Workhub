import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
const root=path.resolve(import.meta.dirname,'..');
const configPath=path.join(root,'.local/compose.json');
const c=JSON.parse(fs.readFileSync(configPath));
const sso=JSON.parse(fs.readFileSync(path.join(root,'.local/integration.json')));
const creds=JSON.parse(fs.readFileSync(path.join(root,'src/report-agent/rocketchat/.local/credentials.json')));
const r=await fetch('http://127.0.0.1:3000/api/v1/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user:creds.admin.username,password:creds.admin.password})});
const login=(await r.json()).data;if(!login)throw Error('Administrator login failed');
const headers={'Content-Type':'application/json','X-User-Id':login.userId,'X-Auth-Token':login.authToken,'X-2fa-Method':'password','X-2fa-Code':crypto.createHash('sha256').update(creds.admin.password).digest('hex')};
const existing=await fetch('http://127.0.0.1:3000/api/v1/users.info?username='+creds.bot.username,{headers});
if(!existing.ok){
 const response=await fetch('http://127.0.0.1:3000/api/v1/users.create',{method:'POST',headers,body:JSON.stringify({username:creds.bot.username,password:creds.bot.password,name:'통합 업무 비서',email:'report-bot@local.invalid',roles:['bot'],verified:true,joinDefaultChannels:false,requirePasswordChange:false,sendWelcomeEmail:false})});
 if(!response.ok)throw Error('Bot provisioning HTTP '+response.status);
}
const d=c.services['document-agent'].environment;
d.RAG_COLLECTION_NAMES=[...new Set((d.RAG_COLLECTION_NAMES||'').split(',').concat('통합 업무'))].filter(Boolean).join(',');
c.services.workhub={build:{context:root,dockerfile:'src/workhub/Dockerfile'},image:'unified-work-assistant/workhub:1.0',restart:'unless-stopped',
 ports:[{host_ip:'127.0.0.1',target:8000,published:'8004',protocol:'tcp'}],networks:{'outline-ai-net':null,'chat-net':null,'chat-data':null},
 volumes:[{type:'bind',source:path.join(root,'runtime/workhub'),target:'/app/data'}],
 environment:{PUBLIC_URL:sso.urls.portal,OIDC_ISSUER:sso.urls.auth+'/application/o/work-assistant/',OIDC_CLIENT_ID:sso.clients['work-assistant'].id,OIDC_CLIENT_SECRET:sso.clients['work-assistant'].secret,
 OUTLINE_URL:d.OUTLINE_URL.replace(/\/api\/?$/,''),OUTLINE_PUBLIC_URL:sso.urls.outline,OUTLINE_API_KEY:d.OUTLINE_API_KEY,
 CHAT_PUBLIC_URL:sso.urls.chat,WEBUI_PUBLIC_URL:sso.urls.webui,ROCKETCHAT_INTERNAL_URL:'http://rocketchat:3000',BOT_USERNAME:creds.bot.username,BOT_PASSWORD:creds.bot.password,
 MONGO_URL:'mongodb://mongodb:27017/rocketchat?replicaSet=rs0',ROCKET_ADMIN_USERNAME:creds.admin.username,ROCKET_ADMIN_PASSWORD:creds.admin.password,DOCUMENT_AGENT_URL:'http://document-agent:8000',AGENT_TOKEN:d.AGENT_TOKEN,
 OLLAMA_BASE_URL:d.OLLAMA_URL,LOCAL_LLM_MODEL:d.OLLAMA_MODEL,LOCAL_LLM_TIMEOUT_SECONDS:'180',LOCAL_LLM_RETRIES:'1',LOCAL_LLM_FALLBACK_TO_MOCK:'false'},
 healthcheck:{test:['CMD','python','-c',"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"],interval:'30s',timeout:'5s',retries:3},mem_limit:'512m'};
fs.mkdirSync(path.join(root,'runtime/workhub'),{recursive:true});
fs.writeFileSync(configPath,JSON.stringify(c,null,2));
console.log(JSON.stringify({service:'workhub',url:sso.urls.portal,model:d.OLLAMA_MODEL,bot:creds.bot.username,ragCollections:d.RAG_COLLECTION_NAMES}));
