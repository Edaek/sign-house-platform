"""Link NAS bucket subfolder → wa_projects (name fields for unique index)."""
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.services.nas_sync_service import (
    _nas_site_project_doc_fields,
    link_nas_bucket_folder_to_project,
)


class LinkNasBucketFolderTests(unittest.TestCase):
    def test_doc_fields_include_name_normalized(self):
        now = datetime.utcnow()
        doc = _nas_site_project_doc_fields('KTEST1', 'KTEST1', 'KTEST', 'owner', now)
        self.assertEqual(doc['name'], 'KTEST1')
        self.assertEqual(doc['nameNormalized'], 'ktest1')
        self.assertEqual(doc['nasParentBucket'], 'KTEST')

    @patch('app.services.nas_sync_service.mongo')
    @patch('app.services.nas_sync_service.nas_mount')
    def test_link_creates_project_when_folder_on_nas(self, mock_mount, mock_mongo):
        mock_mount.is_available.return_value = True
        mock_mount._list_bucket_child_folders_sync.return_value = [
            {'folderName': 'KTEST1', 'code': None, 'isSiteProject': False},
        ]
        mock_mongo.db.wa_projects.find_one.return_value = None
        mock_mongo.db.wa_projects.insert_one.return_value = MagicMock(inserted_id='pid1')

        with patch(
            'app.services.wa_project_validation.find_project_by_code',
            return_value=None,
        ), patch(
            'app.services.wa_project_validation.assert_code_available',
            return_value=None,
        ):
            r = link_nas_bucket_folder_to_project(
                '__standalone:KTEST',
                'KTEST1',
                'owner-id',
            )

        self.assertTrue(r['ok'])
        self.assertEqual(r['projectId'], 'pid1')
        insert_doc = mock_mongo.db.wa_projects.insert_one.call_args[0][0]
        self.assertEqual(insert_doc['nameNormalized'], 'ktest1')


if __name__ == '__main__':
    unittest.main()
