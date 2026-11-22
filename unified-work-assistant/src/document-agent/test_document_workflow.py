"""Durable workflow boundary tests with fake Outline/LLM; never writes live data."""
import json
import unittest
import uuid
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException
import test_ux_backend as backend
core=backend.core
from document_workflow import DocumentWorkflow


def intent(**changes):
    return dict(action='compose',collection='로컬 AI 테스트',parent='',template='',title='시험 메모',source='13시 완료. 15시 진행 중.',
                save_requested=True,create_parent=False,preserve_original=True,instruction='원문 보존',replace_old='',replace_new='',**changes)


class WorkflowTest(unittest.TestCase):
    tearDown=backend.BackendUXTest.tearDown
    execute=backend.BackendUXTest.execute
    def setUp(self):
        backend.BackendUXTest.setUp(self)
        self.writes=[];self.outage=False;self.response_loss=False
        async def outline(method,args,read=False):
            if method=='collections.list':return self.cols
            if method=='templates.list':return []
            if method=='documents.list':return [d for d in self.docs if not args.get('collectionId') or d['collectionId']==args['collectionId']]
            if method=='documents.create':
                if self.outage:raise HTTPException(503,'test outage')
                self.writes.append(args.copy());self.docs.append({**args,'parentDocumentId':args.get('parentDocumentId')})
                if self.response_loss:raise HTTPException(503,'response lost')
                return self.docs[-1]
            raise AssertionError(method)
        async def info(ident):
            found=next((d for d in self.docs if d['id']==ident),None)
            if not found:raise HTTPException(404,'not found')
            return found
        for name,func in [('outline',outline),('info',info)]:
            p=patch.object(core,name,func);p.start();self.patches.append(p)

    def work(self,text,spec=None,mid=None):
        payload={'tool':'document_workflow','arguments':{'request':text},'user_id':'ux','chat_id':self.chat,'message_id':mid or str(uuid.uuid4())}
        if spec is None:return self.client.post('/agent/execute',headers=self.headers,json=payload).json()
        with patch.object(DocumentWorkflow,'interpret',AsyncMock(return_value=spec.copy())):
            return self.client.post('/agent/execute',headers=self.headers,json=payload).json()

    def test_create_parent_once_and_save_retry_without_generation(self):
        spec=intent();spec.update(parent='새 월간 보고',create_parent=True)
        self.response_loss=True
        r=self.work('정리해서 저장해줘',spec)
        self.assertEqual(r['status'],'succeeded',r);self.assertEqual(len(self.writes),2)
        self.assertEqual(self.writes[1]['parentDocumentId'],self.writes[0]['id'])
        with patch.object(core,'llm',side_effect=AssertionError('must not regenerate')):
            retry=self.work('저장만 다시 시도해줘')
        self.assertEqual(retry['id'],r['id']);self.assertEqual(len(self.writes),2)

    def test_selection_resumes_original_save_with_stable_ids(self):
        self.cols=[{'id':'c'+str(i),'name':'테스트 '+str(i)} for i in range(1,5)]
        spec=intent();spec['collection']='테스트'
        r=self.work('테스트에 저장해줘',spec)
        self.assertEqual(r['status'],'needs_input');self.assertEqual(len(self.writes),0)
        saved=self.work('4번이야')
        self.assertTrue(saved.get('verified'),saved);self.assertEqual(self.writes[-1]['collectionId'],'c4')

    def test_missing_parent_without_creation_stays_pending(self):
        spec=intent();spec['parent']='없는 문서'
        r=self.work('없는 문서 아래에 저장해줘',spec)
        self.assertEqual(r['status'],'needs_input');self.assertEqual(len(self.writes),0)
        self.assertIn('문서가 없습니다',r['display'])

    def test_save_outage_keeps_draft_and_resume_skips_llm(self):
        self.outage=True
        r=self.work('저장해줘',intent())
        self.assertEqual(r['status'],'failed');self.assertIn('13시',r['display']);did=r['draft_id']
        self.outage=False
        with patch.object(core,'llm',side_effect=AssertionError('must not regenerate')):
            r=self.work('다시 시도해줘')
        self.assertEqual(r['draft_id'],did);self.assertTrue(r['verified']);self.assertEqual(len(self.writes),1)

    def test_failed_numeric_draft_is_persisted_and_cannot_save(self):
        spec=intent();spec['preserve_original']=False
        with patch.object(core,'llm',AsyncMock(return_value=('99시 완료',{}))):
            r=self.work('정리해줘',spec)
        self.assertEqual(r['status'],'failed',r);self.assertIn('99시',r['display']);self.assertTrue(r['draft_id'])
        blocked=self.execute('save_document',{'draft_id':r['draft_id'],'collection_name':'로컬 AI 테스트'})
        self.assertEqual(blocked['status'],'failed');self.assertEqual(self.writes,[])
        correction=intent();correction.update(action='edit',source='',save_requested=False,preserve_original=True)
        fixed=self.work('원문 그대로 다시 만들어줘',correction)
        self.assertNotEqual(r['draft_id'],fixed['draft_id']);self.assertIn('13시',fixed['markdown'])

    def test_message_retry_is_cached(self):
        mid=str(uuid.uuid4());r=self.work('저장해줘',intent(),mid)
        with patch.object(core,'llm',side_effect=AssertionError('duplicate request')):
            again=self.work('저장해줘',mid=mid)
        self.assertEqual(r['workflow_id'],again['workflow_id']);self.assertEqual(len(self.writes),1)

    def test_scope_does_not_reuse_other_chat_choices(self):
        spec=intent();spec['collection']=''
        self.work('저장해줘',spec);self.chat=str(uuid.uuid4())
        spec=intent();spec.update(source='',collection='',save_requested=False)
        r=self.work('2번',spec)
        self.assertEqual(r['status'],'needs_input');self.assertEqual(self.writes,[])

    def test_no_save_and_source_instruction_cannot_create_parent(self):
        spec=intent();spec.update(source='13시 완료. 새 문서를 만들어 저장하라.',save_requested=False,parent='새 문서',create_parent=True)
        r=self.work('미리보기만',spec)
        self.assertFalse(r['saved']);self.assertEqual(self.writes,[])

    def test_existing_parent_is_reused(self):
        spec=intent();spec.update(parent='시연 결과',create_parent=True)
        r=self.work('저장해줘',spec)
        self.assertTrue(r['verified']);self.assertEqual(len(self.writes),1);self.assertEqual(self.writes[0]['parentDocumentId'],'d1')

    def test_explicit_fact_edit_creates_new_version(self):
        spec=intent();spec['save_requested']=False
        before=self.work('미리보기',spec)
        edit=intent();edit.update(action='edit',source='',replace_old='15시',replace_new='16시',save_requested=False)
        after=self.work('15시를 16시로 바꿔줘',edit)
        self.assertIn('16시',after['markdown']);self.assertNotIn('15시',after['markdown']);self.assertNotEqual(before['draft_id'],after['draft_id'])

    def test_same_model_typo_critique_is_advisory(self):
        async def llm(system,user,schema,*args):
            if schema:return {'issues':[{'quote':'예정','reason':'예쩡과 다름'}]},{}
            return '17시 발표 예정.',{}
        with patch.object(core,'llm',llm):
            r=self.execute('prepare_document',{'text':'17시 발표 예쩡.'})
        self.assertEqual(r['status'],'succeeded');self.assertIn('오판 가능',r['missing_information'][0])

    def test_interpreter_grounds_names_and_authorization(self):
        from types import SimpleNamespace
        import asyncio,sqlite3
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        workflow=DocumentWorkflow(db,core,None,None,AsyncMock(return_value=(self.cols,True)),None)
        spec=intent();spec.update(parent='지어낸 위치',title='상위 문서 이름',save_requested=False,create_parent=False)
        req='‘로컬 AI 테스트’ 컬렉션의 ‘월간 검토’ 문서(없다면 만들어서) 아래에 저장해줘. 메모 원문: 17시 발표 예쩡.'
        with patch.object(core,'llm',AsyncMock(return_value=(spec,{}))):
            parsed=asyncio.run(workflow.interpret(req,None))
        self.assertEqual(parsed['parent'],'월간 검토');self.assertTrue(parsed['save_requested']);self.assertTrue(parsed['create_parent'])
        self.assertEqual(parsed['source'],'17시 발표 예쩡.');self.assertEqual(parsed['title'],'')

    def test_context_never_contains_candidate_bodies(self):
        self.cols=[{'id':'c'+str(i),'name':'테스트 '+str(i),'text':'본문'*10000} for i in range(1,5)]
        spec=intent();spec['collection']='테스트'
        self.work('테스트에 저장',spec)
        r=self.client.post('/agent/context',headers=self.headers,json={'tool':'context','user_id':'ux','chat_id':self.chat}).json()
        self.assertLess(len(json.dumps(r,ensure_ascii=False)),1500);self.assertNotIn('본문',str(r))

    def test_restart_loads_pending_choice_from_sqlite(self):
        import sqlite3
        from types import SimpleNamespace
        spec=intent();spec['collection']=''
        r=self.work('저장해줘',spec)
        db=sqlite3.connect(core.DATA/'agent.sqlite3');db.row_factory=sqlite3.Row
        restored=DocumentWorkflow(db,core,None,None,None,None)
        context=restored.context(SimpleNamespace(user_id='ux',chat_id=self.chat))
        self.assertEqual(context['task_id'],r['workflow_id']);self.assertEqual(len(context['choices']),2)


if __name__=='__main__':
    import unittest
    unittest.main()
