import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
import knowledge_search as k

class KnowledgeSearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.doc={'id':'doc','title':'시스템 설계서','collectionId':'a','publishedAt':'now','revision':1,'url':'/doc/test','text':'설계 내용'}
        self.service=SimpleNamespace(enabled=True,profile='test',syncer=SimpleNamespace(collections=AsyncMock(return_value={'a':'a'}),names={'a':'A'}),
            store=SimpleNamespace(status=AsyncMock(return_value={'collections':[{'collection_id':'a','result':{'inventory_complete':True}}]}),inventory=AsyncMock(return_value=[self.doc])),
            core=SimpleNamespace(info=AsyncMock(return_value=self.doc),doc_result=lambda d:{'url':'http://outline.test'+d['url']},llm=AsyncMock()),
            embeddings=SimpleNamespace(call=AsyncMock()),changed=SimpleNamespace(set=lambda:None))
        self.patches=[patch.object(k.user_acl,'check',AsyncMock(return_value={'collections':['a'],'documents':['doc']})),patch.object(k.user_acl,'verify_used',AsyncMock())]
        for p in self.patches:p.start();self.addCleanup(p.stop)

    async def test_exact_link_no_model_or_embedding(self):
        result=await k.search(self.service,k.Query(query='설계 문서 링크 제공해줘',mode='links'))
        self.assertEqual(result['documents'][0]['id'],'doc')
        self.assertEqual(result['generation_calls'],0)
        self.service.embeddings.call.assert_not_called();self.service.core.llm.assert_not_called()

    async def test_disabled_scope_never_widens(self):
        result=await k.search(self.service,k.Query(query='설계',collections=['disabled']))
        self.assertEqual(result['status'],'not_included');self.service.core.info.assert_not_called()

    async def test_changed_doc_not_sent(self):
        self.service.core.info.side_effect=[self.doc,{**self.doc,'revision':2}]
        result=await k.search(self.service,k.Query(query='설계 링크',mode='links'))
        self.assertEqual(result['status'],'stale');self.assertEqual(result['documents'],[])

    def test_draft_and_archived_not_eligible(self):
        q=k.Query(query='설계')
        self.assertFalse(k.matches({**self.doc,'publishedAt':None},q))
        self.assertFalse(k.matches({**self.doc,'archivedAt':'now'},q))

    def test_filters_constrain_source(self):
        self.assertFalse(k.matches(self.doc,k.Query(query='설계',document_id='other')))
        self.assertFalse(k.matches(self.doc,k.Query(query='배포',title_only=True)))

    def test_query_cleaning_retains_subject(self):
        self.assertEqual(k.terms('설계 문서 링크 제공해줘'),['설계'])
        self.assertEqual(k.terms('배포 오류 해결 문서 찾아줘'),['배포','오류','해결'])

    def test_plain_report_time_is_carried_into_evidence(self):
        text='[9월 29일 화요일 : 9시]\n화면 만들기 진행 중\n[9월 29일 화요일 : 13시]\n화면 만들기 완료'
        position=text.index('화면 만들기 완료')
        self.assertIn('13시',k.dated_evidence(text,position,'9월 29일 13시에 무엇을 완료했어?'))
        self.assertIsNone(k.dated_evidence(text,position,'9월 29일 9시 보고 알려줘'))
        self.assertIsNone(k.dated_evidence(text,position,'9월 28일 13시 보고 알려줘'))
        self.assertIsNone(k.dated_evidence('현재 상태 완료',0,'9월 29일 9시 보고 알려줘'))
        colon='[9월 29일 13:00]\n화면 완료'
        self.assertIsNone(k.dated_evidence(colon,colon.index('화면'),'9시 보고'))
        self.assertIn('13:00',k.dated_evidence(colon,colon.index('화면'),'9월 29일 오후 1시 보고'))
        iso='[2026-09-29 13:20]\n화면 완료'
        self.assertIsNone(k.dated_evidence(iso,iso.index('화면'),'9월 29일 13:00 보고'))
        self.assertIn('13:20',k.dated_evidence(iso,iso.index('화면'),'2026-09-29 13:20 보고'))

    def test_author_filter_matches_native_collaborators(self):
        doc={**self.doc,'createdBy':{'id':'creator'},'collaboratorIds':['editor']}
        self.assertTrue(k.matches(doc,k.Query(query='설계',author_id='editor')))
        self.assertFalse(k.matches(doc,k.Query(query='설계',author_id='creator')))

if __name__=='__main__':unittest.main()
