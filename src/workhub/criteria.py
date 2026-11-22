"""Human-editable Outline checklist; checked items are the progress numerator."""
import re
import uuid
from .domain import source_text

STATES = ('예정', '진행 중', '완료')
HEADING = '## 완료 기준'
SECTION = re.compile(r'^## 완료 기준\s*\n(.*?)(?=^## |\Z)', re.M | re.S)
LINE = re.compile(r'^\s*[-*] \[([ xX])\] (C-[a-f0-9]{8}) \| (.+?) \| 담당자: ([^|]+?) \| 상태: (예정|진행 중|완료)\s*$')


def validate(items):
    if not isinstance(items, list) or not 1 <= len(items) <= 40:
        raise ValueError('완료 기준은 1~40개로 등록하세요.')
    result = []
    for item in items:
        cid = item.get('id') or 'C-' + uuid.uuid4().hex[:8]
        title = str(item.get('title', '')).strip()
        owner = str(item.get('owner', '')).strip().lower()
        state = item.get('state', '예정')
        if not re.fullmatch(r'C-[a-f0-9]{8}', cid):
            raise ValueError('완료 기준 ID가 올바르지 않습니다.')
        if not 2 <= len(title) <= 160 or any(c in title for c in '\r\n|[]\\'):
            raise ValueError('완료 기준 이름은 2~160자이며 줄바꿈·|·대괄호·역슬래시는 사용할 수 없습니다.')
        if not re.fullmatch(r'[^\s@|]+@[^\s@|]+\.[^\s@|]+', owner):
            raise ValueError('각 완료 기준에 담당자 이메일을 지정하세요.')
        if state not in STATES:
            raise ValueError('완료 기준 상태는 예정, 진행 중, 완료입니다.')
        result.append(dict(id=cid, title=title, owner=owner, state=state))
    if len({i['id'] for i in result}) != len(result):
        raise ValueError('완료 기준 ID가 중복되었습니다.')
    if len({i['title'] for i in result}) != len(result):
        raise ValueError('완료 기준 이름은 서로 구분되게 작성하세요.')
    return result


def parse(text):
    from . import human_tasks
    if human_tasks.is_human(text):return human_tasks.parse_items(text)
    text=source_text(text)
    sections = list(SECTION.finditer(text))
    if not sections:
        return []
    if len(sections) != 1:
        raise ValueError('완료 기준 구역은 한 번만 작성하세요.')
    result = []
    for line in sections[0].group(1).splitlines():
        if not line.strip():
            continue
        m = LINE.fullmatch(line)
        if not m:
            raise ValueError('완료 기준 형식을 확인하세요. 체크박스·ID·항목명·담당자·상태를 유지하세요.')
        checked, cid, title, owner, state = m.groups()
        # Checking/unchecking in the native Outline editor has immediate semantic meaning.
        state = '완료' if checked.lower() == 'x' else ('예정' if state == '완료' else state)
        result.append(dict(id=cid, title=title, owner=owner, state=state))
    return validate(result)


def render(items):
    items = validate(items)
    return HEADING + '\n\n' + '\n'.join(
        f"- [{'x' if i['state']=='완료' else ' '}] {i['id']} | {i['title']} | 담당자: {i['owner']} | 상태: {i['state']}"
        for i in items) + '\n\n'


def replace(text, items):
    from . import human_tasks
    if human_tasks.is_human(text):return human_tasks.replace_items(text,items)
    live=source_text(text)
    suffix=text[len(live):]
    return _replace(live,items)+suffix

def _replace(text,items):
    section = render(items)
    if SECTION.search(text):
        if len(list(SECTION.finditer(text))) != 1:
            raise ValueError('완료 기준 구역이 중복되었습니다.')
        return SECTION.sub(lambda _: section, text, count=1).rstrip()
    pos = text.find('## 업무 메모')
    if pos < 0:
        return text.rstrip() + '\n\n' + section.rstrip()
    return text[:pos] + section + text[pos:]


def rollup(items):
    done = sum(i['state'] == '완료' for i in items)
    progress = round(100 * done / len(items), 1)
    status = '완료' if done == len(items) else ('미착수' if all(i['state'] == '예정' for i in items) else '진행 중')
    return {'status': status, 'progress': f'{progress:g}%'}


def select(items, code):
    matches = [i for n, i in enumerate(items, 1) if code in (i['id'], str(n), i['title'])]
    if len(matches) != 1:
        raise ValueError('완료 기준 번호 또는 이름을 확인하세요.')
    return matches[0]
