"""Read-only retrieval for Outline and chat, with live scoped evidence."""
import re, time, calendar
from typing import Literal
from datetime import datetime, timezone, timedelta
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
import user_acl
from rag_sync import available, version
from rag_search import fuse
from rag_answer import answer


class Query(BaseModel):
    model_config={'extra':'forbid'}
    query:str=Field(min_length=1,max_length=1500)
    mode:Literal['links','answer']='answer'
    collections:list[str]=Field(default_factory=list,max_length=100)
    document_id:str=''
    author_id:str=''
    days:int=Field(default=0,ge=0,le=36500)
    date_filter:Literal['','day','week','month','year']=''
    title_only:bool=False


def terms(text):
    text=re.sub(r'(?:문서|자료)?\s*(?:링크|주소)\s*(?:제공해\s*줘|알려\s*줘|보여\s*줘|줘)?|(?:찾아|검색해|제공해|알려|보여)\s*줘|해주세요|해\s*주세요',' ',text)
    return [t.casefold() for t in re.findall(r'[가-힣A-Za-z0-9_-]{2,}',text) if t not in ('문서','자료','관련','대한','관한')]


def title_score(query,title):
    words=terms(query);compact=re.sub(r'\s+','',title).casefold()
    return sum(1 for w in words if w in compact)/max(1,len(words))


def matches(doc,q):
    if q.document_id and doc['id']!=q.document_id:return False
    if not doc.get('publishedAt') or doc.get('archivedAt') or doc.get('deletedAt'):return False
    if q.author_id and q.author_id not in doc.get('collaboratorIds',[]):return False
    if q.days or q.date_filter:
        try:
            now=datetime.now(timezone.utc)
            if q.date_filter in ('month','year'):
                year=now.year-(1 if q.date_filter=='year' else int(now.month==1))
                month=now.month if q.date_filter=='year' else now.month-1 or 12
                cutoff=now.replace(year=year,month=month,day=min(now.day,calendar.monthrange(year,month)[1]))
            else:cutoff=now-timedelta(days={'day':1,'week':7}.get(q.date_filter,q.days))
            if datetime.fromisoformat(doc['updatedAt'].replace('Z','+00:00'))<cutoff:return False
        except (ValueError,KeyError):return False
    if q.title_only and title_score(q.query,doc.get('title',''))<1:return False
    return True


def dated_evidence(text,start,question):
    """Recover plain-text report dates for already indexed source fragments."""
    context=''
    for line in text[:start+1].splitlines():
        if re.search(r'\d{1,2}월\s*\d{1,2}일|\d{4}[-./]\d{1,2}[-./]\d{1,2}',line) and re.search(r'\d{1,2}\s*시|\d{1,2}:\d{2}',line):context=line.strip('*# []')
    def stamp(value):
        result={}
        date=re.search(r'(?:(\d{4})[-./년]\s*)?(\d{1,2})(?:월\s*|[-./])(\d{1,2})(?:일)?',value)
        if date:
            result.update(month=int(date[2]),day=int(date[3]))
            if date[1]:result['year']=int(date[1])
        clock=re.search(r'(오전|오후)?\s*(\d{1,2})\s*(?:시(?:\s*(\d{1,2})분)?|:(\d{2}))',value)
        if clock:
            hour=int(clock[2]);period=clock[1]
            result['hour']=(hour%12+(12 if period=='오후' else 0)) if period else hour
            minute=clock[3] or clock[4]
            if minute is not None:result['minute']=int(minute)
        return result
    wanted,actual=stamp(question),stamp(context)
    if any(actual.get(key)!=value for key,value in wanted.items()):return None
    return context


