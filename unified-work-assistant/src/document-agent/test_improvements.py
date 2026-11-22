import asyncio,json,sqlite3,unittest,uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from fastapi import HTTPException
from request_intent import interpret_read
from evidence_selection import select_evidence
from rag_answer import answer
from template_layout import compact_report
from edit_workflow import EditWorkflow
import test_ux_backend as backend

COLS=[{'name':'로컬 AI 테스트','id':'c1'},{'name':'개인 업무 보고','id':'c2'}]
FAILED_REQUESTS=[
 '로컬 AI 테스트 컬렉션에서 Sat2City 고객 참석 회신을 기다리고 있는 회의 관련 문서를 찾아줘. 담당자와 확인 기한, 출처도 알려줘.',
 '로컬 AI 테스트 컬렉션에서 Sat2City 관련 문서를 찾아 고객 회의 일정이 확정됐는지 알려줘. 출처도 보여줘.',
 'Sat2City 관련 문서에서 다음 할 일과 담당자, 기한을 원문과 출처로 보여줘.',
 'Sat2City 고객 답변은 누가 언제까지 확인해야 해? 원문과 출처도 알려줘.',
 'Sat2City 고객 회의 준비 자료에서 고객 답변을 누가 언제까지 확인하기로 했는지 알려줘. 원문과 출처도 보여줘.',
]

class IntentTest(unittest.TestCase):
    def test_all_previously_failed_forms(self):
        for text in FAILED_REQUESTS:
            with self.subTest(text=text):
                r=interpret_read(text,COLS);self.assertEqual(r['action'],'research');self.assertEqual(r['topic'],'Sat2City')
                self.assertEqual(r['collection_name'],'로컬 AI 테스트' if text.startswith('로컬') else '')
    def test_unknown_collection_does_not_broaden(self):
        for text in ['없는 컬렉션에서 Sat2City 찾아줘','“비공개” 컬렉션에서 자료 찾아줘']:
            self.assertEqual(interpret_read(text,COLS)['action'],'clarify')
    def test_spacing_and_quoted_collection(self):
        for col in ['로컬AI테스트','“로컬 AI 테스트”','‘로컬 AI 테스트’']:
            self.assertEqual(interpret_read(col+' 컬렉션에서 Sat2City 찾아줘',COLS)['collection_name'],'로컬 AI 테스트')
    def test_url_not_model_guess(self):
        r=interpret_read('http://localhost:8090/doc/example-123 원문 보여줘',COLS)
        self.assertEqual(r['action'],'read');self.assertEqual(r['document_id'],'http://localhost:8090/doc/example-123')
    def test_catalog_and_whole_collection(self):
        self.assertEqual(interpret_read('문서함과 양식 목록 보여줘',COLS)['action'],'catalog')
        r=interpret_read('개인 업무 보고 컬렉션의 문서를 모두 읽어줘',COLS)
        self.assertEqual(r['action'],'research');self.assertEqual(r['topic'],'')
    def test_korean_topic_and_date_preserved(self):
        self.assertEqual(interpret_read('서버 장애 관련 문서를 찾아줘',COLS)['topic'],'서버 장애')
        self.assertIn('9월 17일',interpret_read('개인 업무 보고 컬렉션에서 9월 17일 업무 알려줘',COLS)['topic'])

class EvidenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_citations_count_only_returned_evidence(self):
        facts=[{'id':1,'source':1,'text':'자료 첫째.'},{'id':2,'source':2,'text':'자료 둘째.'}]
        text,used,metrics=await answer(facts,'자료',AsyncMock(return_value=({'points':[{'text':'자료 둘째.','facts':[2]},{'text':'자료 둘째.','facts':[2]}]},{})))
        self.assertEqual([f['id'] for f in used],[2]);self.assertEqual(metrics['considered_fact_count'],2);self.assertEqual(metrics['cited_fact_count'],1)
    async def test_meeting_excludes_unrelated_ppt(self):
        facts=[{'id':1,'source':1,'text':'김민수 담당자는 고객 답변을 9월 18일까지 확인할 예정입니다.'},{'id':2,'source':2,'text':'PPT 3장 수정 진행 중.'}]
        text,used,_=await answer(facts,'고객 답변 담당자와 기한 알려줘',AsyncMock(return_value=({'points':[]},{})))
        self.assertEqual([f['id'] for f in used],[1]);self.assertNotIn('PPT',text)
    async def test_unsupported_facet_refuses_without_generation(self):
        llm=AsyncMock();text,used,_=await answer([{'id':1,'source':1,'text':'PPT 수정 완료.'}],'고객 회신 도착했어?',llm)
        self.assertEqual(used,[]);llm.assert_not_awaited();self.assertIn('부족',text)
    def test_generic_question_does_not_drop_evidence(self):
        f=[{'text':'기술 조사 중.'}];self.assertEqual(select_evidence(f,'현재 상태 알려줘'),f)
    def test_release_synonym_excludes_unrelated_owner(self):
        f=[{'text':'고객 승인을 받으면 배포 예정입니다.'},{'text':'담당자가 로그인을 확인할 예정입니다.'}]
        self.assertEqual(select_evidence(f,'출시하려면 어떤 조건이 필요해?'),[f[0]])

