import base64, hashlib, json, os, secrets, time, threading, functools
from urllib.parse import urlencode
import httpx, jwt
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from . import store

BASE=os.environ['PUBLIC_URL'].rstrip('/')
ISSUER=os.environ['OIDC_ISSUER'].rstrip('/')+'/'
CLIENT=os.environ['OIDC_CLIENT_ID']
SECRET=os.environ['OIDC_CLIENT_SECRET']
COOKIE='workhub_session'
discovery={}
SESSION_LOCK=threading.RLock()

def serialized(fn):
    @functools.wraps(fn)
    def wrapped(*args,**kwargs):
        with SESSION_LOCK:return fn(*args,**kwargs)
    return wrapped

def metadata():
    if not discovery:
        r=httpx.get(ISSUER+'.well-known/openid-configuration',timeout=15);r.raise_for_status();discovery.update(r.json())
        if discovery['issuer']!=ISSUER:raise RuntimeError('Unexpected issuer')
    return discovery

def login():
    state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48);nonce=secrets.token_urlsafe(32)
    store.put('oauth:'+state,{'verifier':verifier,'nonce':nonce,'expires':time.time()+600})
    query={'response_type':'code','client_id':CLIENT,'redirect_uri':BASE+'/auth/callback',
           'scope':'openid email profile work_groups offline_access','state':state,'nonce':nonce,
           'code_challenge':base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='),'code_challenge_method':'S256'}
    out=RedirectResponse(metadata()['authorization_endpoint']+'?'+urlencode(query))
    out.set_cookie('workhub_oauth',state,max_age=600,httponly=True,samesite='lax',secure=BASE.startswith('https:'))
    return out

def allowed(info):
    from . import service_identity
    if isinstance(info, service_identity.ServiceIdentity):
        return service_identity.for_subject(info['sub'])
    if not info.get('sub') or not info.get('email') or info.get('email_verified') is not True:raise HTTPException(403,'확인된 Authentik 이메일이 필요합니다.')
    if 'work-assistant-users' not in info.get('groups',[]):raise HTTPException(403,'Authentik 업무 사용자 그룹 권한이 없습니다.')
    from .lifecycle import require_identity
    require_identity(info)
    return {**info,'admin':'work-assistant-admins' in info.get('groups',[])}

def callback(request:Request,code:str,state:str):
    pending=store.get('oauth:'+state)
    with store.db() as c:c.execute('DELETE FROM kv WHERE k=?',('oauth:'+state,))
    if not pending or request.cookies.get('workhub_oauth')!=state or pending['expires']<time.time():raise HTTPException(400,'로그인 요청이 만료되었습니다.')
    r=httpx.post(metadata()['token_endpoint'],data={'grant_type':'authorization_code','code':code,'redirect_uri':BASE+'/auth/callback',
        'client_id':CLIENT,'client_secret':SECRET,'code_verifier':pending['verifier']},timeout=20)
    r.raise_for_status();tokens=r.json()
    key=jwt.PyJWKClient(metadata()['jwks_uri']).get_signing_key_from_jwt(tokens['id_token'])
    claims=jwt.decode(tokens['id_token'],key.key,algorithms=['RS256'],issuer=ISSUER,audience=CLIENT,options={'require':['exp','iat','sub','nonce']})
    if claims['nonce']!=pending['nonce']:raise HTTPException(400,'OIDC nonce 불일치')
    info=allowed(claims)
    sid=secrets.token_urlsafe(40)
    body={'info':info,'tokens':tokens,'checked':0,'csrf':secrets.token_urlsafe(32),'token_expires':time.time()+tokens.get('expires_in',300)}
    with store.db() as c:
        c.execute('INSERT INTO sessions VALUES(?,?,?)',(sid,store.dump(body),time.time()+28800))
    out=RedirectResponse('/');out.delete_cookie('workhub_oauth');out.set_cookie(COOKIE,sid,httponly=True,samesite='lax',max_age=28800,secure=BASE.startswith('https:'))
    return out

def refresh(body):
    # Check centrally on EVERY protected action: group removal/deactivation takes effect without app logout.
    tokens=body['tokens']
    if time.time()>body['token_expires']-20 and tokens.get('refresh_token'):
        old_token=tokens['access_token']
        r=httpx.post(metadata()['token_endpoint'],data={'grant_type':'refresh_token','refresh_token':tokens['refresh_token'],'client_id':CLIENT,'client_secret':SECRET},timeout=15)
        if not r.is_success:raise HTTPException(401,'Authentik에 다시 로그인하세요.')
        tokens.update(r.json());body['token_expires']=time.time()+tokens.get('expires_in',300)
        # Portal and bot share this token family; rotate all copies atomically.
        with store.db() as c:
            for table,key in [('sessions','id'),('identities','sub')]:
                for row in c.execute('SELECT '+key+',body FROM '+table).fetchall():
                    other=json.loads(row['body'])
                    if other['tokens']['access_token']==old_token:
                        other.update(tokens=tokens,token_expires=body['token_expires'])
                        c.execute('UPDATE '+table+' SET body=? WHERE '+key+'=?',(store.dump(other),row[key]))
    r=httpx.get(metadata()['userinfo_endpoint'],headers={'Authorization':'Bearer '+tokens['access_token']},timeout=15)
    if not r.is_success:raise HTTPException(401,'Authentik 로그인이 만료되었습니다.')
    raw_info=r.json()
    if raw_info.get('sub')!=body['info']['sub']:raise HTTPException(401,'SSO 사용자 불일치')
    from .directory import remember
    remember(raw_info)
    info=allowed(raw_info)
    if info['sub']!=body['info']['sub']:raise HTTPException(401,'SSO 사용자 불일치')
    body['info']=info;body['checked']=time.time()
    return body

@serialized
def current(request:Request):
    sid=request.cookies.get(COOKIE,'')
    with store.db() as c:r=c.execute('SELECT * FROM sessions WHERE id=?',(sid,)).fetchone()
    if not r or r['expires']<time.time():raise HTTPException(401,'Authentik 로그인이 필요합니다.')
    try:body=refresh(json.loads(r['body']))
    except httpx.HTTPError:raise HTTPException(503,'Authentik 권한 확인에 실패했습니다. 잠시 후 다시 시도하세요.')
    if request.method not in ('GET','HEAD'):
        if request.headers.get('origin')!=BASE or request.headers.get('x-csrf-token')!=body['csrf']:raise HTTPException(403,'요청 검증 실패')
    try:
        from .provision import reconcile
        # Background board reads must not propagate display-name changes.
        reconcile(body['info'],sync_name=False)
    except Exception as ex:
        __import__('logging').getLogger('workhub').warning('role_provision_pending type=%s',type(ex).__name__)
    with store.db() as c:
        c.execute('UPDATE sessions SET body=? WHERE id=?',(store.dump(body),sid))
        c.execute('INSERT OR REPLACE INTO identities VALUES(?,?,?)',(body['info']['sub'],body['info']['email'],store.dump(body)))
    return {**body['info'],'csrf':body['csrf']}

def for_subject(sub):
    """For authenticated service actors only; a subject alone is not login proof."""
    from .service_identity import for_subject
    return for_subject(sub)

def admin(user):
    if not user.get('admin'):raise HTTPException(403,'관리자 그룹 권한이 필요합니다.')
