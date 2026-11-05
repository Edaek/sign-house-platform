"""Loom turn claim: same worker inbound message only (not pool batch)."""
import time
import unittest
from unittest.mock import patch

from app.services.loom_turn_claim_service import (
    _mem,
    _mem_lock,
    claim_loom_inbound_turn,
    claim_pool_classify_turn,
    claim_wa_inbound_message_turn,
    loom_notify_should_skip_duplicate,
    pool_image_ids_for_turn_claim,
    pool_inbound_turn_anchor_ids,
)


class LoomTurnClaimTests(unittest.TestCase):
    def setUp(self):
        with _mem_lock:
            _mem.clear()

    @patch('app.services.loom_turn_claim_service._claim_mongo', return_value=None)
    def test_list_pool_without_inbound_message_id_never_duplicate(self, _mongo):
        first = claim_loom_inbound_turn(active_inbound_message_id=None)
        second = claim_loom_inbound_turn(active_inbound_message_id=None)
        self.assertFalse(first['duplicateInboundTurn'])
        self.assertFalse(second['duplicateInboundTurn'])

    @patch('app.services.loom_turn_claim_service._claim_mongo', return_value=None)
    def test_follow_up_turns_different_inbound_ids_not_duplicate(self, _mongo):
        self.assertFalse(
            claim_loom_inbound_turn(active_inbound_message_id='text-msg-1')['duplicateInboundTurn'],
        )
        with _mem_lock:
            for k in list(_mem):
                _mem[k] = time.time() - 3
        self.assertFalse(
            claim_loom_inbound_turn(active_inbound_message_id='text-msg-2')['duplicateInboundTurn'],
        )

    @patch('app.services.loom_turn_claim_service._claim_mongo', return_value=None)
    def test_same_inbound_message_second_turn_is_duplicate(self, _mongo):
        mid = 'false_group@g.us_ABC'
        self.assertFalse(
            claim_loom_inbound_turn(active_inbound_message_id=mid)['duplicateInboundTurn'],
        )
        with _mem_lock:
            for k in list(_mem):
                _mem[k] = time.time() - 3
        self.assertTrue(
            claim_loom_inbound_turn(active_inbound_message_id=mid)['duplicateInboundTurn'],
        )

    @patch('app.services.loom_turn_claim_service._claim_mongo', return_value=None)
    def test_same_turn_retry_within_grace_is_not_duplicate(self, _mongo):
        mid = 'only-one'
        self.assertFalse(claim_wa_inbound_message_turn([mid])['duplicateInboundTurn'])
        self.assertFalse(claim_wa_inbound_message_turn([mid])['duplicateInboundTurn'])

    @patch('app.services.loom_turn_claim_service._claim_mongo', return_value=None)
    def test_pool_classify_turn_still_available_internally(self, _mongo):
        ids = ['img-a']
        self.assertFalse(claim_pool_classify_turn(ids)['duplicateInboundTurn'])

    def test_turn_claim_scopes_to_latest_batch(self):
        images = [
            {'_id': 'new1', 'batchId': 'batch-a', 'messageId': 'm1'},
            {'_id': 'old1', 'batchId': 'batch-b', 'messageId': 'm2'},
        ]
        self.assertEqual(pool_image_ids_for_turn_claim(images), ['new1'])

    @patch('app.services.loom_turn_claim_service._claim_mongo', return_value=None)
    def test_notify_skip_after_mcp_claim(self, _mongo):
        mid = 'false_120363@g.us_xyz'
        self.assertFalse(loom_notify_should_skip_duplicate(mid))
        with _mem_lock:
            for k in list(_mem):
                _mem[k] = time.time() - 3
        self.assertTrue(loom_notify_should_skip_duplicate(mid))

    def test_pool_anchor_prefers_batch_id(self):
        images = [
            {'_id': 'a', 'batchId': 'batch-99', 'messageId': 'm-part-1'},
            {'_id': 'b', 'batchId': 'batch-99', 'messageId': 'm-part-2'},
        ]
        self.assertEqual(pool_inbound_turn_anchor_ids(images), ['batch-99'])


if __name__ == '__main__':
    unittest.main()