class CompactTest(unittest.TestCase):
    def test_times_states_no_empty_slots(self):
        text='13시 모델 생성 완료.\n15시 테스트 진행 중.\n17시 발표 예정.';out=compact_report(text)
        for line in text.splitlines():self.assertIn(line,out)
        self.assertNotIn('미기재',out);self.assertNotIn('17시 50분',out);self.assertNotIn('[월',out)
    def test_mixed_and_negative_states_stay_other(self):
        self.assertIn('## 기타 기록',compact_report('1차 완료, 2차 진행 중.'))
        self.assertNotIn('## 완료한 업무',compact_report('작업 미완료.'))

class WriteIntentTest(unittest.IsolatedAsyncioTestCase):
    async def test_live_destination_and_literal_title_override_model_suffix(self):
        from document_workflow import DocumentWorkflow
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        spec={'action':'save','collection':'로컬 AI 테스트 컬렉션','parent':'','template':'','title':'잘못된 제목','source':'','replace_old':'','replace_new':'','save_requested':True,'create_parent':False,'preserve_original':False}
        core=SimpleNamespace(llm=AsyncMock(return_value=(spec,{})))
        workflow=DocumentWorkflow(db,core,None,None,AsyncMock(return_value=(COLS,True)),None)
        r=await workflow.interpret('방금 초안을 로컬 AI 테스트 컬렉션에 ‘[검증] 간단 보고’라는 제목으로 저장해줘.',None)
        self.assertEqual(r['collection'],'로컬 AI 테스트');self.assertEqual(r['title'],'[검증] 간단 보고')

class EditTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.execute('CREATE TABLE research(id TEXT,scope TEXT,result TEXT,created REAL)')
        self.doc={'id':'d1','title':'회의 준비','text':'김민수 담당자는 18일까지 확인 예정. 다른 내용.','revision':1,'updatedAt':'t1','url':'/doc/one'}
        self.writes=[]
        async def info(ident):
            if ident!='d1':raise HTTPException(403,'denied')
            return self.doc.copy()
        async def outline(method,payload):
            self.writes.append(payload);self.assertEqual(payload['lastRevision'],self.doc['revision'])
            self.doc['text']=self.doc['text'].replace(payload['findText'],payload['text'],1);self.doc['revision']+=1;self.doc['updatedAt']='t2'
        self.core=SimpleNamespace(info=info,outline=outline,extract_id=lambda s:'d1',doc_result=lambda d:{**d,'verified':True},normalize=lambda s:s)
        self.editor=EditWorkflow(self.db,self.core,AsyncMock(return_value=([self.doc],True)))
        self.req=SimpleNamespace(user_id='u',chat_id='c',message_id='m')
        self.db.execute('INSERT INTO research VALUES (?,?,?,?)',('r','u:c',json.dumps({'sources':[{'id':'d1','title':'회의 준비','number':1}]}),1))
    async def runedit(self,raw,req=None):return await self.editor({'request':raw},req or self.req)
    async def test_number_preview_apply_and_retry(self):
        preview=await self.runedit('1번 문서에서 ‘김민수 담당자’를 ‘이서연 담당자’로 바꾸기 전에 미리 보여줘.')
        self.assertTrue(preview['edit_preview']);self.assertEqual(self.writes,[])
        result=await self.runedit('적용해줘');self.assertTrue(result['verified']);self.assertIn('다른 내용.',self.doc['text'])
        self.assertTrue((await self.runedit('적용해줘'))['duplicate']);self.assertEqual(len(self.writes),1)
    async def test_revision_changed_blocks_apply(self):
        await self.runedit('1번 문서에서 ‘김민수 담당자’를 ‘이서연 담당자’로 바꾸기 전에 미리 보여줘.')
        self.doc['revision']=2
        with self.assertRaises(HTTPException) as ctx:await self.runedit('적용해줘')
        self.assertEqual(ctx.exception.status_code,409);self.assertEqual(self.writes,[])
    async def test_other_chat_cannot_apply(self):
        await self.runedit('1번 문서에서 ‘김민수 담당자’를 ‘이서연 담당자’로 바꾸기 전에 미리 보여줘.')
        with self.assertRaises(HTTPException):await self.runedit('적용해줘',SimpleNamespace(user_id='other',chat_id='c',message_id='m'))
        self.assertEqual(self.writes,[])
    async def test_duplicate_phrase_rejected(self):
        self.doc['text']='김민수 담당자. 김민수 담당자.'
        with self.assertRaises(HTTPException):await self.runedit('1번 문서에서 ‘김민수 담당자’를 ‘이서연 담당자’로 바꿔줘.')
        self.assertEqual(self.writes,[])
    async def test_invalid_number_never_selects_first(self):
        r=await self.runedit('2번 문서에서 ‘김민수’를 ‘이서연’으로 바꿔줘.')
        self.assertEqual(r['status'],'needs_input');self.assertEqual(self.writes,[])
    async def test_permission_revoked_before_apply(self):
        await self.runedit('1번 문서에서 ‘김민수 담당자’를 ‘이서연 담당자’로 바꾸기 전에 미리 보여줘.')
        self.core.info=AsyncMock(side_effect=HTTPException(403,'denied'))
        with self.assertRaises(HTTPException):await self.runedit('적용해줘')
        self.assertEqual(self.writes,[])

if __name__=='__main__':unittest.main()
