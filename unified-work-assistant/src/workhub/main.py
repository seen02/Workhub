import json, logging, os, threading, time, uuid
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request, Query
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from . import auth, store, outline, domain, assistant, bot, criteria, directory, analytics, search, permissions
from . import search_identity
from . import lifecycle, outline_bridge, project_service, knowledge, analytics_service
from . import deadline_alerts
from . import recurring_service, recurring_worker

logging.basicConfig(level=logging.INFO)
stop=threading.Event()
def sync_loop():
    while not stop.is_set():
        jobs=project_service.sync_snapshot()
        sync_error=None
        try:outline.sync_shared()
        except Exception as ex:
            sync_error=type(ex).__name__
            store.put('last_sync',{'at':store.now(),'ok':False,'error':sync_error})
        try:
            search.sync_registry()
            project_service.sync_complete(jobs,sync_error)
        except Exception as ex:
            project_service.sync_complete(jobs,type(ex).__name__)
            logging.getLogger('workhub').warning('search_sync_pending type=%s',type(ex).__name__)
        stop.wait(20)

@asynccontextmanager
async def lifespan(app):
    store.init()
    knowledge.recover()
    threading.Thread(target=sync_loop,daemon=True).start()
    threading.Thread(target=bot.run,daemon=True).start()
    threading.Thread(target=lifecycle.run,args=(stop,),daemon=True).start()
    threading.Thread(target=deadline_alerts.run,args=(stop,),daemon=True).start()
    recurring_thread=threading.Thread(target=recurring_worker.run,args=(stop,),daemon=True)
    recurring_thread.start()
    yield
    stop.set()
    recurring_thread.join(timeout=5)

app=FastAPI(title='통합 AI 업무 비서',lifespan=lifespan,docs_url=None,redoc_url=None)

class BridgeActor(BaseModel):
    model_config={'extra':'forbid'}
    outlineUserId:str=Field(min_length=1,max_length=100)
    outlineTeamId:str=Field(min_length=1,max_length=100)
    canDeleteTaskList:bool=False
    canManageProject:bool=False
    canCreateCollection:bool=False

class BridgeBody(BaseModel):
    model_config={'extra':'forbid'}
    actor:BridgeActor
    collectionId:str=Field(default='',max_length=100)
    requestId:str=Field(default='',max_length=100)
    expectedRevision:int=Field(default=0,ge=0)
    managerSubject:str|None=Field(default=None,max_length=100)
    deleteTaskList:bool=False
    expectedParentId:str|None=Field(default=None,max_length=100)

@app.post('/internal/outline-projects/{action}')
async def outline_project_bridge(action:str,body:BridgeBody,request:Request):
    from starlette.concurrency import run_in_threadpool
    raw=await request.body()
    def execute():
        outline_bridge.verify(raw,request.url.path,request.headers)
        user=outline_bridge.actor(body.actor.model_dump())
        if action=='capabilities':return {'enabled':True,'manage':bool(user['admin'] or body.actor.canCreateCollection),'subject':user['sub']}
        if action=='connection-group':
            if body.collectionId:
                if not project_service.prepare_link_access(user,body.model_dump(exclude={'actor'}),can_manage=body.actor.canManageProject):
                    return {'skipGrant':True}
            elif not body.actor.canCreateCollection:raise HTTPException(403,'컬렉션 생성 권한이 필요합니다.')
            return permissions.project_connection_group()
        cid=body.collectionId
        if not cid:raise HTTPException(422,'컬렉션을 선택하세요.')
        can_delete=body.actor.canDeleteTaskList
        # These permissions come only from the authenticated, signed Outline request.
        # Collection creation capability never grants management of an existing one.
        can_manage=body.actor.canManageProject
        if action=='info':return project_service.info(user,cid,can_delete,can_manage=can_manage)
        if action=='managers':return {'people':outline_bridge.managers(user,cid)}
        if action=='unlink-preview':return project_service.preview(user,cid,can_delete,can_manage=can_manage)
        if action=='operation':return project_service.operation(user,cid,body.requestId,can_manage=can_manage)
        if action=='resume':return project_service.resume(user,cid,body.requestId,body.expectedParentId,can_delete,can_manage=can_manage)
        if action not in ('link','manager','unlink'):raise HTTPException(404,'지원하지 않는 프로젝트 작업입니다.')
        if len(body.requestId)<8:raise HTTPException(422,'요청 번호가 필요합니다.')
        if action!='unlink' and (body.deleteTaskList or body.expectedParentId):raise HTTPException(422,'등록 요청에 삭제 옵션을 사용할 수 없습니다.')
        if body.deleteTaskList!=bool(body.expectedParentId):raise HTTPException(422,'삭제 옵션과 대상 문서를 확인하세요.')
        return project_service.mutate(user,action,body.model_dump(exclude={'actor'}),can_delete,can_manage=can_manage)
    return await run_in_threadpool(execute)

