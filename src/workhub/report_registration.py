"""A checklist definition is not evidence that its work has been completed."""
import re


def explicit_state(text):
    text=re.sub(r'완료\s*기준','기준',text)
    # Interpret the verb, never the word '완료' inside a field heading.
    if re.search(r'모르|인지|불명|\?',text):return None
    future=bool(re.search(r'예정|할\s*(?:계획|거)|미착수|미완료|아직|안\s*(?:했|됐|끝|해)|못\s*(?:했|끝|해)|않|하지\s*마',text))
    ongoing=bool(re.search(r'진행\s*중|하고\s*있|작업\s*중|조사\s*중|확인\s*중',text))
    if ongoing:return '진행 중'
    if future:return '예정'
    if re.search(r'완료|끝냈|끝났|마쳤|다\s*했',text):return '완료'
    return None


def normalize(source, row, all_titles):
    """Apply only to registration/definition input; ordinary reports stay intact.

    Ground states in each named item's clause. Shared predicates ('A와 B 완료')
    may cover a list, but never leak from another independently stated item.
    """
    registering=bool(re.search(r'(?:업무|기준|항목).{0,100}?(?:추가|등록|넣어|만들어)',source,re.S))
    defining=bool(re.search(r'완료\s*기준\s*(?:은|는|:|으로)',source))
    if not registering and not (defining and not row.get('task_id')):return
    source=re.sub(r'완료\s*기준','기준',source)
    spans=[]
    for title in set(all_titles):
        pattern=r'\s*'.join(re.escape(w) for w in title.split())
        if not pattern:continue
        for m in re.finditer(pattern,source,re.I):spans.append((m.start(),m.end(),title))
    # Prefer the full title if one criterion title contains another.
    chosen=[]
    for span in sorted(spans,key=lambda s:-(s[1]-s[0])):
        if not any(span[0]<s[1] and s[0]<span[1] for s in chosen):chosen.append(span)
    spans=sorted(chosen)
    for item in row['items']:
        states=set()
        for n,(start,end,title) in enumerate(spans):
            if title!=item['title']:continue
            stop=spans[n+1][0] if n+1<len(spans) else len(source)
            tail=source[end:stop]
            # Follow only pure list conjunctions to a shared trailing predicate.
            k=n
            while re.fullmatch(r'\s*(?:(?:와|과|및|그리고|랑|하고|,)\s*)+',tail) and k+1<len(spans):
                next_tail=source[spans[k+1][1]:spans[k+2][0] if k+2<len(spans) else len(source)]
                if re.match(r'\s*(?:은|는|만)',next_tail):break
                k+=1;tail=next_tail
            tail=re.split(r'[.;。\n]',tail,maxsplit=1)[0]
            state=explicit_state(tail)
            if not state:
                prefix=re.search(r'(완료한|끝낸|마친|진행\s*중인|예정인)\s*$',source[:start])
                if prefix:
                    state={'끝낸':'완료','마친':'완료'}.get(prefix[1]) or explicit_state(prefix[1])
            if state:states.add(state)
        # An explicit all-items statement is allowed, not an unrelated '완료'.
        shared=re.search(r'(?:모두|전부|둘\s*다|두\s*항목\s*다)\s*([^.;。\n]+)',source)
        if not states and shared:
            state=explicit_state(shared[1])
            if state:states.add(state)
        if len(states)>1:
            row.update(kind='unresolved',issue='같은 기준의 상태가 서로 다릅니다. 초안을 수정하세요.')
        elif states:item['state']=next(iter(states))
        else:
            item['state']='예정'
    row['registration_defaults']=True
