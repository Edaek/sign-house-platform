"""Tests for classify-intent timing and pool receipt flush guard."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from app.services.pool_receipt_notify_service import _resolve_count


class ResolveReceiptCountTests(unittest.TestCase):
    def test_group_zero_when_all_categorized(self):
        mock_mongo = MagicMock()
        mock_mongo.db.group_pending_images.count_documents.return_value = 0
        entry = {
            'group_id': '120@g.us',
            'group_sender': '85298761823',
            'fileCount': 6,
        }
        with patch('app.mongo', mock_mongo):
            self.assertEqual(_resolve_count(entry), 0)

    def test_group_uses_live_count(self):
        mock_mongo = MagicMock()
        mock_mongo.db.group_pending_images.count_documents.return_value = 3
        entry = {
            'group_id': '120@g.us',
            'group_sender': '85298761823',
            'fileCount': 6,
        }
        with patch('app.mongo', mock_mongo):
            self.assertEqual(_resolve_count(entry), 3)

    def test_private_zero_when_no_pool_rows(self):
        mock_mongo = MagicMock()
        mock_mongo.db.pool_images.count_documents.return_value = 0
        entry = {'phone': '85298761823', 'fileCount': 2}
        with patch('app.mongo', mock_mongo):
            self.assertEqual(_resolve_count(entry), 0)


class ClassifyIntentKeyTests(unittest.TestCase):
    def test_pop_expired_intent(self):
        from app.api import wa_inbound as wi

        mock_mongo = MagicMock()
        old = datetime.utcnow() - timedelta(seconds=wi._CLASSIFY_INTENT_TTL + 5)
        mock_mongo.db.wa_system.find_one_and_delete.return_value = {
            'text': 'P-001',
            'at': old,
        }
        with patch('app.api.wa_inbound.mongo', mock_mongo):
            self.assertIsNone(wi._pop_classify_intent('120@g.us', '85212345678'))

    def test_pop_fresh_intent(self):
        from app.api import wa_inbound as wi

        mock_mongo = MagicMock()
        mock_mongo.db.wa_system.find_one_and_delete.return_value = {
            'text': '2899 carpark sign',
            'at': datetime.utcnow(),
        }
        with patch('app.api.wa_inbound.mongo', mock_mongo):
            self.assertEqual(
                wi._pop_classify_intent('120@g.us', '85212345678'),
                '2899 carpark sign',
            )


class SplitClassifyLabelTests(unittest.TestCase):
    def test_number_and_remark(self):
        from app.services.message_parser_service import split_classify_label_and_remark

        label, remark = split_classify_label_and_remark('2899 carpark sign')
        self.assertEqual(label, '2899')
        self.assertEqual(remark, 'carpark sign')

    def test_plain_name_no_remark(self):
        from app.services.message_parser_service import split_classify_label_and_remark

        label, remark = split_classify_label_and_remark('Sunrise Tower')
        self.assertEqual(label, 'Sunrise Tower')
        self.assertEqual(remark, '')

    def test_uppercase_code_and_remark(self):
        from app.services.message_parser_service import split_classify_label_and_remark

        label, remark = split_classify_label_and_remark('TEST 这是备注文本 111')
        self.assertEqual(label, 'TEST')
        self.assertEqual(remark, '这是备注文本 111')

    def test_numeric_code_and_long_remark(self):
        from app.services.message_parser_service import (
            split_classify_label_and_remark,
            trailing_classify_remark,
        )

        label, remark = split_classify_label_and_remark('3026 123123123123')
        self.assertEqual(label, '3026')
        self.assertEqual(remark, '123123123123')
        self.assertEqual(trailing_classify_remark('3027 这是备注'), '这是备注')
        self.assertIsNone(trailing_classify_remark('3027'))
        from app.services.message_parser_service import site_note_from_text

        self.assertEqual(
            site_note_from_text('归类到1005备注是 这是一条备注信息'),
            '这是一条备注信息',
        )
        self.assertEqual(site_note_from_text('1005 Test'), 'Test')
        self.assertIsNone(site_note_from_text('1005'))


if __name__ == '__main__':
    unittest.main()
