"""Outline stores task values; local storage keeps projections and workflow mode."""
import re
from datetime import date, datetime, timezone, timedelta

FIELDS = {'project':'프로젝트', 'owner':'담당자', 'start':'시작일', 'due':'마감일', 'status':'상태',
          'progress':'진행률', 'blocker':'장애요인', 'next':'다음 행동', 'result':'결과물'}
STATES = ('미착수', '진행 중', '지연', '완료', '보류')
MARKER = '업무 유형: 통합 업무'

def saved_text_key(text):
    """Ignore only empty separators before report headings outside code.

    Outline collapses these separators on Markdown export. Keep task fields,
    notes, report content and blank lines inside fenced evidence exact.
    """
    lines=[];fence=None
    for line in text.split('\n'):
        match=re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$',line)
        if fence:
            if match and match[1][0]==fence[0] and len(match[1])>=fence[1] and not match[2].strip():fence=None
        elif match:
            fence=(match[1][0],len(match[1]))
        elif line=='### 보고 기록':
            # A standalone backslash here represents an empty hard-break
            # paragraph produced by the Outline editor, not report evidence.
            separator=False
            while lines and lines[-1] in ('','\\'):
                lines.pop();separator=True
            if separator:lines.append('')
        lines.append(line)
    return '\n'.join(lines)

def same_saved_text(expected,actual):
    if expected==actual or saved_text_key(expected)==saved_text_key(actual):return True
    from . import human_tasks
    if human_tasks.is_human(expected) and human_tasks.is_human(actual):
        return template_saved_key(expected)==template_saved_key(actual)
    return False

def template_saved_key(text):
    """Outline compacts template paragraph gaps; fenced report evidence stays exact."""
    lines=[];fence=None
    for line in saved_text_key(text).split('\n'):
        match=re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$',line)
        if fence:
            lines.append(line)
            if match and match[1][0]==fence[0] and len(match[1])>=fence[1] and not match[2].strip():fence=None
            continue
        if match:
            fence=(match[1][0],len(match[1]));lines.append(line);continue
        # A single trailing space has no Markdown meaning. Two spaces are a
        # hard line break and must remain significant.
        if line.endswith(' ') and not line.endswith('  '):line=line[:-1]
        if line=='' and lines and lines[-1]=='':continue
        lines.append(line)
    return '\n'.join(lines)

def source_text(text):
    """Historical quoted reports must never become live task fields/checklist rows."""
    return re.split(r'^### 보고 기록\s*$',text,maxsplit=1,flags=re.M)[0].rstrip()

def clean(value):
    return ' '.join(str(value or '').split()).strip()[:1000]

def validate(fields):
    f = {k: clean(fields.get(k)) for k in FIELDS}
    if not f['project']: raise ValueError('프로젝트를 입력하세요.')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', f['owner']): raise ValueError('담당자 이메일을 입력하세요.')
    if f['status'] not in STATES: raise ValueError('상태: '+', '.join(STATES))
    if f['due'] and f['due'] != '미정': date.fromisoformat(f['due'])
    f['due'] = f['due'] or '미정'
    if f['start'] and f['start'] != '미정': date.fromisoformat(f['start'])
    f['start'] = f['start'] or '미정'
    if f['start'] != '미정' and f['due'] != '미정' and f['start'] > f['due']:
        raise ValueError('시작일은 마감일보다 늦을 수 없습니다.')
    if f['progress'] not in ('', '미기재'):
        if not re.fullmatch(r'(100|[1-9]?\d)(\.\d+)?%?', f['progress']): raise ValueError('진행률은 0~100 또는 미기재입니다.')
        p = float(f['progress'].rstrip('%'))
        if p > 100: raise ValueError('진행률은 100을 넘을 수 없습니다.')
        f['progress'] = f'{p:g}%'
    else: f['progress'] = '미기재'
    return f

def render(fields, notes=''):
    f = validate(fields)
    return (MARKER+'\n\n'+'\n\n'.join(f'{label}: {f[k] or "없음"}' for k,label in FIELDS.items())+'\n\n## 업무 메모\n\n'+notes).strip()

def is_legacy_task(text):
    """Only the actual header declares a template, never a quoted source excerpt."""
    head = re.split(r'^## ', source_text(text), maxsplit=1, flags=re.M)[0]
    return bool(re.search(r'^업무 유형: 통합 업무\s*$', head, re.M))


def parse(text):
    text=source_text(text)
    if not is_legacy_task(text):
        from . import human_tasks
        return human_tasks.parse_fields(text) if human_tasks.is_human(text) else None
    fields = {}
    for k,label in FIELDS.items():
        matches = re.findall(r'^'+label+r':\s*([^\n]*)$', text, re.M)
        if k == 'start' and not matches:
            fields[k] = '미정'
            continue
        if len(matches) != 1: raise ValueError(f'{label} 항목은 한 번만 작성하세요.')
        fields[k] = matches[0]
    return validate(fields)

def patch_text(text, changes):
    from . import human_tasks
    if human_tasks.is_human(text):return human_tasks.patch_fields(text,changes)
    live=source_text(text)
    suffix=text[len(live):]
    text=live
    current = parse(text)
    if current is None: raise ValueError('통합 업무 문서가 아닙니다.')
    next_fields = validate({**current, **changes})
    for k in changes:
        if k not in FIELDS: raise ValueError('지원하지 않는 항목입니다.')
        if k == 'start' and not re.search(r'^시작일:', text, re.M):
            text = re.sub(r'^마감일:', lambda _: '시작일: '+next_fields[k]+'\n\n마감일:', text, count=1, flags=re.M)
            continue
        text = re.sub(r'^'+FIELDS[k]+r':[^\n]*$', lambda _: FIELDS[k]+': '+(next_fields[k] or '없음'), text, flags=re.M)
    return text+suffix

def statistics(tasks, today=None):
    today = today or datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    valid = [t for t in tasks if not t.get('error')]
    states = {s: sum(t['fields']['status']==s for t in valid) for s in STATES}
    overdue = [t for t in valid if t['fields']['due'] not in ('','미정') and t['fields']['due']<today and t['fields']['status']!='완료']
    return {'total':len(valid), 'invalid':len(tasks)-len(valid), 'states':states, 'completed':states['완료'],
            'completion_rate':round(100*states['완료']/len(valid),1) if valid else 0,
            'overdue':len(overdue), 'missing_progress':sum(t['fields']['progress']=='미기재' for t in valid),
            'blocked':sum(t['fields']['blocker'] not in ('','없음','-') for t in valid)}
