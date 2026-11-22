"""Read-only planning metrics from the latest Outline task snapshots."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from . import domain

def rounded(value):return float(Decimal(str(value)).quantize(Decimal('0.1'),rounding=ROUND_HALF_UP))

def date_value(value):
    try:return date.fromisoformat(value)
    except (ValueError,TypeError):return None

def useful(value):return bool(value and value.strip() not in ('없음','-','미정'))

def build(tasks,projects,owner='',collection_id='',horizon=7,today=None,owner_members=None):
    today=today or datetime.now(timezone(timedelta(hours=9))).date()
    owner=owner.strip().lower();until=today+timedelta(days=horizon)
    ps=[p for p in projects if not collection_id or p['id']==collection_id];allowed={p['id'] for p in ps}
    # A document, not a report/event, is one task. Last snapshot wins.
    unique={t['id']:t for t in tasks if t.get('collectionId') in allowed}
    ts=[t for t in unique.values() if not owner or t['fields'].get('owner','').lower()==owner or any(i['owner'].lower()==owner for i in t.get('criteria',[]))]
    valid=[t for t in ts if not t.get('error')]
    def items(rows,email=owner):return [i for t in rows for i in t.get('criteria',[]) if not email or i['owner'].lower()==email]
    def pending(t):return t['fields']['status']!='완료'
    def due(t):return date_value(t['fields'].get('due'))
    def late(t):return bool(pending(t) and due(t) and due(t)<today)
    def soon(t):return bool(pending(t) and due(t) and today<=due(t)<=until)
    def blocked(t):return pending(t) and useful(t['fields'].get('blocker',''))
    def counts(rows):
        ci=items(rows);done=sum(i['state']=='완료' for i in ci)
        progress=[]
        for t in rows:
            try:value=float(t['fields'].get('progress','').rstrip('%'))
            except (ValueError,TypeError,AttributeError):continue
            if 0<=value<=100:progress.append(value)
        return {'total':len(rows),'completed':sum(not pending(t) for t in rows),'open':sum(pending(t) for t in rows),
            'average_progress':rounded(sum(progress)/len(progress)) if progress else None,'progress_known':len(progress),
            'completion_rate':rounded(100*sum(not pending(t) for t in rows)/len(rows)) if rows else None,
            'criteria_total':len(ci),'criteria_done':done,'criteria_remaining':len(ci)-done,
            'criteria_progress':rounded(100*done/len(ci)) if ci else None,
            'overdue':sum(late(t) for t in rows),'due_soon':sum(soon(t) for t in rows),'blocked':sum(blocked(t) for t in rows),
            'no_due':sum(pending(t) and not due(t) for t in rows),'states':{s:sum(t['fields']['status']==s for t in rows) for s in domain.STATES}}
    summary=counts(valid);summary['invalid']=len(ts)-len(valid)
    summary['no_criteria']=sum(not t.get('criteria') for t in valid)
    summary['missing_progress']=sum(t['fields'].get('progress') in ('','미기재',None) for t in valid)
    project_rows=[]
    for p in ps:
        rows=[t for t in valid if t['collectionId']==p['id']]
        if owner and not any(t['collectionId']==p['id'] for t in ts):continue
        project_rows.append({'id':p['id'],'name':p['name'],'manager':p.get('manager',''),**counts(rows),'invalid':sum(t.get('error') is not None for t in ts if t['collectionId']==p['id'])})
    measured_projects=[p['average_progress'] for p in project_rows if p['average_progress'] is not None]
    summary['project_progress']=rounded(sum(measured_projects)/len(measured_projects)) if measured_projects else None
    summary['projects_measured']=len(measured_projects)
    summary['projects_total']=len(project_rows)
    owner_valid=[t for t in unique.values() if not t.get('error')] if owner_members is not None else valid
    owner_emails=sorted(owner_members if owner_members is not None else {t['fields']['owner'].lower() for t in valid}|{i['owner'].lower() for t in valid for i in t.get('criteria',[])})
    owner_rows=[]
    for email in owner_emails:
        if owner_members is None and owner and email!=owner:continue
        rows=[t for t in owner_valid if t['fields']['owner'].lower()==email or any(i['owner'].lower()==email for i in t.get('criteria',[]))]
        ci=items(rows,email);done=sum(i['state']=='완료' for i in ci)
        owner_rows.append({'email':email,'tasks':len(rows),'tasks_remaining':sum(pending(t) for t in rows),
            'tasks_completed':sum(not pending(t) for t in rows),'tasks_overdue':sum(late(t) for t in rows),
            'tasks_pending':sum(pending(t) and not late(t) for t in rows),'total':len(ci),'completed':done,'remaining':len(ci)-done,
            'planned':sum(i['state']=='예정' for i in ci),'in_progress':sum(i['state']=='진행 중' for i in ci),
            'overdue_items':sum(i['state']!='완료' for t in rows if late(t) for i in items([t],email)),
            'progress':rounded(100*done/len(ci)) if ci else None})
    owner_rows.sort(key=lambda o:(-o['tasks_overdue'],-o['tasks_remaining'],o['email']))
    actions=[];completed_tasks=[]
    for t in valid:
        f=t['fields'];day=due(t);flags=[]
        if late(t):flags.append('overdue')
        if blocked(t):flags.append('blocked')
        if soon(t):flags.append('due_soon')
        if pending(t) and not day:flags.append('no_due')
        guidance=('담당자와 완료 예상일을 다시 정하세요.' if late(t) else '장애요인 해소에 필요한 결정을 확인하세요.' if blocked(t)
            else '마감 전 남은 완료 기준을 확인하세요.' if soon(t) else '먼저 마감일을 정해 계획에 넣으세요.' if not day else '다음 행동과 남은 완료 기준을 확인하세요.')
        (actions if pending(t) else completed_tasks).append({'id':t['id'],'title':t['title'],'collectionId':t['collectionId'],'collectionName':t['collectionName'],'url':t['url'],
            'owner':f['owner'],'status':f['status'],'progress':f.get('progress','미기재'),'start':f.get('start') if date_value(f.get('start')) else None,'due':day.isoformat() if day else None,
            'days_remaining':(day-today).days if day else None,'flags':flags,'blocker':f.get('blocker','없음'),
            'next':f.get('next') if useful(f.get('next','')) else guidance,'next_is_suggestion':not useful(f.get('next','')),
            'criteria':t.get('criteria',[]),'remaining':sum(i['state']!='완료' for i in items([t]))})
    actions.sort(key=lambda t:('overdue' not in t['flags'],'blocked' not in t['flags'],'due_soon' not in t['flags'],t['due'] or '9999',t['title']))
    schedule=[{'key':'overdue','label':'기한 지남','count':summary['overdue']},
        {'key':'today','label':'오늘','count':sum(pending(t) and due(t)==today for t in valid)},
        {'key':'soon','label':f'내일~{horizon}일 후','count':sum(bool(pending(t) and due(t) and today<due(t)<=until) for t in valid)},
        {'key':'later','label':f'{horizon}일 이후','count':sum(bool(pending(t) and due(t) and due(t)>until) for t in valid)},
        {'key':'no_due','label':'마감 미정','count':summary['no_due']}]
    return {'as_of':today.isoformat(),'until':until.isoformat(),'horizon':horizon,'owner':owner,'collection_id':collection_id,
        'summary':summary,'projects':project_rows,'owners':owner_rows,'actions':actions,'completed_tasks':sorted(completed_tasks,key=lambda t:(t['collectionName'],t['title'],t['id'])),'schedule':schedule,
        'invalid_tasks':[{'id':t['id'],'title':t['title'],'url':t['url'],'error':t['error']} for t in ts if t.get('error')]}
