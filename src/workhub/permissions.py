"""Live Outline ACLs. Workhub roles never grant membership in an Outline collection.

Matches the installed Outline collection readDocument policy: team-visible collections
are readable by non-guests; private collections/guests need a direct or group grant.
No cross-request ACL cache: removed memberships take effect on the next operation.
"""
from fastapi import HTTPException
from . import outline
from contextvars import ContextVar

# Cache only within ONE HTTP request. A later click/search rechecks live ACLs.
request_snapshots=ContextVar('outline_acl_request_snapshots',default=None)

READ={'read','read_write','admin'}

def active(person):
    from .lifecycle import allowed_email
    return not person.get('deletedAt') and not person.get('isSuspended') and allowed_email(person.get('email',''))

def rows(method,body,key):
    result=[]
    for offset in range(0,100000,100):
        data=outline.api(method,{**body,'limit':100,'offset':offset})
        page=data.get(key,[]) if isinstance(data,dict) else data
        if not isinstance(page,list):raise HTTPException(503,'Outline 권한 정보를 확인하지 못했습니다.')
        result.extend(page)
        if len(page)<100:return result
    raise HTTPException(503,'Outline 권한 목록을 모두 확인하지 못했습니다.')

class Access:
    def __init__(self,user):
        self.user=user
        snapshots=request_snapshots.get();key=((user or {}).get('sub'),(user or {}).get('email'))
        if snapshots is not None and key in snapshots:
            from .execution import count
            count('cache_hit.permissions')
            self.__dict__.update(snapshots[key].__dict__);self.user=user;return
        self.users=[p for p in outline.all_items('users.list') if active(p)]
        matches=[p for p in self.users if p.get('email','').lower()==(user or {}).get('email','').lower()]
        if user is not None and len(matches)!=1:raise HTTPException(403,'활성 Outline 계정이 필요합니다. Outline에 먼저 로그인하세요.')
        self.person=matches[0] if matches else None
        # Inventory through the service admin, then authorize the requesting person below.
        # The API key owner's default list omits private collections owned by other users.
        self.collections={p['id']:p for p in outline.all_items('collections.list',{'includeListOnly':True}) if not p.get('deletedAt') and not p.get('archivedAt')}
        self.grants={};self.groups={}
        if snapshots is not None:snapshots[key]=self

    def member_ids(self,cid):
        if cid in self.grants:return self.grants[cid]
        if cid not in self.collections:raise HTTPException(403,'이 프로젝트에 접근할 권한이 없습니다.')
        direct=rows('collections.memberships',{'id':cid},'memberships')
        ids={m['userId'] for m in direct if m.get('permission') in READ}
        for grant in rows('collections.group_memberships',{'id':cid},'groupMemberships'):
            if grant.get('permission') not in READ:continue
            gid=grant['groupId']
            if gid not in self.groups:
                self.groups[gid]={m.get('userId') or m.get('user',{}).get('id') for m in rows('groups.memberships',{'id':gid},'groupMemberships')}
            ids.update(self.groups[gid])
        self.grants[cid]=ids
        return ids

    def readable(self,cid,person=None):
        person=person or self.person
        collection=self.collections.get(cid)
        if not collection:return False
        if collection.get('permission') in READ and person.get('role')!='guest':return True
        return person['id'] in self.member_ids(cid)

    def require(self,cid):
        if not self.readable(cid):raise HTTPException(403,'이 프로젝트의 Outline 읽기 권한이 없습니다.')
        return self.collections[cid]

    def projects(self):
        return [p for p in outline.projects() if self.readable(p['id'])]

    def participants(self,cid):
        self.require(cid)
        return [p for p in self.users if p.get('email') and self.readable(cid,p)]

def collection_people(cid):
    access=Access(None)
    return [p for p in access.users if access.readable(cid,p)]

def projects(user):return Access(user).projects()

PROJECT_LINK_ACCESS_ERROR='API 키 계정에 이 컬렉션의 문서 조회·생성·수정 권한이 없어 프로젝트로 연결할 수 없습니다.'

def project_connection_group():
    """Resolve the configured group and verify the actual token owner is a member."""
    groups=[g for g in outline.all_items('groups.list') if g.get('name')=='Connect_as_a_project']
    if len(groups)!=1:
        raise HTTPException(409,'Connect_as_a_project 그룹을 찾을 수 없습니다. Outline에서 그룹을 만든 뒤 다시 시도하세요.')
    identity=outline.api('auth.info')
    person=identity.get('user',{}) if isinstance(identity,dict) else {}
    if not person.get('id') or not active(person):
        raise HTTPException(403,'활성 API 키 계정을 확인할 수 없습니다.')
    members=rows('groups.memberships',{'id':groups[0]['id']},'groupMemberships')
    if not any((m.get('userId') or m.get('user',{}).get('id'))==person['id'] for m in members):
        raise HTTPException(409,'Connect_as_a_project 그룹에 API 키를 발급받은 Admin 계정이 없습니다. 계정을 그룹에 추가한 뒤 다시 시도하세요.')
    return {'groupId':groups[0]['id'],'serviceUserId':person['id']}

