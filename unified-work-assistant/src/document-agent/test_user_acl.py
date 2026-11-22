import os,unittest
from unittest.mock import AsyncMock,patch
from fastapi import HTTPException
import user_acl

class ACLTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.reset=user_acl.actor.set({'token':'test','identity':{'sub':'alice','user_id':'webui-a'},'collections':['a'],'documents':set()})
    def tearDown(self):user_acl.actor.reset(self.reset)
    async def test_document_read_denied_before_model_receives_content(self):
        with patch.object(user_acl,'check',AsyncMock(return_value={'documents':[]})):
            with self.assertRaises(HTTPException):await user_acl.after('documents.info',{'id':'secret','text':'비공개'})
        self.assertEqual(user_acl.actor.get()['documents'],set())
    async def test_search_results_filter_private_titles(self):
        with patch.object(user_acl,'check',AsyncMock(return_value={'documents':['public']})):
            result=await user_acl.after('documents.search',[{'document':{'id':'secret','title':'비공개'}},{'document':{'id':'public','title':'공개'}}])
        self.assertEqual(len(result),1);self.assertEqual(result[0]['document']['id'],'public');self.assertEqual(result.raw_count,2)
    async def test_recheck_denies_access_revoked_after_read(self):
        with patch.object(user_acl,'check',AsyncMock(side_effect=[{'documents':['a']},{'documents':[]}])):
            await user_acl.require_documents(['a'])
            with self.assertRaises(HTTPException):await user_acl.verify_used()
    def test_body_user_id_cannot_impersonate_another_user(self):
        user_acl.require_user('webui-a')
        with self.assertRaises(HTTPException):user_acl.require_user('webui-b')
    def test_history_scope_changes_when_access_is_removed(self):
        before=user_acl.scope_suffix();user_acl.actor.get()['collections']=[]
        self.assertNotEqual(before,user_acl.scope_suffix())
    def test_background_index_scope_is_restored(self):
        original=user_acl.actor.get()
        with user_acl.index_inventory():self.assertIsNone(user_acl.actor.get())
        self.assertIs(user_acl.actor.get(),original)

if __name__=='__main__':unittest.main()
