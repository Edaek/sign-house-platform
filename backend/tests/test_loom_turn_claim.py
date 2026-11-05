"""Parallel Loom Turns listing the same pool batch should claim once."""
import time
import unittest
from unittest.mock import patch

from app.services.loom_turn_claim_service import (
    _mem,
    _mem_lock,
    claim_pool_classify_turn,
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


if __name__ == '__main__':
    unittest.main()
