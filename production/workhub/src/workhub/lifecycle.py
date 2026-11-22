"""Authentik is the employee source. Never delete records or infer group grants by name.

Each service is independently retryable. Persist revocation intent BEFORE remote writes,
and undo only suspensions made by this provisioner. Full inventory is validated before
detecting removed accounts. Immutable UUID prevents email reuse from merging accounts.
"""
import json, os, threading, time
import httpx
from fastapi import HTTPException
from . import store, outline, directory

LOCK = threading.RLock()
GROUP = 'work-assistant-users'
ADMIN = 'work-assistant-admins'

def enabled(): return bool(os.getenv('AUTHENTIK_DIRECTORY_TOKEN'))

def auth_api(path, params=None):
    r=httpx.get(os.environ['AUTHENTIK_API_URL'].rstrip('/')+'/api/v3/'+path,
        params=params, headers={'Authorization':'Bearer '+os.environ['AUTHENTIK_DIRECTORY_TOKEN'],
                               **({'Host':os.environ['AUTHENTIK_API_HOST']} if os.getenv('AUTHENTIK_API_HOST') else {})},timeout=15)
    r.raise_for_status()
    return r.json()

def inventory(path):
    result=[]
    for page in range(1,1001):
        d=auth_api(path,{'page':page,'page_size':100})
        if not isinstance(d.get('results'),list) or 'pagination' not in d:raise ValueError('Invalid inventory')
        result.extend(d['results'])
        if not d['pagination'].get('next'):
            if len(result)!=d['pagination']['count']:raise ValueError('Incomplete inventory')
            return result
    raise ValueError('Inventory exceeded limit')

def records():
    with store.db() as c:rows=c.execute("SELECT v FROM kv WHERE k LIKE 'employee:%'").fetchall()
    return [json.loads(r[0]) for r in rows]

def save(row): store.put('employee:'+row['sub'],row)

def eligible(u):
    return bool(u.get('type') in ('internal','external') and u.get('is_active') and GROUP in [g['name'] for g in u.get('groups_obj',[])])

def allowed_email(email):
    if not enabled():return True
    matches=[r for r in records() if r['email']==email.lower()]
    return not matches or (len(matches)==1 and matches[0]['active'] and not matches[0].get('review'))

def require_identity(info):
    """Live UUID check also closes the polling interval for portal/bot/search requests."""
    if not enabled():return
    try:
        d=auth_api('core/users/',{'uuid':info['sub'],'page_size':100})
        found=[u for u in d['results'] if str(u.get('uuid'))==info['sub']]
        # Older Authentik versions may ignore uuid filter; never trust another result.
        if not found:
            row=store.get('employee:'+info['sub'])
            if row:
                u=auth_api('core/users/'+str(row['pk'])+'/')
                found=[u] if str(u.get('uuid'))==info['sub'] else []
    except (httpx.HTTPError,KeyError,ValueError):raise HTTPException(503,'Authentik 계정 상태를 확인하지 못했습니다. 잠시 후 다시 시도하세요.')
    if len(found)!=1 or not eligible(found[0]):raise HTTPException(403,'업무 서비스 이용이 중지된 계정입니다.')
    u=found[0]
    try:
        email_rows=auth_api('core/users/',{'email':info['email'],'page_size':100})
        matches=[p for p in email_rows['results'] if p.get('email','').lower()==info['email'].lower()]
        if len(matches)!=1 or str(matches[0].get('uuid'))!=info['sub']:
            raise HTTPException(403,'이메일이 중복된 Authentik 계정입니다. 관리자 확인이 필요합니다.')
    except (httpx.HTTPError,KeyError,ValueError):raise HTTPException(503,'Authentik 계정 연결을 확인하지 못했습니다.')
    row=store.get('employee:'+info['sub'])
    if u.get('email','').lower()!=info['email'].lower() or (row and (row.get('review') or row['email']!=info['email'].lower())):
        raise HTTPException(403,'이메일 변경은 관리자 계정 연결 확인이 필요합니다.')

