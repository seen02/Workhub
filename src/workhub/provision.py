"""Apply the authenticated principal's group role using Rocket.Chat's public administration API.

The community edition does not run its enterprise OAuth role-sync hook. We keep a small,
explicit provisioner rather than changing vendor code or trusting an email/display name.
"""
import os, threading, time
import httpx
from pymongo import MongoClient
LOCK=threading.RLock()
mongo=None
headers={}
expires=0

def get_mongo():
    global mongo
    if mongo is None:mongo=MongoClient(os.environ['MONGO_URL'],serverSelectionTimeoutMS=3000)
    return mongo

def call(method,body):
    global headers,expires
    with LOCK:
        base=os.environ['ROCKETCHAT_INTERNAL_URL']+'/api/v1/'
        for attempt in range(2):
            if time.time()>expires:
                r=httpx.post(base+'login',json={'user':os.environ['ROCKET_ADMIN_USERNAME'],'password':os.environ['ROCKET_ADMIN_PASSWORD']},timeout=15)
                r.raise_for_status();d=r.json()['data'];headers={'X-User-Id':d['userId'],'X-Auth-Token':d['authToken']};expires=time.time()+600
            r=httpx.post(base+method,headers={**headers,'X-2fa-Method':'password','X-2fa-Code':__import__('hashlib').sha256(os.environ['ROCKET_ADMIN_PASSWORD'].encode()).hexdigest()},json=body,timeout=15)
            if r.status_code==401 and attempt==0:expires=0;continue
            r.raise_for_status()
            data=r.json()
            if data.get('success') is False:raise RuntimeError('Rocket.Chat operation failed')
            return data
def reconcile(info, *, sync_name=True):
    global mongo,headers,expires
    if not os.getenv('ROCKET_ADMIN_USERNAME'):return
    get_mongo()
    with LOCK:
        user=mongo.rocketchat.users.find_one({'services.authentik.id':info['sub']},{'_id':1,'roles':1,'name':1})
        if not user:return # First Rocket.Chat SSO login creates the account; next portal request reconciles it.
        roles=set(user.get('roles',[]));desired=(roles-{'admin'})|{'user'}
        if info.get('admin'):desired.add('admin')
        name=info.get('name') or info.get('preferred_username') or info['email']
        data={}
        if roles!=desired:data['roles']=sorted(desired)
        if sync_name and user.get('name')!=name:data['name']=name
        if data:call('users.update',{'userId':user['_id'],'data':data})
