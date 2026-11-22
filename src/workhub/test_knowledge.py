import time, unittest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from . import knowledge as k, knowledge_chat as chat, store

USER={'sub':'knowledge-test','email':'knowledge@test.invalid','admin':False}

class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.access=MagicMock();self.access.readable.side_effect=lambda cid:cid!='private'
        self.rows=[{'id':'a','name':'프로젝트 A','included':True},{'id':'b','name':'공용 지식','included':True},
                   {'id':'private','name':'비밀 프로젝트','included':True},{'id':'off','name':'미포함 자료','included':False}]
        for p in (patch.object(k.permissions,'Access',return_value=self.access),patch.object(k,'targets',return_value=self.rows),patch.object(k.auth,'allowed')):
            p.start();self.addCleanup(p.stop)

    def test_explicit_project_not_last_report(self):
        r=k.resolve(USER,'프로젝트 A 설계 문서 링크 줘')
        self.assertEqual(r['collections'],['a']);self.assertNotIn('프로젝트 A',r['query'])

    def test_all_scope_includes_knowledge_but_not_private_or_disabled(self):
        self.assertEqual(set(k.resolve(USER,'배포 오류')['collections']),{'a','b'})

    def test_duplicate_name_requires_choice(self):
        self.rows.append({'id':'a2','name':'프로젝트 A','included':True})
        self.assertEqual(k.resolve(USER,'프로젝트 A 설계')['status'],'choose')

    def test_multi_project_retains_both(self):
        self.assertEqual(set(k.resolve(USER,'프로젝트 A와 공용 지식 설계 비교')['collections']),{'a','b'})

    def test_disabled_explicit_scope_does_not_expand(self):
        self.assertEqual(k.resolve(USER,'미포함 자료 설계')['status'],'not_included')

    def test_longest_name_wins(self):
        self.rows.append({'id':'aa','name':'프로젝트 A 부록','included':True})
        self.assertEqual(k.resolve(USER,'프로젝트 A 부록 설계')['collections'],['aa'])

    def test_unknown_explicit_project_does_not_search_other_projects(self):
        result=k.resolve(USER,'프로젝트 Z 설계 문서 링크 줘')
        self.assertEqual(result['status'],'no_results')
        self.assertNotIn('collections',result)

    def test_filters_unknown_rejected(self):
        with self.assertRaises(HTTPException):k.execute(USER,{'query':'설계','filters':{'untrusted':'all'}})

    def test_deleted_source_rejected(self):
        with patch.object(k.outline,'api',return_value=None),self.assertRaises(HTTPException):
            k.validate(USER,{'documents':[{'id':'doc','revision':1}]})

    def test_changed_revision_rejected(self):
        with patch.object(k.outline,'api',return_value={'id':'doc','collectionId':'a','publishedAt':'now','revision':2}),self.assertRaises(HTTPException):
            k.validate(USER,{'documents':[{'id':'doc','revision':1}]})

    def test_other_user_job_hidden(self):
        with patch.object(store,'get',return_value={'sub':'other','state':'done','at':time.time()}),self.assertRaises(HTTPException):
            k.result(USER,'job')

    def test_cancel_discards_saved_content(self):
        job={'sub':USER['sub'],'state':'done','at':time.time(),'result':{'answer':'private'}}
        with patch.object(store,'get',return_value=job),patch.object(store,'put') as save:
            self.assertEqual(k.result(USER,'job',True)['status'],'cancelled')
            self.assertNotIn('result',save.call_args.args[1])

    def test_mentions_use_id_not_display(self):
        self.assertFalse(chat.mention({'msg':'@통합 업무 비서'},'bot'))
        self.assertFalse(chat.mention({'mentions':[{'_id':'fake','username':'통합 업무 비서'}]},'bot'))
        self.assertTrue(chat.mention({'mentions':[{'_id':'bot'}]},'bot'))

    def test_channel_policy_default_is_private(self):
        with patch.object(store,'get',return_value={}):self.assertFalse(chat.public(USER,{'_id':'room'},[{'collection_id':'a'}],None))

    def test_policy_does_not_grant_user_permission(self):
        with patch.object(store,'get',return_value={'room':['private']}):self.assertFalse(chat.public(USER,{'_id':'room'},[{'collection_id':'private'}],None))

    def test_send_uses_stable_id_and_does_not_repeat(self):
        b=MagicMock();b.mongo.rocketchat.rocketchat_message.find_one.return_value=None
        mid=chat.send(b,'room','result','request','parent')
        self.assertEqual(b.api.call_args.args[1]['message']['tmid'],'parent')
        b.mongo.rocketchat.rocketchat_message.find_one.return_value={'_id':mid,'rid':'room'}
        self.assertEqual(chat.send(b,'room','result','request','parent'),mid)
        self.assertEqual(b.api.call_count,1)

    def test_document_work_report_does_not_become_search(self):
        b=MagicMock();b.mongo.rocketchat.rocketchat_room.find_one.return_value={'t':'d'}
        with patch.object(chat,'enabled',return_value=True):
            self.assertFalse(chat.eligible({'msg':'프로젝트 A 문서 요약 완료했고 화면 구현은 진행 중이야'},b))
            self.assertTrue(chat.eligible({'msg':'프로젝트 A 설계 문서 링크 제공해줘'},b))
            self.assertTrue(chat.eligible({'msg':'배포 문서 찾아줘'},b))

if __name__=='__main__':unittest.main()