def project_management_location():
    if outline_bridge.enabled():raise HTTPException(409,{'code':'project_management_moved','message':'Outline에서 프로젝트를 관리하세요.','url':outline.PUBLIC+'/workhub/projects'})

class KnowledgeBody(BaseModel):
    model_config={'extra':'forbid'}
    actor:BridgeActor
    query:str=Field(default='',max_length=1500)
    mode:str=Field(default='answer',pattern='^(answer|links)$')
    request_id:str=Field(default='',max_length=100)
    collection_id:str=Field(default='',max_length=100)
    filters:dict=Field(default_factory=dict)
    included:bool=False
    room_id:str=Field(default='',max_length=100)
    collection_ids:list[str]=Field(default_factory=list,max_length=100)

@app.post('/internal/outline-search/{action}')
async def outline_knowledge_bridge(action:str,body:KnowledgeBody,request:Request):
    from starlette.concurrency import run_in_threadpool
    raw=await request.body()
    def execute():
        outline_bridge.verify(raw,request.url.path,request.headers,search_request=True)
        user=outline_bridge.actor(body.actor.model_dump())
        if action=='capabilities':return {'enabled':True,'manage':bool(user.get('admin'))}
        if action=='catalog':return knowledge.catalog(user)
        if action=='include':return knowledge.inclusion(user,body.collection_id,body.included)
        if action=='sharing':return knowledge.sharing(user,body.room_id,body.collection_ids)
        if action=='refresh':
            auth.admin(user);permissions.Access(user).require(body.collection_id)
            search.sync_registry();return search.agent('/rag/knowledge/refresh',{})
        if action=='submit':return knowledge.submit(user,body.model_dump(exclude={'actor','included'}))
        if action in ('result','cancel'):return knowledge.result(user,body.request_id,cancel=action=='cancel')
        raise HTTPException(404,'지원하지 않는 검색 요청입니다.')
    return await run_in_threadpool(execute)
class AnalyticsActor(BaseModel):
    model_config={'extra':'forbid'}
    outlineUserId:str=Field(min_length=1,max_length=100)
    outlineTeamId:str=Field(min_length=1,max_length=100)

class AnalyticsBody(BaseModel):
    model_config={'extra':'forbid'}
    actor:AnalyticsActor
    collectionId:uuid.UUID|None=None
    owner:str=Field(default='',max_length=254)
    managed:bool|None=None
    horizon:int=Field(default=7,ge=1,le=30)

@app.post('/internal/outline-analytics/{action}')
async def outline_analytics_bridge(action:str,body:AnalyticsBody,request:Request):
    from starlette.concurrency import run_in_threadpool
    raw=await request.body()
    def execute():
        outline_bridge.verify(raw,request.url.path,request.headers,feature='analytics')
        user=outline_bridge.actor(body.actor.model_dump())
        if action=='capabilities':return analytics_service.capabilities(user,include_projects=True)
        if action not in ('query','refresh'):raise HTTPException(404,'지원하지 않는 통계 요청입니다.')
        if body.horizon not in (7,30):raise HTTPException(422,'마감 확인 기간은 7일 또는 30일을 선택하세요.')
        options={'collection_id':str(body.collectionId) if body.collectionId else '', 'owner':body.owner,
                 'horizon':body.horizon,'managed':body.managed if body.managed is not None else bool(user.get('admin')),'strict':True}
        # Validate the range before starting an expensive global refresh.
        data=analytics_service.query(user,**options)
        if action=='refresh':
            outline.sync_shared()
            data=analytics_service.query(user,**options)
        return data
    return await run_in_threadpool(execute)

