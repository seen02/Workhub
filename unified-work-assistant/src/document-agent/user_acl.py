"""User-scoped reads for every document-assistant entry point and background job."""
import base64,contextvars,hashlib,hmac,json,os,time
from contextlib import contextmanager
import httpx
from fastapi import HTTPException

actor=contextvars.ContextVar('document_actor',default=None)

def verify(token):
    try:
        body,sig=token.split('.')
        key=hmac.digest(os.environ['AGENT_TOKEN'].encode(),b'workhub-search-identity-v1','sha256')
        expected=base64.urlsafe_b64encode(hmac.digest(key,body.encode(),'sha256')).decode().rstrip('=')
        if not hmac.compare_digest(sig,expected):raise ValueError()
        value=json.loads(base64.urlsafe_b64decode(body+'='*(-len(body)%4)))
        if not value['sub'] or not value['user_id'] or value['exp']<time.time() or value['exp']>time.time()+1805:raise ValueError()
        return value
    except Exception:raise HTTPException(401,'유효한 사용자 검색 인증이 필요합니다.')

async def check(documents=(),collections=(),write=False):
    current=actor.get()
    if current is None:return None  # Internal indexer only; HTTP middleware requires an actor for user routes.
    verify(current['token'])
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r=await c.post(os.getenv('WORKHUB_INTERNAL_URL','http://workhub:8000')+'/internal/search/access',
                headers={'X-Service-Token':os.environ['AGENT_TOKEN']},
                json={'token':current['token'],'documents':list(documents),'collections':list(collections),'write':write})
        if not r.is_success:raise HTTPException(r.status_code if r.status_code in (401,403) else 503,'사용자의 Outline 접근 권한을 확인할 수 없습니다. Workhub 로그인과 프로젝트 권한을 확인하세요.')
        return r.json()
    except httpx.HTTPError:raise HTTPException(503,'권한 확인 서버에 연결할 수 없어 요청을 중단했습니다.')

async def require_documents(ids):
    if actor.get() is None:return
    ids=list(dict.fromkeys(ids))
    for start in range(0,len(ids),100):
        batch=ids[start:start+100];allowed=await check(documents=batch)
        if set(batch)-set(allowed['documents']):raise HTTPException(403,'문서 접근 권한이 없거나 검색 도중 권한이 변경되었습니다.')
    actor.get()['documents'].update(ids)

async def verify_used():
    current=actor.get()
    if current is not None:await require_documents(current['documents'])

def scope_suffix():
    current=actor.get()
    if current is None:return ''
    return ':'+hashlib.sha256(json.dumps([current['identity']['sub'],sorted(current['collections'])]).encode()).hexdigest()[:24]

def require_user(user_id):
    current=actor.get()
    if current is None or current['identity']['user_id']!=user_id:
        raise HTTPException(403,'요청 사용자와 인증한 사용자가 일치하지 않습니다.')

@contextmanager
def index_inventory():
    """Read service-wide index metadata, then intersect scope before any retrieval."""
    token=actor.set(None)
    try:yield
    finally:actor.reset(token)

class FilteredList(list):
    def __init__(self,rows,raw_count):super().__init__(rows);self.raw_count=raw_count

async def before(method,payload):
    if actor.get() is None:return
    if payload.get('collectionId'):await check(collections=[payload['collectionId']])
    if method in ('collections.info','collections.documents') and payload.get('id'):await check(collections=[payload['id']])
    if method.startswith('documents.') and method not in ('documents.list','documents.search','documents.info','documents.create'):
        if payload.get('id'):await require_documents([payload['id']])
    if method in ('documents.create','documents.update','documents.delete','documents.move'):
        await check(write=True)
        if payload.get('parentDocumentId'):await require_documents([payload['parentDocumentId']])

async def after(method,data):
    current=actor.get()
    if current is None:return data
    if method=='collections.list':
        allowed=(await check())['collections'];return FilteredList([c for c in data if c['id'] in allowed],len(data))
    if method in ('documents.list','documents.search','templates.list'):
        docs=[row.get('document',row) for row in data];allowed=set()
        for start in range(0,len(docs),100):allowed.update((await check(documents=[d['id'] for d in docs[start:start+100]]))['documents'])
        current['documents'].update(allowed)
        return FilteredList([row for row in data if row.get('document',row)['id'] in allowed],len(data))
    if method in ('documents.info','templates.info'):
        await require_documents([data['id']])
    return data
