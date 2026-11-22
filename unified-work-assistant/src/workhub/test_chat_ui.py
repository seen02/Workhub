import os,tempfile,unittest
from unittest.mock import patch
from . import chat_ui,store,bot,domain,criteria

class ChatSelectionTests(unittest.TestCase):
    def setUp(self):
        from .testing_acl import allow_fixture
        allow_fixture(self)
        self.folder=tempfile.TemporaryDirectory();self.patch=patch.object(store,'DB',os.path.join(self.folder.name,'test.db'));self.patch.start();store.init()
    def tearDown(self):self.patch.stop();self.folder.cleanup()
    def test_buttons_are_scoped_to_account_and_room(self):
        a=chat_ui.bind('alice:room1','업무','업무 선택 · 제목',{'kind':'task','id':'a'})
        self.assertEqual(chat_ui.resolve('alice:room1',a['msg'])['id'],'a')
        self.assertIsNone(chat_ui.resolve('bob:room1',a['msg']))
        self.assertIsNone(chat_ui.resolve('alice:room2',a['msg']))
    def test_project_menu_excludes_deleted_collection_and_refreshes_name(self):
        from . import outline
        store.put('projects',[{'id':'p','name':'옛 이름'},{'id':'deleted','name':'삭제된 컬렉션'}])
        with patch.object(outline,'PROJECTS_CACHE',{'until':0,'available':{}}),patch.object(outline,'all_items',return_value=[{'id':'p','name':'새 이름'},{'id':'private','name':'연결하지 않은 컬렉션'}]):
            self.assertEqual(outline.projects(),[{'id':'p','name':'새 이름','code':'p'}])
        self.assertEqual(len(store.get('projects')),2)
    def test_same_title_never_repoints_an_old_button(self):
        a=chat_ui.bind('a','제목','업무 선택 · 제목',{'kind':'task','id':'first'})
        b=chat_ui.bind('a','제목','업무 선택 · 제목',{'kind':'task','id':'second'})
        self.assertNotEqual(a['msg'],b['msg']);self.assertNotEqual(a['text'],b['text'])
        self.assertEqual(chat_ui.resolve('a',a['msg'])['id'],'first')
        self.assertEqual(chat_ui.resolve('a',b['msg'])['id'],'second')
    def test_numbered_selection_and_pagination_use_displayed_page(self):
        rows=[{'id':str(n),'name':'프로젝트 '+str(n)} for n in range(10)]
        text,attachments=chat_ui.menu('a',rows,'project',2)
        self.assertEqual(chat_ui.resolve('a',chat_ui.numbered('a','1'))['id'],'8')
        self.assertIn('(2/2쪽)',text)
        self.assertTrue(any(a['text']=='이전 목록' for row in attachments for a in row['actions']))
        with self.assertRaises(ValueError):chat_ui.numbered('a','9')
        chat_ui.clear_menu('a')
        with self.assertRaises(ValueError):chat_ui.numbered('a','1')
    def test_worker_menu_contains_only_reportable_items(self):
        rows=[{'id':'a','title':'내 업무','fields':{'owner':'lead','progress':'0%'},'criteria':[{'owner':'worker'}]},
              {'id':'b','title':'다른 사람 업무','fields':{'owner':'other','progress':'0%'},'criteria':[]}]
        with patch.object(chat_ui.outline,'project',return_value={'id':'p','name':'P'}),patch.object(chat_ui.outline,'tasks',return_value=rows):
            text,_=chat_ui.tasks('a',{'email':'worker','admin':False},'p')
        self.assertIn('내 업무',text);self.assertNotIn('다른 사람 업무',text)
    def test_confirmation_buttons_bind_exact_proposal_not_latest(self):
        p={'id':'p1','doc_id':'d','title':'업무','created':'2026-09-18T00:00:00+00:00'}
        first=chat_ui.confirmation('a',p)[0]['actions'][0]
        second=chat_ui.confirmation('a',{**p,'id':'p2'})[0]['actions'][0]
        self.assertEqual(chat_ui.resolve('a',first['msg'])['id'],'p1')
        self.assertEqual(chat_ui.resolve('a',second['msg'])['id'],'p2')
        self.assertNotIn('p1',first['msg'])
    def test_old_project_task_button_keeps_its_own_project(self):
        context='chat-context:s:r';store.put(context,{'collectionId':'other','taskId':'other-task'})
        a=chat_ui.bind(context,'Task','업무 선택 · P / Task',{'kind':'task','id':'doc','collectionId':'p'})
        doc={'id':'doc','collectionId':'p','title':'Task','text':domain.render({'project':'P','owner':'a@example.com','status':'미착수','progress':'0%'})}
        with patch.object(bot,'identity',return_value={'sub':'s','email':'a@example.com','admin':True}),patch.object(bot.outline,'project',side_effect=lambda cid:{'id':cid,'name':cid}),patch.object(bot.outline,'sync'),patch.object(bot.outline,'find',return_value=doc) as find,patch.object(bot,'say'):
            bot.handle({'_id':'m','rid':'r','u':{'_id':'u'},'msg':a['msg']})
        find.assert_called_once_with('doc','p',{'sub':'s','email':'a@example.com','admin':True});self.assertEqual(store.get(context)['collectionId'],'p')
    def test_foreign_confirmation_cannot_reach_write(self):
        a=chat_ui.bind('chat-context:other:r','확정','보고 확정 · 작업',{'kind':'confirm','id':'p','taskId':'d'})
        with patch.object(bot,'identity',return_value={'sub':'s','email':'a@example.com'}),patch.object(bot.outline,'confirm') as confirm,patch.object(bot,'say'):
            bot.handle({'_id':'m','rid':'r','u':{'_id':'u'},'msg':a['msg']})
        confirm.assert_not_called()
    def test_report_prefix_in_project_name_is_preserved(self):
        raw='보고 개편 검증의 로그인 화면은 완료했어'
        with patch.object(bot,'identity',return_value={'sub':'s','email':'a@example.com'}),patch.object(bot.report_chat.report_transport,'require_dm'),patch.object(bot.report_chat,'route',return_value=None),patch.object(bot.report_chat,'draft',return_value=('초안',None)) as draft,patch.object(bot,'say'):
            bot.handle({'_id':'report-prefix','rid':'r','u':{'_id':'u'},'msg':raw})
        self.assertEqual(draft.call_args.args[-2],raw)
    def test_long_report_preview_preserves_all_text_and_final_buttons(self):
        body='보고문\n'+'가'*9000+'\n처리 정보\n'+'나'*2000;buttons=[{'actions':[]}]
        with patch.object(bot,'api') as api:bot.say('room',body,buttons)
        sent=[c.args[1] for c in api.call_args_list]
        self.assertEqual(''.join(m['text'] for m in sent),body)
        self.assertNotIn('attachments',sent[0]);self.assertEqual(sent[-1]['attachments'],buttons)

if __name__=='__main__':unittest.main()
