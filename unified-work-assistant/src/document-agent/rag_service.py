import asyncio
import hashlib
import os
import re
import time
import uuid
import user_acl
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from rag_store import RagStore
from rag_embeddings import Embeddings
from rag_sync import Synchronizer, available, version
from rag_search import project_codes, fuse
from rag_answer import answer, business_question

class ProjectSpec(BaseModel):
    id:uuid.UUID
    name:str=Field(min_length=1,max_length=200)
class ProjectRegistry(BaseModel):
    projects:list[ProjectSpec]=Field(max_length=1000)
    refresh:bool=False
    managed:bool=False
class SyncRequest(BaseModel):
    collection_id:str=''

class ReportCandidates(BaseModel):
    text:str=Field(min_length=2,max_length=4000)
    collections:list[str]=Field(min_length=1,max_length=200)
    documents:list[str]=Field(min_length=1,max_length=2000)

class RagService:
    def __init__(self, core):
        self.core=core
        self.enabled=os.getenv('RAG_ENABLED','false').lower()=='true'
        configured=os.getenv('RAG_COLLECTION_NAMES') or os.getenv('RAG_COLLECTION_NAME','로컬 AI 테스트')
        self.collection_names=list(dict.fromkeys(name.strip() for name in configured.split(',') if name.strip()))
        self.collection_name=self.collection_names[0]
        self.profile=os.getenv('RAG_EMBEDDING_PROFILE','e5-small-pending')
        namespace=os.getenv('RAG_SOURCE_NAMESPACE','outline-local')+':'+hashlib.sha256(core.KEY.encode()).hexdigest()[:16]
        self.store=RagStore(namespace,self.profile)
        self.embeddings=Embeddings(self.profile)
        self.syncer=Synchronizer(core,self.store,self.embeddings,self.collection_names)
        self.poll_task=None;self.last_error=None;self.changed=asyncio.Event();self.registry_lock=asyncio.Lock()

    async def quick(self, question, topic, collection_name, progress):
        times={};start=time.monotonic()
        with user_acl.index_inventory():collections=await self.syncer.collections()
        if collection_name and collection_name not in collections:
            raise HTTPException(409,'이 프로젝트는 아직 검색 대상으로 등록되지 않았습니다.')
        selected_names=[collection_name] if collection_name else [n for n in self.collection_names if n in collections]
        access=await user_acl.check()
        if access is not None:
            if collection_name and collections.get(collection_name) not in access['collections']:
                raise HTTPException(403,'선택한 문서함에 접근할 권한이 없습니다.')
            selected_names=[name for name in selected_names if collections[name] in access['collections']]
            if not selected_names:raise HTTPException(403,'접근 가능한 검색 대상 문서함이 없습니다.')
        selected_ids=[collections[name] for name in selected_names]
        state=await self.store.status()
        selected_states=[item for item in state['collections'] if item['collection_id'] in selected_ids]
        if len(selected_states)!=len(selected_ids) or not state['documents']:
            raise HTTPException(503,'선택한 범위의 RAG 초기 색인이 없거나 실패했습니다. /rag/status와 /rag/sync를 확인하세요.')
        times['request_scope']=round(time.monotonic()-start,3)
        progress('질문 의미를 검색하고 있습니다')
        codes=project_codes(question)
        semantic_question=business_question(question)
        for code in codes:semantic_question=re.sub(re.escape(code),'',semantic_question,flags=re.I)
        semantic_question=semantic_question.strip() or question
        lexical_query=topic
        t=time.monotonic();vector=(await self.embeddings.call(query=semantic_question))['vector'];times['embedding']=round(time.monotonic()-t,3)
        t=time.monotonic();lexical,semantic=await self.store.candidates(lexical_query.strip() or semantic_question,vector,selected_ids,codes)
        include_history=bool(re.search(r'보고\s*(기록|이력)|이전|과거|변경\s*이력',question))
        before_release=bool(re.search(r'(배포|출시|오픈).*전',question))
        def eligible(row):
            heading=row['metadata'].get('heading','')
            if before_release and re.search(r'배포 후 확인|출시 후 확인',heading):return False
            return include_history or not re.search(r'보고\s*(기록|이력)|이전 메모',heading)
        lexical=[r for r in lexical if eligible(r)];semantic=[r for r in semantic if eligible(r)]
        threshold=float(os.getenv('RAG_MIN_SIMILARITY','0.80'))
        if semantic:
            threshold=max(threshold,semantic[0]['similarity']-float(os.getenv('RAG_SCORE_WINDOW','0.06')))
        semantic=[row for row in semantic if row['similarity']>=threshold]
        # Exact named-topic matches remain candidates even when generic question
        # wording has a lower vector score. Question-facet filtering happens
        # after live permission/version checks, before the answer model.
        needle=re.sub(r'\s+','',lexical_query).casefold()
        lexical=[row for row in lexical if row['similarity']>=threshold or (len(needle)>=2 and needle in re.sub(r'\s+','',row['document'].get('title','')+' '+row['text']).casefold())]
        rows=fuse(lexical,semantic,limit=18)
        # One bounded keyword retry in the SAME collection; do not widen scope.
        retried=False
        if len(rows)<3:
            keywords=' '.join(re.findall(r'[가-힣A-Za-z0-9_-]{2,}',semantic_question)[:6])
            if keywords and keywords!=lexical_query:
                extra,_=await self.store.candidates(keywords,vector,selected_ids,codes)
                rows=fuse([r for r in extra if eligible(r) and r['similarity']>=threshold],rows,limit=18);retried=True
        times['search']=round(time.monotonic()-t,3)
        progress('선택한 원문의 접근 권한과 버전을 확인하고 있습니다')
        t=time.monotonic();checked={};live_cache={};valid=[];failed=[]
        for row in rows:
            did=row['document_id']
            if did not in checked:
                try:
                    live=await self.core.info(did)
                    live_cache[did]=live
                    checked[did]=available(live,selected_ids) and version(live,self.profile)==row['version']
                    if not checked[did]:
                        await self.store.deactivate(did)
                        self.changed.set()
                except HTTPException as exc:
                    checked[did]=False
                    if exc.status_code==404:await self.store.deactivate(did)
                if not checked[did]:failed.append({'id':did,'reason':'접근·상태·버전 재확인 실패'})
            if checked[did]:
                # Recover the full original source unit for long fragments, and
                # include headings/table headers rather than isolated cell text.
                meta=row['metadata'];text=row['text']
                if meta.get('fragmented'):
                    text=live_cache[did].get('text','')[meta.get('unit_start',meta['start']):meta.get('unit_end',meta['end'])].strip()
                context=' / '.join(x for x in (row['document'].get('title'),meta.get('heading')) if x)
                row={**row,'context':context,'text':(meta.get('table_header','')+'\n' if meta.get('table_header') else '')+text}
                if row['text'] not in {r['text'] for r in valid}:valid.append(row)
        times['source_validation']=round(time.monotonic()-t,3)
        numbers={};facts=[]
        for row in valid:
            did=row['document_id'];numbers.setdefault(did,len(numbers)+1)
            facts.append({'id':len(facts)+1,'source':numbers[did],'text':row['text'],
                'context':row.get('context',''),
                'body_kind':row['metadata'].get('body_kind','unknown')})
        progress('근거로 답변을 작성하고 있습니다')
        t=time.monotonic();report,used,metrics=await answer(facts,question,self.core.llm);times['qwen_generation']=round(time.monotonic()-t,3)
        await user_acl.verify_used()
        used_rows=[valid[f['id']-1] for f in used];sources=[]
        for did,number in numbers.items():
            group=[r for r in used_rows if r['document_id']==did]
            if not group:continue
            doc=group[0]['document'];sources.append({'id':did,'document_id':did,'number':number,
                'title':doc['title'],'url':self.core.doc_result(doc)['url'],'revision':doc.get('revision'),
                'version':group[0]['version'],'chunk_ids':[r['chunk_id'] for r in group],'read_scope':'selected_chunks','excerpts':[r['text'] for r in group]})
        scope_names='”, “'.join(self.syncer.names.get(cid,cid) for cid in selected_ids)
        scope=f'“{scope_names}”의 활성 색인에서 정확 검색과 의미 검색을 결합했습니다.'
        display=report+f'\n\n근거: 문서 {len(sources)}개에서 {len(used_rows)}개 부분 사용 · 문서 전체 읽기 아님\n\n### 출처\n\n'
        display+='\n'.join(f"[{s['number']}] [{s['title']}]({s['url']})" for s in sources)
        display+='\n\n'+scope+f'\n원문 재확인 실패·제외 {len(failed)}개'
        display+=f"\n답변 검토 후보 {metrics.get('considered_fact_count',0)}개 · 실제 인용 {len(used_rows)}개"
        sync_failures=sum(len(s['result'].get('failed',[])) for s in selected_states)
        if sync_failures:display+=f'\n색인 실패 {sync_failures}개가 있어 검색 범위가 일부입니다.'
        times['server_total']=round(time.monotonic()-start,3)
        result={'research_id':str(uuid.uuid4()),'mode':'quick','topic':topic or question,'collection_name':collection_name,'collection_names':selected_names,
            'read_count':0,'matched_count':len({r['document_id'] for r in rows}),'sources':sources,'failed':failed,
            'report':report,'display':display,'scope':scope,'metrics':metrics,'timings':times,
            'retrieval':{'strategy':'hybrid','keyword_retry':retried,'used_document_count':len(sources),'used_chunk_count':len(used_rows),
                'fully_read_document_count':0,'candidate_document_count':len({r['document_id'] for r in rows}),
                'live_revalidated':True,'minimum_similarity':threshold,'inventory_complete':all(s['result'].get('inventory_complete') for s in selected_states),
                'index_as_of':str(min(s['synced_at'] for s in selected_states))},
            'findings':[{'number':s['number'],'title':s['title'],'url':s['url'],'evidence':[
                {'category':'핵심 내용','quote':r['text'],'body_kind':r['metadata'].get('body_kind','unknown')}
                for r in used_rows if r['document_id']==s['id']]} for s in sources]}
        return result

    def install(self, app, authorize):
        from knowledge_search import install
        install(app,authorize,self)
        @app.post('/agent/report-candidates',dependencies=[Depends(authorize)])
        async def report_candidates(body:ReportCandidates):
            if not self.enabled:raise HTTPException(503,'RAG 검색 준비 중입니다.')
            access=await user_acl.check()
            if access is None:raise HTTPException(401,'보고 검색 사용자 인증이 필요합니다.')
            selected=list(set(body.collections)&set(access['collections']))
            if not selected:raise HTTPException(403,'접근 가능한 검색 범위가 없습니다.')
            vector=(await self.embeddings.call(query=body.text))['vector']
            lexical,semantic=await self.store.candidates(body.text,vector,selected,[])
            ids=set(body.documents);found={}
            for row in fuse(lexical,semantic,limit=40):
                did=row['document_id']
                if did not in ids or did in found:continue
                try:
                    live=await self.core.info(did)
                    if not available(live,selected) or version(live,self.profile)!=row['version']:continue
                except HTTPException:continue
                found[did]={'id':did,'score':float(row['similarity']),'revision':live.get('revision',0)}
            await user_acl.verify_used()
            return {'candidates':list(found.values()),'mode':'hybrid'}

        @app.get('/rag/status',dependencies=[Depends(authorize)])
        async def status():
            return {'enabled':self.enabled,'poll_error':self.last_error,'syncing':self.syncer.lock.locked(),**(await self.store.status() if self.enabled else {})}
        @app.post('/rag/workhub/projects',dependencies=[Depends(authorize)])
        async def projects(body:ProjectRegistry):
            if not self.enabled:raise HTTPException(409,'RAG 검색이 비활성화되어 있습니다.')
            projects=sorted([{'id':str(p.id),'name':p.name} for p in body.projects],key=lambda p:p['id'])
            if len({p['id'] for p in projects})!=len(projects):raise HTTPException(422,'중복 프로젝트 ID')
            async with self.registry_lock:
                old=await self.store.workhub_projects()
                if body.managed:await self.store.set_workhub_projects(projects,managed=True)
                elif old!=projects:await self.store.set_workhub_projects(projects)
            if old!=projects or body.refresh:self.changed.set()
            return {'registered':len(projects)}
        @app.post('/rag/sync',dependencies=[Depends(authorize)])
        async def sync(body:SyncRequest=SyncRequest()):
            if not self.enabled:raise HTTPException(409,'RAG_ENABLED=false')
            return await self.syncer.sync(collection_id=body.collection_id)
        @app.post('/rag/reindex',dependencies=[Depends(authorize)])
        async def reindex():
            if not self.enabled:raise HTTPException(409,'RAG_ENABLED=false')
            return await self.syncer.sync(force=True)
        async def poll():
            while True:
                self.changed.clear()
                try:
                    outcome=await self.syncer.sync();self.last_error=None if outcome['status']=='succeeded' else 'partial'
                except Exception as exc:self.last_error=type(exc).__name__
                try:await asyncio.wait_for(self.changed.wait(),timeout=30 if self.last_error else max(30,int(os.getenv('RAG_SYNC_INTERVAL_SECONDS','300'))))
                except TimeoutError:pass
        @app.on_event('startup')
        async def start():
            if self.enabled:
                await self.store.migrate()
                self.poll_task=asyncio.create_task(poll())
        @app.on_event('shutdown')
        async def stop():
            if self.poll_task:
                self.poll_task.cancel()
                await asyncio.gather(self.poll_task,return_exceptions=True)
