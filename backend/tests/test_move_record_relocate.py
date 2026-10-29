"""Move record to project with NAS path cleanup after sync."""
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from bson import ObjectId


class MoveRecordRelocateTests(unittest.TestCase):
    @patch('app.services.image_pool_service.assign_images_to_project')
    @patch('app.services.image_pool_service.mongo')
    def test_move_collects_nas_paths_for_relocate(self, mock_mongo, mock_assign):
        from app.services.image_pool_service import move_images_to_project

        rid = ObjectId()
        img_id = ObjectId()
        old_path = '/nas/PJ-3014/Photo/2026-10-29/photo.jpg'
        mock_mongo.db.pool_images.find.return_value = [{
            '_id': img_id,
            'recordId': rid,
            'nasPath': old_path,
            'imagePath': '/uploads/x.jpg',
            'projectCode': 'PJ-3014',
        }]
        mock_mongo.db.wa_records.find_one.return_value = {
            '_id': rid,
            'nasPhotos': [old_path],
            'nasSourcePath': None,
        }
        mock_mongo.db.wa_records.update_one = MagicMock()
        mock_mongo.db.pool_images.update_one = MagicMock()
        mock_mongo.db.pool_images.update_many = MagicMock()
        rec_after = {'_id': ObjectId(), 'referenceNumber': 'SUB-NEW-001'}
        full_rec = {'_id': rid, 'nasPhotos': [old_path], 'nasSourcePath': None, 'rawMessage': '现场备注'}
        mock_mongo.db.wa_records.find_one.side_effect = lambda q, *a, **k: (
            full_rec if q.get('_id') == rid else rec_after if q.get('projectId') else None
        )
        mock_assign.return_value = 1

        new_proj = {'_id': ObjectId(), 'code': 'PJ-3014A', 'name': 'A site'}
        result = move_images_to_project(
            [str(img_id)], new_proj, relocate_nas=True,
        )

        self.assertEqual(result['moved'], 1)
        mock_assign.assert_called_once()
        kwargs = mock_assign.call_args.kwargs
        self.assertIn(old_path, kwargs.get('nas_delete_after_sync') or [])


if __name__ == '__main__':
    unittest.main()
