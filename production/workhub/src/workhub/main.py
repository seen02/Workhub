"""Internal Outline-only project/task/kanban/statistics service."""
import logging, os, threading, uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from . import store, outline, lifecycle, outline_bridge, project_service, analytics_service, permissions, http_pool

logging.basicConfig(level=logging.INFO)

def configured():
    return all(os.getenv(k) for k in ('OUTLINE_API_KEY','OUTLINE_WORKHUB_TEAM_ID','AUTHENTIK_DIRECTORY_TOKEN'))

def background(stop):
    while not stop.is_set():
        if configured():
            jobs=project_service.sync_snapshot()
            try:
                lifecycle.reconcile(sync_names=False)
                outline.sync_shared()
                project_service.sync_complete(jobs)
            except Exception as error:
                project_service.sync_complete(jobs,type(error).__name__)
                logging.getLogger('workhub').warning('sync_pending type=%s',type(error).__name__)
        stop.wait(max(15,int(os.getenv('SYNC_INTERVAL_SECONDS','30'))))

@asynccontextmanager
async def lifespan(app):
    store.init()
    stop=threading.Event()
    worker=threading.Thread(target=background,args=(stop,),daemon=True)
    worker.start()
    yield
    stop.set()
    worker.join(timeout=5)

app=FastAPI(title='Custom Outline backend',lifespan=lifespan,docs_url=None,redoc_url=None)

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

@app.get('/health')
def health():return {'ok':True}
