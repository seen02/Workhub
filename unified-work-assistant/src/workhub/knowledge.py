"""Shared read-only search and durable per-user jobs; no report side effects."""
import hashlib, hmac, json, os, re, threading, time, uuid
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from fastapi import HTTPException
from . import auth, execution, outline, permissions, search, store

POOL=ThreadPoolExecutor(max_workers=2,thread_name_prefix='knowledge')
SLOTS=threading.BoundedSemaphore(12)
LOCK=threading.RLock()


def enabled():return os.getenv('OUTLINE_AI_SEARCH_ENABLED','false').lower()=='true'


def current_user(subject):
    return auth.for_subject(subject)


def live_access(user,documents=()):
    """Use Outline's own current ACL policy in one signed, read-only call."""
    from . import lifecycle, http_pool
    records=[r for r in lifecycle.records() if r['sub']==user['sub'] and r.get('outline_id')]
    if len(records)!=1:raise HTTPException(403,'Outline 계정 연결을 확인하세요.')
    oid=records[0]['outline_id'];ids=list(documents);stamp=str(int(time.time()))
    signature=hmac.new(os.environ['OUTLINE_WORKHUB_BRIDGE_SECRET'].encode(),('\n'.join([oid,json.dumps(ids,separators=(',',':')),stamp])).encode(),hashlib.sha256).hexdigest()
    response=http_pool.request('outline','POST',outline.URL+'/api/workhub.searchAccess',metric='knowledge_access',
        headers={**outline.HEADERS,'X-Workhub-Access-Time':stamp,'X-Workhub-Access-Signature':signature},json={'userId':oid,'documentIds':ids},timeout=40)
    if not response.is_success:raise HTTPException(503 if response.status_code>=500 or response.status_code==429 else 403,'Outline 검색 권한을 확인하지 못했어요.')
    return response.json()['data']


class ReadAccess:
    def __init__(self,user):self.ids=set(live_access(user)['collections'])
    def readable(self,cid):return cid in self.ids
    def require(self,cid):
        if cid not in self.ids:raise HTTPException(403,'이 컬렉션을 읽을 권한이 없어요.')
        return {'id':cid}


def access(user):return ReadAccess(user) if enabled() else permissions.Access(user)


def targets():
    """One policy source by immutable collection ID; import legacy names once."""
    saved=store.get('knowledge:inclusions')
    if saved is None:
        legacy=search.agent('/rag/knowledge/catalog').get('legacy',[])
        with LOCK:
            saved=store.get('knowledge:inclusions')
            if saved is None:saved={p['id']:True for p in legacy};store.put('knowledge:inclusions',saved)
    rows=outline.all_items('collections.list')
    projects={p['id'] for p in outline.projects()}
    return [{**c,'project':c['id'] in projects,'knowledge':bool(saved.get(c['id'])),
             'included':c['id'] in projects or bool(saved.get(c['id']))} for c in rows if not c.get('deletedAt')]


def catalog(user):
    auth.allowed(user)
    acl=access(user);rows=[c for c in targets() if acl.readable(c['id'])]
    state=search.agent('/rag/status');states={s['collection_id']:s for s in state.get('collections',[])}
    items=[]
    for c in rows:
        s=states.get(c['id']);r=(s or {}).get('result',{})
        status='not_included' if not c['included'] else 'preparing' if not s else 'partial' if r.get('failed') or not r.get('inventory_complete') or state.get('poll_error') else 'syncing' if state.get('syncing') else 'ready'
        items.append({k:c[k] for k in ('id','name','project','knowledge','included')}|{'state':status,'synced_at':(s or {}).get('synced_at'),
            'documents':r.get('inventory_count',0),'failed':len(r.get('failed',[]))})
    extra={}
    if user.get('admin'):
        rooms=share_rooms(user)
        rules=store.get('knowledge:channel-policy',{})
        extra={'rooms':rooms,'sharing':{r['id']:rules.get(r['id'],[]) for r in rooms}}
    return {'manage':bool(user.get('admin')),'collections':items,**extra}


