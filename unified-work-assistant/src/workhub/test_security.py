import json, os, tempfile, unittest
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from . import auth,domain,store,outline
from .main import app
class SecurityTests(unittest.TestCase):
 def test_email_does_not_grant_admin(self):
  u=auth.allowed({'sub':'s','email':'admin@example.com','email_verified':True,'groups':['work-assistant-users']})
  self.assertFalse(u['admin'])
  with self.assertRaises(HTTPException):auth.admin(u)
 def test_no_group_denied(self):
  with self.assertRaises(HTTPException):auth.allowed({'sub':'s','email':'admin@example.com','email_verified':True,'groups':[]})
 def test_unverified_email_denied(self):
  with self.assertRaises(HTTPException):auth.allowed({'sub':'s','email':'user@example.com','email_verified':False,'groups':['work-assistant-users']})
 def test_other_owner_denied(self):
  text=domain.render(dict(project='P',owner='owner@example.com',due='미정',status='미착수',progress='미기재'))
  with patch.object(outline.permissions,'document'),self.assertRaises(HTTPException):outline.can_write({'email':'other@example.com','admin':False},{'text':text})
 def test_legacy_stats_and_weekly_require_admin(self):
  app.dependency_overrides[auth.current]=lambda:{'sub':'s','email':'admin@example.com','admin':False}
  try:
   client=TestClient(app,raise_server_exceptions=False)
   with patch.object(outline,'tasks',return_value=[]),patch.object(outline,'history',return_value=[]),patch('workhub.main.store.get',return_value=None):
    self.assertEqual(client.get('/api/stats').status_code,403)
   self.assertEqual(client.get('/api/weekly').status_code,403)
  finally:app.dependency_overrides.clear()
 def test_other_user_cannot_read_proposal(self):
  with tempfile.TemporaryDirectory() as folder,patch.object(store,'DB',os.path.join(folder,'test.db')):
   store.init()
   with store.db() as c:c.execute('INSERT INTO proposals VALUES(?,?,?,?,?,?)',('p','owner','i','{}','PENDING',store.now()))
   with self.assertRaises(HTTPException):outline.proposal({'sub':'other'},'p')
if __name__=='__main__':unittest.main()
