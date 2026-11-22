import hashlib, json, os, re, threading, uuid, time
from datetime import datetime, timezone, timedelta
import httpx
from fastapi import HTTPException
from . import store, domain, criteria, permissions, human_tasks, execution, http_pool, task_status

URL=os.environ['OUTLINE_URL'].rstrip('/')
PUBLIC=os.environ['OUTLINE_PUBLIC_URL'].rstrip('/')
HEADERS={'Authorization':'Bearer '+os.environ['OUTLINE_API_KEY']}
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
    if name in ('documents.create','documents.update','documents.delete','documents.move'):
        from .search import dirty
        dirty.set()
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

def collection():
    cid=store.get('collection')
    if cid:return cid
    matches=[c for c in all_items('collections.list') if c['name']=='통합 업무']
    c=matches[0] if matches else api('collections.create',{'name':'통합 업무','description':'담당자가 직접 관리하는 업무 원본. 통합 AI 비서와 관리자 통계가 이 문서를 참조합니다.','permission':None,'color':'#2563eb'})
    store.put('collection',c['id']);return c['id']

def projects():
    saved=store.get('projects')
    if saved is None:
        # New installations require an explicit project connection with live access checks.
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

def register_project(user,name,existing_id='',idem=''):
    from .auth import admin
    admin(user)
    with MUTEX:
        key='project-create:'+user['sub']+':'+idem
        old=store.get(key)
        if old:return permissions.project(user,old)
        ps=projects();available=all_items('collections.list',{'includeListOnly':True})
        if existing_id:
            c=next((p for p in available if p['id']==existing_id),None)
            if not c:raise HTTPException(404,'Outline 컬렉션을 찾을 수 없습니다.')
            permissions.Access(user).require(c['id'])
            permissions.require_project_linkable(c)
        else:
            raise HTTPException(400,'Outline에서 컬렉션을 만든 뒤 API 키 계정에 편집 권한을 부여하고 프로젝트로 연결해 주세요.')
        if not any(p['id']==c['id'] for p in ps):
            ps.append({'id':c['id'],'name':c['name'],'manager':user['email'].lower()});store.put('projects',ps)
        store.put(key,c['id'])
        PROJECTS_CACHE['until']=0
        return project(c['id'])

def project_managers(user,collection_id):
    from . import auth,directory
    auth.admin(user);permissions.project(user,collection_id)
    eligible={p['email'] for p in permissions.assignees(user,collection_id)}
    return [p for p in directory.people() if p.get('admin') and p['email'] in eligible]

def set_project_manager(user,collection_id,email):
    from .auth import admin
    admin(user)
    with MUTEX:
        p=permissions.project(user,collection_id);email=email.strip().lower()
        if email and email not in {x['email'] for x in project_managers(user,p['id'])}:
            raise HTTPException(403,'프로젝트에 접근할 수 있는 활성 관리자만 프로젝트 책임자로 지정할 수 있습니다.')
        saved=store.get('projects') or []
        for row in saved:
            if row['id']==p['id']:row['manager']=email
        store.put('projects',saved)
        return project(p['id'])

def unlink_preview(user,collection_id,*,can_manage=False):
    from .project_service import require_manage
    require_manage(user,collection_id,can_manage)
    p=permissions.project(user,collection_id);saved=store.get('task-parent:'+p['id'])
    parent=api('documents.info',{'id':saved['id']},missing_ok=True) if saved else None
    safe=bool(parent and parent.get('collectionId')==p['id'] and not parent.get('parentDocumentId')
        and not parent.get('deletedAt') and not domain.is_legacy_task(parent.get('text','')))
    return {'project':p,'parent':{'id':parent['id'],'title':parent['title'],'url':PUBLIC+parent['url']} if safe else None,
        'note':'삭제 옵션은 업무 목록과 그 아래 모든 문서를 Outline 휴지통으로 이동합니다. 컬렉션과 다른 문서는 유지됩니다.'}