def share_rooms(user):
    from . import bot, report_transport
    if bot.mongo is None:return []
    person=bot.mongo.rocketchat.users.find_one({'$or':[{'services.authentik.id':user['sub']},{'services.Authentik.id':user['sub']}]})
    if not person:return []
    rooms=[]
    for sub in bot.mongo.rocketchat.rocketchat_subscription.find({'u._id':person['_id'],'t':{'$in':['c','p']}}):
        room=bot.mongo.rocketchat.rocketchat_room.find_one({'_id':sub['rid']})
        if room and report_transport.permitted(bot,person['_id'],room) and report_transport.permitted(bot,bot.bot_id,room):
            rooms.append({'id':room['_id'],'name':room.get('fname') or room.get('name'),'kind':'토론방' if room.get('prid') else '채널'})
    return rooms


def sharing(user,rid,cids):
    auth.admin(user)
    if rid not in {r['id'] for r in share_rooms(user)}:raise HTTPException(403,'본인과 봇이 참여한 채널만 설정할 수 있어요.')
    acl=access(user);included={c['id'] for c in targets() if c['included']}
    for cid in cids:
        acl.require(cid)
        if cid not in included:raise HTTPException(422,'먼저 AI 검색에 포함해 주세요.')
    with LOCK:
        policies=store.get('knowledge:channel-policy',{});policies[rid]=list(dict.fromkeys(cids));store.put('knowledge:channel-policy',policies)
    return {'sharing':policies[rid]}


def inclusion(user,cid,value):
    auth.admin(user);access(user).require(cid)
    targets()
    with LOCK:
        saved=store.get('knowledge:inclusions',{});saved[cid]=bool(value);store.put('knowledge:inclusions',saved)
    search.dirty.set();search.sync_registry()
    return catalog(user)


def normalize(value):return re.sub(r'\s+','',value).casefold()


def resolve(user,query,cid=''):
    acl=access(user)
    available=[p for p in targets() if acl.readable(p['id'])]
    if cid:
        acl.require(cid);selected=[p for p in available if p['id']==cid]
    else:
        # Longest full collection name wins over a substring, no fuzzy project guesses.
        named=[p for p in available if normalize(p['name']) in normalize(query)]
        if named:
            selected=[p for p in named if not any(p['id']!=q['id'] and normalize(p['name'])!=normalize(q['name']) and normalize(p['name']) in normalize(q['name']) for q in named)]
            names={normalize(p['name']) for p in selected}
            if len(names)!=len(selected):
                return {'status':'choose','answer':'어느 컬렉션에서 찾을까요?','choices':[{'id':p['id'],'name':p['name']} for p in selected]}
        else:
            if re.search(r'프로젝트\s+[A-Za-z0-9_-]+',query):
                return {'status':'no_results','answer':'지정한 프로젝트를 찾지 못했어요. 컬렉션 이름을 확인해 주세요.','documents':[]}
            selected=[p for p in available if p['included']]
    if not selected or any(not p['included'] for p in selected):return {'status':'not_included','answer':'선택한 범위가 AI 검색 대상에 포함되지 않았어요.','documents':[]}
    # Remove collection names from retrieval text, retain original for answer semantics.
    clean=query
    for p in selected:
        clean=re.sub(re.escape(p['name']), ' ',clean,flags=re.I)
    clean=re.sub(r'^\s*(?:의|에서|에\s*있는)\s*','',clean).strip() or query
    return {'collections':[p['id'] for p in selected],'query':clean}


def execute(user,body):
    with execution.request('knowledge_search',user):
        auth.allowed(user)
        query=body.get('query','').strip()
        if not query or len(query)>1500:raise HTTPException(422,'검색어를 1~1500자로 입력하세요.')
        scope=resolve(user,query,body.get('collection_id',''))
        if scope.get('status'):return scope
        filters=body.get('filters') or {}
        unsupported=set(filters)-{'document_id','author_id','days','date_filter','title_only'}
        if unsupported:raise HTTPException(422,'이 필터는 AI 검색에서 지원하지 않습니다.')
        arguments={**scope,**filters,'mode':body.get('mode','answer')}
        result=search.agent('/agent/knowledge-search',arguments,timeout=240,user=user)
        # New ACL phase after the potentially long model call.
        with execution.fresh():validate(user,result)
        return result


