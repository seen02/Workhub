"""Conservative query facets before generation; no generated text is evidence."""
import re

# Synonyms describe the same explicit question facet, not a project whitelist.
FACETS = (
    ('고객|거래처', ('고객','거래처')),
    ('회의|참석', ('회의','참석','회신')),
    ('답변|회신', ('답변','회신','응답')),
    ('담당|누가|누구', ('담당','책임','확인할','확인할 예정')),
    ('납기|납품', ('납기','납품')),
    ('배포|승인|출시', ('배포','승인','출시')),
    (r'PPT|발표\s*자료', ('ppt','발표 자료')),
    ('장애|오류', ('장애','오류','실패')),
)


def select_evidence(facts, question):
    groups = [terms for pattern,terms in FACETS if re.search(pattern,question,re.I)]
    if not groups or not facts:
        return facts
    scored = []
    for fact in facts:
        body = fact['text'].lower()
        score = sum(any(term in body for term in terms) for terms in groups)
        scored.append((score,fact))
    best = max(score for score,_ in scored)
    # Explicit named facets with no support must not produce an unrelated answer.
    # Facets are ranking hints, not an exclusion gate for semantic matches.
    return [fact for score,fact in sorted(scored,key=lambda pair:pair[0],reverse=True)]
