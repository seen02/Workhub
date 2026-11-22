"""Check VM configuration boundaries without contacting or starting services."""
import contextlib
import io
import shutil
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch
import configure


class VMConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('.env.example', '.env.vm.example'):
            shutil.copy2(configure.ROOT / name, self.root / name)
        self.root_patch = patch.object(configure, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def initialize(self, profile='vm', mode='docker'):
        with contextlib.redirect_stdout(io.StringIO()):
            configure.init(Namespace(profile=profile, mode=mode, admin_email='admin@example.com'))
        return configure.load_env()

    def test_new_vm_separates_forwarded_port_from_listener(self):
        env = self.initialize()
        self.assertEqual(env['HTTP_PORT'], '80')
        self.assertEqual(configure.public_urls(env), (
            'http://pms.example.com:21801',
            'http://pms.example.com:21801'))
        self.assertEqual(env['COMPOSE_FILE'], 'compose.yaml,compose.vm.yaml')
        before = (self.root / '.env').read_bytes()
        with self.assertRaises(SystemExit):
            self.initialize()
        self.assertEqual((self.root / '.env').read_bytes(), before)

    def test_existing_docker_secrets_and_api_key_survive_vm_switch(self):
        env = self.initialize(profile='local')
        env['OUTLINE_API_KEY'] = 'fixture-api-key'
        configure.save_env(env)
        with contextlib.redirect_stdout(io.StringIO()):
            configure.vm(None)
        changed = configure.load_env()
        for key in ('OUTLINE_DB_PASSWORD', 'AUTHENTIK_BOOTSTRAP_PASSWORD',
                    'OUTLINE_SECRET_KEY', 'OIDC_CLIENT_SECRET', 'OUTLINE_API_KEY'):
            self.assertEqual(changed[key], env[key])
        self.assertEqual(changed['HTTP_PORT'], '80')

    def test_native_test_configuration_is_not_overwritten(self):
        env = self.initialize(profile='local', mode='native')
        with self.assertRaises(SystemExit):
            configure.vm(None)
        self.assertEqual(configure.load_env(), env)
        self.assertEqual(configure.public_urls(env)[0], 'http://outline.custom-outline.test:18880')

    def test_outline_connection_uses_local_port_and_public_host(self):
        self.initialize()
        with patch.object(configure.getpass, 'getpass', return_value='fixture-api-key'), \
             patch.object(configure, 'call_api', return_value={
                 'data': {'user': {'role': 'admin'}, 'team': {'id': 'fixture-team'}}}) as api, \
             contextlib.redirect_stdout(io.StringIO()):
            configure.connect(None)
        api.assert_called_once_with('http://127.0.0.1:80', '/api/auth.info',
                                    'fixture-api-key', {}, host='pms.example.com:21801')
        self.assertEqual(configure.load_env()['OUTLINE_WORKHUB_TEAM_ID'], 'fixture-team')

    def test_authentik_setup_uses_prefix_and_admin_virtual_host(self):
        env = self.initialize()
        with patch.object(configure, 'call_api', side_effect=RuntimeError('fixture stop')) as api:
            with self.assertRaises(RuntimeError):
                configure.oidc(None)
        api.assert_called_once_with('http://127.0.0.1:80',
            '/authentik/api/v3/core/groups/?page_size=100&page=1',
            env['AUTHENTIK_BOOTSTRAP_TOKEN'], None, None, 'auth.custom-outline.test:21801')

if __name__ == '__main__':
    unittest.main()