def unlink_project(user,collection_id,idem,delete_task_list=False,expected_parent_id=''):
    from .auth import admin
    admin(user)
    with MUTEX:
        key='project-unlink:'+user['sub']+':'+idem
        request={'collectionId':collection_id,'deleteTaskList':delete_task_list,'parentId':expected_parent_id}
        saved=store.get(key)
        if saved and saved['request']!=request:raise HTTPException(409,'같은 요청 번호로 연결 해제 옵션을 바꿀 수 없습니다.')
        if saved and saved.get('result'):
            permissions.Access(user).require(collection_id)
            return saved['result']
        p=permissions.project(user,collection_id)
        if delete_task_list:
            mapping=store.get('task-parent:'+p['id'])
            if not expected_parent_id or not mapping or mapping['id']!=expected_parent_id:
                raise HTTPException(409,'업무 목록이 변경되었습니다. 프로젝트 관리 화면을 다시 열어 확인하세요.')
            parent=api('documents.info',{'id':expected_parent_id},missing_ok=True)
            if parent and not parent.get('deletedAt'):
                if parent.get('collectionId')!=p['id'] or parent.get('parentDocumentId') or domain.is_legacy_task(parent.get('text','')):
                    raise HTTPException(409,'업무 목록의 위치나 내용이 바뀌어 삭제를 중단했습니다. 연결 해제만 선택할 수 있습니다.')
                # Journal intent first so a lost delete response can be retried safely.
                store.put(key,{'request':request})
                api('documents.delete',{'id':expected_parent_id,'permanent':False})
                after=api('documents.info',{'id':expected_parent_id},missing_ok=True)
                if after and not after.get('deletedAt'):raise HTTPException(409,'문서 삭제 결과를 확인하지 못했습니다. 다시 시도하세요.')
            elif not saved:
                raise HTTPException(409,'삭제할 업무 목록이 없습니다. 연결 해제만 선택하거나 화면을 새로 여세요.')
        result={'id':p['id'],'name':p['name'],'unlinked':True,'taskListDeleted':delete_task_list,'collectionDeleted':False}
        with store.db() as c:
            registry=store.get('projects',[])
            c.execute('INSERT OR REPLACE INTO kv VALUES(?,?)',('projects',store.dump([v for v in registry if v['id']!=p['id']])))
            for row in c.execute('SELECT id,body FROM tasks WHERE active=1').fetchall():
                if json.loads(row['body']).get('collectionId')==p['id']:c.execute('UPDATE tasks SET active=0 WHERE id=?',(row['id'],))
            for row in c.execute("SELECT k,v FROM kv WHERE k LIKE 'chat-context:%'").fetchall():
                if json.loads(row['v']).get('collectionId')==p['id']:c.execute('DELETE FROM kv WHERE k=?',(row['k'],))
            if delete_task_list:c.execute('DELETE FROM kv WHERE k=?',('task-parent:'+p['id'],))
            c.execute('INSERT OR REPLACE INTO kv VALUES(?,?)',(key,store.dump({'request':request,'result':result})))
        PROJECTS_CACHE['until']=0
        return result

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
                'text':'이 프로젝트의 업무를 모아 보는 문서입니다.\n\nOutline에서 업무를 직접 작성하려면 이 문서 바로 아래에 하위 문서를 만들고 업무 템플릿을 적용한 뒤 게시하세요. Rocket.Chat 업무 비서에서 등록한 업무도 이 문서 아래에 생성됩니다. 각 하위 업무에서 담당자, 완료 기준, 진행 상황과 보고 이력을 확인하세요.',
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

