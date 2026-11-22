"""Server-to-server user attestation; the browser never receives the shared key."""
import base64,hashlib,hmac,json,os,time
from fastapi import HTTPException
from . import auth,store

def key():return hmac.digest(os.environ['AGENT_TOKEN'].encode(),b'workhub-search-identity-v1','sha256')
def encode(raw):return base64.urlsafe_b64encode(raw).decode().rstrip('=')
def issue(user,user_id=None):
    payload=encode(json.dumps({'sub':user['sub'],'user_id':user_id or 'workhub:'+user['sub'],'exp':int(time.time())+1800},separators=(',',':')).encode())
    return payload+'.'+encode(hmac.digest(key(),payload.encode(),'sha256'))
def decode(token):
    try:
        body,signature=token.split('.')
        if not hmac.compare_digest(signature,encode(hmac.digest(key(),body.encode(),'sha256'))):raise ValueError()
        data=json.loads(base64.urlsafe_b64decode(body+'='*(-len(body)%4)))
        if data['exp']<time.time() or data['exp']>time.time()+1805 or not data['sub'] or not data['user_id']:raise ValueError()
        return data
    except Exception:raise HTTPException(401,'검색 사용자 인증이 만료되었거나 올바르지 않습니다.')

def webui_user(email,subject,user_id):
    """Subject comes from WebUI's server-side OIDC binding, never an email lookup."""
    if not subject or not user_id:raise HTTPException(401,'문서 비서에 Authentik으로 로그인하세요.')
    user=auth.for_subject(subject)
    if user['email']!=email.lower():raise HTTPException(403,'문서 비서와 Authentik 계정 연결이 일치하지 않습니다.')
    # Pin the first verified binding so changing a WebUI account cannot inherit
    # another subject's saved document jobs through email-based account merging.
    with store.db() as c:
        key='webui-identity:'+user_id
        c.execute('INSERT OR IGNORE INTO kv(k,v) VALUES(?,?)',(key,store.dump({'sub':subject})))
        binding=json.loads(c.execute('SELECT v FROM kv WHERE k=?',(key,)).fetchone()[0])
        if binding['sub']!=subject:raise HTTPException(403,'문서 비서 계정의 SSO 연결 변경은 관리자 확인이 필요합니다.')
    return user
