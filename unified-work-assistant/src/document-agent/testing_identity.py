"""Signed user fixture for offline non-ACL integration regressions."""
import base64,hashlib,hmac,json,os,time
from unittest.mock import AsyncMock,patch
import user_acl

def headers(user_id):
    body=base64.urlsafe_b64encode(json.dumps({'sub':'unit-user','user_id':user_id,'exp':time.time()+1800}).encode()).decode().rstrip('=')
    key=hmac.digest(os.environ['AGENT_TOKEN'].encode(),b'workhub-search-identity-v1','sha256')
    sig=base64.urlsafe_b64encode(hmac.digest(key,body.encode(),'sha256')).decode().rstrip('=')
    return {'Authorization':'Bearer '+os.environ['AGENT_TOKEN'],'X-Workhub-Identity':body+'.'+sig}

def policy():
    async def check(documents=(),collections=(),write=False):
        return {'collections':['c','c1','c2'],'documents':list(documents)}
    return patch.object(user_acl,'check',side_effect=check)
