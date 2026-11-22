"""Small, deterministic helpers for name resolution and evidence presentation."""
import re
import unicodedata

CATEGORIES = ['개요', '핵심 내용', '진행 상태·결과', '문제점', '다음 계획']

def normalized(value):
    return re.sub(r'[^\w]', '', unicodedata.normalize('NFKC', value).casefold())

def candidates(rows, query, field='title'):
    q = normalized(query)
    if not q: return []
    exact = [r for r in rows if r.get('id') == query or normalized(r.get(field, '')) == q]
    if exact: return exact
    # Tolerate spacing/punctuation and unique partial names; never choose by rank.
    return [r for r in rows if len(q) >= 2 and q in normalized(r.get(field, ''))]

def source_units(text):
    """Give the model IDs to choose, never ask it to reproduce source quotes."""
    text = re.sub(r'\\([.\[\]#*_!])', r'\1', text)
    units = []
    heading = ''
    for line in text.splitlines():
        line = line.strip()
        if not line or re.fullmatch(r'[|:\-\s]+', line): continue
        if line.startswith('#'):
            heading = line.lstrip('# ').strip()
            continue
        if re.match(r'^(프로젝트|작성|분류)\s*[:：]',line): continue
        if '모두 가상 설정' in line: continue
        if line.startswith('|'):
            parts = [' · '.join(x.strip() for x in line.strip('|').split('|'))]
        else:
            parts = re.split(r'(?<=[.!?])\s+(?=[가-힣A-Z0-9“])', line)
        for part in parts:
            part = re.sub(r'^[-*]\s+', '', part).strip()
            if part:
                kind='quoted' if line.startswith('>') or re.search('인용|원문|이전 메모',heading) else 'example' if re.search('예시|템플릿|양식 안내',heading) else 'current'
                units.append({'id': len(units)+1, 'section': heading, 'text': part, 'body_kind':kind})
    return units

def render_research(result):
    if not result.get('matched_count'):
        return '**관련 문서를 찾지 못했습니다.**\n\n프로젝트 이름의 일부나 문서 제목으로 다시 찾아볼 수 있습니다.'
    findings = result.get('findings', [])
    groups = {c: [] for c in CATEGORIES}
    seen = set()
    for f in findings:
        for e in f['evidence']:
            key = normalized(e['quote'])
            if key in seen: continue
            seen.add(key)
            groups.get(e['category'], groups['핵심 내용']).append((e['quote'], f['number']))
    sections = []
    # Display concise sections, retain the remaining evidence in expandable details.
    for category in CATEGORIES:
        items = groups[category]
        lines = [f'- {quote} [{number}]' for quote, number in items]
        sections.append('## '+category+'\n\n'+('\n'.join(lines[:3]) if lines else '읽은 자료에서 별도로 확인된 내용이 없습니다.'))
        if len(lines)>3:
            sections.append('<details>\n<summary>추가 근거 '+str(len(lines)-3)+'개</summary>\n\n'+'\n'.join(lines[3:])+'\n\n</details>')
    return '\n\n'.join(sections)

def research_display(r):
    header=f"**문서 {r['read_count']}개 읽음 / 관련 {r['matched_count']}개 · Outline에 저장하지 않았습니다**"
    if r.get('reused'): header+='\n\n이 대화에서 읽은 자료를 재사용했습니다. 새로 검색하려면 ‘최신 자료로 다시 찾아줘’라고 요청하세요.'
    text=header+'\n\n'+r['report']+'\n\n---\n### 출처\n\n'
    text+='\n'.join(f"{s.get('number',i+1)}. [{s['title']}]({s['url']})" for i,s in enumerate(r.get('sources',[])))
    text+='\n\n### 조사 범위\n\n'+r['scope']
    text+=f"\n\n목록 {r['inventory_count']}개 확인 · 읽기 실패/제외 {len(r.get('failed',[]))}개"
    if not r.get('inventory_complete'): text+=' · 목록 한도에 도달해 전체 목록은 확인하지 못했습니다.'
    for f in r.get('failed',[]): text+=f"\n- {f['title']}: {f['reason']}"
    for warning in r.get('warnings',[]): text+='\n- '+warning
    return text