def sync_outline(row, *, sync_names=True):
    if row.get('outline_id'):
        person=outline.api('users.info',{'id':row['outline_id']})
    else:
        people=outline.all_items('users.list')+outline.all_items('users.list',{'filter':'suspended'})
        matches={p['id']:p for p in people if p.get('email','').lower()==row['email']}
        if len(matches)>1:raise ValueError('Outline account collision')
        person=next(iter(matches.values()),None)
        if not person and row['active']:
            d=outline.api('users.invite',{'invites':[{'email':row['email'],'name':row['name'],'role':'member'}],'suppressEmail':True})
            person=next((u for u in d['users'] if u['email'].lower()==row['email']),None)
            if not person:raise ValueError('Outline invitation not created')
        if not person:return '계정 없음 · 차단 대상 없음'
        row['outline_id']=person['id'];save(row)
    if person.get('email','').lower()!=row['email']:raise ValueError('Outline email changed; manual review required')
    if not row['active']:
        if not person.get('isSuspended'):
            if outline.api('auth.info').get('user',{}).get('id')==person['id']:
                raise ValueError('Integration Outline owner requires transfer')
            row['outline_suspended']=True;save(row)
            outline.api('users.suspend',{'id':person['id']})
        return '이용 정지'
    if person.get('isSuspended'):
        if not row.get('outline_suspended'):return '관리자 수동 정지 유지'
        outline.api('users.activate',{'id':person['id']})
    row.pop('outline_suspended',None)
    if sync_names and person.get('name')!=row['name']:outline.api('users.update',{'id':person['id'],'name':row['name']})
    return '이름·계정 준비 완료' if sync_names else '계정 상태 반영 완료'

def sync_groups(row):
    if not row.get('outline_id'):return 'Outline 계정 준비 대기'
    mappings=store.get('employee_group_mappings',[])
    for m in mappings:
        members=__import__('workhub.permissions',fromlist=['rows']).rows('groups.memberships',{'id':m['outline_id']},'groupMemberships')
        present=any((x.get('userId') or x.get('user',{}).get('id'))==row['outline_id'] for x in members)
        wanted=row['active'] and m['authentik_id'] in row['groups']
        if wanted and not present:outline.api('groups.add_user',{'id':m['outline_id'],'userId':row['outline_id']})
        elif present and not wanted:outline.api('groups.remove_user',{'id':m['outline_id'],'userId':row['outline_id']})
    return '지정 그룹 반영 완료' if mappings else '자동 연결 그룹 없음 · Outline에서 직접 지정'

def sync_account(row, *, sync_names=True):
    if row.get('review'):
        revoke_local(row);save(row);return
    directory.remember({'sub':row['sub'],'email':row['email'],'email_verified':True,'name':row['name'],
        'preferred_username':row['username'],'groups':([GROUP]+([ADMIN] if row['admin'] else [])) if row['active'] else []})
    if not row['active']:revoke_local(row)
    result_key='services' if sync_names else 'security_services'
    for service,fn in [('outline',sync_outline),('groups',sync_groups)]:
        previous=row.get(result_key,{}).get(service,{})
        try:
            message=fn(row,sync_names=sync_names) if service == 'outline' else fn(row)
            row.setdefault(result_key,{})[service]={'ok':True,'message':message,'at':store.now()}
        except Exception as ex:
            # API payloads and tokens never go to status/audit output.
            message=type(ex).__name__+' · 다음 동기화 때 재시도'
            if str(ex)=='Integration Outline owner requires transfer':message='연동 API 소유 계정 · Outline 운영 API 소유권을 먼저 이전하세요'
            row.setdefault(result_key,{})[service]={'ok':False,'message':message,'at':store.now()}
        save(row)
        current=row[result_key][service]
        if previous.get('ok')!=current['ok']:
            audit('service_recovered' if current['ok'] else 'service_failed',{'email':row['email'],'service':service,'message':current['message']})
    row['security_pending']=any(not s['ok'] for s in row[result_key].values())
    if sync_names and not row['security_pending']:row.pop('security_services',None)
    save(row)

def security_state(row):
    return [row.get('active'),row.get('authentik_active'),row.get('admin'),sorted(str(g) for g in row.get('groups',[])),row.get('review'),bool(row.get('removed'))]

def apply_account(row, *, sync_names):
    # Poll the directory, but contact services only on security changes or retry.
    state=security_state(row)
    if sync_names or row.get('security_state')!=state or row.get('security_pending'):
        sync_account(row,sync_names=sync_names)
        row['security_state']=state
        save(row)

