"""Identity and startup regressions using mock services and isolated databases."""
import copy
import os
import tempfile
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from . import auth, lifecycle, service_identity, store
from .main import app


class IdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        for replacement in [patch.object(store,'DB',temp.name+'/state.db'),
                            patch.dict(os.environ,{'AUTHENTIK_DIRECTORY_TOKEN':'fixture'})]:
            replacement.start();self.addCleanup(replacement.stop)
        store.init()
        self.row={'sub':'uuid','pk':1,'email':'alice@example.test','username':'alice','name':'Alice','active':True}
        lifecycle.save(self.row)
        self.person={'uuid':'uuid','pk':1,'email':self.row['email'],'username':'alice','name':'Alice',
                     'is_active':True,'type':'internal','groups_obj':[{'name':lifecycle.GROUP}]}
        def api(path,params=None):
            return {'results':[copy.deepcopy(self.person)]} if path=='core/users/' else copy.deepcopy(self.person)
        replacement=patch.object(lifecycle,'auth_api',side_effect=api)
        replacement.start();self.addCleanup(replacement.stop)

    def test_valid_identity_needs_no_portal_session(self):
        user=service_identity.for_subject('uuid')
        self.assertIsInstance(user,service_identity.ServiceIdentity)
        self.assertEqual(auth.allowed(user)['sub'],'uuid')
        with store.db() as db:
            tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn('sessions',tables)

    def test_json_identity_cannot_claim_service_authentication(self):
        with self.assertRaises(HTTPException):auth.allowed(dict(self.row,service_authenticated=True))

    def test_inactive_or_group_removed_identity_denied(self):
        self.person['is_active']=False
        with self.assertRaises(HTTPException):service_identity.for_subject('uuid')
        self.person['is_active']=True;self.person['groups_obj']=[]
        with self.assertRaises(HTTPException):service_identity.for_subject('uuid')

    def test_email_change_and_recycled_identity_denied(self):
        self.person['email']='new@example.test'
        with self.assertRaises(HTTPException):service_identity.for_subject('uuid')
        self.person['email']=self.row['email']
        lifecycle.save({**self.row,'sub':'old-uuid'})
        with self.assertRaises(HTTPException):service_identity.for_subject('uuid')

    def test_unknown_subject_and_review_denied(self):
        with self.assertRaises(HTTPException):service_identity.for_subject('unknown')
        lifecycle.save({**self.row,'review':'manual review'})
        with self.assertRaises(HTTPException):service_identity.for_subject('uuid')

    def test_directory_failure_is_not_permission_success(self):
        with patch.object(lifecycle,'auth_api',side_effect=RuntimeError):
            with self.assertRaises(HTTPException) as result:service_identity.for_subject('uuid')
        self.assertEqual(result.exception.status_code,503)

    def test_removed_features_have_no_http_routes(self):
        client=TestClient(app)
        for path in ['/','/auth/login','/api/analytics','/api/report','/internal/search/access','/internal/outline-search/submit']:
            self.assertEqual(client.get(path).status_code,404)
            self.assertEqual(client.post(path,json={}).status_code,404)

    def test_fresh_store_creates_no_default_outline_collection(self):
        self.assertEqual(store.get('projects'),[])

    def test_lifecycle_sync_calls_only_outline_and_groups(self):
        with (patch.object(lifecycle,'sync_outline',return_value='ok') as outline,
              patch.object(lifecycle,'sync_groups',return_value='ok') as groups):
            lifecycle.sync_account({**self.row,'groups':[],'admin':False})
        outline.assert_called_once();groups.assert_called_once()
