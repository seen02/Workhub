import hashlib, json, os, re, threading, uuid, time
from datetime import datetime, timezone, timedelta
import httpx
from fastapi import HTTPException
from . import store, domain, criteria, permissions, human_tasks, execution, http_pool, task_status

URL=os.environ['OUTLINE_URL'].rstrip('/')
PUBLIC=os.environ['OUTLINE_PUBLIC_URL'].rstrip('/')
HEADERS={'Authorization':'Bearer '+os.getenv('OUTLINE_API_KEY','')}
MUTEX=threading.RLock()
PROJECTS_CACHE={'until':0,'available':{}}
SYNC_CONDITION=threading.Condition()
SYNC_RUNNING=False
SYNC_FAILURE=None

def sync_shared():
    """Join one in-flight refresh instead of queuing duplicate full inventories."""
    global SYNC_RUNNING, SYNC_FAILURE
    with SYNC_CONDITION:
        if SYNC_RUNNING:
            if not SYNC_CONDITION.wait_for(lambda:not SYNC_RUNNING,timeout=55):
                raise HTTPException(503,'원본 동기화가 지연되고 있습니다. 잠시 후 다시 확인하세요.')
            if SYNC_FAILURE:raise HTTPException(503,'원본 동기화를 완료하지 못했습니다.')
            return tasks()
        SYNC_RUNNING=True
        SYNC_FAILURE=None
    try:
        return sync()
    except Exception as ex:
        with SYNC_CONDITION:SYNC_FAILURE=type(ex).__name__
        store.put('last_sync',{'at':store.now(),'ok':False})
        raise
    finally:
        with SYNC_CONDITION:
            SYNC_RUNNING=False
            SYNC_CONDITION.notify_all()

def api(name,body=None,missing_ok=False):
    cacheable=name in {'users.list','collections.list','collections.memberships',
        'collections.group_memberships','groups.memberships','documents.info','documents.list'}
    if cacheable:
        key=('outline',name,json.dumps(body or {},sort_keys=True),missing_ok)
        return execution.read(key,lambda:_api(name,body,missing_ok),name)
    # Invalidate before and after mutations, even on timeout/unknown outcome.
    if not name.endswith(('.info','.list','.memberships','.group_memberships')):
        with execution.fresh():return _api(name,body,missing_ok)
    return _api(name,body,missing_ok)

def _api(name,body=None,missing_ok=False,*,full_response=False):
    # Mutations never auto-retry: confirmation receipts reconcile uncertain writes.
    read=name.endswith(('.info','.list','.memberships','.group_memberships'))
    try:
        for attempt in range(3 if read else 1):
            r=http_pool.request('outline','POST',URL+'/api/'+name,metric=name,json=body or {},headers=HEADERS,timeout=30)
            if r.status_code!=429 or not read or attempt==2:break
            execution.count('retry.outline.'+name)
            try:delay=float(r.headers.get('Retry-After') or r.headers.get('RateLimit-Reset') or 1)
            except ValueError:delay=1
            time.sleep(max(.5,min(delay,8)))
    except httpx.HTTPError:raise HTTPException(503,'Outline에 연결하지 못해 권한과 원본을 확인할 수 없습니다. 잠시 후 다시 시도하세요.')
    if missing_ok and r.status_code==404:return None
    if not r.is_success:
        if r.status_code==429:raise HTTPException(503,'Outline 요청이 일시적으로 많습니다. 잠시 후 다시 시도하세요.',headers={'Retry-After':'15'})
        if r.status_code==409:raise HTTPException(409,'Outline 원본 버전이 변경되었습니다. 새 제안을 작성하세요.')
        raise HTTPException(502, f'Outline {name} 요청 실패 ({r.status_code})')
    payload=r.json()
    return payload if full_response else payload.get('data')

def collection_access(cid):
    """Read native collection abilities as the actual API key owner, not the actor."""
    return execution.read(('outline','collection_access',cid),
        lambda:_api('collections.info',{'id':cid},full_response=True),'collections.info')

def all_items(name,body=None):
    result=[];offset=0
    while True:
        page=api(name,{**(body or {}),'limit':100,'offset':offset})
        if isinstance(page,dict):page=next((v for v in page.values() if isinstance(v,list)),[])
        result.extend(page)
        if len(page)<100:return result
        offset+=100

