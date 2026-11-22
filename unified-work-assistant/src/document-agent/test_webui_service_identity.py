import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import webui_bridge


class WebUIServiceIdentityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = {'id': 'webui-alice', 'email': 'alice@example.test', 'subject': 'forged'}
        self.account = SimpleNamespace(id='webui-alice', email='alice@example.test', role='user',
                                       oauth={'oidc': {'sub': 'real-subject'}})
        module = types.ModuleType('open_webui.models.users')
        self.users = SimpleNamespace(get_user_by_id=AsyncMock(return_value=self.account))
        module.Users = self.users
        p = patch.dict(sys.modules, {'open_webui.models.users': module})
        p.start(); self.addCleanup(p.stop)
        self.client = MagicMock()
        self.client.__aenter__ = AsyncMock(return_value=self.client)
        self.client.__aexit__ = AsyncMock(return_value=False)
        response = MagicMock()
        response.json.return_value = {'token': 'signed-token'}
        self.client.post = AsyncMock(return_value=response)
        p = patch.object(webui_bridge.httpx, 'AsyncClient', return_value=self.client)
        p.start(); self.addCleanup(p.stop)
        self.tools = webui_bridge.Tools()
        self.tools.valves.AGENT_TOKEN = 'fixture'

    async def test_uses_server_side_oidc_binding_not_supplied_subject(self):
        result = await self.tools._identity_headers(self.user)
        self.assertEqual(result['X-Workhub-Identity'], 'signed-token')
        self.assertEqual(self.client.post.call_args.kwargs['json'], {
            'email': self.account.email, 'user_id': self.account.id, 'subject': 'real-subject'})

    async def test_local_account_cannot_use_email_to_impersonate_sso(self):
        self.account.oauth = None
        with self.assertRaises(ValueError): await self.tools._identity_headers(self.user)
        self.client.post.assert_not_called()

    async def test_different_provider_binding_not_accepted(self):
        self.account.oauth = {'google': {'sub': 'real-subject'}}
        with self.assertRaises(ValueError): await self.tools._identity_headers(self.user)

    async def test_pending_deleted_and_changed_email_accounts_denied(self):
        for change in ('pending', 'missing', 'email'):
            with self.subTest(change=change):
                self.account.role = 'pending' if change == 'pending' else 'user'
                self.account.email = 'changed@example.test' if change == 'email' else self.user['email']
                self.users.get_user_by_id.return_value = None if change == 'missing' else self.account
                with self.assertRaises(ValueError): await self.tools._identity_headers(self.user)
        self.client.post.assert_not_called()


if __name__ == '__main__': unittest.main()
