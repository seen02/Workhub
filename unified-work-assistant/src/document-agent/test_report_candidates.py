import unittest
from unittest.mock import AsyncMock,patch
from fastapi import FastAPI,HTTPException
from rag_service import RagService,ReportCandidates

class CandidateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.s=RagService.__new__(RagService);self.s.enabled=True;self.s.profile='test'
        self.s.core=AsyncMock();self.s.store=AsyncMock();self.s.embeddings=AsyncMock()
        self.s.embeddings.call.return_value={'vector':[1.]}
        self.s.core.info.return_value={'id':'d','collectionId':'allowed','revision':2}
        self.s.store.candidates.return_value=([{'document_id':'d','chunk_id':'a','version':'v','similarity':.9,'text':'로그인 화면 구현','metadata':{}}],[])
        app=FastAPI();self.s.install(app,lambda:None)
        self.fn=next(r.endpoint for r in app.routes if r.path=='/agent/report-candidates')
        self.body=ReportCandidates(text='로그인 화면 끝났어',collections=['allowed','private'],documents=['d'])
    async def test_no_user_identity_denied(self):
        with patch('user_acl.check',AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException):await self.fn(self.body)
        self.s.store.candidates.assert_not_awaited()
    async def test_scope_intersection_and_revision_validation(self):
        with patch('user_acl.check',AsyncMock(return_value={'collections':['allowed']})),patch('user_acl.verify_used',AsyncMock()),patch('rag_service.version',return_value='v'):
            result=await self.fn(self.body)
        self.assertEqual(result['candidates'][0]['id'],'d')
        self.assertEqual(self.s.store.candidates.call_args.args[2],['allowed'])
    async def test_old_revision_and_unrequested_documents_excluded(self):
        with patch('user_acl.check',AsyncMock(return_value={'collections':['allowed']})),patch('user_acl.verify_used',AsyncMock()),patch('rag_service.version',return_value='changed'):
            self.assertEqual((await self.fn(self.body))['candidates'],[])
        self.body.documents=['other']
        with patch('user_acl.check',AsyncMock(return_value={'collections':['allowed']})),patch('user_acl.verify_used',AsyncMock()):
            self.assertEqual((await self.fn(self.body))['candidates'],[])
    async def test_revoked_during_search_blocks_release(self):
        with patch('user_acl.check',AsyncMock(return_value={'collections':['allowed']})),patch('user_acl.verify_used',AsyncMock(side_effect=HTTPException(403))),patch('rag_service.version',return_value='v'):
            with self.assertRaises(HTTPException):await self.fn(self.body)

if __name__=='__main__':unittest.main()
