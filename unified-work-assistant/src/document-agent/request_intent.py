"""Deterministic read intent; user text and the live catalogue own scope."""
import re

QUOTES = '\"“”‘’\''


def interpret_read(raw, collections):
    text = raw.strip()
    col = ''
    # Match known names longest first, only with an explicit collection suffix.
    for row in sorted(collections, key=lambda r: len(r['name']), reverse=True):
        pattern = r'\s*'.join(re.escape(part) for part in row['name'].split()) + r'[\"”’\']?\s*(?:컬렉션|문서함)(?:에서|의|에)?'
        match = re.search(pattern, text)
        if match:
            col = row['name']
            text = (text[:match.start()].rstrip(QUOTES) + ' ' + text[match.end():]).strip()
            break
    unknown = re.search(r'[\"“‘\']([^\"”’\']+)[\"”’\']\s*(?:컬렉션|문서함)', text)
    if unknown and not col:
        return {'action':'clarify','topic':'','collection_name':unknown[1],'document_id':''}
    if not col and re.search(r'(?:컬렉션|문서함)(?:에서|의|에)\s',text):
        return {'action':'clarify','topic':'','collection_name':'','document_id':''}
    url = re.search(r'https?://[^\s<>\"”’]+/doc/[^\s<>\"”’]+', text)
    base = {'collection_name':col,'document_id':'','topic':''}
    if url and not re.search(r'관련|비교', text):
        return {**base,'action':'read','document_id':url[0].rstrip('.。,')}
    if re.search(r'할 수 있|사용법|어떻게.*사용', text):
        return {**base,'action':'help'}
    if re.search(r'(?:컬렉션|문서함|양식|템플릿|문서)\s*(?:목록|리스트)|문서함과.*양식', text) or (col and re.search(r'^\s*목록', text)):
        return {**base,'action':'catalog'}
    if col and re.search(r'모두|전체|전부', text) and re.search(r'읽|조사', text):
        return {**base,'action':'research'}
    codes = re.findall(r'(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9_-]*\d[A-Za-z0-9_-]*', text)
    if codes:
        topic = codes[0]
    else:
        topic = re.split(r'\s*(?:관련\s*(?:문서|자료)?|자료(?:를)?\s*찾|문서(?:를)?\s*찾|찾아|검색해|알려|보여)', text, maxsplit=1)[0]
        topic = topic.strip(' '+QUOTES)
        topic = re.sub(r'^(?:아래|이|해당)\s+', '', topic)
    if re.search(r'찾|검색|알려|보여|읽|정리|확정|누가|언제|누구|뭐|어떻게|\?', text) and topic:
        return {**base,'action':'research','topic':topic[:300]}
    return {**base,'action':'clarify'}