def projects():
    saved=store.get('projects')
    if saved is None:
        saved=[]
        store.put('projects',saved)
    # A deleted/renamed Outline collection must not remain a broken login/menu
    # target. Resolve IDs through the admin inventory, including private collections.
    # User-facing callers must still filter through permissions.Access.
    with MUTEX:
        if time.monotonic()>=PROJECTS_CACHE['until']:
            PROJECTS_CACHE['available']={p['id']:p['name'] for p in all_items('collections.list',{'includeListOnly':True})}
            PROJECTS_CACHE['until']=time.monotonic()+5
        available=PROJECTS_CACHE['available']
    return [{**p,'name':available[p['id']],'code':p['id'][:8]} for p in saved if p['id'] in available]

def project(code=''):
    ps=projects()
    if not code:code=next((p['id'] for p in ps if p['id']==store.get('collection')),ps[0]['id'] if ps else '')
    matches=[p for p in ps if code in (p['id'],p['code'],p['name'])]
    if len(matches)!=1:raise HTTPException(404,'등록된 프로젝트(컬렉션)를 선택하세요.')
    return matches[0]

def unlink_preview(user,collection_id,*,can_manage=False):
    from .project_service import require_manage
    require_manage(user,collection_id,can_manage)
    p=permissions.project(user,collection_id);saved=store.get('task-parent:'+p['id'])
    parent=api('documents.info',{'id':saved['id']},missing_ok=True) if saved else None
    safe=bool(parent and parent.get('collectionId')==p['id'] and not parent.get('parentDocumentId')
        and not parent.get('deletedAt') and not domain.is_legacy_task(parent.get('text','')))
    return {'project':p,'parent':{'id':parent['id'],'title':parent['title'],'url':PUBLIC+parent['url']} if safe else None,
        'note':'삭제 옵션은 업무 목록과 그 아래 모든 문서를 Outline 휴지통으로 이동합니다. 컬렉션과 다른 문서는 유지됩니다.'}

def ensure_member(user,collection_id=None):
    # Compatibility for callers: verify identity, never grant access during login.
    access=permissions.Access(user)
    if collection_id:access.require(collection_id)
    return access.person['id']

def task_parent(collection_id):
    """One durable, top-level task container per collection; never match a rename."""
    with MUTEX:
        key='task-parent:'+collection_id
        saved=store.get(key)
        if saved:
            # A known ID is authoritative; list responses may briefly lag writes.
            parent=api('documents.info',{'id':saved['id']},missing_ok=True)
            if not parent and saved.get('ready'):
                raise HTTPException(409,'업무 목록 문서가 삭제·보관되었거나 다른 프로젝트로 이동했습니다. Outline에서 원래 위치로 복원하세요.')
        else:
            docs=all_items('documents.list',{'collectionId':collection_id})
            matches=[d for d in docs if d['title']=='업무 목록' and not d.get('parentDocumentId') and d.get('publishedAt') and not d.get('archivedAt') and not d.get('deletedAt')]
            if len(matches)>1:raise HTTPException(409,'최상위에 업무 목록 문서가 여러 개 있습니다. 사용할 문서 하나만 이 이름으로 남겨주세요.')
            parent=matches[0] if matches else None
            saved={'id':parent['id'] if parent else str(uuid.uuid4()),'ready':False}
            # Reserve an ID before sending the request, including response-loss retries.
            if parent is None:store.put(key,saved)
        if parent is None:
            api('documents.create',{'id':saved['id'],'collectionId':collection_id,'title':'업무 목록',
                'text':'이 프로젝트의 업무를 모아 보는 문서입니다.\n\nOutline에서 업무를 직접 작성하려면 이 문서 바로 아래에 하위 문서를 만들고 업무 템플릿을 적용한 뒤 게시하세요. 각 하위 업무에서 담당자, 완료 기준, 진행 상황과 보고 이력을 확인하세요.',
                'publish':True})
        parent=api('documents.info',{'id':saved['id']})
        if (parent.get('collectionId')!=collection_id or parent.get('parentDocumentId') or not parent.get('publishedAt')
            or parent.get('archivedAt') or parent.get('deletedAt') or domain.is_legacy_task(parent.get('text',''))):
            raise HTTPException(409,'업무 목록은 같은 프로젝트의 최상위 일반 문서여야 합니다. 위치와 내용을 확인하세요.')
        store.put(key,{'id':parent['id'],'ready':True})
        return parent

