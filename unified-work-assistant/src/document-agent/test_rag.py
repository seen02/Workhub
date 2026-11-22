"""Offline contract, grounding, cancellation, permissions and resume regressions."""
import asyncio
import json
import os
import sqlite3
import unittest
from unittest.mock import AsyncMock,patch
from fastapi import HTTPException
from rag_answer import answer,business_question,equivalent
from rag_chunks import split_document
from rag_search import project_codes,fuse
from rag_sync import Synchronizer,available
from token_budget import enforce,measure
from task_runtime import TaskRuntime
import test_ux_backend as backend
core=backend.core

class GroundingTest(unittest.IsolatedAsyncioTestCase):
    async def test_status_numbers_owner_and_conditions_cannot_change(self):
        cases=[('PPT 3장 수정 완료.','PPT 3장 수정 진행 중.'),
            ('고객 참석 회신 전이므로 일정 미확정.','고객 일정 확정.'),
            ('승인을 받으면 17시 배포 예정.','17시 배포 예정.'),
            ('김철수 담당, 17일 검토.','이영희 담당, 17일 검토.'),
            ('처리 시간 11.8초.','처리 시간 10초.'),
            ('서버 응답 대기 중.','서버 장애 때문에 응답 대기 중.')]
        for source,bad in cases:
            with self.subTest(source=source):
                llm=AsyncMock(return_value=({'points':[{'text':bad,'facts':[1]}]},{}))
                result,used,metrics=await answer([{'id':1,'source':1,'text':source,'body_kind':'current'}],'현황 알려줘',llm)
                self.assertIn(source,result);self.assertNotIn('- '+bad,result);self.assertTrue(metrics['fallback'])
                self.assertIn(llm.await_count,(1,2)) # summaries also require a support check

    async def test_unknown_citation_and_server_metadata_fallback(self):
        for point in [{'text':'자료 없음','facts':[999]},{'text':'읽은 문서 수는 명시되지 않음','facts':[1]}]:
            result,_,_=await answer([{'id':1,'source':1,'text':'작업 완료.'}],'상태와 읽은 문서 수도 알려줘.',AsyncMock(return_value=({'points':[point]},{})))
            self.assertIn('작업 완료.',result);self.assertNotIn(point['text'],result)
        self.assertNotIn('문서 수',business_question('상태 알려줘. 읽은 문서 수도 알려줘.'))

    async def test_conflicting_quoted_state_is_not_merged(self):
        facts=[{'id':1,'source':1,'text':'수정 완료.','body_kind':'current'},
               {'id':2,'source':1,'text':'수정 진행 중.','body_kind':'quoted'}]
        result,_,_=await answer(facts,'상태',AsyncMock(return_value=({'points':[{'text':'수정 완료.','facts':[1]}]},{})))
        self.assertIn('서로 다른 상태',result);self.assertIn('인용된 원문',result);self.assertIn('수정 진행 중',result)

    async def test_no_evidence_does_not_call_model(self):
        llm=AsyncMock();result,_,_=await answer([],'무엇?',llm)
        self.assertIn('부족',result);llm.assert_not_awaited()

class ChunkBudgetTest(unittest.TestCase):
    def test_large_input_rejected_before_network(self):
        with self.assertRaises(HTTPException):enforce('안내','매우 긴 원문'*3000,{},800)
        self.assertFalse(measure('s','가나다라마바사'*3000,{},1600)['fits'])

    def test_chunk_offsets_table_header_and_kind(self):
        class Tok:
            def encode(self,text,**kwargs):return list(text)
        doc={'title':'현황','text':'# 현재\n  완료.\n> 진행 중.\n| 항목 | 상태 |\n|---|---|\n| 서버 | 완료 |\n'+('가'*700)}
        rows=split_document(doc,Tok(),100)
        for r in rows:
            self.assertEqual(doc['text'][r['start']:r['end']],r['text'])
            self.assertLessEqual(len(r['embedding_text']),512)
        self.assertTrue(any(r['body_kind']=='quoted' for r in rows))
        self.assertTrue(any(r['table_header']=='| 항목 | 상태 |' for r in rows))
        self.assertEqual(''.join(r['text'] for r in rows if r['fragmented']),'가'*700)

    def test_codes_and_rrf_dedup(self):
        self.assertEqual(project_codes('Sat2City랑 Sat3DGen 자료'),['Sat2City','Sat3DGen'])
        row={'document_id':'d','chunk_id':'1','text':'근거'}
        self.assertEqual(len(fuse([row],[row])),1)

class MultiCollectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_and_syncs_all_configured_collections(self):
        docs={
            'a':{'id':'a','title':'시험','text':'첫 내용','collectionId':'c1','revision':1},
            'b':{'id':'b','title':'업무','text':'둘째 내용','collectionId':'c2','revision':1},
        }
        async def outline(method,args,read=False):
            self.assertTrue(read)
            if method=='collections.list':return [{'id':'c1','name':'로컬 AI 테스트'},{'id':'c2','name':'개인 업무 보고'}]
            if method=='documents.list':return [doc for doc in docs.values() if doc['collectionId']==args['collectionId']]
            self.fail(method)
        async def info(docid):return docs[docid]
        store=AsyncMock();store.profile='test';store.current.return_value=None
        embeddings=AsyncMock();embeddings.call.return_value={'chunks':[]}
        syncer=Synchronizer(type('Core',(),{'outline':staticmethod(outline),'info':staticmethod(info)})(),store,embeddings,
            ['로컬 AI 테스트','개인 업무 보고'])
        result=await syncer.sync()
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['indexed'],2)
        self.assertEqual(result['inventory_count'],2);self.assertEqual(store.sync_state.await_count,2)
        self.assertTrue(available(docs['a'],['c1','c2']))
        self.assertFalse(available({**docs['a'],'collectionId':'outside'},['c1','c2']))

    async def test_missing_collection_fails_closed(self):
        async def outline(method,args,read=False):return [{'id':'c1','name':'로컬 AI 테스트'}]
        syncer=Synchronizer(type('Core',(),{'outline':staticmethod(outline)})(),AsyncMock(),AsyncMock(),
            ['로컬 AI 테스트','개인 업무 보고'])
        with self.assertRaises(HTTPException):await syncer.collections()

class RuntimeTest(unittest.IsolatedAsyncioTestCase):
    def make(self):
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        db.execute('CREATE TABLE events(id TEXT PRIMARY KEY,scope TEXT,tool TEXT,args TEXT,result TEXT,status TEXT,started REAL,seconds REAL)')
        return db,TaskRuntime(db)

    async def test_real_cancel_preserves_checkpoint_and_stops_next_call(self):
        db,runtime=self.make();started=asyncio.Event();calls=[]
        async def work():
            runtime.update(display='첫 문서 완료',pending_documents=[{'id':'remaining'}]);started.set()
            await asyncio.sleep(30);calls.append('must not run')
        eid=runtime.register('u:c','research_documents',{})
        task=asyncio.create_task(runtime.run(eid,'u:c',work,60));runtime.tasks[eid]=task
        await started.wait()
        self.assertIsNone(runtime.cancel(eid,'another:chat'));self.assertFalse(task.cancelled())
        runtime.cancel(eid,'u:c');result=await task
        self.assertEqual(result['status'],'cancelled');self.assertIn('첫 문서 완료',result['display'])
        self.assertEqual(len(result['pending_documents']),1);self.assertEqual(calls,[])

    async def test_restart_recovers_stale_states(self):
        db,runtime=self.make();eid=runtime.register('u:c','read_request',{})
        db.execute("UPDATE events SET status='running',result=? WHERE id=?",(json.dumps({'display':'부분 결과'}),eid));db.commit()
        recovered=TaskRuntime(db).result(eid,'u:c')
        self.assertEqual(recovered['status'],'interrupted');self.assertEqual(recovered['display'],'부분 결과')

    async def test_timeout_keeps_partial(self):
        _,runtime=self.make();eid=runtime.register('u:c','read_request',{})
        async def work():runtime.update(display='보관됨');await asyncio.sleep(30)
        result=await runtime.run(eid,'u:c',work,.01)
        self.assertEqual(result['status'],'partial');self.assertIn('보관됨',result['display'])

    async def test_cancel_during_save_reconciles_uuid_on_retry(self):
        import httpx
        from testing_identity import headers,policy
        guard=policy();guard.start();self.addCleanup(guard.stop)
        docs={};writes=[];started=asyncio.Event()
        async def info(did):
            if did not in docs:raise HTTPException(404,'missing')
            return docs[did]
        async def outline(method,args,read=False):
            if method=='collections.list':return [{'id':'c','name':'시험'}]
            if method=='documents.create':
                docs[args['id']]=dict(args);writes.append(args['id']);started.set()
                await asyncio.sleep(30)
            else:raise AssertionError(method)
        payload={'tool':'prepare_document','user_id':'save-cancel','chat_id':str(__import__('uuid').uuid4()),
                 'arguments':{'text':'17시 발표 예정.','title':'취소 시험','preserve_original':True}}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=core.app),base_url='http://testserver',headers=headers('save-cancel')) as client:
            with patch.object(core,'info',info),patch.object(core,'outline',outline):
                draft=(await client.post('/agent/execute',json=payload)).json()
                saving={**payload,'tool':'save_document','arguments':{'draft_id':draft['draft_id'],'collection_name':'시험'}}
                first=(await client.post('/agent/submit',json=saving)).json()
                await asyncio.wait_for(started.wait(),2)
                scoped={**payload,'arguments':{'event_id':first['event_id']}}
                await client.post('/agent/cancel',json=scoped)
                await asyncio.gather(*list(core.app.state.task_runtime.tasks.values()),return_exceptions=True)
                retry=(await client.post('/agent/execute',json=saving)).json()
                self.assertTrue(retry['verified']);self.assertEqual(len(writes),1);self.assertEqual(retry['id'],writes[0])

