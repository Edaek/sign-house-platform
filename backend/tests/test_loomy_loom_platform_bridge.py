import os
import unittest
from unittest.mock import patch

from app.services.loomy_loom_platform_bridge import (
    build_loom_classify_payload,
    is_pool_classify_turn,
    try_loom_platform_classify,
    wa_loom_platform_classify_enabled,
)


class LoomPlatformBridgeTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('LOOMY_WA_LOOM_PLATFORM_CLASSIFY', None)
            self.assertFalse(wa_loom_platform_classify_enabled())

    def test_classify_turn_with_pool(self):
        self.assertTrue(is_pool_classify_turn({'pool_ids': ['abc'], 'user_text': ''}))

    def test_not_classify_turn_command(self):
        self.assertFalse(is_pool_classify_turn({'user_text': '*help*'}))

    @patch('app.services.loomy_loom_platform_bridge.fetch_project_catalogue_for_loom')
    def test_payload_shape(self, mock_catalogue):
        mock_catalogue.return_value = [{'code': '1005', 'name': 'A'}]
        p = build_loom_classify_payload({
            'phone': '8521',
            'caption': '1006',
            'pool_ids': ['id1'],
        })
        self.assertEqual(p['channel'], 'whatsapp_pool_classify')
        self.assertEqual(p['context']['intent'], 'pool_classify')
        self.assertIn('id1', p['context']['pool_image_ids'])
        self.assertEqual(p['poolImageIds'], ['id1'])
        self.assertEqual(p['projectCatalogue'], [{'code': '1005', 'name': 'A'}])
        self.assertEqual(p['context']['projectCatalogue'], p['projectCatalogue'])

    @patch.dict(os.environ, {
        'LOOMY_WA_LOOM_PLATFORM_CLASSIFY': 'true',
        'LOOM_PLATFORM_CHAT_URL': 'http://loom.test/chat',
        'LOOM_PLATFORM_SERVICE_TOKEN': 'secret',
    })
    @patch('app.services.loomy_loom_platform_bridge.fetch_project_catalogue_for_loom', return_value=[])
    @patch('app.services.loomy_loom_platform_bridge.requests.post')
    def test_try_classify_parses_reply(self, mock_post, _mock_cat):
        mock_post.return_value.ok = True
        mock_post.return_value.content = b'{"reply_zh":"ok"}'
        mock_post.return_value.json.return_value = {'reply_zh': 'ok'}
        out = try_loom_platform_classify({
            'phone': '852',
            'user_text': '1005',
            'pool_ids': ['x'],
        })
        self.assertEqual(out, 'ok')