async def search(service,q):
    start=time.monotonic();timings={};core=service.core
    if not service.enabled:raise HTTPException(503,'AI 검색을 준비하고 있어요.')
    current_actor=user_acl.actor.get()
    access={'collections':current_actor['collections']} if current_actor is not None else await user_acl.check()
    if access is None:raise HTTPException(401,'검색 사용자 인증이 필요합니다.')
    with user_acl.index_inventory():registered=await service.syncer.collections()
    selected=set(registered.values())&set(access['collections'])
    if q.collections:selected&=set(q.collections)
    if not selected:return {'status':'not_included','answer':'선택한 범위가 AI 검색 대상에 포함되지 않았어요.','documents':[],'citations':[]}
    if q.collections and set(q.collections)-selected:raise HTTPException(403,'선택한 범위의 검색 권한 또는 검색 포함 설정을 확인하세요.')
    state=await service.store.status();states=[s for s in state['collections'] if s['collection_id'] in selected]
    warnings=[]
    if len(states)<len(selected):warnings.append('일부 문서를 검색할 수 있도록 준비하고 있어요.')
    if any(s['result'].get('failed') or not s['result'].get('inventory_complete') for s in states):warnings.append('일부 문서 갱신에 실패해 검색 결과가 완전하지 않을 수 있어요.')
    if not states:return {'status':'preparing','answer':'문서를 검색할 수 있도록 준비하고 있어요.','documents':[],'citations':[]}
    docs=[d for d in await service.store.inventory(list(selected)) if matches(d,q)]
    byid={d['id']:d for d in docs}
    direct=sorted([d for d in docs if title_score(q.query,d.get('title',''))>=1],key=lambda d:(-title_score(q.query,d['title']),d['title'])) if terms(q.query) else []
    rows=[];llm_calls=0
    if q.mode=='links' and direct:
        candidates=direct[:6]
    else:
        t=time.monotonic();vector=(await service.embeddings.call(query=q.query))['vector'];timings['embedding']=round(time.monotonic()-t,3)
        lexical,semantic=await service.store.candidates(' '.join(terms(q.query)) or q.query,vector,list(selected),[])
        threshold=float(__import__('os').getenv('RAG_MIN_SIMILARITY','0.80'))
        if semantic:threshold=max(threshold,semantic[0]['similarity']-0.045)
        identifiers=[t for t in terms(q.query) if re.search(r'[A-Za-z가-힣_-]+\d',t) and not re.search(r'\d(?:월|일|시|분)',t)]
        def relevant(row):
            hay=(row['document'].get('title','')+' '+row['text']).casefold()
            return row['document_id'] in byid and all(t in hay for t in identifiers)
        semantic=[r for r in semantic if r['similarity']>=threshold and relevant(r)]
        lexical=[r for r in lexical if relevant(r) and (r['similarity']>=threshold or title_score(q.query,r['document'].get('title',''))>=.6)]
        rows=fuse(lexical,semantic,limit=24)
        candidates=[byid[did] for did in dict.fromkeys(r['document_id'] for r in rows)]
    timings['retrieval']=round(time.monotonic()-start,3)
    # Authorize only ranked candidates, before fetching their text or calling the model.
    allowed=set((await user_acl.check(documents=[d['id'] for d in candidates[:12]]))['documents'])
    candidates=[d for d in candidates[:12] if d['id'] in allowed]
    live={};stale=False;failures=False
    for d in candidates[:12]:
        try:
            with user_acl.index_inventory():current=await core.info(d['id'])
            if not available(current,selected) or not matches(current,q):continue
            if q.mode=='answer' and any(r['document_id']==d['id'] and r['version']!=version(current,service.profile) for r in rows):
                stale=True;service.changed.set();continue
            live[d['id']]=current
        except HTTPException as ex:
            if ex.status_code not in (403,404):failures=True
    valid=[r for r in rows if r['document_id'] in live]
    # Batch live ACL before model input; avoid one callback per fragment/document.
    await user_acl.require_documents(list(live))
    numbers={};facts=[]
    for row in valid:
        did=row['document_id'];numbers.setdefault(did,len(numbers)+1)
        meta=row['metadata'];text=row['text']
        context=dated_evidence(live[did].get('text',''),meta.get('start',0),q.query)
        if context is None:continue
        if meta.get('body_kind')=='example' and not re.search(r'예시|양식|템플릿',q.query):continue
        if meta.get('fragmented'):text=live[did].get('text','')[meta.get('unit_start',meta['start']):meta.get('unit_end',meta['end'])].strip()
        # Fact IDs retain original row positions even when another time is filtered out.
        facts.append({'id':valid.index(row)+1,'source':numbers[did],'text':(context+'\n' if context else '')+text,'context':live[did]['title']+' / '+meta.get('heading',''),'body_kind':meta.get('body_kind','unknown')})
    used=[];report='';metrics={}
    if q.mode=='answer' and facts:
        async def counted_llm(*args,**kwargs):
            nonlocal llm_calls
            llm_calls+=1
            return await core.llm(*args,**kwargs)
        t=time.monotonic();report,used,metrics=await answer(facts,q.query,counted_llm);timings['generation']=round(time.monotonic()-t,3)
        used_ids={valid[f['id']-1]['document_id'] for f in used}
        live={did:d for did,d in live.items() if did in used_ids}
    elif q.mode=='answer':live={}
    # Re-read after generation so a changed or removed source cannot be cited.
    final=[]
    for did,d in live.items():
        with user_acl.index_inventory():latest=await core.info(did)
        if not available(latest,selected) or not matches(latest,q) or version(latest,service.profile)!=version(d,service.profile):
            return {'status':'stale','answer':'문서가 변경되었어요. 다시 검색해 주세요.','documents':[],'citations':[]}
        final.append({'id':did,'title':d['title'],'collection_id':d['collectionId'],'collection':service.syncer.names.get(d['collectionId'],''),
                      'url':core.doc_result(d)['url'],'revision':d.get('revision'),
                      'number':numbers.get(did,len(final)+1)})
    if q.mode=='links':final=final[:3]
    await user_acl.verify_used()
    if failures:warnings.append('일부 문서를 확인하지 못했어요.')
    if stale:warnings.append('변경된 문서의 검색 정보를 갱신하고 있어요. 잠시 후 다시 검색해 주세요.')
    status='succeeded' if final else 'preparing' if stale else 'failed' if failures else 'no_results'
    if not final:report=warnings[-1] if warnings else '선택한 범위에서 검색 근거를 찾지 못했어요.'
    timings['total']=round(time.monotonic()-start,3)
    return {'status':status,'mode':q.mode,'answer':report,'documents':final,'citations':final,'warnings':warnings,
            'effective_scope':[{'id':cid,'name':service.syncer.names.get(cid,'')} for cid in sorted(selected)],
            'timings':timings,'generation_calls':llm_calls,'metrics':metrics}


def install(app,authorize,service):
    @app.get('/rag/knowledge/catalog',dependencies=[Depends(authorize)])
    async def catalog():
        rows=[]
        for offset in range(0,10000,100):
            page=await service.core.outline('collections.list',{'limit':100,'offset':offset},read=True);rows+=page
            if len(page)<100:break
        else:raise HTTPException(503,'컬렉션 목록을 모두 확인하지 못했습니다.')
        return {'legacy':[{'id':c['id'],'name':c['name']} for c in rows if c['name'] in service.collection_names],
                'managed':await service.store.managed_scope()}

    @app.post('/rag/knowledge/refresh',dependencies=[Depends(authorize)])
    async def refresh():
        service.changed.set();return {'status':'queued'}

    @app.post('/agent/knowledge-search',dependencies=[Depends(authorize)])
    async def query(body:Query):return await search(service,body)
