"""Markdown units retain original offsets, headings, quote kind and table context."""
import hashlib
import re

def units(text):
    heading=[]; offset=0; header=''; table=False
    for line in text.splitlines(keepends=True):
        raw=line.strip(); start=offset+(line.find(raw) if raw else 0); offset+=len(line)
        if not raw: table=False; header=''; continue
        if raw.startswith('#'):
            depth=len(raw)-len(raw.lstrip('#'));heading=heading[:depth-1]+[raw.lstrip('# ').strip()];continue
        if re.fullmatch(r'[|:\-\s]+',raw): continue
        kind='quoted' if raw.startswith('>') or any(re.search('인용|원문|이전 메모',h) for h in heading) else 'example' if any(re.search('예시|템플릿|양식 안내',h) for h in heading) else 'current'
        is_table=raw.startswith('|')
        context=header if is_table and table else ''
        if is_table and not table: header=raw
        table=is_table
        if raw in ('미기재','- 미기재'): continue
        yield {'text':raw,'heading':' / '.join(heading),'body_kind':kind,'start':start,'end':offset,'table_header':context}

def split_document(doc, tokenizer, max_tokens=350):
    output=[]
    for unit in units(doc.get('text','')):
        prefix='passage: '+doc['title']+' / '+unit['heading']+'\n'+unit['table_header']+'\n'
        if len(tokenizer.encode(prefix,add_special_tokens=False))+2>=512:
            raise ValueError('Document heading exceeds embedding budget')
        remaining=unit['text']; consumed=0
        while remaining:
            capacity=min(max_tokens,510-len(tokenizer.encode(prefix,add_special_tokens=False)))
            hi=len(remaining);lo=1;best=0
            while lo<=hi:
                mid=(lo+hi)//2
                if len(tokenizer.encode(remaining[:mid],add_special_tokens=False))<=capacity:
                    best=mid;lo=mid+1
                else:hi=mid-1
            if not best:raise ValueError('Cannot fit source unit')
            piece=remaining[:best]
            if best<len(remaining):
                boundary=max(piece.rfind('. ')+1,piece.rfind(' '))
                if boundary>best//2:piece=piece[:boundary]
            start=unit['start']+consumed
            cid=hashlib.sha256((str(start)+':'+piece).encode()).hexdigest()[:24]
            output.append({**unit,'text':piece,'start':start,'end':start+len(piece),'chunk_id':cid,
                'unit_start':unit['start'],'unit_end':unit['end'],
                'fragmented':len(piece)!=len(unit['text']), 'embedding_text':prefix+piece})
            consumed+=len(piece);remaining=remaining[len(piece):]
    return output
