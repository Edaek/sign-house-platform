"""Deterministic Loomy replies (no Ollama)."""
import os
import unittest
from unittest.mock import MagicMock, patch

from app.services.loomy_wa_deterministic_reply import (
    hk_datetime_display,
    try_deterministic_loomy_reply,
)
from app.services.loomy_wa_nas_summary import format_wa_nas_summary_zh as fmt


class FormatNasSummaryTests(unittest.TestCase):
    def test_mounted_cache_stale(self):
        msg = fmt({
            'enabled': True,
            'connected': True,
            'degraded': False,
            'foldersFound': 0,
            'foldersCacheStale': True,
            'mongoActiveProjects': 12,
        }, open_pool_count=2)
        self.assertIn('已掛載', msg)
        self.assertIn('刷新中', msg)
        self.assertIn('12', msg)
        self.assertIn('2', msg)

    def test_not_mounted(self):
        msg = fmt({'enabled': True, 'connected': False})
        self.assertIn('尚未掛載', msg)


class DeterministicReplyTests(unittest.TestCase):
    def test_date_question(self):
        reply = try_deterministic_loomy_reply({'user_text': '今天是几月几号'})
        self.assertIsNotNone(reply)
        self.assertIn('香港', reply)
        self.assertIn(hk_datetime_display()[:10], reply)

    def test_greeting(self):
        reply = try_deterministic_loomy_reply({'user_text': 'hi'})
        self.assertIsNotNone(reply)
        self.assertIn('Loomy', reply)

    def test_weather(self):
        reply = try_deterministic_loomy_reply({'user_text': '今天天气怎么样'})
        self.assertIsNotNone(reply)
        self.assertIn('天氣', reply)

    def test_project_code_not_handled(self):
        reply = try_deterministic_loomy_reply({'user_text': 'PJ-2991 北角'})
        self.assertIsNone(reply)

    @patch('app.services.nas_watcher_service.nas_mount')
    def test_status(self, mock_mount):
        mock_mount.status.return_value = {
            'enabled': True,
            'connected': True,
            'foldersFound': 100,
            'foldersCacheStale': False,
            'mongoActiveProjects': 5,
        }
        with patch('app.services.loomy_wa_deterministic_reply._open_pool_count', return_value=0):
            reply = try_deterministic_loomy_reply({'user_text': '现在状态如何', 'phone': '85212345678'})
        self.assertIsNotNone(reply)
        self.assertIn('掛載', reply)

    def test_disabled_via_env(self):
        os.environ['LOOMY_WA_DETERMINISTIC'] = '0'
        try:
            self.assertIsNone(try_deterministic_loomy_reply({'user_text': 'hi'}))
        finally:
            os.environ.pop('LOOMY_WA_DETERMINISTIC', None)


if __name__ == '__main__':
    unittest.main()