def read_project_tasks(user, collection_id):
    """Fresh, paginated project inventory without normalize/record/task_parent writes.

    Treat an invalid API page as failure, never as an empty successful inventory.
    A failed document read is counted, rather than hiding a possible personal task.
    """
    permissions.project(user, collection_id)
    result=[]; errors=0; offset=0; seen=set()
    while True:
        page=api('documents.list',{'collectionId':collection_id,'limit':100,'offset':offset})
        if not isinstance(page,list):raise ValueError('업무 목록을 확인하지 못했습니다.')
        for d in page:
            try:
                if not isinstance(d,dict) or not d.get('id'):raise ValueError('잘못된 문서 응답')
                if d['id'] in seen:continue
                seen.add(d['id'])
                if 'text' not in d:d=api('documents.info',{'id':d['id']})
                if d.get('collectionId')!=collection_id or not d.get('publishedAt') or d.get('archivedAt') or d.get('deletedAt') or d.get('template'):continue
                task=projected(d)
                if task is None:continue
                if task.get('error'):errors+=1
                else:result.append(task)
            except Exception as ex:
                execution.count('my_tasks.document_failure')
                errors+=1
        if len(page)<100:break
        offset+=100
        if offset>=100000:raise ValueError('업무 목록이 너무 많아 모두 확인하지 못했습니다.')
    return result,errors


def tasks(collection_id='',user=None):
    if user is not None:
        ids={permissions.project(user,collection_id)['id']} if collection_id else {p['id'] for p in permissions.projects(user)}
    else:ids={project(collection_id)['id']} if collection_id else {p['id'] for p in projects()}
    with store.db() as c:rows=c.execute('SELECT body FROM tasks WHERE active=1').fetchall()
    ts=[json.loads(r[0]) for r in rows]
    return [t for t in ts if t.get('collectionId') in ids]

def find(code,collection_id='',user=None):
    ts=[t for t in tasks(collection_id,user) if t['id']==code or t['code']==code]
    if len(ts)!=1:raise HTTPException(404,'업무 번호를 확인하세요.')
    return document(ts[0]['id'],user)

def can_write(user,d):
    permissions.document(user,d)
    f=domain.parse(d['text'])
    if not user.get('admin') and (not f or f['owner'].lower()!=user['email'].lower()):raise HTTPException(403,'담당자 또는 관리자만 변경을 확정할 수 있습니다.')

def can_report(user,d):
    permissions.document(user,d)
    items=criteria.parse(d['text'])
    if items:
        if not user.get('admin') and not any(i['owner']==user['email'].lower() for i in items):
            raise HTTPException(403,'배정된 완료 기준의 담당자 또는 관리자만 보고할 수 있습니다.')
    else:can_write(user,d)

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

def propose(user,docid,changes,idem,notes='',metadata=None):
    with MUTEX:
        with store.db() as c:row=c.execute('SELECT * FROM proposals WHERE owner=? AND idem=?',(user['sub'],idem)).fetchone()
        if row:return proposal(user,row['id'])
        d=document(docid,user);authorize_changes(user,d,changes)
        after=apply_changes(d['text'],changes,docid)
        if notes:
            # Literal block preserves the original company layout and raw evidence.
            # Outline normalizes nested Markdown lists/quotes, so do not interpret reports as markup.
            note=notes.strip()[:10000]
            fence='`'*max(3,1+max((len(m.group()) for m in re.finditer(r'`+',note)),default=0))
            after+='\n\n### 보고 기록\n\n'+store.now()+' · '+user['email']+'\n\n'+fence+'text\n'+note+'\n'+fence
        p={'id':str(uuid.uuid4()),'doc_id':docid,'title':d['title'],'before':d['text'],'after':after,
           'revision':d.get('revision',0),'updatedAt':d['updatedAt'],'changes':changes,'url':PUBLIC+d['url'],
           'collectionId':d['collectionId'],**(metadata or {})}
        with store.db() as c:c.execute('INSERT INTO proposals VALUES(?,?,?,?,?,?)',(p['id'],user['sub'],idem,store.dump(p),'PENDING',store.now()))
        return {**p,'state':'PENDING'}

def require_task_access(user,docid):
    permissions.document(user,api('documents.info',{'id':docid}))

def proposal(user,pid):
    with store.db() as c:rows=c.execute('SELECT * FROM proposals WHERE owner=? AND (id=? OR substr(id,1,8)=?)',(user['sub'],pid,pid)).fetchall()
    if len(rows)!=1:raise HTTPException(404,'본인의 변경 제안이 아닙니다.')
    body=json.loads(rows[0]['body'])
    require_task_access(user,body['doc_id'])
    return {**body,'state':rows[0]['state']}

