"""WhatsApp Loomy MCP agent: allowlist, JWT guard, mocked tool loop."""
import os
import unittest
from unittest.mock import MagicMock, patch

from mcp_wa.inprocess_client import JWT_MISSING_MSG
from mcp_wa.wa_tool_registry import allowed_tools, execute_tool, is_tool_allowed


class WaToolAllowlistTests(unittest.TestCase):
    def test_default_allows_nas_and_assign(self):
        self.assertTrue(is_tool_allowed('wa_get_nas_status'))
        self.assertTrue(is_tool_allowed('wa_assign_pool_images'))
        self.assertTrue(is_tool_allowed('wa_append_site_remark'))
        self.assertTrue(is_tool_allowed('wa_move_record_to_project'))
        self.assertTrue(is_tool_allowed('wa_list_pool_images'))

    def test_default_denies_send_and_sync(self):
        self.assertFalse(is_tool_allowed('wa_send_message'))
        self.assertFalse(is_tool_allowed('wa_sync_nas_bidirectional'))
        self.assertFalse(is_tool_allowed('wa_delete_project'))

    @patch.dict(os.environ, {'LOOMY_WA_MCP_TOOLS_DENY': 'wa_get_nas_status'}, clear=False)
    def test_env_deny_overrides(self):
        # Re-import would cache; allowed_tools reads env each call
        self.assertFalse(is_tool_allowed('wa_get_nas_status'))

    def test_assign_posts_site_remark(self):
        from mcp_wa.wa_tool_registry import _exec_wa_append_site_remark, _exec_wa_assign_pool_images

        client = MagicMock()
        client.post.return_value = {'assigned': 1, 'siteRemarkQueued': True}
        _exec_wa_assign_pool_images(client, {
            'image_ids': ['a'],
            'project_id': 'p',
            'remark': 'Test',
            'nas_folder_name': '1005',
            'nas_parent_bucket': 'T-1000-2002',
        })
        body = client.post.call_args.kwargs['json_body']
        self.assertEqual(body['remark'], 'Test')
        self.assertEqual(body['nasFolderName'], '1005')
        self.assertEqual(body['nasParentBucket'], 'T-1000-2002')
        self.assertEqual(client.post.call_args.args[0], '/wa/image-pool/assign')

        client.post.reset_mock()
        client.post.return_value = {'ok': True, 'path': '/nas/1005/Photo/2026-10-28/1005_2026-10-28.txt'}
        _exec_wa_append_site_remark(client, {
            'project_code': '1005',
            'text': '补一句',
            'nas_folder_name': '1005',
        })
        body = client.post.call_args.kwargs['json_body']
        self.assertEqual(body['projectCode'], '1005')
        self.assertEqual(body['text'], '补一句')
        self.assertEqual(client.post.call_args.args[0], '/wa/image-pool/site-remark')

    def test_execute_rejects_blocked_tool(self):
        client = MagicMock()
        out = execute_tool('wa_delete_project', {}, client)
        self.assertIn('not allowed', out)
        client.get.assert_not_called()

    def test_execute_unknown_allowed_name_without_executor(self):
        client = MagicMock()
        # Hypothetical tool: allowed set is static; unknown names hit allowlist first.
        name = 'wa_not_a_real_tool_xyz'
        self.assertNotIn(name, allowed_tools())
        out = execute_tool(name, {}, client)
        self.assertIn('not allowed', out)


def _load_loomy_wa_mcp_agent_module():
    """Load agent module without pulling Flask app factory."""
    import importlib.util
    import json
    import sys
    import types

    def _parse_structured(raw: str):
        raw = (raw or '').strip()
        if raw.startswith('```'):
            raw = raw.split('\n', 1)[-1]
        if raw.endswith('```'):
            raw = raw.rsplit('```', 1)[0]
        return json.loads(raw.strip())

    ai = types.ModuleType('app.services.ai_extract_service')
    ai._get_config = lambda: {
        'base_url': 'http://127.0.0.1:11434',
        'text_model': 'test-model',
    }
    ai._parse_structured = _parse_structured
    pkg_app = types.ModuleType('app')
    pkg_services = types.ModuleType('app.services')
    sys.modules.setdefault('app', pkg_app)
    sys.modules['app.services'] = pkg_services
    sys.modules['app.services.ai_extract_service'] = ai

    path = os.path.join(
        os.path.dirname(__file__), '..', 'app', 'services', 'loomy_wa_mcp_agent.py',
    )
    spec = importlib.util.spec_from_file_location('loomy_wa_mcp_agent_test', path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class RunMcpAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent_mod = _load_loomy_wa_mcp_agent_module()

    def test_auth_missing_when_inprocess_disabled(self):
        run_mcp_agent = self.agent_mod.run_mcp_agent
        sent = []

        def capture(phone, group_id, text):
            sent.append((phone, group_id, text))

        with patch.dict(
            os.environ,
            {'LOOMY_WA_INPROCESS_TOOLS': 'false'},
            clear=False,
        ):
            os.environ.pop('SIGN_HOUSE_JWT', None)
            os.environ.pop('MCP_BOT_EMAIL', None)
            os.environ.pop('MCP_BOT_PASSWORD', None)
            run_mcp_agent(
                {'phone': '+8521', 'group_id': '', 'user_text': 'hi'},
                send_wa=capture,
            )
        self.assertEqual(len(sent), 1)
        self.assertIn('鑑權', sent[0][2])

    @patch.dict(os.environ, {'SIGN_HOUSE_JWT': 'test-jwt'}, clear=False)
    def test_two_round_tool_then_reply(self):
        mod = self.agent_mod
        with patch.object(mod, 'try_get_inprocess_client') as mock_client, patch.object(
            mod, '_call_ollama',
        ) as mock_ollama, patch.object(mod, 'execute_tool') as exec_tool:
            mock_client.return_value = MagicMock()
            mock_ollama.side_effect = [
                '{"action":"tool","tool":"wa_get_nas_status","arguments":{}}',
                '{"action":"reply","reply_zh":"NAS 已掛載。"}',
            ]
            exec_tool.return_value = '{"mounted": true}'
            sent = []

            def capture(phone, group_id, text):
                sent.append(text)

            mod.run_mcp_agent(
                {'phone': '+8521', 'user_text': 'NAS 連了嗎'},
                send_wa=capture,
            )

        self.assertEqual(mock_ollama.call_count, 2)
        exec_tool.assert_called_once()
        self.assertEqual(sent, ['NAS 已掛載。'])


if __name__ == '__main__':
    unittest.main()
