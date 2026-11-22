"""Code-free Outline task templates. Markdown stays the source of truth.

Checklist identity is derived from its exact title and resolved account, not its
position. Renames/reassignments are new identities; revision checks reject old
proposals. Workflow choices remain readable in the document header.
"""
import hashlib
import re

SECTION = re.compile(r'^## 완료 기준[ \t]*(?:\n|\Z)(.*?)(?=^#{1,2} |\Z)', re.M | re.S)
LINE = re.compile(r'^\s*[-*] \[([ xX])\] (.+?)\s+[—–|]\s*담당자:\s*(.+?)(?:\s+[—–|]\s*상태:\s*(예정|진행 중|완료))?\s*$')


def source(text):
    from .domain import source_text
    return source_text(text)


def is_human(text):
    text=source(text)
    from .domain import is_legacy_task
    return not is_legacy_task(text) and bool(re.search(r'^## 업무 내용\s*$',text,re.M)) and bool(re.search(r'^## 완료 기준\s*$',text,re.M))


def people():
    from . import outline, directory, permissions
    cache=permissions.request_snapshots.get()
    key=('human-template-people',)
    if cache is not None and key in cache:
        from .execution import count
        count('cache_hit.people')
        return cache[key]
    names=directory.names()
    rows=[{**p,'label':names.get(p.get('email','').lower(),p.get('name',''))} for p in outline.all_items('users.list') if permissions.active(p)]
    if cache is not None:cache[key]=rows
    return rows


def resolve(value):
    value=value.strip()
    explicit=re.fullmatch(r'(?:.*?\s*[<(])?([^\s<>\(\)@]+@[^\s<>\(\)@]+\.[^\s<>\(\)@]+)[>)]?',value)
    rows=people()
    matches={p['email'].lower() for p in rows if (p['email'].lower()==explicit[1].lower() if explicit else value in (p.get('name'),p.get('label')))}
    if len(matches)!=1:raise ValueError('담당자 "'+value+'"를 한 명으로 확인할 수 없습니다. 이름 또는 이름 (이메일)을 입력하세요.')
    return matches.pop()


def label(email):
    rows=people();person=next((p for p in rows if p['email'].lower()==email.lower()),None)
    if not person:return email
    name=person.get('label') or person.get('name') or email
    # Explicit account prevents future name collisions from reassigning a report.
    return f'{name} ({email})'


def header(text):return re.split(r'^## ',source(text),maxsplit=1,flags=re.M)[0]


def field(text,name,default=None):
    matches=re.findall(r'^\s*(?:\*\*)?'+re.escape(name)+r':(?:\*\*)?\s*(.*?)\s*$',header(text),re.M)
    if len(matches)>1:raise ValueError(name+' 항목은 한 번만 작성하세요.')
    if not matches:
        if default is not None:return default
        raise ValueError(name+' 항목을 입력하세요.')
    return matches[0].strip()


def parse_fields(text):
    from . import domain
    fields={k:field(text,v,'') for k,v in domain.FIELDS.items()}
    fields.update(project='Outline 업무',owner=resolve(field(text,'담당자')),status=field(text,'상태'))
    for k in ('start','due'):
        if not fields[k] or fields[k]=='미정':fields[k]='미정'
        elif not re.fullmatch(r'\d{4}-\d{2}-\d{2}',fields[k]):raise ValueError(domain.FIELDS[k]+'은 YYYY-MM-DD 형식의 실제 날짜 또는 미정으로 입력하세요.')
    fields['progress']=fields['progress'] or '미기재'
    return domain.validate(fields)


def parse_items(text):
    from . import criteria
    sections=list(SECTION.finditer(source(text)))
    if len(sections)!=1:raise ValueError('완료 기준 제목은 한 번만 작성하세요.')
    items=[]
    for line in sections[0][1].splitlines():
        if not line.strip():continue
        match=LINE.fullmatch(line)
        if not match:raise ValueError('완료 기준은 체크박스 항목명 — 담당자: 이름 형식으로 작성하세요.')
        checked,title,owner,state=match.groups();owner=resolve(owner);title=title.strip()
        if title.startswith('완료 여부를 확인할 수 있는 항목 작성'):raise ValueError('완료 기준 예시 문구를 실제 업무 항목으로 바꿔주세요.')
        state='완료' if checked.lower()=='x' else ('예정' if state in (None,'완료') else state)
        cid='C-'+hashlib.sha256((title+'\0'+owner).encode()).hexdigest()[:8]
        items.append({'id':cid,'title':title,'owner':owner,'state':state})
    return criteria.validate(items) if items else []


def replace_items(text,items):
    from . import criteria
    criteria.validate(items)
    # Human IDs are derived; callers must not rely on legacy IDs after reallocation.
    body='## 완료 기준\n\n'+'\n'.join(f"- [{'x' if i['state']=='완료' else ' '}] {i['title']} — 담당자: {label(i['owner'])}"+(f" — 상태: 진행 중" if i['state']=='진행 중' else '') for i in items)+'\n\n'
    live=source(text);matches=list(SECTION.finditer(live))
    if len(matches)!=1:raise ValueError('완료 기준 구역을 확인하세요.')
    return SECTION.sub(lambda _:body,live,count=1).rstrip()+text[len(live):]


def patch_fields(text,changes):
    from . import domain, task_status
    fields=domain.validate({**parse_fields(text),**changes})
    original=source(text);head=header(original);tail=original[len(head):]
    for key in changes:
        if key not in domain.FIELDS:raise ValueError('지원하지 않는 항목입니다.')
        # Criteria progress is derived; plain tasks retain their editable progress field.
        if key=='project' or (key=='progress' and parse_items(text) and not task_status.manual(text)):continue
        name=domain.FIELDS[key];value=label(fields[key]) if key=='owner' else fields[key]
        pattern=re.compile(r'^[ \t]*(?:\*\*)?'+re.escape(name)+r':(?:\*\*)?[^\n]*$',re.M)
        if pattern.search(head):head=pattern.sub(lambda _:name+': '+value,head,count=1)
        else:head=head.rstrip()+'\n\n'+name+': '+value+'\n\n'
    return (head+tail).rstrip()+text[len(original):]


def eligible(d):
    """Only direct children of the project's published task container qualify."""
    from . import outline, store
    if not d.get('publishedAt') or d.get('archivedAt') or d.get('deletedAt') or d.get('template'):return False
    cid=d.get('collectionId');parent_id=d.get('parentDocumentId')
    if not cid or not parent_id:return False
    parent=outline.api('documents.info',{'id':parent_id},missing_ok=True)
    if not parent or parent.get('collectionId')!=cid or parent.get('parentDocumentId') or not parent.get('publishedAt') or parent.get('archivedAt') or parent.get('deletedAt'):return False
    saved=store.get('task-parent:'+cid)
    return parent_id==saved['id'] if saved else parent.get('title')=='업무 목록'


def validate_assignment(d,fields,items):
    from . import permissions
    allowed={p['email'].lower() for p in permissions.collection_people(d['collectionId'])}
    if any(email not in allowed for email in [fields['owner'],*[i['owner'] for i in items]]):
        raise ValueError('해당 Outline 컬렉션에 접근 가능한 활성 구성원만 담당자로 지정하세요.')