class KanbanActor(AnalyticsActor):
    canUpdate:bool=False

class KanbanGrant(BaseModel):
    model_config={'extra':'forbid'}
    id:uuid.UUID
    canUpdate:bool=False

class TaskEditCriterion(BaseModel):
    model_config={'extra':'forbid'}
    id:str=Field(default='',max_length=20)
    title:str=Field(min_length=2,max_length=160)
    owner:str=Field(min_length=3,max_length=200)

class TaskEditChanges(BaseModel):
    model_config={'extra':'forbid'}
    owner:str|None=Field(default=None,min_length=3,max_length=200)
    start:str|None=Field(default=None,max_length=10)
    due:str|None=Field(default=None,max_length=10)
    shiftDays:int|None=Field(default=None,ge=-3660,le=3660)
    shiftBoth:bool=False
    transferCriteria:bool=False
    reopen:bool=False
    criteria:list[TaskEditCriterion]|None=Field(default=None,max_length=40)

class TaskEditItem(BaseModel):
    model_config={'extra':'forbid'}
    documentId:uuid.UUID
    revision:int=Field(ge=0)
    updatedAt:str=Field(min_length=1,max_length=100)
    changes:TaskEditChanges
    canUpdate:bool=False

class KanbanBody(BaseModel):
    model_config={'extra':'forbid'}
    actor:KanbanActor
    collectionId:uuid.UUID
    parentDocumentId:uuid.UUID
    grants:list[KanbanGrant]=Field(default_factory=list,max_length=1000)
    documentId:uuid.UUID|None=None
    requestId:uuid.UUID|None=None
    revision:int|None=Field(default=None,ge=0)
    updatedAt:str=Field(default='',max_length=100)
    status:str=Field(default='',max_length=20)
    criterionId:str=Field(default='',max_length=200)
    criterionState:str=Field(default='',max_length=20)
    edits:list[TaskEditItem]=Field(default_factory=list,max_length=100)

@app.post('/internal/outline-kanban/{action}')
async def outline_kanban_bridge(action:str,body:KanbanBody,request:Request):
    from starlette.concurrency import run_in_threadpool
    from . import kanban, task_edit
    raw=await request.body()
    def execute():
        outline_bridge.verify(raw,request.url.path,request.headers,feature='kanban')
        user=outline_bridge.actor(body.actor.model_dump())
        payload=body.model_dump(mode='json',exclude={'actor'})
        cid,parent_id=payload['collectionId'],payload['parentDocumentId']
        if action=='info':return kanban.info(user,cid,parent_id)
        if action=='query':
            if len({g.id for g in body.grants})!=len(body.grants):raise HTTPException(422,'문서 ID가 중복되었습니다.')
            return kanban.query(user,cid,parent_id,payload['grants'])
        if action in ('preview','edit','undo'):
            if not body.requestId or not body.edits or len({i.documentId for i in body.edits})!=len(body.edits):
                raise HTTPException(422,'중복 없는 업무와 변경 요청 번호가 필요합니다.')
            payload['edits']=[i.model_dump(mode='json',exclude_none=True,exclude_unset=True) for i in body.edits]
            if action=='preview':return task_edit.preview(user,payload)
            return task_edit.mutate(user,payload,undo=action=='undo')
        if action=='mutate':
            if not body.documentId or not body.requestId or body.revision is None or not body.updatedAt:
                raise HTTPException(422,'변경 요청과 원본 버전을 확인하세요.')
            return kanban.mutate(user,payload,body.actor.canUpdate)
        raise HTTPException(404,'지원하지 않는 칸반 요청입니다.')
    return await run_in_threadpool(execute)

