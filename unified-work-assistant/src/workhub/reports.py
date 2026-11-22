"""Persistent multi-task reports. Posting and Outline application are independent."""
import hashlib,re,threading,uuid
from datetime import datetime,timezone,timedelta
from urllib.parse import quote
from fastapi import HTTPException
from . import store,outline,permissions,criteria,domain,human_tasks,report_parser,report_transport,execution,job_control

LOCK=threading.RLock()
ICON={'완료':'✅','진행 중':'⏳','예정':'🕒'}
REPORT_SEPARATOR='────────────────────────'

def clean(text):return re.sub(r'[*`<>\[\]\r\n]','',str(text)).strip()
def save(r):
    job_control.check()
    store.put('report-v2:'+r['id'],r);return r

def report_time(raw,default):
    """Only explicit report timestamps override time, never task start/due dates."""
    base=datetime.fromisoformat(default).astimezone(timezone(timedelta(hours=9)))
    iso=re.search(r'보고\s*시각\s*[:：]\s*(\d{4})-(\d{2})-(\d{2})[ T]+(\d{1,2}):(\d{2})',raw)
    korean=re.search(r'(?:보고\s*시각\s*[:：]|\[)\s*(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일\s*(?:[월화수목금토일]요일)?\s*:?\s*(\d{1,2})시\s*(\d{1,2})분',raw)
    m=iso or korean
    if not m:return default
    y,month,day,hour,minute=m.groups()
    return datetime(int(y or base.year),int(month),int(day),int(hour),int(minute),tzinfo=base.tzinfo).isoformat()

def get(user,rid,version=None):
    r=store.get('report-v2:'+rid)
    if not r or r['owner']!=user['sub']:raise HTTPException(404,'본인의 보고 초안이 아닙니다.')
    if version is not None and r['version']!=version:raise HTTPException(409,'수정 전 버튼입니다. 최근 초안의 버튼을 사용하세요.')
    if r.get('cancelled'):raise HTTPException(409,'취소된 초안입니다. 새 보고를 작성하세요.')
    for cid in {g['project_id'] for g in r['groups'] if g.get('project_id')}:permissions.project(user,cid)
    return r

def group_title(r,g):
    return clean(g['title'])+(' ('+clean(g['project_name'])+')' if g.get('project_confirmed') or sum(x['title']==g['title'] for x in r['groups'])>1 else '')

def text(r):
    groups=r['groups']
    def title(g):return group_title(r,g)
    def entry(g):
        did=g.get('task_id') if g['kind']=='update' else ((g.get('creation') or {}).get('id') or g.get('planned_document_id')) if g['kind']=='create' and g['state']!='SKIPPED' else None
        label=title(g).replace('\\','')
        return f'[{label}]({outline.PUBLIC}/doc/{quote(str(did),safe="")})' if did else label
    when=datetime.fromisoformat(r['when']).astimezone(timezone(timedelta(hours=9)))
    # Rocket.Chat treats a bracketed heading plus a later Markdown link as one
    # multiline link label. Keep this heading bracket-free.
    result='**업무목록**\n\n'+'\n'.join('- '+entry(g) for g in groups)
    result+=f"\n\n**[{when.month}월 {when.day}일 {'월화수목금토일'[when.weekday()]}요일 : {when:%H시 %M분}]**"
    for g in groups:
        result+='\n\n**'+title(g)+'**\n\n'+'\n'.join(f"{n}. {clean(i['title'])}({ICON[i['state']]} {i['state']})" for n,i in enumerate(g['items'],1))
    return result+'\n\n'+REPORT_SEPARATOR

@execution.operation('report_create')
def create(user,raw,idem,uid,dm,recent=None):
    report_transport.require_dm(user,uid,dm)
    key='report-v2-idem:'+user['sub']+':'+idem
    with LOCK:
        old=store.get(key)
        if old:return get(user,old)
        when=report_time(raw,store.now())
        groups,mode=report_parser.plan(user,raw,recent)
        r={'id':str(uuid.uuid4()),'owner':user['sub'],'author':user['email'],'author_name':clean(user.get('name') or user['email']),'version':1,'raw':raw,
           'when':when,'uid':uid,'dm':dm,'groups':groups,'search_mode':mode,'posting':{'state':'NOT_POSTED'},'destination':None}
        default=store.get('report-destination:'+user['sub'])
        if default:
            try:r['destination']=report_transport.destination(user,uid,default['id'])
            except Exception:pass
        if len(text(r))>9000:raise ValueError('보고가 너무 깁니다. 업무를 나누어 입력하세요. 초안은 저장하지 않았습니다.')
        save(r);store.put(key,r['id']);return r

