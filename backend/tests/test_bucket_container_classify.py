"""Bucket root containers cannot receive pool assign; sites must be subfolders."""
import unittest
from unittest.mock import MagicMock, patch

from app.services.nas_sync_service import _bucket_child_site_code
from app.services.project_number_match_service import is_wa_classify_target
from app.services.wa_project_bucket_rules import (
    is_bucket_container_project,
    is_reserved_nas_folder_name,
)
from app.services.wa_project_validation import assert_code_available


class BucketContainerClassifyTests(unittest.TestCase):
    def test_reserved_photo_folder(self):
        self.assertTrue(is_reserved_nas_folder_name('Photo'))
        self.assertTrue(is_reserved_nas_folder_name('processed'))
        self.assertFalse(is_reserved_nas_folder_name('P1001'))

    def test_bucket_child_site_code_skips_photo(self):
        self.assertIsNone(_bucket_child_site_code({'folderName': 'Photo'}))
        self.assertEqual(
            _bucket_child_site_code({'folderName': 'P1001'}),
            'P1001',
        )

    def test_container_same_code_as_parent(self):
        proj = {'code': 'KTEST', 'nasParentBucket': 'KTEST', 'status': 'active'}
        self.assertTrue(is_bucket_container_project(proj))
        self.assertFalse(is_wa_classify_target(proj))

    def test_site_under_bucket_is_classify_target(self):
        proj = {'code': 'P1001', 'nasParentBucket': 'KTEST', 'status': 'active'}
        self.assertFalse(is_bucket_container_project(proj))
        self.assertTrue(is_wa_classify_target(proj))

    def test_root_bucket_row_not_classify_target(self):
        proj = {'code': 'KTEST', 'status': 'active'}
        self.assertTrue(is_bucket_container_project(proj))
        self.assertFalse(is_wa_classify_target(proj))

    @patch('app.services.wa_project_validation.mongo')
    def test_create_rejects_code_equal_parent_bucket(self, mock_mongo):
        mock_mongo.db.wa_projects.find.return_value = iter([])
        err = assert_code_available('KTEST', parent_bucket='KTEST')
        self.assertIsNotNone(err)
        self.assertIn('subfolder', err or '')

    @patch('app.services.wa_project_validation.mongo')
    def test_create_rejects_reserved_code(self, mock_mongo):
        mock_mongo.db.wa_projects.find.return_value = iter([])
        err = assert_code_available('Photo', parent_bucket='KTEST')
        self.assertIsNotNone(err)
        self.assertIn('reserved', err.lower())

    @patch('app.services.loomy_pool_batch.assert_pool_images_assignable')
    @patch('app.services.image_pool_service.mongo')
    def test_assign_rejects_container_project(self, mock_mongo, _scope):
        from bson import ObjectId

        from app.services.image_pool_service import assign_images_to_project
        from app.services.loomy_pool_batch import PoolAssignNotClassifyTargetError

        oid = ObjectId()
        mock_mongo.db.pool_images.find.return_value = [{
            '_id': oid,
            'phone': '852',
            'imagePath': '/uploads/x.jpg',
        }]
        container = {'_id': ObjectId(), 'code': 'KTEST', 'nasParentBucket': 'KTEST'}
        with self.assertRaises(PoolAssignNotClassifyTargetError):
            assign_images_to_project([str(oid)], container, 'test')


if __name__ == '__main__':
    unittest.main()