class TaskCreationActor(AnalyticsActor):
    canCreateChild:bool=False
    canReadSource:bool=False

class TaskCreationCriterion(BaseModel):
    model_config={'extra':'forbid'}
    title:str=Field(min_length=1,max_length=200)
    assigneeId:str=Field(min_length=1,max_length=200)

class TaskCreationSource(BaseModel):
    model_config={'extra':'forbid'}
    documentId:uuid.UUID
    revision:int=Field(ge=0)
    from_:int=Field(alias='from',ge=0)
    to:int=Field(gt=0)
    quote:str=Field(min_length=1,max_length=10000)
    prefix:str=Field(max_length=64)
    suffix:str=Field(max_length=64)

class TaskCreationBody(BaseModel):
    model_config={'extra':'forbid'}
    actor:TaskCreationActor
    collectionId:uuid.UUID
    parentDocumentId:uuid.UUID|None=None
    requestId:uuid.UUID|None=None
    title:str=Field(default='',max_length=150)
    ownerId:str=Field(default='',max_length=200)
    startDate:str|None=Field(default=None,max_length=10)
    dueDate:str|None=Field(default=None,max_length=10)
    notes:str=Field(default='',max_length=10000)
    resultUrl:str=Field(default='',max_length=2000)
    criteria:list[TaskCreationCriterion]=Field(default_factory=list,max_length=40)
    source:TaskCreationSource|None=None
    sourceTitle:str=Field(default='',max_length=500)
    sourceUrl:str=Field(default='',max_length=2000)

@app.post('/internal/outline-tasks/{action}')
async def outline_task_creation_bridge(action:str,body:TaskCreationBody,request:Request):
    from starlette.concurrency import run_in_threadpool
    from . import task_creation
    raw=await request.body()
    def execute():
        outline_bridge.verify(raw,request.url.path,request.headers,feature='tasks')
        user=outline_bridge.actor(body.actor.model_dump())
        payload=body.model_dump(mode='json',by_alias=True,exclude={'actor'})
        if action=='resolve':return task_creation.resolve_target(user,payload['collectionId'])
        if not body.parentDocumentId:raise HTTPException(422,'업무 목록을 확인하세요.')
        if action=='status':
            if not body.requestId:raise HTTPException(422,'등록 요청 번호가 필요합니다.')
            return task_creation.status(user,payload,body.actor.canCreateChild,body.actor.canReadSource)
        if action=='info':return task_creation.info(user,payload['collectionId'],payload['parentDocumentId'],body.actor.canCreateChild)
        if action=='create':
            if not body.requestId:raise HTTPException(422,'등록 요청 번호가 필요합니다.')
            return task_creation.create(user,payload,body.actor.canCreateChild,body.actor.canReadSource)
        raise HTTPException(404,'지원하지 않는 업무 등록 요청입니다.')
    return await run_in_threadpool(execute)

class RecurringBody(BaseModel):
    model_config={'extra':'forbid'}
    actor:TaskCreationActor
    collectionId:uuid.UUID
    parentDocumentId:uuid.UUID
    payload:dict=Field(default_factory=dict)

@app.post('/internal/outline-recurring/{action}')
async def outline_recurring_bridge(action:str,body:RecurringBody,request:Request):
    from starlette.concurrency import run_in_threadpool
    raw=await request.body()
    def execute():
        if not recurring_service.enabled():raise HTTPException(404,'반복 업무 기능이 활성화되지 않았습니다.')
        outline_bridge.verify(raw,request.url.path,request.headers,feature='tasks')
        user=outline_bridge.actor(body.actor.model_dump())
        cid,parent_id=str(body.collectionId),str(body.parentDocumentId)
        payload={**body.payload,'collectionId':cid,'parentDocumentId':parent_id}
        if action=='query':return recurring_service.query(user,cid,parent_id,body.actor.canCreateChild)
        if action=='history':return recurring_service.history(user,cid,parent_id,payload['ruleId'])
        if not body.actor.canCreateChild:raise HTTPException(403,'업무 목록에 문서를 작성할 권한이 필요합니다.')
        if action=='preview':return recurring_service.preview(user,cid,parent_id,payload['settings'],payload.get('todayMode','next'))
        if action=='save':return recurring_service.save(user,body.actor.model_dump(),payload)
        if action in ('pause','resume','archive','adopt'):return recurring_service.change(user,body.actor.model_dump(),payload,action)
        if action in ('retry','skip'):return recurring_service.process_occurrence(user,payload,action)
        raise HTTPException(404,'지원하지 않는 반복 업무 요청입니다.')
    return await run_in_threadpool(execute)

