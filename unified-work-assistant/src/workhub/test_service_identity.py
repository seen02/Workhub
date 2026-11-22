"""No live services: exercise the service-authentication boundaries with an empty portal DB."""
import copy
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request
from . import auth, bot, knowledge, lifecycle, outline_bridge, search_identity, service_identity, store


class ServiceIdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        for p in (patch.object(store, 'DB', temp.name + '/test.db'),
                  patch.dict(os.environ, {'AUTHENTIK_DIRECTORY_TOKEN': 'fixture',
                                          'OUTLINE_WORKHUB_TEAM_ID': 'team'})):
            p.start(); self.addCleanup(p.stop)
        store.init()
        self.row = {'sub': 'subject', 'pk': 1, 'email': 'alice@example.test',
                    'username': 'alice', 'name': 'Alice', 'active': True,
                    'admin': True, 'outline_id': 'outline-alice'}
        lifecycle.save(self.row)
        self.person = {'uuid': 'subject', 'pk': 1, 'email': self.row['email'],
                       'username': 'alice', 'name': 'Alice', 'type': 'internal',
                       'is_active': True, 'groups_obj': [{'name': lifecycle.GROUP}]}
        self.users = [self.person]
        p = patch.object(lifecycle, 'auth_api', side_effect=self.directory_api)
        self.api = p.start(); self.addCleanup(p.stop)
        self.mongo = MagicMock()
        self.chat_user = {'active': True, 'services': {'authentik': {'id': 'subject'}}}
        self.mongo.rocketchat.users.find_one.return_value = self.chat_user
        p = patch.object(bot, 'mongo', self.mongo)
        p.start(); self.addCleanup(p.stop)

    def directory_api(self, path, params=None):
        if path == 'core/users/1/': return copy.deepcopy(self.person)
        if path == 'core/users/': return {'results': copy.deepcopy(self.users)}
        raise AssertionError(path)

    def denied(self, fn, status=403):
        with self.assertRaises(HTTPException) as raised: fn()
        self.assertEqual(raised.exception.status_code, status)
        self.assertNotIn('포털', raised.exception.detail)

    def test_chat_without_any_portal_login(self):
        with store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM identities').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM sessions').fetchone()[0], 0)
        user = bot.identity('chat-alice')
        self.assertEqual(user['sub'], 'subject')
        self.assertIsInstance(user, service_identity.ServiceIdentity)
        self.assertNotIn('email_verified', user)
        self.assertFalse(user['admin'])  # Stale local admin flag cannot grant access.
        self.assertEqual(auth.allowed(user)['sub'], 'subject')

    def test_expired_or_removed_portal_tokens_do_not_affect_chat(self):
        with store.db() as db:
            db.execute('INSERT INTO identities VALUES(?,?,?)', ('subject', self.row['email'], '{}'))
        self.assertEqual(bot.identity('chat-alice')['sub'], 'subject')
        with store.db() as db: db.execute('DELETE FROM identities')
        self.assertEqual(bot.identity('chat-alice')['sub'], 'subject')

    def test_outline_without_portal_login(self):
        with patch.object(outline_bridge.outline, 'api', return_value={'id': 'outline-alice', 'email': self.row['email']}):
            user = outline_bridge.actor({'outlineTeamId': 'team', 'outlineUserId': 'outline-alice'})
        self.assertEqual(user['sub'], 'subject')

    def test_outline_suspension_still_blocks(self):
        with patch.object(outline_bridge.outline, 'api', return_value={'email': self.row['email'], 'isSuspended': True}):
            self.denied(lambda: outline_bridge.actor({'outlineTeamId': 'team', 'outlineUserId': 'outline-alice'}))

    def test_unmapped_outline_id_and_foreign_team_blocked(self):
        for actor in ({'outlineTeamId': 'other', 'outlineUserId': 'outline-alice'},
                      {'outlineTeamId': 'team', 'outlineUserId': 'unknown'}):
            self.denied(lambda: outline_bridge.actor(actor))

    def test_local_password_only_chat_account_denied(self):
        self.chat_user['services'] = {'password': {}}
        with self.assertRaises(ValueError): bot.identity('chat-alice')

    def test_inactive_or_ambiguous_chat_binding_denied(self):
        self.chat_user['active'] = False
        with self.assertRaises(ValueError): bot.identity('chat-alice')
        self.chat_user['active'] = True
        self.chat_user['services']['Authentik'] = {'sub': 'other'}
        with self.assertRaises(ValueError): bot.identity('chat-alice')

    def test_missing_active_flag_denied(self):
        del self.chat_user['active']
        with self.assertRaises(ValueError): bot.identity('chat-alice')

    def test_disabled_authentik_account_immediately_denied(self):
        bot.identity('chat-alice')
        self.person['is_active'] = False
        self.denied(lambda: bot.identity('chat-alice'))

    def test_group_removal_immediately_denied(self):
        user = bot.identity('chat-alice')
        self.person['groups_obj'] = []
        self.denied(lambda: auth.allowed(user))
        self.denied(lambda: knowledge.current_user(user['sub']))

    def test_live_admin_role_changes(self):
        self.person['groups_obj'].append({'name': lifecycle.ADMIN})
        self.assertTrue(bot.identity('chat-alice')['admin'])
        self.person['groups_obj'].pop()
        self.assertFalse(bot.identity('chat-alice')['admin'])

    def test_service_account_and_subject_mismatch_denied(self):
        self.person['type'] = 'service_account'
        self.denied(lambda: bot.identity('chat-alice'))
        self.person['type'] = 'internal'
        self.person['uuid'] = 'someone-else'
        self.denied(lambda: bot.identity('chat-alice'))

    def test_email_and_username_changes_require_review(self):
        self.person['email'] = 'changed@example.test'
        self.denied(lambda: bot.identity('chat-alice'))
        self.person['email'] = self.row['email']
        self.person['username'] = 'changed'
        self.denied(lambda: bot.identity('chat-alice'))

    def test_duplicate_live_email_denied_before_sync(self):
        self.users.append({**self.person, 'uuid': 'other', 'pk': 2})
        self.denied(lambda: bot.identity('chat-alice'))

    def test_historical_email_reuse_denied(self):
        lifecycle.save({**self.row, 'sub': 'former-employee', 'active': False})
        self.denied(lambda: bot.identity('chat-alice'))

    def test_review_and_deleted_mapping_denied(self):
        for change in ({'review': 'manual review'}, {'removed': True}):
            lifecycle.save({**self.row, **change})
            self.denied(lambda: bot.identity('chat-alice'))

    def test_no_mapping_does_not_require_portal_or_auto_enroll(self):
        with store.db() as db: db.execute('DELETE FROM kv')
        self.denied(lambda: bot.identity('chat-alice'))
        self.api.assert_not_called()

    def test_directory_outage_and_missing_config_fail_closed(self):
        self.api.side_effect = httpx.ConnectError('offline')
        self.denied(lambda: bot.identity('chat-alice'), 503)
        with patch.dict(os.environ, {'AUTHENTIK_DIRECTORY_TOKEN': ''}):
            self.denied(lambda: bot.identity('chat-alice'), 503)

    def test_json_marker_does_not_bypass_verified_oidc_email(self):
        user = dict(service_identity.for_subject('subject'))
        user.update(identity_source='authentik-directory', email_verified=False)
        self.denied(lambda: auth.allowed(user))

    def test_portal_still_requires_own_session(self):
        request = Request({'type': 'http', 'method': 'GET', 'headers': []})
        self.denied(lambda: auth.current(request), 401)

    def test_portal_post_still_requires_csrf(self):
        body = {'info': {'sub': 'subject'}, 'csrf': 'expected'}
        with store.db() as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?)', ('session', json.dumps(body), 9999999999))
        request = Request({'type': 'http', 'method': 'POST', 'headers': [(b'cookie', b'workhub_session=session')]})
        with patch.object(auth, 'refresh', return_value=body): self.denied(lambda: auth.current(request))

    def test_webui_uses_subject_not_email_lookup(self):
        user = search_identity.webui_user(self.row['email'], 'subject', 'webui-alice')
        self.assertEqual(search_identity.decode(search_identity.issue(user, 'webui-alice'))['sub'], 'subject')
        self.denied(lambda: search_identity.webui_user('other@example.test', 'subject', 'webui-alice'))
        self.denied(lambda: search_identity.webui_user(self.row['email'], 'unknown', 'webui-alice'))

    def test_webui_account_rebinding_denied(self):
        store.put('webui-identity:webui-alice', {'sub': 'different-original-subject'})
        self.denied(lambda: search_identity.webui_user(self.row['email'], 'subject', 'webui-alice'))

    def test_internal_endpoint_rejects_unsigned_and_legacy_email_only_calls(self):
        from .main import app
        client = TestClient(app)  # No lifespan: background workers must not start.
        payload = {'email': self.row['email'], 'subject': 'subject', 'user_id': 'webui-alice'}
        self.assertEqual(client.post('/internal/search/identity', json=payload).status_code, 401)
        headers = {'X-Service-Token': os.environ['AGENT_TOKEN']}
        self.assertEqual(client.post('/internal/search/identity', headers=headers,
                                    json={k: v for k, v in payload.items() if k != 'subject'}).status_code, 422)
        response = client.post('/internal/search/identity', headers=headers, json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(search_identity.decode(response.json()['token'])['sub'], 'subject')

    def test_document_access_still_checked_after_service_login(self):
        from .main import app
        user = service_identity.for_subject('subject')
        token = search_identity.issue(user, 'webui-alice')
        with patch.object(knowledge, 'enabled', return_value=True), patch.object(knowledge, 'live_access', return_value={'collections': [], 'documents': []}):
            response = TestClient(app).post('/internal/search/access',
                headers={'X-Service-Token': os.environ['AGENT_TOKEN']},
                json={'token': token, 'collections': ['private']})
        self.assertEqual(response.status_code, 403)


if __name__ == '__main__': unittest.main()
