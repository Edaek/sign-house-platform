"""Move to same Photo/day folder must not queue NAS delete/copy duplicate."""
import unittest
from unittest.mock import MagicMock, patch

from bson import ObjectId


class MoveSameFolderNoDuplicateTests(unittest.TestCase):
    @patch('app.services.image_pool_service.assign_images_to_project')
    @patch('app.services.image_pool_service.mongo')
    @patch('app.services.nas_watcher_service.nas_mount')
    @patch('app.services.nas_site_remark_service.assign_photo_day_hk', return_value='2026-11-05')
    @patch(
        'app.services.nas_site_remark_service.collect_move_remark_bundle',
        return_value={'text': '', 'days': [], 'oldTxtPaths': [], 'stripText': ''},
    )
    def test_same_day_dir_clears_nas_delete_queue(
        self, _bundle, _day, mock_nas_mount, mock_mongo, mock_assign,
    ):
        from app.services.image_pool_service import move_images_to_project

        rid = ObjectId()
        img_id = ObjectId()
        day_dir = '/nas/PJ-2937 粉嶺北/Photo/2026-11-05'
        old_path = f'{day_dir}/1793883125306-fb164872.jpg'

        mock_nas_mount.is_available.return_value = True
        mock_nas_mount.ensure_photo_day_dir.return_value = day_dir

        mock_mongo.db.pool_images.find.return_value = [{
            '_id': img_id,
            'recordId': rid,
            'nasPath': old_path,
            'imagePath': '/uploads/x.jpg',
            'projectCode': 'PJ-2937',
        }]
        full_rec = {'_id': rid, 'nasPhotos': [old_path], 'photos': ['/uploads/x.jpg']}
        mock_mongo.db.wa_records.find_one.side_effect = lambda q, *a, **k: (
            full_rec if q.get('_id') == rid else {'_id': ObjectId(), 'referenceNumber': 'SUB-1'}
        )
        mock_mongo.db.wa_records.update_one = MagicMock()
        mock_mongo.db.pool_images.update_one = MagicMock()
        mock_assign.return_value = 1

        new_proj = {
            '_id': ObjectId(),
            'code': 'PJ-2937',
            'nasFolderName': 'PJ-2937 粉嶺北(Yau Lee)_RN',
            'nasParentBucket': 'PJ-2900-2999',
        }
        result = move_images_to_project([str(img_id)], new_proj, relocate_nas=True)

        self.assertEqual(result['moved'], 1)
        kwargs = mock_assign.call_args.kwargs
        self.assertEqual(kwargs.get('nas_delete_after_sync'), [])


if __name__ == '__main__':
    unittest.main()
