import unittest
from unittest.mock import AsyncMock
from fastapi import HTTPException
from rag_sync import Synchronizer
from rag_answer import answer
from evidence_selection import select_evidence

class ProjectScopeTest(unittest.IsolatedAsyncioTestCase):
    async def test_ids_survive_rename_and_unlink_preserves_legacy(self):
        async def outline(method,args,read=False):
            return [{'id':'legacy','name':'기존 자료'},{'id':'project','name':'새 프로젝트 이름'}]
        store=AsyncMock();store.workhub_projects.return_value=[{'id':'project','name':'옛 이름'}]
        sync=Synchronizer(type('Core',(),{'outline':staticmethod(outline)})(),store,AsyncMock(),['기존 자료'])
        self.assertEqual(await sync.collections(),{'기존 자료':'legacy','project':'project'})
        store.workhub_projects.return_value=[]
        self.assertEqual(await sync.collections(),{'기존 자료':'legacy'})

    async def test_sync_rejects_unregistered_id(self):
        core=AsyncMock();core.outline.return_value=[{'id':'a','name':'기존 자료'}]
        store=AsyncMock();store.workhub_projects.return_value=[]
        sync=Synchronizer(core,store,AsyncMock(),['기존 자료'])
        with self.assertRaises(HTTPException):await sync.sync(collection_id='private')
        store.replace.assert_not_awaited()

class SummaryTest(unittest.IsolatedAsyncioTestCase):
    async def test_supported_paraphrase_with_citation_is_allowed(self):
        facts=[{'id':1,'source':1,'text':'화면 검증 담당자는 홍길동입니다.'}]
        llm=AsyncMock(side_effect=[({'points':[{'text':'홍길동이 화면 검증을 담당합니다.','facts':[1]}]},{}),({'supported':True},{})])
        report,used,metrics=await answer(facts,'화면 검증은 누가 맡나요?',llm)
        self.assertIn('홍길동이 화면 검증을 담당합니다. [1]',report)
        self.assertFalse(metrics['fallback']);self.assertEqual(len(used),1)

    async def test_unsupported_paraphrase_falls_back_to_source(self):
        facts=[{'id':1,'source':1,'text':'화면 검증 담당자는 홍길동입니다.'}]
        llm=AsyncMock(side_effect=[({'points':[{'text':'김철수가 검증을 담당합니다.','facts':[1]}]},{}),({'supported':False},{})])
        report,_,metrics=await answer(facts,'담당자?',llm)
        self.assertNotIn('김철수',report);self.assertTrue(metrics['fallback'])

    async def test_irrelevant_retrieval_can_return_no_answer(self):
        report,sources,metrics=await answer([{'id':1,'source':1,'text':'화면 검증 담당자는 홍길동입니다.'}],
            '예산은 얼마인가요?',AsyncMock(return_value=({'points':[]},{})))
        self.assertEqual(sources,[]);self.assertTrue(metrics['no_answer'])

    def test_missing_literal_keyword_does_not_drop_semantic_match(self):
        facts=[{'id':1,'text':'운영 환경에 올리기 전에 화면을 점검한다.'}]
        self.assertEqual(select_evidence(facts,'배포 전 확인 사항'),facts)

if __name__=='__main__':unittest.main()