def require_project_linkable(collection):
    """Require native document abilities of the API key owner, even for public collections.

    Outline admins may read private collection metadata without document access.
    Policies are evaluated by Outline with the token owner's direct/group grants;
    no display name, actor role, or collection visibility can substitute for them.
    """
    cid=collection['id']
    try:response=outline.collection_access(cid)
    except HTTPException as error:
        if error.status_code==502 and error.detail=='Outline collections.info 요청 실패 (403)':
            raise HTTPException(403,PROJECT_LINK_ACCESS_ERROR) from error
        raise
    policies=response.get('policies') if isinstance(response,dict) else None
    data=response.get('data') if isinstance(response,dict) else None
    if not isinstance(data,dict) or data.get('id')!=cid or not isinstance(policies,list):
        raise HTTPException(503,'API 키 계정의 컬렉션 권한을 확인하지 못했습니다. 잠시 후 다시 시도하세요.')
    matches=[p.get('abilities') for p in policies if isinstance(p,dict) and p.get('id')==cid]
    required=('readDocument','createDocument','updateDocument')
    if len(matches)!=1 or not isinstance(matches[0],dict) or any(k not in matches[0] for k in required):
        raise HTTPException(503,'API 키 계정의 컬렉션 권한을 확인하지 못했습니다. 잠시 후 다시 시도하세요.')
    def granted(value):
        # Native policies serialize a grant as true or nonempty membership IDs.
        return value is True or (isinstance(value,list) and bool(value) and all(isinstance(v,str) and v for v in value))
    if not all(granted(matches[0][k]) for k in required):
        raise HTTPException(403,PROJECT_LINK_ACCESS_ERROR)


def require_create(user,cid):
    """Creating a report task requires Outline write access, not only membership."""
    access=Access(user);collection=access.require(cid);person=access.person
    if collection.get('permission') in ('read_write','admin') and person.get('role')!='guest':return
    for m in rows('collections.memberships',{'id':cid},'memberships'):
        if m.get('userId')==person['id'] and m.get('permission') in ('read_write','admin'):return
    for grant in rows('collections.group_memberships',{'id':cid},'groupMemberships'):
        if grant.get('permission') not in ('read_write','admin'):continue
        members=rows('groups.memberships',{'id':grant['groupId']},'groupMemberships')
        if any((m.get('userId') or m.get('user',{}).get('id'))==person['id'] for m in members):return
    raise HTTPException(403,'이 프로젝트에 새 문서를 작성할 Outline 권한이 없습니다.')

def project(user,code=''):
    access=Access(user)
    if not code:
        ps=access.projects()
        if not ps:raise HTTPException(403,'접근 가능한 프로젝트가 없습니다. Outline 구성원 권한을 확인하세요.')
        return ps[0]
    p=outline.project(code);access.require(p['id']);return p

def document(user,doc):
    from .project_service import ensure_writable
    ensure_writable(doc.get('collectionId',''))
    # Workhub tasks are published documents of a registered project.
    project(user,doc.get('collectionId',''))
    if not doc.get('collectionId') or not doc.get('publishedAt') or doc.get('archivedAt') or doc.get('deletedAt'):
        raise HTTPException(403,'이 문서에 접근할 권한이 없습니다.')
    return doc

def assignees(user,cid):
    from . import directory
    access=Access(user);people=access.participants(cid)
    labels=directory.names()
    return sorted([{'id':'outline:'+p['id'],'outline_id':p['id'],'email':p['email'].lower(),
                    'name':labels.get(p['email'].lower()) or p['name'],'username':p['email'],'active':True}
                   for p in people],key=lambda p:(p['name'],p['email']))

def resolve(user,cid,person_id):
    from . import directory
    candidates=assignees(user,cid)
    email=next((p['email'] for p in candidates if p['id']==person_id),None)
    if email is None:
        # Accept existing portal identity IDs only when they still belong here.
        email=directory.resolve(person_id)
    if email not in {p['email'] for p in candidates}:raise HTTPException(403,'선택한 프로젝트의 구성원만 담당자로 배정할 수 있습니다.')
    return email

def validate_owners(user,cid,items,old_items=()):
    allowed={p['email'] for p in assignees(user,cid)}
    previous={p['id']:p.get('owner','').lower() for p in old_items}
    for item in items:
        owner=str(item.get('owner','')).lower()
        if owner not in allowed and previous.get(item.get('id'))!=owner:
            raise HTTPException(403,'선택한 프로젝트의 구성원만 담당자로 배정할 수 있습니다.')

def assignments(user,cid,items):
    return [{**i,'owner':resolve(user,cid,i['assignee_id'])} if i.get('assignee_id') else i for i in items]
