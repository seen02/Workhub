import os,tempfile,unittest,threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from fastapi import HTTPException
from . import outline,store,domain,chat_ui,bot

USER={'sub':'s','email':'worker@example.com','admin':False}

class CancellationTests(unittest.TestCase):
    def setUp(self):
        from .testing_acl import allow_fixture
        allow_fixture(self)
        self.folder=tempfile.TemporaryDirectory();self.patch=patch.object(store,'DB',os.path.join(self.folder.name,'test.db'));self.patch.start();store.init()
        self.doc={'id':'d','title':'업무','collectionId':'c','text':domain.render({'project':'P','owner':USER['email'],'status':'미착수','progress':'0%'}),'revision':1,'updatedAt':'now','url':'/doc/d'}
        with patch.object(outline,'document',return_value=self.doc):self.p=outline.propose(USER,'d',{'status':'진행 중'},'initial-idem')
    def tearDown(self):self.patch.stop();self.folder.cleanup()
    def set_state(self,state):
        with store.db() as c:c.execute('UPDATE proposals SET state=? WHERE id=?',(state,self.p['id']))
    def test_cancel_is_idempotent_without_outline_access(self):
        with patch.object(outline,'document') as doc,patch.object(outline,'api') as api:
            first=outline.cancel(USER,self.p['id']);second=outline.cancel(USER,self.p['id'])
        self.assertEqual(first,second);self.assertEqual(first['state'],'CANCELLED');self.assertIn('cancelled_at',first)
        doc.assert_not_called();api.assert_not_called()
    def test_cancelled_proposal_cannot_be_confirmed(self):
        outline.cancel(USER,self.p['id'])
        with patch.object(outline,'document') as doc,patch.object(outline,'api') as api:
            with self.assertRaises(HTTPException) as e:outline.confirm(USER,self.p['id'])
        self.assertEqual(e.exception.status_code,409);doc.assert_not_called();api.assert_not_called()
    def test_another_account_cannot_cancel(self):
        with self.assertRaises(HTTPException) as e:outline.cancel({'sub':'other','admin':True},self.p['id'])
        self.assertEqual(e.exception.status_code,404);self.assertEqual(outline.proposal(USER,self.p['id'])['state'],'PENDING')
    def test_applied_or_uncertain_write_cannot_be_cancelled(self):
        for state in ['APPLIED','APPLYING']:
            self.set_state(state)
            with self.assertRaises(HTTPException):outline.cancel(USER,self.p['id'])
            self.assertEqual(outline.proposal(USER,self.p['id'])['state'],state)
    def test_conflicting_draft_can_be_cancelled_without_source(self):
        self.set_state('CONFLICT');self.assertEqual(outline.cancel(USER,self.p['id'])['state'],'CANCELLED')
    def test_confirm_and_cancel_race_has_exactly_one_winner(self):
        barrier=threading.Barrier(2);source=dict(self.doc)
        def api(name,body):source.update(text=body['text'],revision=2,updatedAt='later')
        def run(fn):
            barrier.wait()
            try:return fn(USER,self.p['id'])['state']
            except HTTPException:return 'REJECTED'
        with patch.object(outline,'document',side_effect=lambda _:dict(source)),patch.object(outline,'api',side_effect=api),patch.object(outline,'record'),ThreadPoolExecutor(2) as pool:
            a=pool.submit(run,outline.confirm);b=pool.submit(run,outline.cancel);results=[a.result(),b.result()]
        self.assertEqual(results.count('REJECTED'),1)
        state=outline.proposal(USER,self.p['id'])['state']
        self.assertIn(state,['APPLIED','CANCELLED']);self.assertEqual(source['text'],self.p['after'] if state=='APPLIED' else self.p['before'])
    def test_cancel_button_binds_exact_draft(self):
        a=chat_ui.confirmation('ctx',self.p)[0]['actions'][1]
        self.assertEqual(a['text'],'이 초안 취소');self.assertEqual(chat_ui.resolve('ctx',a['msg']),{'kind':'cancel','id':self.p['id'],'taskId':'d'})
        self.assertIsNone(chat_ui.resolve('other',a['msg']))
    def test_repeated_chat_cancel_does_not_cancel_an_older_draft(self):
        context='chat-context:s:r';store.put(context,{'taskId':'d','collectionId':'c','proposalId':self.p['id']})
        with patch.object(bot,'identity',return_value=USER),patch.object(bot,'say'):
            for n in range(2):bot.handle({'_id':str(n),'rid':'r','u':{'_id':'u'},'msg':'취소'})
        self.assertEqual(outline.proposal(USER,self.p['id'])['state'],'CANCELLED')
        self.assertEqual(store.get(context)['proposalId'],self.p['id'])
    def test_legacy_chat_lookup_is_scoped_and_keeps_terminal_latest(self):
        with store.db() as c:
            c.execute('INSERT INTO messages VALUES(?,?,?)',('m','DONE',store.dump({'rid':'r'})))
            c.execute('UPDATE proposals SET idem=?,state=? WHERE id=?',('rc:m','APPLIED',self.p['id']))
        self.assertEqual(bot.latest_chat_draft(USER,'r',{'taskId':'d'}),self.p['id'])
        with self.assertRaises(ValueError):bot.latest_chat_draft(USER,'other-room',{'taskId':'d'})
    def test_cancelling_older_button_keeps_newest_draft_for_short_command(self):
        with patch.object(outline,'document',return_value=self.doc):newer=outline.propose(USER,'d',{'status':'진행 중'},'newer-idem')
        context='chat-context:s:r';store.put(context,{'taskId':'d','collectionId':'c','proposalId':newer['id']})
        button=chat_ui.confirmation(context,self.p)[0]['actions'][1]
        with patch.object(bot,'identity',return_value=USER),patch.object(bot,'say'):
            bot.handle({'_id':'cancel-old','rid':'r','u':{'_id':'u'},'msg':button['msg']})
        self.assertEqual(outline.proposal(USER,self.p['id'])['state'],'CANCELLED')
        self.assertEqual(store.get(context)['proposalId'],newer['id'])
        self.assertEqual(outline.proposal(USER,newer['id'])['state'],'PENDING')

if __name__=='__main__':unittest.main()
