"""Worker WhatsApp policy: no interim message before wa_list_pool_images."""
import unittest
from unittest.mock import MagicMock, patch

from app.services.loom_wa_worker_reply_policy import (
    build_worker_whatsapp_policy,
    register_gateway_pool_intake,
)


class LoomWaWorkerReplyPolicyTests(unittest.TestCase):
    @patch('app.services.wa_classify_mode.wa_loom_runtime_brain_enabled', return_value=True)
    @patch('app.services.loom_wa_worker_reply_policy._open_unassigned_count', return_value=2)
    @patch('app.services.loom_wa_worker_reply_policy._session_row', return_value={})
    def test_blocks_before_list_pool(self, _row, _cnt, _loom):
        out = build_worker_whatsapp_policy(phone='143766212071433', group_id='120363409744113388@g.us')
        pol = out['workerWhatsAppPolicy']
        self.assertFalse(pol['allowWorkerWhatsAppNow'])
        self.assertIn('list_pool', pol['instruction'].lower())

    @patch('app.services.wa_classify_mode.wa_loom_runtime_brain_enabled', return_value=True)
    @patch('app.services.loom_wa_worker_reply_policy._open_unassigned_count', return_value=2)
    @patch('app.services.loom_wa_worker_reply_policy.mark_list_pool_called')
    @patch('app.services.loom_wa_worker_reply_policy._session_row')
    def test_allows_after_list_pool(self, row, mark, _cnt, _loom):
        row.return_value = {'listPoolCalledAt': '2026-11-05T10:00:00Z'}
        out = build_worker_whatsapp_policy(
            phone='143766212071433',
            list_pool_just_called=True,
        )
        pol = out['workerWhatsAppPolicy']
        self.assertTrue(pol['allowWorkerWhatsAppNow'])
        mark.assert_called_once()

    @patch('app.mongo.db')
    def test_register_intake(self, db):
        db.wa_system = MagicMock()
        register_gateway_pool_intake(
            phone='143766212071433',
            group_id='120363409744113388@g.us',
            inbound_message_id='false_msg_1',
        )
        db.wa_system.update_one.assert_called_once()


if __name__ == '__main__':
    unittest.main()