def editable(r):
    if r['posting']['state'] not in ('NOT_POSTED','FAILED') or any(g['state'] not in ('PENDING','SKIPPED','FAILED','CONFLICT') or g.get('proposal') or g.get('creation',{}).get('attempted') for g in r['groups']):
        raise ValueError('이미 전송·반영을 시작한 보고는 보존됩니다. 새 보고를 작성해 정정하세요.')

@execution.operation('report_revise')
def revise(user,rid,version,raw):
    with LOCK:
        r=get(user,rid,version);editable(r)
        groups,mode=report_parser.plan(user,raw)
        store.put(f"report-v2-history:{rid}:{version}",r)
        r.update(version=version+1,raw=raw,groups=groups,search_mode=mode,when=report_time(raw,r['when']))
        if len(text(r))>9000:raise ValueError('보고가 너무 깁니다. 업무를 나누어 입력하세요. 기존 초안은 유지됩니다.')
        return save(r)

def choose(user,rid,version,index,kind,target=''):
    with LOCK:
        r=get(user,rid,version);editable(r)
        if not 0<=index<len(r['groups']):raise ValueError('보고 항목을 확인하세요.')
        g=r['groups'][index]
        if kind=='skip':g.update(state='SKIPPED',issue='사용자가 Outline 반영에서 제외')
        elif kind in ('task','candidate'):
            if kind=='candidate' and (not g.get('needs_task_choice') or target not in g.get('candidates',[])):
                raise ValueError('표시된 프로젝트의 업무를 선택하세요.')
            d=outline.document(target,user,normalize_fields=False)
            if not outline.projected(d):raise ValueError('업무 문서를 선택하세요.')
            p=permissions.project(user,d['collectionId'])
            if kind=='candidate' and not any(o['id']==target and o.get('project_id')==d['collectionId'] for o in g['options']):
                raise ValueError('업무의 프로젝트가 변경됐어요. 보고 내용을 다시 입력해 주세요.')
            if kind=='candidate' and report_parser.compact(d['title'])!=report_parser.compact(g['title']):
                raise ValueError('업무 이름이 변경됐어요. 보고 내용을 다시 입력해 주세요.')
            if target!=g.get('task_id'):
                for item in g['items']:
                    item.pop('criterion_id',None);item.pop('id',None)
            outline.can_report(user,d)
            g.update(task_id=d['id'],project_id=p['id'],project_name=p['name'],title=d['title'],kind='update',issue='',state='PENDING')
            report_parser.resolve_items(user,g)
            g.update(needs_task_choice=False,project_confirmed=True,candidates=[],options=[])
        elif kind=='project':
            p=permissions.project(user,target);g.update(project_id=p['id'],project_name=p['name'],task_id='',kind='unresolved',state='PENDING',issue='기존 업무를 선택하거나 새 업무 추가를 선택하세요.')
        elif kind=='create':
            permissions.require_create(user,g['project_id'])
            if any(re.fullmatch(r'(기준|항목)\s*\d+',i['title']) for i in g['items']):raise ValueError('번호 대신 구체적인 완료 기준명을 적어주세요.')
            g.update(kind='create',task_id='',state='PENDING',issue='')
        else:raise ValueError('지원하지 않는 선택입니다.')
        r['version']+=1;return save(r)

def set_destination(user,rid,version,target):
    with LOCK:
        r=get(user,rid,version)
        if r['posting']['state'] not in ('NOT_POSTED','FAILED'):raise ValueError('전송을 시작한 보고의 목적지는 바꿀 수 없습니다.')
        r['destination']=report_transport.destination(user,r['uid'],target)
        r['version']+=1
        store.put('report-destination:'+user['sub'],r['destination']);return save(r)

