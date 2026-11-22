import copy
from pathlib import Path
import unittest
from unittest.mock import MagicMock
from update_service_sso_webui import patch_content, apply_updates

BRIDGE = (Path(__file__).resolve().parents[1] / 'src/document-agent/webui_bridge.py').read_text(encoding='utf-8')


class PatchTests(unittest.TestCase):
    def test_idempotent_and_preserves_other_methods(self):
        original = BRIDGE + '\n    async def custom_tool(self):\n        return "keep me"\n'
        self.assertEqual(patch_content(original, BRIDGE), original)

    def test_replaces_identity_and_errors_only(self):
        old = BRIDGE.replace("subject=((account.oauth or {}).get('oidc') or {}).get('sub')", "subject='old-binding'")
        old = old.replace('문서 비서에 Authentik으로 다시 로그인하세요.', '통합 포털에 먼저 로그인하세요.')
        self.assertEqual(patch_content(old, BRIDGE), BRIDGE)

    def test_unrecognized_bridge_stops_before_mutation(self):
        with self.assertRaises((StopIteration, KeyError)): patch_content('class Tools: pass', BRIDGE)

    def test_preserves_metadata_and_verifies_source(self):
        before = {'content': 'old', 'valves': {'secret': 'fixture'}, 'access_grants': ['unchanged']}
        after = {**copy.deepcopy(before), 'content': 'new'}
        client = MagicMock(); client.get.return_value.json.return_value = after
        apply_updates(client, [('tools', 'id', before, after)])
        self.assertEqual(client.post.call_args.kwargs['json']['access_grants'], before['access_grants'])
        self.assertEqual(before['content'], 'old')

    def test_ambiguous_failure_rolls_back_attempted_definition(self):
        before, after = {'content': 'old'}, {'content': 'new'}
        client = MagicMock()
        client.post.side_effect = [RuntimeError('lost response'), MagicMock()]
        client.get.return_value.json.return_value = before
        with self.assertRaisesRegex(RuntimeError, 'previous tool definitions restored'):
            apply_updates(client, [('tools', 'id', before, after)])
        self.assertEqual(client.post.call_args.kwargs['json'], before)

    def test_restore_failure_is_reported(self):
        client = MagicMock(); client.post.side_effect = RuntimeError('offline')
        with self.assertRaisesRegex(RuntimeError, 'manual restore needed for: id'):
            apply_updates(client, [('tools', 'id', {'content': 'old'}, {'content': 'new'})])


if __name__ == '__main__': unittest.main()