def applied_receipt(p,d):
    """Persist what was verified at confirmation, not the current live state."""
    fields=domain.parse(d['text']);items=criteria.parse(d['text'])
    if items:fields.update(task_status.summary(d['text'],items,document_id=d['id']))
    return {**{k:v for k,v in p.items() if k!='state'},'applied_at':store.now(),
        'result':{'status':fields['status'],'progress':fields['progress'],
                  'criteria_done':sum(i['state']=='완료' for i in items),
                  'criteria_total':len(items),'criteria':items,
                  'revision':d.get('revision',0),'updatedAt':d['updatedAt']}}

def finish_confirmation(user,p,d):
    body=applied_receipt(p,d)
    record(d,user['email'],'confirmed')
    with store.db() as c:c.execute('UPDATE proposals SET state=?,body=? WHERE id=?',('APPLIED',store.dump(body),p['id']))
    return {**body,'state':'APPLIED'}

@execution.operation('outline_confirm',refresh=True)
def confirm(user,pid):
    with MUTEX:
        p=proposal(user,pid)
        if p['state']=='APPLIED':return p
        if p['state']=='CANCELLED':raise HTTPException(409,'취소된 초안은 확정할 수 없습니다. 새 보고를 작성하세요.')
        if p['state']=='CONFLICT':raise HTTPException(409,'Outline 원본이 바뀌었습니다. 새 제안을 작성하세요.')
        if p['state'] not in ('PENDING','APPLYING'):raise HTTPException(409,'확정할 수 없는 초안 상태입니다.')
        d=document(p['doc_id']);authorize_changes(user,d,p['changes'])
        # Recover after a lost response/crash only when this exact write was attempted.
        if p['state']=='APPLYING' and domain.same_saved_text(p['after'],d['text']):
            return finish_confirmation(user,p,d)
        elif d['text']!=p['before'] or d.get('revision',0)!=p['revision'] or d['updatedAt']!=p['updatedAt']:
            if p['state']=='APPLYING':
                raise HTTPException(409,'저장 요청 후 원본이 변경되어 이 보고의 반영 여부를 확정할 수 없습니다. 변경 내용을 확인하세요. 자동으로 다시 저장하지 않습니다.')
            with store.db() as c:c.execute('UPDATE proposals SET state=? WHERE id=?',('CONFLICT',p['id']))
            raise HTTPException(409,'Outline 원본이 수정되어 덮어쓰기를 중단했습니다. 새 제안을 작성하세요.')
        else:
            with store.db() as c:c.execute('UPDATE proposals SET state=? WHERE id=?',('APPLYING',p['id']))
            try:
                api('documents.update',{'id':p['doc_id'],'text':p['after'],'lastRevision':p['revision']})
            except (httpx.HTTPError,HTTPException) as error:
                # A timeout may happen after Outline committed the write.
                try:observed=document(p['doc_id'])
                except Exception:
                    raise HTTPException(503,'저장 요청을 보냈으나 결과를 확인하지 못했습니다. 잠시 후 반영 결과 다시 확인을 눌러주세요.') from error
                if domain.same_saved_text(p['after'],observed['text']):return finish_confirmation(user,p,observed)
                raise HTTPException(503,'저장 결과를 아직 확인하지 못했습니다. 잠시 후 반영 결과 다시 확인을 눌러주세요.') from error
            try:d=document(p['doc_id'])
            except (httpx.HTTPError,HTTPException) as error:
                raise HTTPException(503,'저장 요청을 보냈으나 결과 조회가 지연되었습니다. 반영 결과 다시 확인을 눌러주세요.') from error
            if not domain.same_saved_text(p['after'],d['text']):raise HTTPException(409,'저장 요청은 전송했지만 원본 내용이 변경안과 다릅니다. 반영 결과 다시 확인을 눌러 확인하세요. 자동으로 덮어쓰지 않습니다.')
        return finish_confirmation(user,p,d)

