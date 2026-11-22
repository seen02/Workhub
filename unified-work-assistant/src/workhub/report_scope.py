"""Project mentions guide retrieval and completeness, never authorize writes."""
import re
from difflib import SequenceMatcher

def compact(value):return re.sub(r'[^가-힣a-z0-9]','',value.casefold())

def task_names(task):
    title=task['title'].strip();names=[title]
    short=re.sub(r'\s*업무$','',title).strip()
    if len(compact(short))>=2 and short!=title:names.append(short)
    return names

def task_mentions(raw,tasks):
    """Unique full names or a unique title without the generic '업무' suffix."""
    hits=[]
    for t in tasks:
        for name in task_names(t):
            if sum(name in task_names(other) for other in tasks)!=1:continue
            pattern=r'(?<![가-힣a-zA-Z0-9])'+r'\s*'.join(re.escape(w) for w in name.split())+r'(?=$|\s|[은는의을를에])'
            for m in re.finditer(pattern,raw,re.I):hits.append({'start':m.start(),'end':m.end(),'task':t})
    selected=[]
    for h in sorted(hits,key=lambda x:-(x['end']-x['start'])):
        if not any(h['start']<s['end'] and s['start']<h['end'] for s in selected):selected.append(h)
    return sorted(selected,key=lambda x:x['start'])

def project_clauses(raw,projects):
    hits=mentions(raw,projects)
    if not hits or raw[:hits[0]['start']].strip():return []
    # Do not apply a known project's scope across an unrecognized second name.
    for h in hits:
        tail=raw[h['end']:h['start']+len(h['text'])]
        tail=re.sub(r'^\s*(?:프로젝트|컬렉션)','',tail,count=1)
        if re.search(r'프로젝트|컬렉션',tail):return []
    return hits

def task_clauses(text,tasks):
    hits=task_mentions(text,tasks)
    if not hits or text[:hits[0]['start']].strip():return []
    result=[]
    for n,h in enumerate(hits):
        end=hits[n+1]['start'] if n+1<len(hits) else len(text)
        clause=text[h['start']:end]
        if n+1<len(hits) and not re.search(r'완료|끝났|끝냈|마쳤|진행|예정|하고\s*있',clause):return []
        result.append({'task':h['task'],'text':clause,'body':text[h['end']:end]})
    return result

def mentions(raw,projects):
    hits=[]
    for p in projects:
        pattern=r'\s*'.join(re.escape(x) for x in p['name'].split())
        for m in re.finditer(pattern,raw,re.I):hits.append({'start':m.start(),'end':m.end(),'id':p['id'],'name':p['name']})
    # Consider a near-exact project name immediately before a project/collection
    # marker. Only a unique strong candidate survives; never resolve a close tie.
    for m in re.finditer(r'([^.!?\n,]{1,90}?)\s*(?:프로젝트|컬렉션)(?=\s|[은는의에을를]|$)',raw):
        prefix=m.group(1).rstrip();words=list(re.finditer(r'\S+',prefix));ranked=[]
        for p in projects:
            name=compact(re.sub(r'^프로젝트\s*|\s*프로젝트$','',p['name']))
            options=[]
            for word in words[-6:]:
                q=compact(prefix[word.start():])
                if min(len(q),len(name))<3:continue
                ratio=SequenceMatcher(None,q,name).ratio()
                # Prefer a full name with one mistyped character over chopping
                # that character off and matching only the remaining suffix.
                if ratio>=.8:options.append((ratio-.15*abs(len(q)-len(name)),m.start(1)+word.start()))
            if options:
                value,start=max(options);ranked.append((value,start,p))
        ranked.sort(key=lambda x:x[0],reverse=True)
        if ranked and (len(ranked)==1 or ranked[0][0]-ranked[1][0]>=.15):
            _,start,p=ranked[0];hits.append({'start':start,'end':m.start(1)+len(prefix),'id':p['id'],'name':p['name']})
    # A short project named "시연" inside "팀 협업 시연" is not another mention.
    selected=[]
    for h in sorted(hits,key=lambda x:-(x['end']-x['start'])):
        if not any(h['start']<s['end'] and s['start']<h['end'] for s in selected):selected.append(h)
    selected.sort(key=lambda x:x['start'])
    for n,h in enumerate(selected):h['text']=raw[h['start']:selected[n+1]['start'] if n+1<len(selected) else len(raw)]
    return selected

def required_tasks(raw,projects,tasks):
    result=set()
    for h in mentions(raw,projects):
        scoped=[t for t in tasks if t['project_id']==h['id']]
        result.update(m['task']['id'] for m in task_mentions(h['text'],scoped))
    return result

def check_coverage(raw,projects,tasks,parsed):
    for h in mentions(raw,projects):
        # Ignore bare project references with no reported status/action.
        if not re.search(r'완료|끝났|끝냈|마쳤|진행|예정|하는\s*중|하고\s*있',h['text']):continue
        groups=[g for g in parsed.groups if g.project_id==h['id']]
        if not groups:raise ValueError('보고에서 프로젝트를 빠뜨렸습니다: '+h['name']+'. 해당 구절의 업무를 별도 group으로 포함하세요.')
        required=required_tasks(h['text'],[p for p in projects if p['id']==h['id']],tasks)
        for t in tasks:
            if t['id'] not in required:continue
            if not any(g.task_id==t['id'] or compact(g.title)==compact(t['title']) for g in groups):
                raise ValueError('보고에서 업무를 빠뜨렸습니다: '+h['name']+' / '+t['title'])
    scope=project_clauses(raw,projects)
    if scope:
        allowed={h['id'] for h in scope}
        if any(g.project_id and g.project_id not in allowed for g in parsed.groups):
            raise ValueError('보고에 지정한 프로젝트 밖의 업무를 선택했습니다.')