def normalize(d):
    """Reconcile direct Outline checkbox edits with the displayed summary fields."""
    if human_tasks.is_human(d.get('text','')):
        if not human_tasks.eligible(d):raise HTTPException(404,'템플릿 업무는 해당 프로젝트의 업무 목록 바로 아래에 게시하세요.')
        fields=domain.parse(d['text']);items=criteria.parse(d['text'])
        human_tasks.validate_assignment(d,fields,items)
        if not items:return d
        computed=task_status.summary(d['text'],items,preserve_human=True,document_id=d.get('id',''))
        changes={'status':computed['status']}
        if task_status.manual(d['text'],d.get('id','')):changes['progress']=computed['progress']
        if any(fields[key]!=value for key,value in changes.items()):
            text=task_status.mark_manual(d['text']) if task_status.manual(d['text'],d.get('id','')) else d['text']
            after=domain.patch_text(text,changes)
            api('documents.update',{'id':d['id'],'text':after,'lastRevision':d.get('revision',0)})
            return api('documents.info',{'id':d['id']})
        return d
    if not domain.is_legacy_task(d.get('text','')):return d
    items=criteria.parse(d['text'])
    if items:
        after=domain.patch_text(criteria.replace(d['text'],items),task_status.summary(d['text'],items,document_id=d['id']))
        if after!=d['text']:
            api('documents.update',{'id':d['id'],'text':after,'lastRevision':d.get('revision',0)})
            return api('documents.info',{'id':d['id']})
    return d

def document(docid,user=None,*,normalize_fields=True):
    d=api('documents.info',{'id':docid})
    if d.get('collectionId') not in {p['id'] for p in projects()} or not d.get('publishedAt') or d.get('archivedAt') or d.get('deletedAt'):raise HTTPException(404,'접근 가능한 프로젝트 업무 문서가 아닙니다.')
    if user is not None:permissions.document(user,d)
    return normalize(d) if normalize_fields else d

def projected(d):
    text=d.get('text','')
    items=[]
    if human_tasks.is_human(text) and not human_tasks.eligible(d):return None
    try:
        fields=domain.parse(text);error=None
        if fields is not None:
            items=criteria.parse(text)
            if human_tasks.is_human(text):
                human_tasks.validate_assignment(d,fields,items)
                fields['project']=project(d['collectionId'])['name']
            if items:
                computed=task_status.summary(text,items,preserve_human=True,document_id=d['id'])
                fields.update(computed)
    except (ValueError,TypeError) as ex:fields={};error=str(ex)
    if fields is None:return None
    return {'id':d['id'],'code':d['id'][:8],'title':d['title'],'fields':fields,'error':error,
        'collectionId':d['collectionId'],'collectionName':project(d['collectionId'])['name'],'criteria':items,'parentDocumentId':d.get('parentDocumentId'),
        'revision':d.get('revision',0),'updatedAt':d['updatedAt'],'url':PUBLIC+d['url'],'text':text}

def record(d,actor='Outline 직접 수정',kind='sync'):
    task=projected(d)
    if task is None:return
    task_status.remember(d['id'],d['text'])
    source=f"{d.get('revision',0)}:{d['updatedAt']}"
    with store.db() as c:
        c.execute('INSERT INTO tasks VALUES(?,?,?,1) ON CONFLICT(id) DO UPDATE SET body=excluded.body,source_key=excluded.source_key,active=1',(d['id'],store.dump(task),source))
        c.execute('INSERT OR IGNORE INTO events(doc_id,source_key,observed,actor,kind,body) VALUES(?,?,?,?,?,?)',(d['id'],source,store.now(),actor,kind,store.dump(task)))
    return task

def sync():
    token=permissions.request_snapshots.set({})
    try:return _sync()
    finally:permissions.request_snapshots.reset(token)

def _sync():
    with MUTEX:
        docs=[]
        for p in projects():docs.extend(all_items('documents.list',{'collectionId':p['id']}))
        ids=[]
        for d in docs:
            if d.get('archivedAt') or d.get('deletedAt') or not d.get('publishedAt'):continue
            # list may omit text depending on Outline version.
            if 'text' not in d:d=api('documents.info',{'id':d['id']})
            if human_tasks.is_human(d.get('text','')) and not human_tasks.eligible(d):continue
            try:d=normalize(d)
            except ValueError:pass # Show invalid documents rather than silently omitting them.
            t=record(d)
            if t:ids.append(d['id'])
        with store.db() as c:
            old=c.execute('SELECT * FROM tasks WHERE active=1').fetchall()
            for row in old:
                if row['id'] not in ids:
                    c.execute('UPDATE tasks SET active=0 WHERE id=?',(row['id'],))
                    c.execute('INSERT OR IGNORE INTO events(doc_id,source_key,observed,actor,kind,body) VALUES(?,?,?,?,?,?)',(row['id'],'inactive:'+row['source_key'],store.now(),'Outline','removed',row['body']))
        store.put('last_sync',{'at':store.now(),'ok':True,'count':len(ids)})
    return tasks()

