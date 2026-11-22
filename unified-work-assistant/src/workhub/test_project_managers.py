import os,tempfile,unittest
from unittest.mock import patch
from fastapi import HTTPException
from . import outline,store

ADMIN={'sub':'lead','email':'lead@example.com','admin':True}
class ProjectManagerTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        db=patch.object(store,'DB',os.path.join(folder.name,'db'));db.start();self.addCleanup(db.stop);store.init()
        store.put('projects',[{'id':'p','name':'P'},{'id':'q','name':'Q'}])
    def test_manager_metadata_persists_without_changing_memberships_or_tasks(self):
        with patch('workhub.permissions.project',return_value={'id':'p'}),patch.object(outline,'project_managers',return_value=[{'email':ADMIN['email']}]),patch.object(outline,'project',side_effect=lambda cid:next(p for p in store.get('projects') if p['id']==cid)),patch.object(outline,'api') as api:
            p=outline.set_project_manager(ADMIN,'p',ADMIN['email'])
            self.assertEqual(p['manager'],ADMIN['email']);self.assertNotIn('manager',store.get('projects')[1]);api.assert_not_called()
    def test_non_admin_and_ineligible_manager_denied(self):
        with self.assertRaises(HTTPException) as e:outline.set_project_manager({**ADMIN,'admin':False},'p',ADMIN['email'])
        self.assertEqual(e.exception.status_code,403)
        with patch('workhub.permissions.project',return_value={'id':'p'}),patch.object(outline,'project_managers',return_value=[]):
            with self.assertRaises(HTTPException) as e:outline.set_project_manager(ADMIN,'p','outsider@example.com')
            self.assertEqual(e.exception.status_code,403)
        self.assertNotIn('manager',store.get('projects')[0])
    def test_unreadable_project_denied_before_update(self):
        with patch('workhub.permissions.project',side_effect=HTTPException(403,'denied')):
            with self.assertRaises(HTTPException):outline.set_project_manager(ADMIN,'p',ADMIN['email'])
        self.assertNotIn('manager',store.get('projects')[0])