@app.middleware('http')
async def secure_headers(request,call_next):
    token=permissions.request_snapshots.set({})
    try:r=await call_next(request)
    finally:permissions.request_snapshots.reset(token)
    r.headers['X-Content-Type-Options']='nosniff';r.headers['X-Frame-Options']='DENY'
    r.headers['Referrer-Policy']='same-origin';r.headers['Cache-Control']='no-store'
    r.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    return r

@app.exception_handler(ValueError)
async def bad_value(request,ex):return JSONResponse({'detail':str(ex)},status_code=422)

@app.get('/')
def home():return FileResponse(Path(__file__).parent/'static/index.html')
@app.get('/app.js')
def js():return FileResponse(Path(__file__).parent/'static/projects.js',media_type='text/javascript')
@app.get('/style.css')
def css():return FileResponse(Path(__file__).parent/'static/style.css',media_type='text/css')
@app.get('/analytics.js')
def analytics_js():return FileResponse(Path(__file__).parent/'static/analytics.js',media_type='text/javascript')
@app.get('/analytics.css')
def analytics_css():return FileResponse(Path(__file__).parent/'static/analytics.css',media_type='text/css')
@app.get('/workflow.css')
def workflow_css():return FileResponse(Path(__file__).parent/'static/workflow.css',media_type='text/css')
@app.get('/accounts.js')
def accounts_js():return FileResponse(Path(__file__).parent/'static/accounts.js',media_type='text/javascript')
@app.get('/api/accounts')
def accounts(user=Depends(auth.current)):
    auth.admin(user)
    return lifecycle.status(user)
@app.post('/api/accounts/sync')
def account_sync(user=Depends(auth.current)):
    auth.admin(user)
    result=lifecycle.reconcile()
    lifecycle.audit('manual_sync',{'actor':user['email'],'ok':result['ok']})
    return result
@app.get('/api/accounts/groups')
def account_groups(user=Depends(auth.current)):
    auth.admin(user)
    return {'groups':[{'id':str(g['pk']),'name':g['name']} for g in lifecycle.inventory('core/groups/')]}
class AccountGroup(BaseModel):
    authentik_id:str=Field(min_length=1,max_length=100)
@app.post('/api/accounts/groups')
def account_group(body:AccountGroup,user=Depends(auth.current)):
    auth.admin(user)
    return lifecycle.map_group(body.authentik_id,user)
@app.get('/workhub-logo.png')
def workhub_logo():return FileResponse(Path(__file__).parent/'static/workhub-logo.png',media_type='image/png')
@app.get('/health')
def health():return {'ok':True}

def internal_service(request:Request):
    import secrets
    if not secrets.compare_digest(request.headers.get('X-Service-Token',''),os.environ['AGENT_TOKEN']):
        raise HTTPException(401,'서비스 인증이 필요합니다.')

class SearchIdentity(BaseModel):
    email:str=Field(max_length=320)
    user_id:str=Field(min_length=1,max_length=200)
    subject:str=Field(min_length=1,max_length=200)

@app.post('/internal/search/identity',dependencies=[Depends(internal_service)])
def search_identity_issue(body:SearchIdentity):
    user=search_identity.webui_user(body.email,body.subject,body.user_id)
    return {'token':search_identity.issue(user,body.user_id)}

class SearchAccess(BaseModel):
    token:str=Field(max_length=4000)
    documents:list[str]=Field(default_factory=list,max_length=100)
    collections:list[str]=Field(default_factory=list,max_length=100)
    write:bool=False