def tasks(collection_id='',user=None):
    if user is not None:
        ids={permissions.project(user,collection_id)['id']} if collection_id else {p['id'] for p in permissions.projects(user)}
    else:ids={project(collection_id)['id']} if collection_id else {p['id'] for p in projects()}
    with store.db() as c:rows=c.execute('SELECT body FROM tasks WHERE active=1').fetchall()
    ts=[json.loads(r[0]) for r in rows]
    return [t for t in ts if t.get('collectionId') in ids]

def can_write(user,d):
    permissions.document(user,d)
    f=domain.parse(d['text'])
    if not user.get('admin') and (not f or f['owner'].lower()!=user['email'].lower()):raise HTTPException(403,'담당자 또는 관리자만 변경을 확정할 수 있습니다.')

def authorize_changes(user,d,changes):
    permissions.document(user,d)
    items=criteria.parse(d['text'])
    if 'kanban_status' in changes:
        if set(changes)!={'kanban_status'} or changes['kanban_status'] not in domain.STATES:
            raise ValueError('칸반 업무 상태를 확인하세요.')
        can_write(user,d)
    elif 'criteria' in changes:
        if set(changes)!={'criteria'}:raise ValueError('완료 기준 변경과 일반 항목 변경은 나누어 제출하세요.')
        if not user.get('admin'):raise HTTPException(403,'완료 기준 작성·분배는 관리자만 할 수 있습니다.')
        criteria.validate(changes['criteria'])
        permissions.validate_owners(user,d['collectionId'],changes['criteria'],items)
    elif 'criterion_states' in changes:
        if set(changes)!={'criterion_states'}:raise ValueError('항목 보고와 일반 항목 변경은 나누어 제출하세요.')
        updates=changes['criterion_states']
        if not isinstance(updates,dict) or not updates:raise ValueError('변경할 완료 기준을 선택하세요.')
        for cid,state in updates.items():
            item=criteria.select(items,cid)
            if not user.get('admin') and item['owner']!=user['email'].lower():
                raise HTTPException(403,'자신에게 배정된 완료 기준만 보고할 수 있습니다.')
            if state not in criteria.STATES:raise ValueError('예정, 진행 중, 완료 중 하나를 선택하세요.')
    else:
        can_write(user,d)
        if 'owner' in changes and changes['owner']!=domain.parse(d['text']).get('owner'):
            permissions.validate_owners(user,d['collectionId'],[{'owner':changes['owner']}])
        if items and {'status','progress'} & set(changes):
            raise ValueError('완료 기준이 있는 업무의 상태·진행률은 항목에서 자동 계산됩니다.')

def apply_changes(text,changes,document_id=''):
    if task_status.manual(text,document_id):text=task_status.mark_manual(text)
    if 'kanban_status' in changes:
        status=changes['kanban_status'];items=criteria.parse(text)
        fields=domain.parse(text);updates={'status':status}
        if items:
            previous=task_status.summary(text,items,preserve_human=True,document_id=document_id)['status']
            if status=='완료' or (previous=='완료' and status=='미착수'):
                for item in items:item['state']='완료' if status=='완료' else '예정'
                text=criteria.replace(text,items)
            updates['progress']=criteria.rollup(items)['progress']
        elif status=='완료':updates['progress']='100%'
        elif fields['progress']=='100%':updates['progress']='0%'
        return domain.patch_text(task_status.mark_manual(text),updates)
    if 'criteria' in changes:
        items=criteria.validate(changes['criteria'])
        return domain.patch_text(criteria.replace(text,items),task_status.summary(text,items))
    if 'criterion_states' in changes:
        items=criteria.parse(text)
        for cid,state in changes['criterion_states'].items():criteria.select(items,cid)['state']=state
        return domain.patch_text(criteria.replace(text,items),task_status.summary(text,items))
    if task_status.manual(text):changes={k:v for k,v in changes.items() if k!='status'}
    return domain.patch_text(text,changes)
