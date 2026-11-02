"""Group-chat pool assign must not merge different senders or batches."""
import unittest
from unittest.mock import MagicMock, patch

from bson import ObjectId

from app.services.loomy_pool_batch import PoolAssignScopeError, assert_pool_images_assignable


GROUP = '120363409744113388@g.us'


def _img(phone, *, batch_id='b1', message_id=None):
    return {
        '_id': ObjectId(),
        'phone': phone,
        'chatJid': GROUP,
        'batchId': batch_id,
        'messageId': message_id or f'm-{phone}-{batch_id}',
        'imagePath': f'/uploads/{phone}.jpg',
    }


class PoolAssignGroupScopeTests(unittest.TestCase):
    def test_rejects_two_senders_same_group(self):
        a = _img('+85211111111')
        b = _img('+85222222222')
        with self.assertRaises(PoolAssignScopeError):
            assert_pool_images_assignable([a, b], group_id=GROUP)

    def test_allows_one_sender_same_batch(self):
        a = _img('+85211111111', batch_id='b1')
        b = _img('+85211111111', batch_id='b1', message_id='m2')
        assert_pool_images_assignable([a, b], group_id=GROUP)

    def test_rejects_one_sender_two_batches_in_group(self):
        a = _img('+85211111111', batch_id='b1')
        b = _img('+85211111111', batch_id='b2', message_id='m-other')
        with self.assertRaises(PoolAssignScopeError):
            assert_pool_images_assignable([a, b], group_id=GROUP)

    def test_private_chat_ignores_batch_split(self):
        """Private chat (no @g.us): only sender bucket matters — not batch enforcement."""
        a = {'phone': '+85211111111', 'chatJid': '', 'batchId': 'b1', 'messageId': 'm1'}
        b = {'phone': '+85211111111', 'chatJid': '', 'batchId': 'b2', 'messageId': 'm2'}
        assert_pool_images_assignable([a, b])

    @patch('app.services.nas_site_remark_service.set_site_remark_context')
    @patch('app.services.image_pool_service.mongo')
    @patch('app.services.image_pool_service.generate_reference_number')
    def test_assign_api_path_rejects_mixed_group_senders(
        self, mock_ref, mock_mongo, _mock_ctx,
    ):
        from app.services.image_pool_service import assign_images_to_project

        mock_ref.return_value = 'SUB-TEST-003'
        id_a, id_b = ObjectId(), ObjectId()
        img_a = _img('+85211111111')
        img_a['_id'] = id_a
        img_b = _img('+85222222222')
        img_b['_id'] = id_b

        mock_mongo.db.pool_images.find.return_value = [img_a, img_b]
        proj = {
            '_id': ObjectId(),
            'code': '1005',
            'name': '1005',
            'status': 'active',
        }

        with self.assertRaises(PoolAssignScopeError):
            assign_images_to_project(
                [str(id_a), str(id_b)],
                proj,
                assigned_by='test',
                group_id=GROUP,
            )
        mock_mongo.db.wa_records.insert_one.assert_not_called()


if __name__ == '__main__':
    unittest.main()