@execution.operation('report_publish')
def publish(user,rid,version):
    with LOCK:
        r=get(user,rid,version);report_transport.require_dm(user,r['uid'],r['dm'])
        if any(g.get('needs_task_choice') and g['state']!='SKIPPED' for g in r['groups']):
            raise ValueError('같은 이름의 업무가 있어 프로젝트를 먼저 선택해 주세요.')
        if not r['destination']:raise ValueError('보고할 곳을 먼저 선택하세요.')
        dest=report_transport.destination(user,r['uid'],r['destination']['id']);post=r['posting']
        if post['state']=='POSTED':return r
        # Reconcile the exact payload already attempted, including reports from
        # before a formatting deployment. Never reformat an uncertain message.
        payload=post.get('payload')
        if payload is None:
            for g in r['groups']:
                if g['kind']=='create' and g['state']!='SKIPPED' and not g.get('creation') and not g.get('planned_document_id'):
                    g['planned_document_id']=str(uuid.uuid4())
            save(r)
            payload=text(r)
        if len(payload)>9000:raise ValueError('보고가 너무 깁니다. 9,000자 이하로 나누어 새 보고를 작성하세요.')
        mid=post.get('message_id') or 'wh'+hashlib.sha256((rid+':'+str(version)).encode()).hexdigest()[:30]
        previous=report_transport.lookup(mid)
        if previous:
            if previous.get('rid')!=dest['id'] or previous.get('msg')!=payload or previous.get('u',{}).get('_id')!=report_transport.client().bot_id:
                post.update(state='UNKNOWN',error='전송 기록과 실제 메시지가 다릅니다. 원문을 확인하세요.');return save(r)
        elif post['state'] in ('POSTING','UNKNOWN'):
            post.update(state='UNKNOWN',error='이전 전송 결과를 확인하지 못했습니다. 중복 방지를 위해 재전송하지 않습니다.');return save(r)
        else:
            post.update(state='POSTING',message_id=mid,payload=payload);save(r)
            try:report_transport.send(dest['id'],payload,mid,author=r.get('author_name',r['author']))
            except Exception:pass
            try:previous=report_transport.lookup(mid)
            except Exception:previous=None
            if not previous or previous.get('rid')!=dest['id'] or previous.get('msg')!=payload:
                post.update(state='UNKNOWN',error='전송 결과 확인 필요. 다시 확인 버튼을 이용하세요.');return save(r)
        post.update(state='POSTED',message_id=mid,url=report_transport.link(dest['id'],mid),at=store.now(),error='')
        return save(r)

@execution.operation('report_submit',refresh=True)
def submit(user,rid,version,target=None):
    """One user action; reconcile posting before applying, never claim atomicity."""
    with LOCK:
        r=get(user,rid,version)
        report_transport.require_dm(user,r['uid'],r['dm'])
        if target is not None:
            r=set_destination(user,rid,version,target)
        # Catch known permission/content conflicts before publishing anything.
        if r['posting']['state'] in ('NOT_POSTED','FAILED'):
            errors=False
            for g in r['groups']:
                try:preflight(user,g,r)
                except Exception as ex:
                    g.update(error=str(getattr(ex,'detail',ex)),state='CONFLICT' if getattr(ex,'status_code',0)==409 else 'FAILED');errors=True
            save(r)
            if errors:return r
        r=publish(user,rid,r['version'])
        if r['posting']['state']!='POSTED':return r
        return apply(user,rid,r['version'])

def new_text(user,g,r):
    items=criteria.validate([{**i,'owner':user['email'].lower()} for i in g['items']])
    label=human_tasks.label(user['email'].lower());status=criteria.rollup(items)['status']
    # Use the registration day in Korea, not the draft's (possibly backdated) report time.
    # apply_new persists this text before the first write, keeping recovery retries stable.
    start=datetime.fromisoformat(store.now()).astimezone(timezone(timedelta(hours=9))).date().isoformat()
    body=f'담당자: {label}\n\n시작일: {start}\n\n마감일: 미정\n\n상태: {status}\n\n## 업무 내용\n\n{clean(g["title"])}\n\n## 완료 기준\n\n'
    body+='\n'.join(f"- [{'x' if i['state']=='완료' else ' '}] {i['title']} — 담당자: {label}"+(' — 상태: 진행 중' if i['state']=='진행 중' else '') for i in items)
    evidence=g['evidence'];fence='`'*max(3,max((len(m[0])+1 for m in re.finditer(r'`+',evidence)),default=3))
    return body+'\n\n## 진행 기록\n\n## 결과물 및 참고 자료\n\n### 보고 기록\n\n보고 ID: '+r['id']+'\n\n'+fence+'text\n'+evidence+'\n'+fence

@execution.operation('report_preflight',refresh=True)
def preflight(user,g,r):
    if g['state'] in ('APPLIED','SKIPPED'):return
    if g['kind']=='unresolved':raise ValueError(g.get('issue') or '연결할 업무를 확인하세요.')
    if g['kind']=='create':
        permissions.require_create(user,g['project_id'])
        permissions.validate_owners(user,g['project_id'],[{'owner':user['email'].lower()}])
        if not g.get('creation'):
            # Complete live inventory before considering a task absent.
            docs=outline.all_items('documents.list',{'collectionId':g['project_id']})
            if any(report_parser.compact(d['title'])==report_parser.compact(g['title']) and not d.get('archivedAt') and not d.get('deletedAt') for d in docs):
                raise ValueError('같은 이름의 문서가 생겼습니다. 새 보고에서 기존 업무를 연결하세요.')
        new_text(user,g,r)
    else:
        d=outline.document(g['task_id'],user)
        changes=changes_for(g)
        outline.authorize_changes(user,d,changes)
        if not g.get('proposal') and (d['text']!=g['before'] or d.get('revision',0)!=g['revision'] or d['updatedAt']!=g['updatedAt']):
            raise HTTPException(409,'초안 작성 후 Outline 원문이 바뀌었습니다. 초안을 수정하세요.')

