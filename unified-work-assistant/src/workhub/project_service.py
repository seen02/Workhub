"""Durable, revision-checked project management shared by the Outline bridge."""
import hashlib, json, time
from fastapi import HTTPException
from . import store, outline, permissions, auth, search

def init():
    with store.db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS project_link_state(collection_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,linked INTEGER NOT NULL,last_manager_subject TEXT,last_manager_email TEXT,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS project_operations(request_id TEXT PRIMARY KEY,actor_subject TEXT NOT NULL,collection_id TEXT NOT NULL,action TEXT NOT NULL,payload_hash TEXT NOT NULL,expected_revision INTEGER NOT NULL,status TEXT NOT NULL,result TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS project_sync_jobs(collection_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,error TEXT,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS bridge_nonces(nonce TEXT PRIMARY KEY,expires REAL NOT NULL);
        ''')
        if 'payload' not in {r[1] for r in c.execute('PRAGMA table_info(project_operations)')}:
            c.execute('ALTER TABLE project_operations ADD COLUMN payload TEXT')
        row=c.execute("SELECT v FROM kv WHERE k='projects'").fetchone()
        registry=json.loads(row[0]) if row else []
        for p in registry:
            c.execute('INSERT OR IGNORE INTO project_link_state VALUES(?,1,1,NULL,?,?)',(p['id'],p.get('manager',''),store.now()))
        # Re-enabling after a legacy UI rollback must invalidate old revision receipts.
        linked={p['id']:p for p in registry}
        for s in c.execute('SELECT * FROM project_link_state').fetchall():
            current=linked.get(s['collection_id']);email=current.get('manager','') if current else s['last_manager_email']
            if bool(s['linked'])!=bool(current) or (current and email!=s['last_manager_email']):
                if not c.execute("SELECT 1 FROM project_operations WHERE collection_id=? AND status='pending'",(s['collection_id'],)).fetchone():
                    c.execute('UPDATE project_link_state SET revision=revision+1,linked=?,last_manager_subject=NULL,last_manager_email=?,updated_at=? WHERE collection_id=?',(int(bool(current)),email,store.now(),s['collection_id']))

def state(cid):
    with store.db() as c:
        row=c.execute('SELECT * FROM project_link_state WHERE collection_id=?',(cid,)).fetchone()
    return dict(row) if row else {'collection_id':cid,'revision':0,'linked':False,'last_manager_subject':None,'last_manager_email':''}

def require_manage(user,cid,can_manage=False):
    """Require a live identity's admin role or Outline's signed collection update policy."""
    if not (user.get('admin') or can_manage):
        raise HTTPException(403,'업무 관리자 또는 해당 컬렉션 관리 권한이 필요합니다.')
    return permissions.Access(user).require(cid)


def info(user,cid,can_delete=False,*,can_manage=False):
    collection=permissions.Access(user).require(cid)
    s=state(cid)
    with store.db() as c:
        job=c.execute('SELECT status FROM project_sync_jobs WHERE collection_id=?',(cid,)).fetchone()
        pending=c.execute("SELECT request_id,action,payload FROM project_operations WHERE collection_id=? AND status='pending'",(cid,)).fetchone()
    pending_body=json.loads(pending['payload']) if pending and pending['payload'] else {}
    manage=bool(user.get('admin') or can_manage)
    can_resume=manage and pending and (user.get('admin') or
        (pending['action'] in ('link','unlink') and not pending_body.get('deleteTaskList') and not pending_body.get('managerSubject')))
    return {'linked':bool(s['linked']),'revision':s['revision'],
        'project':{'id':cid,'name':collection['name'],'manager':s['last_manager_email'] if s['linked'] else '',
                   'managerSubject':s['last_manager_subject'] if s['linked'] else None},
        'permissions':{'manage':manage,'updateManager':bool(user.get('admin')),'deleteTaskList':bool(user.get('admin') and can_delete)},
        'syncStatus':job[0] if job else 'synced','pendingRequestId':pending[0] if pending else None,
        'pendingOperation':{'requestId':pending['request_id'],'action':pending['action'],'expectedParentId':pending_body.get('expectedParentId'),'deleteTaskList':pending_body.get('deleteTaskList',False)} if can_resume else None,
        'workhubUrl':auth.BASE}

def operation(user,cid,request_id,*,can_manage=False):
    require_manage(user,cid,can_manage)
    with store.db() as c:r=c.execute('SELECT * FROM project_operations WHERE request_id=? AND collection_id=?',(request_id,cid)).fetchone()
    if not r:raise HTTPException(404,'처리 기록을 찾을 수 없습니다.')
    return {'requestId':request_id,'operationStatus':r['status'],'result':json.loads(r['result']) if r['result'] else None,'current':info(user,cid,can_manage=can_manage)}

def prepare_link_access(user,body,*,can_manage=False):
    """Check the original link receipt before Outline changes any group permission."""
    cid=body['collectionId'];rid=body['requestId']
    require_manage(user,cid,can_manage)
    if len(rid)<8:raise HTTPException(422,'요청 번호가 필요합니다.')
    if body.get('managerSubject'):auth.admin(user)
    fingerprint=hashlib.sha256(store.dump({'action':'link','body':body}).encode()).hexdigest()
    with outline.MUTEX, store.db() as c:
        old=c.execute('SELECT * FROM project_operations WHERE request_id=?',(rid,)).fetchone()
        if old and (old['actor_subject']!=user['sub'] or old['payload_hash']!=fingerprint):
            raise HTTPException(409,'동일 요청 번호의 사용자 또는 내용이 다릅니다.')
        if old and old['status']=='completed':return False
        current=state(cid)
        if current['revision']!=body['expectedRevision'] or current['linked']:
            raise HTTPException(409,'프로젝트 설정이 변경되었습니다. 다시 불러오세요.')
        if c.execute("SELECT 1 FROM project_operations WHERE collection_id=? AND status='pending' AND request_id<>?",(cid,rid)).fetchone():
            raise HTTPException(409,'진행 중인 프로젝트 변경을 먼저 완료하세요.')
    return True

def preview(user,cid,can_delete=False,*,can_manage=False):
    require_manage(user,cid,can_manage)
    current=info(user,cid,can_delete,can_manage=can_manage)
    if not current['linked']:raise HTTPException(409,'이미 연결 해제된 프로젝트입니다.')
    return {**current,**outline.unlink_preview(user,cid,can_manage=can_manage)}

def resume(user,cid,request_id,expected_parent_id,can_delete=False,*,can_manage=False):
    require_manage(user,cid,can_manage)
    with store.db() as c:r=c.execute('SELECT * FROM project_operations WHERE request_id=? AND collection_id=?',(request_id,cid)).fetchone()
    if not r:raise HTTPException(404,'처리 기록을 찾을 수 없습니다.')
    if r['status']=='completed' and user.get('admin'):return json.loads(r['result'])
    if not r['payload']:raise HTTPException(409,'이전 요청의 복구 정보가 없습니다. 관리자 점검이 필요합니다.')
    body=json.loads(r['payload'])
    if r['action']=='manager' or body.get('deleteTaskList') or body.get('managerSubject'):auth.admin(user)
    if r['status']=='completed':return json.loads(r['result'])
    if body.get('expectedParentId')!=expected_parent_id:raise HTTPException(409,'복구할 문서가 다릅니다. 다시 확인하세요.')
    return mutate(user,r['action'],body,can_delete,recovering=True,can_manage=can_manage)

def mutate(user,action,body,can_delete=False,recovering=False,*,can_manage=False):
    from .outline_bridge import managers
    cid=body['collectionId'];rid=body['requestId'];revision=body['expectedRevision']
    collection=require_manage(user,cid,can_manage)
    if action=='link':permissions.require_project_linkable(collection)
    if action=='manager' or body.get('deleteTaskList') or body.get('managerSubject'):auth.admin(user)
    fingerprint=hashlib.sha256(store.dump({'action':action,'body':body}).encode()).hexdigest()
    # Same mutex as sync and task/report writes; database pending records also survive restart.
    with outline.MUTEX:
        with store.db() as c:
            old=c.execute('SELECT * FROM project_operations WHERE request_id=?',(rid,)).fetchone()
            if old and ((old['actor_subject']!=user['sub'] and not recovering) or old['payload_hash']!=fingerprint):
                raise HTTPException(409,'동일 요청 번호의 사용자 또는 내용이 다릅니다.')
            if old and old['status']=='completed':return {**json.loads(old['result']),'currentRevision':state(cid)['revision']}
        current=state(cid)
        if current['revision']!=revision:raise HTTPException(409,'프로젝트 설정이 변경되었습니다. 다시 불러오세요.')
        if action in ('manager','unlink') and not current['linked']:raise HTTPException(409,'연결된 프로젝트가 아닙니다.')
        if action=='link' and current['linked']:raise HTTPException(409,'이미 연결된 프로젝트입니다. 설정을 다시 불러오세요.')
        if action=='link':permissions.require_create(user,cid)
        selected=None
        if action in ('link','manager') and body.get('managerSubject'):
            selected=next((p for p in managers(user,cid) if p['id']==body['managerSubject']),None)
            if not selected:raise HTTPException(403,'접근 가능한 활성 관리자만 책임자가 될 수 있습니다.')
        deleting=action=='unlink' and body.get('deleteTaskList',False)
        if deleting:
            if not can_delete:raise HTTPException(403,'업무 목록을 삭제할 Outline 권한이 없습니다.')
            mapping=store.get('task-parent:'+cid)
            if not mapping or mapping['id']!=body.get('expectedParentId'):raise HTTPException(409,'업무 목록이 변경되었습니다. 미리보기를 다시 확인하세요.')
            parent=outline.api('documents.info',{'id':mapping['id']},missing_ok=True)
            if parent and not parent.get('deletedAt'):
                if parent.get('collectionId')!=cid or parent.get('parentDocumentId') or parent.get('archivedAt') or outline.domain.is_legacy_task(parent.get('text','')):
                    raise HTTPException(409,'업무 목록의 위치나 상태가 변경되었습니다.')
            elif not old:raise HTTPException(409,'삭제할 업무 목록을 확인할 수 없습니다.')
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            pending=c.execute("SELECT request_id FROM project_operations WHERE collection_id=? AND status='pending' AND request_id<>?",(cid,rid)).fetchone()
            if pending:raise HTTPException(409,'진행 중인 프로젝트 변경을 먼저 완료하세요.')
            live=c.execute('SELECT revision FROM project_link_state WHERE collection_id=?',(cid,)).fetchone()
            if (live[0] if live else 0)!=revision:raise HTTPException(409,'프로젝트 설정이 변경되었습니다.')
            c.execute('INSERT OR IGNORE INTO project_operations(request_id,actor_subject,collection_id,action,payload_hash,expected_revision,status,result,created_at,updated_at,payload) VALUES(?,?,?,?,?,?,\'pending\',NULL,?,?,?)',(rid,user['sub'],cid,action,fingerprint,revision,store.now(),store.now(),store.dump(body)))
        if action=='link':
            # The durable intent and task-parent ID make response-loss retries safe.
            # Complete registration only after a published task container is ready.
            outline.task_parent(cid)
        if deleting and parent and not parent.get('deletedAt'):
            # Persist intent before sending. A timeout keeps pending and retries inspect the same ID.
            outline.api('documents.delete',{'id':body['expectedParentId'],'permanent':False})
            after=outline.api('documents.info',{'id':body['expectedParentId']},missing_ok=True)
            if after and not after.get('deletedAt'):raise HTTPException(503,'휴지통 이동 결과를 확인하지 못했습니다. 같은 요청으로 다시 확인하세요.')
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            prior=c.execute('SELECT status,result FROM project_operations WHERE request_id=?',(rid,)).fetchone()
            if prior['status']=='completed':return json.loads(prior['result'])
            live=c.execute('SELECT revision FROM project_link_state WHERE collection_id=?',(cid,)).fetchone()
            if (live[0] if live else 0)!=revision:raise HTTPException(409,'프로젝트 설정이 변경되었습니다.')
            row=c.execute("SELECT v FROM kv WHERE k='projects'").fetchone();registry=json.loads(row[0]) if row else []
            if action=='unlink':
                registry=[p for p in registry if p['id']!=cid]
                for row in c.execute('SELECT id,body FROM tasks WHERE active=1').fetchall():
                    if json.loads(row['body']).get('collectionId')==cid:c.execute('UPDATE tasks SET active=0 WHERE id=?',(row['id'],))
                for row in c.execute("SELECT k,v FROM kv WHERE k LIKE 'chat-context:%'").fetchall():
                    if json.loads(row['v']).get('collectionId')==cid:c.execute('DELETE FROM kv WHERE k=?',(row['k'],))
                if deleting:c.execute('DELETE FROM kv WHERE k=?',('task-parent:'+cid,))
                manager=current['last_manager_email'];subject=current['last_manager_subject']
            else:
                manager=selected['email'] if selected else '';subject=selected['id'] if selected else None
                # Collection managers may reconnect without changing the previous responsibility.
                if action=='link' and not user.get('admin'):
                    manager=current['last_manager_email'];subject=current['last_manager_subject']
                if action=='link':registry.append({'id':cid,'name':permissions.Access(user).collections[cid]['name'],'manager':manager})
                else:
                    for p in registry:
                        if p['id']==cid:p['manager']=manager
            linked=action!='unlink';new_revision=revision+1
            result={'requestId':rid,'operationStatus':'completed','linked':linked,'revision':new_revision,'syncStatus':'pending','taskListDeleted':deleting,'appliedBy':user['sub']}
            c.execute('INSERT OR REPLACE INTO kv VALUES(?,?)',('projects',store.dump(registry)))
            c.execute('INSERT OR REPLACE INTO project_link_state VALUES(?,?,?,?,?,?)',(cid,new_revision,int(linked),subject,manager,store.now()))
            c.execute("UPDATE project_operations SET status='completed',result=?,updated_at=? WHERE request_id=?",(store.dump(result),store.now(),rid))
            c.execute("INSERT OR REPLACE INTO project_sync_jobs VALUES(?,?,'pending',0,NULL,?)",(cid,new_revision,store.now()))
        outline.PROJECTS_CACHE['until']=0;search.dirty.set()
        return result

def sync_snapshot():
    with store.db() as c:return [(r['collection_id'],r['revision']) for r in c.execute("SELECT collection_id,revision FROM project_sync_jobs WHERE status!='synced'").fetchall()]

def sync_complete(jobs,error=None):
    with store.db() as c:
        for cid,revision in jobs:
            c.execute("UPDATE project_sync_jobs SET status=?,attempts=attempts+1,error=?,updated_at=? WHERE collection_id=? AND revision=?",('error' if error else 'synced',error,store.now(),cid,revision))

def ensure_writable(cid):
    # Only the bridge creates these records; legacy installations retain existing behavior.
    with store.db() as c:
        exists=c.execute("SELECT 1 FROM sqlite_master WHERE name='project_operations'").fetchone()
        if exists and c.execute("SELECT 1 FROM project_operations WHERE collection_id=? AND action='unlink' AND status='pending'",(cid,)).fetchone():
            raise HTTPException(409,'프로젝트 연결 해제가 진행 중입니다. 처리가 끝난 뒤 다시 확인하세요.')
