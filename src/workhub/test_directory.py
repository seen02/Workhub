import os,tempfile,unittest
from unittest.mock import patch
from . import directory,store

class DirectoryTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.patcher=patch.object(store,'DB',os.path.join(self.folder.name,'db.sqlite3'));self.patcher.start();store.init()
    def tearDown(self):self.patcher.stop();self.folder.cleanup()
    def person(self,sub='a',email='a@example.com',name='홍길동'):
        return dict(sub=sub,email=email,name=name,preferred_username=sub,email_verified=True,groups=['work-assistant-users'])
    def test_same_names_remain_separate_accounts(self):
        directory.remember(self.person());directory.remember(self.person('b','b@example.com'))
        self.assertEqual(len(directory.people()),2)
        self.assertEqual(directory.resolve('a'),'a@example.com');self.assertEqual(directory.resolve('b'),'b@example.com')
    def test_rename_does_not_change_assignment_key(self):
        directory.remember(self.person());directory.remember(self.person(name='변경된 이름'))
        self.assertEqual(directory.resolve('a'),'a@example.com');self.assertEqual(directory.label('a@example.com'),'변경된 이름')
    def test_selected_account_wins_over_forged_email(self):
        directory.remember(self.person())
        self.assertEqual(directory.assignments([{'assignee_id':'a','owner':'other@example.com','title':'항목'}])[0]['owner'],'a@example.com')
    def test_unknown_or_revoked_account_denied(self):
        with self.assertRaises(ValueError):directory.resolve('unknown')
        directory.remember(self.person());directory.remember({**self.person(),'groups':[]})
        with self.assertRaises(ValueError):directory.resolve('a')
        self.assertEqual(directory.people(),[]);self.assertEqual(directory.label('a@example.com'),'홍길동')
    def test_unverified_identity_not_listed(self):
        directory.remember({**self.person(),'email_verified':False});self.assertEqual(directory.people(),[])
    def test_logout_does_not_erase_person(self):
        directory.remember(self.person())
        with store.db() as c:c.execute('DELETE FROM identities')
        self.assertEqual(directory.resolve('a'),'a@example.com')

if __name__=='__main__':unittest.main()
