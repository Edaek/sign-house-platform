"""NAS bucket sync must not merge stub + long folders that share a site number."""
import unittest
from unittest.mock import MagicMock, patch

from app.services.nas_sync_service import sync_bucket_site_projects_from_nas


class NasSyncDuplicateFolderTests(unittest.TestCase):
    @patch('app.services.nas_sync_service.mongo')
    @patch('app.services.nas_sync_service.nas_mount')
    def test_sync_does_not_overwrite_long_folder_with_stub(self, mock_mount, mock_mongo):
        long_name = 'PJ-2937 粉嶺北(Yau Lee)_RN'
        long_proj = {
            '_id': 'site-id',
            'code': 'PJ-2937',
            'nasFolderName': long_name,
            'nasParentBucket': 'PJ-2900-2999',
            'name': long_name,
        }

        def find_nas_folder(folder, *, parent_bucket=None):
            if folder == long_name:
                return long_proj
            return None

        mock_mount.is_available.return_value = True
        mock_mount._list_bucket_child_folders_sync.return_value = [
            {'folderName': 'PJ-2937', 'code': 'PJ-2937', 'isSiteProject': True},
            {'folderName': long_name, 'code': 'PJ-2937', 'isSiteProject': True},
        ]
        mock_mongo.db.wa_projects.update_one = MagicMock()
        mock_mongo.db.wa_projects.insert_one = MagicMock()

        with patch(
            'app.services.wa_project_validation.find_project_by_nas_folder',
            side_effect=find_nas_folder,
        ), patch(
            'app.services.nas_sync_service._long_site_peer_in_bucket',
            return_value=False,
        ), patch(
            'app.services.wa_project_validation.resolve_wa_code_for_new_nas_folder',
            return_value='PJ-2937',
        ), patch(
            'app.services.wa_project_validation.assert_code_available',
            return_value='already exists',
        ):
            r = sync_bucket_site_projects_from_nas('PJ-2900-2999', 'owner')

        self.assertTrue(r['ok'])
        self.assertEqual(r['updated'], 1)
        sets = [c[0][1]['$set'] for c in mock_mongo.db.wa_projects.update_one.call_args_list]
        self.assertTrue(all(s.get('nasFolderName') != 'PJ-2937' for s in sets))
        self.assertEqual(sets[0].get('nasFolderName'), long_name)


if __name__ == '__main__':
    unittest.main()