def validate(user,result):
    auth.allowed(user);acl=access(user)
    if enabled() and result.get('documents'):
        ids=[d['id'] for d in result['documents']]
        if set(ids)-set(live_access(user,ids)['documents']):raise HTTPException(403,'문서 접근 권한이 변경되었어요.')
    active={p['id'] for p in targets() if p['included']}
    for d in result.get('documents',[]):
        live=outline.api('documents.info',{'id':d['id']},missing_ok=True)
        if not live or not live.get('publishedAt') or live.get('deletedAt') or live.get('archivedAt'):
            raise HTTPException(409,'검색한 문서가 변경되었어요. 다시 검색해 주세요.')
        acl.require(live['collectionId'])
        if live['collectionId'] not in active or live['collectionId']!=d.get('collection_id',live['collectionId']) or live.get('revision')!=d.get('revision'):
            raise HTTPException(409,'검색한 문서가 변경되었어요. 다시 검색해 주세요.')
        path=urlparse(live.get('url','')).path
        if not path.startswith('/doc/'):raise HTTPException(409,'문서 링크를 확인하지 못했어요.')
        d['url']=outline.PUBLIC+path
    byid={d['id']:d for d in result.get('documents',[])}
    for cite in result.get('citations',[]):
        if cite['id'] in byid:cite['url']=byid[cite['id']]['url']


def submit(user,body):
    auth.allowed(user)
    rid=body.get('request_id') or str(uuid.uuid4())
    if not re.fullmatch(r'[a-zA-Z0-9-]{8,100}',rid):raise HTTPException(422,'잘못된 검색 요청입니다.')
    key='knowledge:job:'+rid;fingerprint=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
    with LOCK:
        existing=store.get(key)
        if existing:
            if existing['sub']!=user['sub'] or existing['fingerprint']!=fingerprint:raise HTTPException(409,'다른 검색 요청입니다.')
            return {'request_id':rid,'status':existing['state']}
        if not SLOTS.acquire(blocking=False):raise HTTPException(429,'검색 요청이 많아요. 잠시 후 다시 시도해 주세요.')
        store.put(key,{'sub':user['sub'],'fingerprint':fingerprint,'state':'queued','at':time.time()})
    def run():
        try:
            with LOCK:
                job=store.get(key)
                if job['state']=='cancelled':return
                job['state']='running';store.put(key,job)
            result=execute(current_user(user['sub']),body)
            with LOCK:
                job=store.get(key)
                if job['state']!='cancelled':job.update(state='done',result=result);store.put(key,job)
        except Exception as exc:
            with LOCK:
                job=store.get(key)
                if job['state']!='cancelled':
                    job.update(state='failed',error=exc.detail if isinstance(exc,HTTPException) and isinstance(exc.detail,str) else '지금은 검색 결과를 가져오지 못했어요. 다시 시도해 주세요.')
                    store.put(key,job)
        finally:SLOTS.release()
    POOL.submit(run)
    return {'request_id':rid,'status':'queued'}


def result(user,rid,cancel=False):
    auth.allowed(user)
    with LOCK:
        job=store.get('knowledge:job:'+rid)
        if not job or job['sub']!=user['sub']:raise HTTPException(404,'검색 요청을 찾지 못했어요.')
        if time.time()-job['at']>1800:raise HTTPException(410,'검색 결과가 만료되었어요. 다시 검색해 주세요.')
        if cancel:
            job['state']='cancelled';job.pop('result',None);store.put('knowledge:job:'+rid,job)
    if job['state']=='done':
        with execution.request('knowledge_result',user):validate(user,job['result'])
        return {**job['result'],'request_id':rid}
    return {'status':job['state'],'request_id':rid,'answer':job.get('error','')}


def recover():
    # Jobs interrupted by restart fail visibly; no stale privileged result reuse.
    with store.db() as c:
        for row in c.execute("SELECT k,v FROM kv WHERE k LIKE 'knowledge:job:%'").fetchall():
            job=json.loads(row['v'])
            if time.time()-job['at']>1800:c.execute('DELETE FROM kv WHERE k=?',(row['k'],))
            elif job['state'] in ('queued','running'):
                job.update(state='failed',error='서비스가 다시 시작되었어요. 다시 검색해 주세요.')
                c.execute('UPDATE kv SET v=? WHERE k=?',(store.dump(job),row['k']))
