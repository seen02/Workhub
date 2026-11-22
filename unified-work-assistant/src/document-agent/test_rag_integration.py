"""Real E5 + pgvector, fake Outline source. Dedicated rag_test DB only."""
import asyncio
import copy
import json
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from fastapi import HTTPException
from rag_service import RagService
from rag_sync import version

async def main():
    assert os.environ.get('RAG_DATABASE_NAME')=='rag_test','Only the dedicated test DB is allowed'
    docs=json.loads(Path('tests/fixtures/rag/documents.json').read_text())
    docs+=[{'id':f'filler-{i}','title':f'일반 공지 {i}','text':f'사무실 비품 {i}번 주문 완료. 공유 회의실 청소 예정.'} for i in range(14)]
    docs={d['id']:{**d,'collectionId':'fixture','revision':1,'url':'/doc/'+d['id']} for d in docs}
    blocked=set();requests=[]
    async def outline(method,args,read=False):
        assert read,'Test fixture must never call a write API'
        requests.append(method)
        if method=='collections.list':return [{'id':'fixture','name':'로컬 AI 테스트'}]
        if method=='documents.list':return [copy.deepcopy(d) for d in docs.values() if d['collectionId']=='fixture'][args['offset']:args['offset']+args['limit']]
        raise AssertionError(method)
    async def info(did):
        if did in blocked:raise HTTPException(403,'revoked')
        if did not in docs:raise HTTPException(404,'deleted')
        return copy.deepcopy(docs[did])
    core=SimpleNamespace(KEY='test-'+str(uuid.uuid4()),outline=outline,info=info,
        llm=AsyncMock(return_value=({'points':[]},{})),doc_result=lambda d:{**d,'url':'http://fixture'+d['url']})
    service=RagService(core)
    initial=await service.syncer.sync();assert initial['indexed']==20 and initial['status']=='succeeded',initial
    repeated=await service.syncer.sync();assert repeated['unchanged']==20 and repeated['indexed']==0,repeated
    cases=[('Sat2City 고객 참석 확정됐어?','meeting'),('고객 측 답변이 도착했나요?','meeting'),
           ('Sat2City 발표 자료 수정 상태','slides'),('Sat3DGen 고객 일정','different'),
           ('Sat2City 출시하려면 어떤 조건이 필요해?','conditional')]
    records=[]
    for question,expected in cases:
        result=await service.quick(question,question,'',lambda _:None)
        ids=[s['id'] for s in result['sources']]
        records.append({'question':question,'expected':expected,'sources':ids,'hit':expected in ids,'timings':result['timings']})
        assert expected in ids,records[-1]
        assert ids==[expected],records[-1]
        if 'Sat2City' in question:assert 'different' not in ids
        assert result['read_count']==0
    noanswer=await service.quick('목성의 위성 개수와 대기 구성은?','목성의 위성 개수와 대기 구성은?','',lambda _:None)
    assert not noanswer['sources'],noanswer['sources']
    old=await service.store.current('meeting')
    try:
        await service.store.replace(old['metadata'],'rollback-test',[
            {'chunk_id':'good','text':'미완성 새 조각','embedding':[0.0]*384},
            {'chunk_id':'bad','text':'차원 오류로 롤백','embedding':[1.0]}])
        raise AssertionError('Invalid vector transaction unexpectedly committed')
    except Exception as exc:
        assert type(exc).__name__!='AssertionError'
    assert (await service.store.current('meeting'))['active_version']==old['active_version']
    original_outline=core.outline
    async def incomplete(method,args,read=False):
        if method=='documents.list':
            if args['offset']:raise HTTPException(503,'incomplete inventory')
            return [copy.deepcopy(docs['meeting'])]*100
        return await original_outline(method,args,read)
    core.outline=incomplete
    try:await service.syncer.sync()
    except HTTPException:pass
    assert (await service.store.current('slides'))['active'],'Incomplete listing invalidated a document'
    core.outline=original_outline
    docs['meeting']['text']='고객 참석 회신 완료. 회의 일정은 9월 22일로 확정되었습니다.';docs['meeting']['revision']=2
    original_call=service.embeddings.call
    service.embeddings.call=AsyncMock(side_effect=RuntimeError('embedding unavailable'))
    try:await service.syncer.one('meeting','fixture')
    except RuntimeError:pass
    assert (await service.store.current('meeting'))['active_version']==old['active_version'],'Failed replacement lost old version'
    service.embeddings.call=original_call
    assert await service.syncer.one('meeting','fixture')=='indexed'
    assert (await service.store.current('meeting'))['active_version']!=old['active_version']
    docs['owner']['collectionId']='elsewhere';del docs['measurement'];blocked.add('different')
    await service.syncer.sync()
    for did in ('owner','measurement','different'):assert not (await service.store.current(did))['active']
    # Incomplete inventory cannot remove otherwise accessible active records.
    blocked.add('meeting')
    revoked=await service.quick('Sat2City 고객 참석','Sat2City 고객 참석','',lambda _:None)
    assert 'meeting' not in [s['id'] for s in revoked['sources']]
    result={'initial':initial,'repeated':repeated,'retrieval':records,'unknown_question_abstained':True,
        'atomic_replacement':True,'sql_transaction_rollback':True,'incomplete_inventory_safe':True,
        'move_delete_revoke':True,'permission_revalidation':True,'outline_writes':0}
    Path('/app/data/rag-integration.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':asyncio.run(main())