@app.post('/internal/search/access',dependencies=[Depends(internal_service)])
def search_access(body:SearchAccess):
    identity=search_identity.decode(body.token)
    user=knowledge.current_user(identity['sub'])
    if knowledge.enabled():
        result=knowledge.live_access(user,body.documents)
        if set(body.collections)-set(result['collections']):raise HTTPException(403,'선택한 컬렉션을 읽을 권한이 없습니다.')
        if body.write and not user.get('admin'):raise HTTPException(403,'문서 직접 수정은 관리자만 할 수 있습니다.')
        return {**result,'user_id':identity['user_id']}
    access=permissions.Access(user)
    allowed=[cid for cid in access.collections if access.readable(cid)]
    if any(cid not in allowed for cid in body.collections):raise HTTPException(403,'요청한 문서함의 Outline 읽기 권한이 없습니다.')
    documents=[]
    for did in body.documents:
        d=outline.api('documents.info',{'id':did},missing_ok=True)
        if d and not d.get('deletedAt') and not d.get('archivedAt') and d.get('publishedAt') and d.get('collectionId') in allowed:
            documents.append(d['id'])
    if body.write and not user.get('admin'):raise HTTPException(403,'문서 비서의 문서 직접 수정은 관리자만 할 수 있습니다. 업무 보고는 Workhub에서 진행하세요.')
    return {'collections':allowed,'documents':documents,'user_id':identity['user_id']}
@app.get('/auth/login')
def login():return auth.login()
@app.get('/auth/callback')
def callback(request:Request,code:str='',state:str=''):return auth.callback(request,code,state)
@app.post('/auth/logout')
def logout(request:Request,user=Depends(auth.current)):
    with store.db() as c:
        c.execute('DELETE FROM sessions WHERE id=?',(request.cookies.get(auth.COOKIE),))
        c.execute('DELETE FROM identities WHERE sub=?',(user['sub'],))
    r=JSONResponse({'ok':True});r.delete_cookie(auth.COOKIE);return r

@app.get('/api/me')
def me(user=Depends(auth.current)):
    ps=permissions.projects(user)
    return {**user,'project_management_outline':outline_bridge.enabled(),'links':{'outline':outline.PUBLIC,'chat':os.environ['CHAT_PUBLIC_URL'],'webui':os.environ['WEBUI_PUBLIC_URL'],'auth':auth.ISSUER.split('/application')[0]},'collection':ps[0]['id'] if ps else '', 'projects':ps}
@app.get('/api/projects')
def projects(user=Depends(auth.current)):
    return {'projects':permissions.projects(user)}
@app.get('/api/assignees')
def assignees(collection_id:str='',user=Depends(auth.current)):
    if not collection_id:return {'people':[],'names':{},'note':'프로젝트를 먼저 선택하세요.'}
    ps=permissions.assignees(user,permissions.project(user,collection_id)['id'])
    return {'people':ps,'names':{p['email']:p['name'] for p in ps},
            'note':'선택한 프로젝트에 직접 또는 그룹으로 접근할 수 있는 활성 Outline 구성원입니다.'}
@app.get('/api/project-candidates')
def candidates(user=Depends(auth.current)):
    auth.admin(user)
    existing={p['id'] for p in outline.projects()}
    access=permissions.Access(user)
    return {'collections':[{'id':p['id'],'name':p['name']} for p in access.collections.values() if p['id'] not in existing and access.readable(p['id'])]}
class ProjectCreate(BaseModel):
    name:str=Field(default='',max_length=100)
    existing_id:str=Field(default='',max_length=100)
    idem:str=Field(min_length=8,max_length=100)
@app.post('/api/projects')
def project_create(body:ProjectCreate,user=Depends(auth.current)):
    project_management_location()
    p=outline.register_project(user,body.name,body.existing_id,body.idem)
    outline.sync()
    return p