def changes_for(g):
    if g['items'] and all(i.get('id') for i in g['items']):return {'criterion_states':{i['id']:i['state'] for i in g['items']}}
    states={i['state'] for i in g['items']}
    if len(states)!=1:raise ValueError('완료 기준이 없는 업무의 전체 상태를 하나로 알려주세요.')
    changes={'status':{'완료':'완료','진행 중':'진행 중','예정':'미착수'}[next(iter(states))]}
    amounts=re.findall(r'(?<!\d)(100|[1-9]?\d)(?:\.(\d+))?\s*%',g['evidence'])
    if amounts:
        values={float(a+('.'+b if b else '')) for a,b in amounts}
        if len(values)!=1 or max(values)>100:raise ValueError('업무 전체 진행률을 하나로 알려주세요.')
        changes['progress']=f'{next(iter(values)):g}%'
    return changes

@execution.operation('report_create_document',refresh=True)
def apply_new(user,g,r):
    permissions.require_create(user,g['project_id'])
    if not g.get('creation'):
        parent=outline.task_parent(g['project_id'])
        g['creation']={'id':g.get('planned_document_id') or str(uuid.uuid4()),'text':new_text(user,g,r),'parent':parent['id']};save(r)
    c=g['creation'];d=outline.api('documents.info',{'id':c['id']},missing_ok=True)
    if d is None:
        if c.get('attempted'):raise ValueError('새 업무 생성 결과 확인 필요. 중복 방지를 위해 다시 생성하지 않습니다.')
        c['attempted']=True;save(r)
        try:outline.api('documents.create',{'id':c['id'],'collectionId':g['project_id'],'parentDocumentId':c['parent'],
                                          'title':g['title'],'text':c['text'],'publish':True})
        except Exception:pass
        d=outline.api('documents.info',{'id':c['id']},missing_ok=True)
    if not d or d.get('collectionId')!=g['project_id'] or d.get('parentDocumentId')!=c['parent'] or not domain.same_saved_text(c['text'],d['text']):
        raise ValueError('생성 결과 또는 후속 편집을 확인하세요. 자동으로 덮어쓰지 않습니다.')
    permissions.document(user,d)
    outline.record(d,user['email'],'created')
    from .search import dirty
    dirty.set()
    return {'url':outline.PUBLIC+d['url'],'doc_id':d['id'],'revision':d.get('revision',0)}

@execution.operation('report_apply')
def apply(user,rid,version):
    with LOCK:
        r=get(user,rid,version);report_transport.require_dm(user,r['uid'],r['dm'])
        errors=False
        for g in r['groups']:
            try:preflight(user,g,r)
            except Exception as ex:g.update(error=str(getattr(ex,'detail',ex)),state='CONFLICT' if getattr(ex,'status_code',0)==409 else 'FAILED');errors=True
        save(r)
        if errors:return r
        for n,g in enumerate(r['groups']):
            if g['state'] in ('APPLIED','SKIPPED'):continue
            try:
                g['state']='APPLYING';save(r)
                if g['kind']=='create':
                    with outline.MUTEX:
                        preflight(user,g,r)
                        result=apply_new(user,g,r)
                else:
                    if not g.get('proposal'):
                        # Recheck immediately before persisting a proposal, including concurrent external edits.
                        preflight(user,g,r)
                        p=outline.propose(user,g['task_id'],changes_for(g),f"report-v2:{rid}:{version}:{n}",
                          '보고 ID: '+rid+'\n'+g['evidence'])
                        if p['before']!=g['before'] or p['revision']!=g['revision']:raise HTTPException(409,'원문이 바뀌었습니다. 새 보고를 작성하세요.')
                        g['proposal']=p['id'];save(r)
                    result=outline.confirm(user,g['proposal'])
                g.update(state='APPLIED',result=result,error='')
            except Exception as ex:g.update(state='FAILED',error=str(getattr(ex,'detail',ex)))
            save(r)
        return r

def cancel(user,rid,version):
    with LOCK:
        r=get(user,rid,version);editable(r);r['cancelled']=True;return save(r)
