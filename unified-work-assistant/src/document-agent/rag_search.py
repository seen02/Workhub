import re

def project_codes(query):
    return list(dict.fromkeys(re.findall(r'(?<![A-Za-z0-9])(?=[A-Za-z0-9_-]*\d)[A-Za-z][A-Za-z0-9_-]+',query)))

def fuse(lexical, semantic, limit=6):
    scores={};rows={}
    for ranking in (lexical,semantic):
        for rank,row in enumerate(ranking,1):
            key=(row['document_id'],row['chunk_id'])
            scores[key]=scores.get(key,0)+1/(60+rank);rows[key]=row
    result=[];seen=set();per_doc={}
    for key in sorted(scores,key=scores.get,reverse=True):
        row=rows[key];text=re.sub(r'\s+','',row['text'])
        if text in seen or per_doc.get(row['document_id'],0)>=5:continue
        seen.add(text);per_doc[row['document_id']]=per_doc.get(row['document_id'],0)+1
        result.append(row)
        if len(result)>=limit:break
    return result
