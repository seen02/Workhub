"""Isolated server boundary tests: no live Outline or model requests."""
import os,tempfile,unittest,uuid
from unittest.mock import AsyncMock,patch
os.environ['DATA_DIR']=tempfile.mkdtemp(prefix='outline-ux-test-')
os.environ.setdefault('OUTLINE_API_KEY','test')
os.environ.setdefault('AGENT_TOKEN','test')
import app as core
from fastapi.testclient import TestClient

class BackendUXTest(unittest.TestCase):
    def setUp(self):
        self.chat=str(uuid.uuid4())
        self.cols=[{'id':'c1','name':'로컬 AI 테스트'},{'id':'c2','name':'다른 문서함'}]
        self.docs=[{'id':'d1','title':'[회사시연] 시연 결과','collectionId':'c1','parentDocumentId':None,'text':'결과 저장 위치'},
                   {'id':'d2','title':'업무 결과','collectionId':'c2','parentDocumentId':None,'text':'결과 저장 위치'}]
        async def outline(method,args,read=False):
            if method=='collections.list':return self.cols
            if method=='templates.list':return []
            if method=='documents.list':return [d for d in self.docs if not args.get('collectionId') or d['collectionId']==args['collectionId']]
            raise AssertionError('Unexpected write: '+method)
        async def info(ident):return next(d for d in self.docs if d['id']==ident)
        from testing_identity import headers,policy
        self.patches=[patch.object(core,'outline',outline),patch.object(core,'info',info),policy(),patch.object(core.app.state.rag,'enabled',False)]
        for p in self.patches:p.start()
        self.client=TestClient(core.app);self.headers=headers('ux')
    def tearDown(self):
        for p in self.patches:p.stop()
    def execute(self,tool,args):
        return self.client.post('/agent/execute',headers=self.headers,json={'tool':tool,'arguments':args,'user_id':'ux','chat_id':self.chat}).json()
    def test_partial_parent_infers_collection(self):
        draft=self.execute('prepare_document',{'text':'진행 중','preserve_original':True,'title':'시험'})
        async def verify(plan):return {**plan,'parentDocumentId':plan.get('parentDocumentId')}
        with patch.object(core,'verify_create',verify):
            r=self.execute('save_document',{'draft_id':draft['draft_id'],'parent_title':'시연 결과'})
        self.assertTrue(r['verified']);self.assertIn('로컬 AI 테스트 / [회사시연] 시연 결과',r['location'])
    def test_read_request_searches_without_catalog(self):
        self.docs=[{**self.docs[0],'title':'간단검토0916-회의','text':'내부 시연은 17시 예정. 고객 일정은 미확정.'}]
        prompts=[]
        async def llm(system,user,schema,*_):
            prompts.append(user)
            if 'action' in schema.get('properties',{}):
                return {'action':'research','topic':'로컬 AI 테스트 간단검토0916','collection_name':'로컬 AI 테스트','document_id':'unused guessed ID'},{}
            if 'points' in schema.get('properties',{}):return {'points':[]},{}
            return {'핵심 내용':[1]},{}
        with patch.object(core,'llm',llm):
            r=self.execute('read_request',{'request':'‘로컬 AI 테스트’ 컬렉션에서 간단검토0916 관련 문서를 찾아 현재 상태와 다음 할 일을 짧게 정리해줘. 읽은 문서 수와 출처도 알려줘.'})
        self.assertEqual(r['status'],'succeeded');self.assertEqual(r['read_count'],1)
        self.assertEqual(r['collection_name'],'로컬 AI 테스트');self.assertIn('출처',r['display'])
        self.assertNotIn('[회사시연]',prompts[0]);self.assertNotIn('다른 문서함',prompts[0])

    def test_read_request_never_asks_model_to_invent_scope(self):
        intent={'action':'research','topic':'간단검토0916','collection_name':'모델이 만든 문서함','document_id':''}
        with patch.object(core,'llm',AsyncMock(return_value=(intent,{}))):
            r=self.execute('read_request',{'request':'간단검토0916 자료 찾아줘'})
        self.assertEqual(r['status'],'succeeded');self.assertEqual(r.get('collection_name',''),'')

    def test_read_request_followup_reuses_scoped_sources(self):
        self.docs=[{**self.docs[0],'title':'간단검토0916','text':'테스트 진행 중.'}]
        async def llm(system,user,schema,*_):
            if 'action' in schema.get('properties',{}):
                raise AssertionError('Explicit followup must not ask the model for a new search topic')
            if 'points' in schema.get('properties',{}):return {'points':[]},{}
            return {'핵심 내용':[1]},{}
        with patch.object(core,'llm',llm):
            original=self.execute('research_documents',{'topic':'간단검토0916','collection_name':'로컬 AI 테스트'})
            with patch.object(core,'outline',AsyncMock(side_effect=AssertionError('Must reuse prior sources'))):
                followup=self.execute('read_request',{'request':'그 내용에서 다음 할 일만 알려줘'})
        self.assertEqual(original['read_count'],1);self.assertTrue(followup['reused'])
        self.assertEqual(followup['sources'],original['sources'])

    def test_ambiguous_parent_keeps_draft_without_writing(self):
        r=self.execute('prepare_document',{'text':'진행 중','preserve_original':True,'title':'시험','save_requested':True,'parent_title':'결과'})
        self.assertTrue(r['needs_input']);self.assertFalse(r['saved']);self.assertEqual(len(r['question']['candidates']),2)
    def test_result_retrieval_is_scoped(self):
        r=self.execute('catalog',{})
        body={'tool':'result','arguments':{'event_id':r['event_id']},'user_id':'ux','chat_id':self.chat}
        self.assertEqual(self.client.post('/agent/result',headers=self.headers,json=body).status_code,200)
        body['chat_id']='someone-else'
        self.assertEqual(self.client.post('/agent/result',headers=self.headers,json=body).status_code,404)

    def test_time_range_markdown_escape_is_not_a_content_change(self):
        self.assertEqual(core.normalize('15:00~15:30'),core.normalize('15:00\\~15:30'))
        self.assertNotEqual(core.normalize('15:00~15:30'),core.normalize('15:00\\~16:30'))
    def test_bad_model_evidence_does_not_discard_read_document(self):
        self.docs=[{**self.docs[0],'text':'CITY-PILOT 처리시간 11.8초. 상태는 진행 중.'}]
        async def llm(*args):
            if 'points' in args[2].get('properties',{}):return {'points':[]},{}
            return {'개요':[99999]},{}
        with patch.object(core,'llm',llm):r=self.execute('research_documents',{'topic':'CITY-PILOT'})
        self.assertEqual(r['read_count'],1);self.assertEqual(r['failed'],[]);self.assertIn('11.8초',r['display'])

    def test_failed_draft_preserves_written_parts_without_saving(self):
        import json
        async def llm(system,user,schema,*_):
            if schema:return {'issues':[]},{}
            data=json.loads(user)
            return ('99시' if data['부분'].startswith('2/') else data['원문']),{}
        source='가'*1800+'원문17시'+'나'*1795+'끝'
        with patch.object(core,'llm',llm):
            r=self.execute('prepare_document',{'text':source,'save_requested':True,'parent_title':'시연 결과'})
        self.assertEqual(r['status'],'failed')
        self.assertIn('가'*1800,r['error']['candidate']);self.assertIn('99시',r['error']['candidate'])
        self.assertTrue(r['error']['partial']);self.assertEqual(r['error']['processed_parts'],2)
        self.assertNotIn('draft_id',r);self.assertNotIn('verified',r)

if __name__=='__main__':unittest.main()