class ProjectUnlink(BaseModel):
    model_config={'extra':'forbid'}
    idem:str=Field(min_length=8,max_length=100)
    delete_task_list:bool=False
    expected_parent_id:str=Field(default='',max_length=100)
class ProjectManager(BaseModel):
    manager:str=Field(default='',max_length=200)
@app.get('/api/projects/{collection_id}/managers')
def project_managers(collection_id:str,user=Depends(auth.current)):
    return {'people':outline.project_managers(user,collection_id)}
@app.post('/api/projects/{collection_id}/manager')
def project_manager(collection_id:str,body:ProjectManager,user=Depends(auth.current)):
    project_management_location()
    return outline.set_project_manager(user,collection_id,body.manager)
@app.get('/api/projects/{collection_id}/unlink-preview')
def project_unlink_preview(collection_id:str,user=Depends(auth.current)):
    return outline.unlink_preview(user,collection_id)
@app.post('/api/projects/{collection_id}/unlink')
def project_unlink(collection_id:str,body:ProjectUnlink,user=Depends(auth.current)):
    project_management_location()
    return outline.unlink_project(user,collection_id,body.idem,body.delete_task_list,body.expected_parent_id)
@app.get('/api/tasks')
def tasks(collection_id:str='',user=Depends(auth.current)):return {'tasks':outline.tasks(collection_id,user),'sync':{k:v for k,v in (store.get('last_sync') or {}).items() if k in ('at','ok')},'bot':store.get('bot_status')}
@app.post('/api/sync')
def sync(user=Depends(auth.current)):
    outline.sync_shared()
    return {'tasks':outline.tasks(user=user)}

class Create(BaseModel):
    title:str=Field(min_length=1,max_length=150)
    fields:dict
    idem:str=Field(min_length=8,max_length=100)
    notes:str=Field(default='',max_length=10000)
    collection_id:str=Field(default='',max_length=100)
    criteria:list[dict]=Field(default_factory=list,max_length=40)
    assignee_id:str=Field(default='',max_length=200)
@app.post('/api/tasks')
def create(body:Create,user=Depends(auth.current)):
    cid=permissions.project(user,body.collection_id)['id']
    fields={**body.fields,'owner':permissions.resolve(user,cid,body.assignee_id)} if body.assignee_id else body.fields
    return outline.create(user,body.title,fields,body.idem,body.notes,cid,permissions.assignments(user,cid,body.criteria))

class Change(BaseModel):
    changes:dict
    idem:str=Field(min_length=8,max_length=100)
    notes:str=Field(default='',max_length=4000)
@app.post('/api/tasks/{docid}/proposals')
def propose(docid:str,body:Change,user=Depends(auth.current)):
    changes={**body.changes}
    if 'criteria' in changes:
        auth.admin(user)
        d=outline.document(docid,user)
        changes['criteria']=permissions.assignments(user,d['collectionId'],changes['criteria'])
    return outline.propose(user,docid,changes,body.idem,body.notes)
@app.get('/api/proposals/{pid}')
def proposal(pid:str,user=Depends(auth.current)):return outline.proposal(user,pid)
@app.post('/api/proposals/{pid}/confirm')
def confirm(pid:str,user=Depends(auth.current)):return outline.confirm(user,pid)
@app.post('/api/proposals/{pid}/cancel')
def cancel(pid:str,user=Depends(auth.current)):return outline.cancel(user,pid)

class Report(BaseModel):
    code:str
    text:str=Field(min_length=5,max_length=4000)
    idem:str=Field(min_length=8,max_length=100)
    collection_id:str=Field(default='',max_length=100)
    criterion_id:str=Field(default='',max_length=100)
@app.post('/api/report')
def report(body:Report,user=Depends(auth.current)):return assistant.report(user,body.code,body.text,body.idem,body.collection_id,body.criterion_id)
class Question(BaseModel):
    text:str=Field(min_length=2,max_length=1000)
    collection_id:str=Field(default='',max_length=100)
@app.post('/api/research')
def research(body:Question,user=Depends(auth.current)):return assistant.research(user,body.text,body.collection_id)