class ResearchRecoveryTest(unittest.TestCase):
    setUp=backend.BackendUXTest.setUp
    tearDown=backend.BackendUXTest.tearDown
    execute=backend.BackendUXTest.execute
    def test_collection_noun_suffix_and_entire_inventory(self):
        intent={'action':'catalog','topic':'','collection_name':'로컬 AI 테스트 컬렉션','document_id':''}
        async def llm(system,user,schema,*_):
            return (intent if 'action' in schema['properties'] else {'points':[]}),{}
        with patch.object(core,'llm',llm):
            result=self.execute('read_request',{'request':'로컬 AI 테스트 컬렉션의 문서를 모두 읽어줘'})
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['read_count'],1)
        self.assertEqual(result['collection_name'],'로컬 AI 테스트')
    def test_partial_resume_and_revoked_followup(self):
        self.docs=[{'id':f'd{i}','title':'시험 프로젝트 '+str(i),'collectionId':'c1','text':f'{i}번째 작업 완료.'} for i in range(3)]
        with patch.dict(os.environ,{'RESEARCH_MAX_DOCUMENTS':'1'}),patch.object(core,'llm',AsyncMock(return_value=({'points':[]},{}))):
            first=self.execute('research_documents',{'topic':'시험 프로젝트'})
            self.assertEqual(first['status'],'partial');self.assertEqual(first['read_count'],1);self.assertEqual(len(first['pending_documents']),2)
            second=self.execute('read_request',{'request':'조사 이어서'})
            self.assertEqual(second['read_count'],2);self.assertEqual(len(second['pending_documents']),1)
            with patch.object(core,'info',AsyncMock(side_effect=HTTPException(403,'revoked'))):
                final=self.execute('read_request',{'request':'그 내용에서 다음 할 일만 알려줘'})
            self.assertEqual(final['sources'],[]);self.assertNotIn('0번째 작업 완료',final['display'])

    def test_scoped_cancel_endpoint(self):
        payload={'tool':'read_request','user_id':'ux','chat_id':'x','arguments':{'event_id':'unknown'}}
        self.assertEqual(self.client.post('/agent/cancel',headers=self.headers,json=payload).status_code,404)

    def test_transient_read_failure_can_resume(self):
        with patch.object(core,'llm',AsyncMock(return_value=({'points':[]},{}))):
            with patch.object(core,'info',AsyncMock(side_effect=HTTPException(503,'outage'))):
                first=self.execute('research_documents',{'topic':'시연 결과','collection_name':'로컬 AI 테스트'})
            self.assertEqual(first['status'],'partial');self.assertEqual(first['read_count'],0)
            resumed=self.execute('read_request',{'request':'조사 이어서'})
            self.assertEqual(resumed['status'],'succeeded');self.assertEqual(resumed['read_count'],1);self.assertEqual(resumed['failed'],[])

    def test_revoked_source_does_not_renumber_remaining_citations(self):
        self.docs=[{'id':'one','title':'시험 A','collectionId':'c1','text':'첫 문서 완료.'},
                   {'id':'two','title':'시험 B','collectionId':'c1','text':'두 번째 문서 진행 중.'}]
        async def restricted(did):
            if did=='one':raise HTTPException(403,'revoked')
            return self.docs[1]
        with patch.object(core,'llm',AsyncMock(return_value=({'points':[]},{}))):
            self.execute('research_documents',{'topic':'시험'})
            with patch.object(core,'info',restricted):
                result=self.execute('read_request',{'request':'그 내용에서 상태를 알려줘'})
        self.assertIn('[2]',result['report']);self.assertIn('2. [시험 B]',result['display'])
        self.assertNotIn('첫 문서 완료',result['display'])

if __name__=='__main__':unittest.main()
