"""code, name, and nasFolderName should follow the NAS folder label (no stub rows)."""
import unittest
from unittest.mock import MagicMock, patch

from app.services.wa_project_validation import resolve_wa_code_for_new_nas_folder


class ResolveWaCodeTests(unittest.TestCase):
    @patch('app.services.wa_project_validation.assert_code_available')
    def test_prefers_full_folder_label(self, mock_avail):
        mock_avail.return_value = None
        long_name = 'PJ-2937 粉嶺北(Yau Lee)_RN'
        code = resolve_wa_code_for_new_nas_folder('PJ-2937', long_name, parent_bucket='PJ-2900-2999')
        self.assertEqual(code, long_name)


class NasSyncSkipStubTests(unittest.TestCase):
    @patch('app.services.nas_sync_service.mongo')
    @patch('app.services.nas_sync_service.nas_mount')
    def test_skips_insert_for_short_folder_when_long_exists(self, mock_mount, mock_mongo):
        from app.services.nas_sync_service import sync_bucket_site_projects_from_nas

        long_name = 'PJ-2937 粉嶺北(Yau Lee)_RN'
        long_proj = {
            '_id': 'site-id',
            'code': long_name,
            'nasFolderName': long_name,
            'nasParentBucket': 'PJ-2900-2999',
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
            'app.services.wa_project_validation.assert_code_available',
            return_value=None,
        ), patch(
            'app.services.nas_sync_service._long_site_peer_in_bucket',
            side_effect=lambda fn, sc, pb: fn == 'PJ-2937',
        ):
            r = sync_bucket_site_projects_from_nas('PJ-2900-2999', 'owner')

        self.assertTrue(r['ok'])
        mock_mongo.db.wa_projects.insert_one.assert_not_called()


if __name__ == '__main__':
    unittest.main()
