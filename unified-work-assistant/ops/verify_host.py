import json
import time
import urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def request(url,body=None):
    data=json.dumps(body).encode() if body is not None else None
    req=urllib.request.Request(url,data=data,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=30) as res:
        return res.status,res.read()
checks={}
for name,url in [('outline','http://127.0.0.1:8090'),('webui','http://127.0.0.1:3001'),
                 ('document-agent','http://127.0.0.1:3002/health'),('authentik','http://127.0.0.1:9000/-/health/live/'),
                 ('rocketchat','http://127.0.0.1:3000/api/info')]:
    status,body=request(url);checks[name]={'http_status':status}
credentials=json.loads((ROOT/'src/report-agent/rocketchat/.local/credentials.json').read_text())
admin=credentials['admin']
status,raw=request('http://127.0.0.1:3000/api/v1/login',{'user':admin['username'],'password':admin['password']})
login=json.loads(raw)
assert login['status']=='success'
checks['rocketchat_admin_login']=True
# Do not create another plaintext password file. Reuse the setup credential store.
(ROOT/'reports/http-verification.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
print(json.dumps(checks))