def reconcile(*, sync_names=True):
    if not enabled():return {'ok':False,'message':'계정 동기화 설정이 필요합니다.'}
    if not LOCK.acquire(blocking=False):raise HTTPException(409,'계정 동기화가 진행 중입니다.')
    try:
        try:
            users=inventory('core/users/')
            if len({str(u['uuid']) for u in users})!=len(users):raise ValueError('Duplicate UUID')
        except Exception as ex:
            result={'ok':False,'at':store.now(),'error':type(ex).__name__,'message':'Authentik 목록 조회 실패. 기존 계정을 변경하지 않았습니다.'}
            store.put('employee_sync' if sync_names else 'employee_security_sync',result);return result
        previous={r['sub']:r for r in records()}
        email_subjects={}
        for u in users:
            if u.get('email'):email_subjects.setdefault(u['email'].lower(),set()).add(str(u['uuid']))
        for r in previous.values():email_subjects.setdefault(r['email'],set()).add(r['sub'])
        selected=[u for u in users if str(u['uuid']) in previous or (u.get('type') in ('internal','external') and eligible(u))]
        seen=set()
        for u in selected:
            sub=str(u['uuid']);seen.add(sub)
            row=previous.get(sub,{'sub':sub,'email':u['email'].lower(),'username':u['username'],'pk':u['pk'],'created':store.now()})
            before=(row.get('active'),row.get('name'),row.get('groups'))
            if sync_names or 'name' not in row:row['name']=u.get('name') or u['username']
            row.update(active=eligible(u),authentik_active=bool(u.get('is_active')),admin=ADMIN in [g['name'] for g in u.get('groups_obj',[])],groups=[g['pk'] for g in u.get('groups_obj',[])],checked=store.now())
            row.pop('removed',None)
            if row['email']!=u.get('email','').lower() or row['username']!=u['username']:
                row['review']='이메일·로그인 ID 변경: 자동 연결 중지, 관리자 확인 필요'
            if len(email_subjects.get(row['email'],set()))>1:
                row['review']='다른 계정과 이메일 중복: 계정 병합 금지, 관리자 확인 필요'
            if not row['email']:row['review']='이메일 없음'
            save(row);apply_account(row,sync_names=sync_names)
            if before!=(row['active'],row['name'],row['groups']):audit('account_changed',{'sub':sub,'email':row['email'],'active':row['active'],'name':row['name']})
        for sub,row in previous.items():
            if sub in seen:continue
            row.update(active=False,authentik_active=False,checked=store.now(),removed=True);save(row);apply_account(row,sync_names=sync_names)
        rows=records();result_key='services' if sync_names else 'security_services'
        result={'ok':not any(r.get('review') or r.get('security_pending') or any(not s['ok'] for s in r.get(result_key,{}).values()) for r in rows),'at':store.now(),'count':len(rows)}
        store.put('employee_sync' if sync_names else 'employee_security_sync',result);return result
    finally:LOCK.release()

def audit(action,detail):
    # Bounded durable audit (newest 500 actions), no tokens or session bodies.
    with LOCK:
        items=store.get('employee_audit',[]);items.append({'at':store.now(),'action':action,**detail});store.put('employee_audit',items[-500:])

def run(stop):
    while not stop.is_set():
        try:reconcile(sync_names=False)
        except Exception:__import__('logging').getLogger('workhub').exception('account_sync_failed')
        stop.wait(max(15,int(os.getenv('ACCOUNT_SECURITY_CHECK_SECONDS','60'))))

def map_group(authentik_id,actor):
    with LOCK:
        groups=inventory('core/groups/')
        group=next((g for g in groups if str(g['pk'])==authentik_id),None)
        if not group:raise HTTPException(404,'Authentik 그룹을 찾지 못했습니다.')
        mappings=store.get('employee_group_mappings',[])
        if any(m['authentik_id']==authentik_id for m in mappings):raise HTTPException(409,'이미 연결한 그룹입니다.')
        # Dedicated group: never take over an existing manually managed Outline group.
        name='Workhub 자동 · '+group['name']
        result=outline.api('groups.create',{'name':name})
        target=result.get('group',result)
        mapping={'authentik_id':authentik_id,'name':group['name'],'outline_id':target['id'],'outline_name':name}
        mappings.append(mapping);store.put('employee_group_mappings',mappings)
        audit('group_mapping_created',{'actor':actor['email'],**mapping})
        return mapping


def revoke_local(row):
    person=store.get('person:'+row['sub'])
    if person:store.put('person:'+row['sub'],{**person,'active':False})