def cancel(user,pid):
    # Same lock as confirm: exactly one operation wins, without touching Outline.
    with MUTEX:
        p=proposal(user,pid)
        if p['state']=='CANCELLED':return p
        if p['state']=='APPLIED':raise HTTPException(409,'이미 확정된 보고는 초안 취소로 되돌릴 수 없습니다. 새 보고로 수정하세요.')
        if p['state']=='APPLYING':raise HTTPException(409,'반영 결과를 확인 중인 보고는 취소할 수 없습니다. 원본과 확정 결과를 먼저 확인하세요.')
        if p['state'] not in ('PENDING','CONFLICT'):raise HTTPException(409,'취소할 수 없는 초안 상태입니다.')
        body={k:v for k,v in p.items() if k!='state'}
        body['cancelled_at']=store.now()
        with store.db() as c:
            c.execute('UPDATE proposals SET state=?,body=? WHERE id=?',('CANCELLED',store.dump(body),p['id']))
        return {**body,'state':'CANCELLED'}

def create(user,title,fields,idem,notes='',collection_id='',checklist=None):
    selected=permissions.project(user,collection_id)
    permissions.validate_owners(user,selected['id'],[{'owner':fields.get('owner','')},*(checklist or [])])
    if not user.get('admin') and fields.get('owner','').lower()!=user['email'].lower():raise HTTPException(403,'자신의 업무만 생성할 수 있습니다.')
    title=domain.clean(title)[:150]
    if not title:raise ValueError('업무명을 입력하세요.')
    fields={**fields,'project':selected['name']}
    if not fields.get('start') or fields['start'] == '미정':
        fields['start']=datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    text=domain.render(fields,notes)
    if checklist:
        if not user.get('admin'):raise HTTPException(403,'완료 기준 작성·분배는 관리자만 할 수 있습니다.')
        items=criteria.validate(checklist)
        text=domain.patch_text(criteria.replace(text,items),criteria.rollup(items))
    with MUTEX:
        key='create:'+user['sub']+':'+idem
        from .project_service import ensure_writable
        selected=permissions.project(user,selected['id'])
        ensure_writable(selected['id'])
        saved=store.get(key)
        if saved and saved.get('result'):return saved['result']
        did=saved['id'] if saved else str(uuid.uuid4())
        store.put(key,{'id':did})
        # documents.create accepts an explicit UUID, permitting response-loss recovery.
        existing=next((d for d in all_items('documents.list',{'collectionId':selected['id']}) if d['id']==did),None)
        if existing:d=existing
        else:
            parent=task_parent(selected['id'])
            d=api('documents.create',{'id':did,'collectionId':selected['id'],'parentDocumentId':parent['id'],'title':title,'text':text,'publish':True})
        d=document(d['id']);result=record(d,user['email'],'created')
        store.put(key,{'id':did,'result':result});return result

def history(user=None):
    with store.db() as c:rows=c.execute('SELECT * FROM events ORDER BY seq DESC LIMIT 1000').fetchall()
    ids={p['id'] for p in (permissions.projects(user) if user is not None else projects())}
    return [{**dict(r),'body':json.loads(r['body'])} for r in rows if json.loads(r['body']).get('collectionId') in ids]

def weekly(user,collection_id=''):
    selected=permissions.project(user,collection_id)
    sync();ts=tasks(selected['id'],user);s=domain.statistics(ts)
    lines=['# 주간 업무 현황',f'집계 시각: {store.now()}',f"업무 {s['total']}건 · 완료 {s['completed']}건 · 완료율 {s['completion_rate']}% · 기한 초과 {s['overdue']}건",'',
           '집계 기준: 선택한 프로젝트의 문서 ID별 현재 상태. 아래 수치는 생성 시점의 스냅샷입니다.','']
    for t in ts:
        f=t['fields'];lines.append(f"- [{t['title']}]({t['url']}) · {f.get('owner','?')} · {f.get('status','형식 오류')} · {f.get('progress','미기재')} · 마감 {f.get('due','미정')}")
    return '\n'.join(lines)
