"""The server owns template headings; model values contain body text only."""
import re


def compact_template(name):
    key=re.sub(r'\s+','',name)
    if key in ('builtin-compact-work-report','간단업무보고','간단업무보고양식','간단업무보고템플릿'):
        return {'id':'builtin-compact-work-report','title':'간단 업무 보고 양식','text':'## 완료한 업무\n\n## 진행 중인 업무\n\n## 예정 업무\n\n## 기타 기록'}
    return None


def compact_report(source):
    """Keep each supplied record verbatim; never infer dates or replace times."""
    groups={key:[] for key in ('완료한 업무','진행 중인 업무','예정 업무','기타 기록')}
    for record in re.split(r'\n+|\s+/\s+|(?<=[.!?])\s+',source.strip()):
        record=record.strip()
        if not record:continue
        plain=re.sub(r'\s+','',record)
        flags=[bool(re.search(pattern,plain)) for pattern in (r'(?<!미)완료',r'진행중|검토중|확인중',r'예정|계획')]
        key=list(groups)[flags.index(True)] if sum(flags)==1 and not re.search('미완료|미해결|실패|보류',plain) else '기타 기록'
        groups[key].append(record)
    return '\n\n'.join('## '+key+'\n\n'+'\n'.join('- '+record for record in records) for key,records in groups.items() if records)


def heading_key(value):
    value=re.sub(r'\\([\[\]*#])',r'\1',value).strip()
    value=re.sub(r'^(?:(?:[-*+] |\d+[.)] )|#{1,6}\s*)+','',value).strip()
    return re.sub(r'\s+','',value.strip('*_[]:： '))


def clean_slot_text(text, headings, source=''):
    """Remove leading echoed labels only; preserve labels quoted in source.

    Never globally replace heading words: sentences mentioning a heading,
    Markdown links and actual source labels are document content.
    """
    keys={heading_key(h) for h in headings}
    original={line.strip() for line in source.splitlines() if line.strip()}
    lines=text.strip().splitlines()
    while lines:
        line=lines[0].strip()
        if not line:lines.pop(0);continue
        if line not in original and heading_key(line) in keys:
            lines.pop(0);continue
        # An echoed bracket heading may precede the body on the same line.
        match=re.match(r'^(?:[-*+]\s+)?(?:#{1,6}\s*)?(?:\*\*)?(\[[^\]\n]+\])(?:\*\*)?(?:\s*[:：]\s*|\s+)(.+)$',line)
        if match and heading_key(match[1]) in keys and match[1] not in source:
            lines[0]=match[2];continue
        break
    return '\n'.join(lines).strip()


def render_slots(headings, groups):
    return '\n\n'.join(heading+'\n\n'+('\n'.join('- '+text.replace('\n','\n  ') for text in items) if items else '미기재')
                       for heading,items in zip(headings,groups))
