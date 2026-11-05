"""Parallel Loom Turns listing the same pool batch should claim once."""
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
    def test_second_list_after_grace_is_duplicate(self, _mongo):
        ids = ['img-a', 'img-b']
        first = claim_pool_classify_turn(ids)
        self.assertFalse(first['duplicateInboundTurn'])
        with _mem_lock:
            key = next(iter(_mem))
            _mem[key] = time.time() - 3
        second = claim_pool_classify_turn(ids)
        self.assertTrue(second['duplicateInboundTurn'])
        self.assertIn('SILENCE', second['duplicateInboundMessage'])

    @patch('app.services.loom_turn_claim_service._claim_mongo', return_value=None)
    def test_same_turn_retry_within_grace_is_not_duplicate(self, _mongo):
        ids = ['only-one']
        self.assertFalse(claim_pool_classify_turn(ids)['duplicateInboundTurn'])
        self.assertFalse(claim_pool_classify_turn(ids)['duplicateInboundTurn'])

    @patch('app.services.loom_turn_claim_service._claim_mongo', return_value=None)
    def test_empty_ids_skipped(self, _mongo):
        out = claim_pool_classify_turn([])
        self.assertFalse(out['duplicateInboundTurn'])
        self.assertEqual(out['classifyTurnClaim'], 'skipped_no_ids')

    def test_turn_claim_scopes_to_latest_batch(self):
        images = [
            {'_id': 'new1', 'batchId': 'batch-a', 'messageId': 'm1'},
            {'_id': 'old1', 'batchId': 'batch-b', 'messageId': 'm2'},
        ]
        self.assertEqual(pool_image_ids_for_turn_claim(images), ['new1'])

    @patch('app.services.loom_turn_claim_service._claim_mongo')
    def test_parallel_turn_mongo_duplicate_is_silent(self, mongo_claim):
        mongo_claim.side_effect = [False, True]
        ids = ['img-a']
        self.assertFalse(claim_pool_classify_turn(ids)['duplicateInboundTurn'])
        self.assertTrue(claim_pool_classify_turn(ids)['duplicateInboundTurn'])

    @patch('app.services.loom_turn_claim_service._claim_mongo', return_value=None)
    def test_wa_message_second_turn_is_duplicate(self, _mongo):
        mid = 'false_group@g.us_ABC'
        self.assertFalse(claim_wa_inbound_message_turn([mid])['duplicateInboundTurn'])
        with _mem_lock:
            key = next(iter(_mem))
            _mem[key] = time.time() - 3
        self.assertTrue(claim_wa_inbound_message_turn([mid])['duplicateInboundTurn'])

    @patch('app.services.loom_turn_claim_service._claim_mongo', return_value=None)
    def test_loom_unified_claim_message_wins_before_pool(self, _mongo):
        mid = 'msg-1'
        first = claim_loom_inbound_turn(image_ids=['p1'], wa_message_ids=[mid])
        self.assertFalse(first['duplicateInboundTurn'])
        with _mem_lock:
            for k in list(_mem):
                _mem[k] = time.time() - 3
        second = claim_loom_inbound_turn(image_ids=['p1'], wa_message_ids=[mid])
        self.assertTrue(second['duplicateInboundTurn'])

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
