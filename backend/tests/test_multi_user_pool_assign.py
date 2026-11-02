"""Multi-user Media Pool — assign scope (group chat enforced in test_pool_assign_group_scope)."""
import unittest
from unittest.mock import MagicMock, patch

from bson import ObjectId


def _fake_project(code='1005'):
    return {
        '_id': ObjectId(),
        'code': code,
        'name': code,
        'status': 'active',
        'nasFolderName': code,
        'nasParentBucket': 'T-1000-2002',
    }


class MultiUserPoolAssignTests(unittest.TestCase):
    @patch('app.services.nas_site_remark_service.set_site_remark_context')
    @patch('app.services.image_pool_service.mongo')
    @patch('app.services.image_pool_service.generate_reference_number')
    def test_assign_only_requested_unassigned_ids(self, mock_ref, mock_mongo, _mock_ctx):
        from app.services.image_pool_service import assign_images_to_project

        mock_ref.return_value = 'SUB-TEST-001'
        proj = _fake_project()
        id_a = ObjectId()
        img_a = {
            '_id': id_a,
            'phone': '+85211111111',
            'imagePath': '/uploads/a.jpg',
            'mediaType': 'image',
        }

        mock_mongo.db.pool_images.find.return_value = [img_a]
        mock_mongo.db.pool_images.update_many = MagicMock()
        mock_mongo.db.pool_images.update_one = MagicMock()
        mock_mongo.db.wa_records.insert_one.return_value = MagicMock(inserted_id=ObjectId())

        n = assign_images_to_project([str(id_a)], proj, assigned_by='test')
        self.assertEqual(n, 1)
        doc = mock_mongo.db.wa_records.insert_one.call_args[0][0]
        self.assertEqual(doc['senderPhone'], '+85211111111')

    @patch('app.services.project_number_match_service.match_classify_targets_by_site_number')
    @patch('app.services.image_pool_service.assign_images_to_project')
    def test_loomy_mongo_classify_passes_pool_ids_from_session(self, mock_assign, mock_match):
        from app.services.loomy_wa_mongo_site_classify import try_loomy_mongo_site_classify_reply

        proj = _fake_project('1005')
        mock_match.return_value = [(proj, 100)]
        mock_assign.return_value = 2
        pool_ids = [str(ObjectId()), str(ObjectId())]
        reply = try_loomy_mongo_site_classify_reply(
            phone='+85211111111',
            caption='1005 防火門牌',
            pool_ids=pool_ids,
            group_id='120363409744113388@g.us',
        )
        self.assertIsNotNone(reply)
        mock_assign.assert_called_once()
        self.assertEqual(mock_assign.call_args[0][0], pool_ids)


if __name__ == '__main__':
    unittest.main()
