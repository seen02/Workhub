"""Authenticated Outline server bridge; never trust browser supplied identities."""
import hashlib, hmac, json, os, time
from fastapi import HTTPException
from . import store, lifecycle, outline, permissions

def enabled():
    return os.getenv('OUTLINE_PROJECT_MANAGEMENT_ENABLED','false').lower()=='true'

def verify(raw, path, headers, feature=None):
    from . import analytics_service, task_creation, kanban
    feature = feature or 'projects'
    switches = {'projects': enabled, 'analytics': analytics_service.enabled, 'tasks': task_creation.enabled, 'kanban': kanban.enabled}
    if feature not in switches or not switches[feature]():raise HTTPException(404,'요청한 Outline 기능이 활성화되지 않았습니다.')
    key=os.getenv('OUTLINE_WORKHUB_BRIDGE_SECRET','')
    stamp=headers.get('x-workhub-time','');nonce=headers.get('x-workhub-nonce','')
    signature=headers.get('x-workhub-signature','')
    try:valid=abs(time.time()-int(stamp))<=60 and 16<=len(nonce)<=100
    except ValueError:valid=False
    message='\n'.join(['POST',path,stamp,nonce,hashlib.sha256(raw).hexdigest()])
    if not key or not valid or not hmac.compare_digest(signature,hmac.new(key.encode(),message.encode(),hashlib.sha256).hexdigest()):
        raise HTTPException(401,'Outline 연동 인증에 실패했습니다.')
    with store.db() as c:
        c.execute('DELETE FROM bridge_nonces WHERE expires<?',(time.time(),))
        if c.execute('SELECT 1 FROM bridge_nonces WHERE nonce=?',(nonce,)).fetchone():raise HTTPException(401,'이미 사용한 인증 요청입니다.')
        c.execute('INSERT INTO bridge_nonces VALUES(?,?)',(nonce,time.time()+180))

def live_employee(row):
    if not row or row.get('review'):
        raise HTTPException(403,'계정 연결을 확인하세요. 관리자 계정 동기화가 필요합니다.')
    from .service_identity import for_subject
    return for_subject(row['sub'])

def actor(identity):
    if identity['outlineTeamId']!=os.getenv('OUTLINE_WORKHUB_TEAM_ID'):
        raise HTTPException(403,'허용되지 않은 Outline 워크스페이스입니다.')
    rows=[r for r in lifecycle.records() if r.get('outline_id')==identity['outlineUserId']]
    if len(rows)!=1:raise HTTPException(403,'계정 연결을 확인하세요. 관리자 계정 동기화가 필요합니다.')
    user=live_employee(rows[0])
    person=outline.api('users.info',{'id':identity['outlineUserId']})
    if person.get('isSuspended') or person.get('deletedAt') or person.get('email','').lower()!=user['email']:
        raise HTTPException(403,'활성 Outline 계정 연결이 필요합니다.')
    return user

def managers(user,cid):
    from .auth import admin
    admin(user)
    eligible={p['email'].lower() for p in permissions.Access(user).participants(cid)}
    result=[]
    for row in lifecycle.records():
        if row['email'] not in eligible:continue
        try:person=live_employee(row)
        except HTTPException as ex:
            if ex.status_code==503:raise
            continue
        if person['admin']:result.append({'id':person['sub'],'name':person['name'],'email':person['email']})
    return sorted(result,key=lambda p:(p['name'],p['email']))