@app.get('/api/research/status')
def research_status(collection_id:str,user=Depends(auth.current)):return search.status(user,collection_id)

@app.post('/api/research/refresh')
def research_refresh(body:Question,user=Depends(auth.current)):return search.refresh(user,body.collection_id)

@app.get('/api/stats')
def stats(project:str='',owner:str='',collection_id:str='',user=Depends(auth.current)):
    # Legacy administrator statistics must not bypass personal analytics restrictions.
    auth.admin(user)
    ts=[t for t in outline.tasks(collection_id,user) if (not project or t['fields'].get('project')==project) and (not owner or t['fields'].get('owner')==owner or any(i['owner']==owner for i in t.get('criteria',[])))]
    events=outline.history(user)
    history=[e for e in events if (not collection_id or e['body'].get('collectionId')==outline.project(collection_id)['id']) and (not project or e['body']['fields'].get('project')==project) and (not owner or e['body']['fields'].get('owner')==owner or any(i['owner']==owner for i in e['body'].get('criteria',[])))]
    groups={}
    for t in ts:
        name=t['fields'].get('owner','확인 필요');groups.setdefault(name,[]).append(t)
    checklist=[i for t in ts if not t.get('error') for i in t.get('criteria',[]) if not owner or i['owner']==owner]
    by_owner={}
    for i in checklist:
        o=by_owner.setdefault(i['owner'],{'total':0,**{s:0 for s in criteria.STATES}})
        o['total']+=1;o[i['state']]+=1
    return {'summary':domain.statistics(ts),'owners':{k:domain.statistics(v) for k,v in groups.items()},'events':history,'sync':{k:v for k,v in (store.get('last_sync') or {}).items() if k in ('at','ok')},
            'criteria':{'total':len(checklist),'completed':sum(i['state']=='완료' for i in checklist),'owners':by_owner,
                        'progress':round(100*sum(i['state']=='완료' for i in checklist)/len(checklist),1) if checklist else 0}}

@app.get('/api/analytics')
def planning_stats(collection_id:str='',owner:str='',horizon:int=Query(default=7,ge=1,le=90),managed:bool=False,user=Depends(auth.current)):
    return analytics_service.query(user,collection_id,owner,horizon,managed)

@app.get('/api/weekly')
def weekly(collection_id:str='',user=Depends(auth.current)):
    auth.admin(user);selected=permissions.project(user,collection_id);text=outline.weekly(user,selected['id']);pid=uuid.uuid4().hex
    store.put('weekly:'+pid,{'owner':user['sub'],'text':text,'collectionId':selected['id']})
    return {'id':pid,'text':text}
@app.post('/api/weekly/{pid}/publish')
def publish(pid:str,user=Depends(auth.current)):
    auth.admin(user)
    with outline.MUTEX:
        p=store.get('weekly:'+pid)
        if not p or p['owner']!=user['sub']:raise HTTPException(404,'본인의 보고서 초안이 아닙니다.')
        permissions.project(user,p.get('collectionId',''))
        if p.get('url'):return p
        did=p.setdefault('doc_id',str(uuid.uuid4()));store.put('weekly:'+pid,p)
        cid=outline.project(p.get('collectionId',''))['id']
        old=next((d for d in outline.all_items('documents.list',{'collectionId':cid}) if d['id']==did),None)
        d=old or outline.api('documents.create',{'id':did,'collectionId':cid,'title':'프로젝트 업무 현황 '+store.now()[:10],'text':p['text'],'publish':True})
        p['url']=outline.PUBLIC+d['url'];store.put('weekly:'+pid,p);return p

@app.get('/api/operations')
def operations(user=Depends(auth.current)):
    auth.admin(user)
    with store.db() as c:
        counts={t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['tasks','events','proposals','sessions']}
    return {'counts':counts,'sync':store.get('last_sync'),'bot':store.get('bot_status'),'model':os.getenv('LOCAL_LLM_MODEL'),'history_note':'Outline에서 관측된 버전의 이력입니다. 동기화 사이에 발생한 모든 키 입력을 기록하지는 않습니다.'}
