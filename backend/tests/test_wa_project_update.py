"""WA project PATCH + NAS folder rename."""
import unittest
from unittest.mock import MagicMock, patch
from bson import ObjectId

from app.services.nas_sync_service import _migrate_bucket_parent_code, update_web_project


class WaProjectUpdateTests(unittest.TestCase):
    @patch('app.services.nas_sync_service.mongo')
    def test_migrate_bucket_parent_updates_sites(self, mongo):
        _migrate_bucket_parent_code('T-1000-2000', 'T-1000-2001', exclude_project_id=ObjectId())
        mongo.db.wa_projects.update_many.assert_called_once()
        call_filter = mongo.db.wa_projects.update_many.call_args[0][0]
        self.assertIn('nasParentBucket', call_filter)
        mongo.db.wa_projects.delete_many.assert_called_once()

    @patch('app.services.wa_project_validation.find_project_by_code', return_value=None)
    @patch('app.services.nas_sync_service.mongo')
    @patch('app.services.nas_sync_service.nas_mount')
    @patch('app.services.nas_sync_service.nas_folder_index')
    def test_site_code_change_renames_nas_folder_to_new_code(self, _idx, nas_mount, mongo, _find):
        pid = ObjectId()
        project = {
            '_id': pid,
            'code': '1002',
            'location': '',
            'stage': 'active',
            'status': 'active',
            'nasParentBucket': 'T-1000-2002',
        }
        nas_mount.is_available.return_value = True
        folder = MagicMock()
        folder.name = '1002'
        folder.resolve.return_value = folder
        nas_mount._resolve_project_folder.return_value = folder
        nas_mount.rename_site_folder.return_value = {
            'ok': True,
            'path': '/vol/T-1000-2002/1003',
        }
        mongo.db.wa_projects.find_one.return_value = {**project, 'code': '1003'}

        r = update_web_project(
            project,
            {'code': '1003', 'nasFolderName': '1002', 'syncNas': True},
            sync_nas=True,
        )
        self.assertTrue(r['ok'])
        nas_mount.rename_site_folder.assert_called_once()
        _args, kwargs = nas_mount.rename_site_folder.call_args
        self.assertEqual(_args[1], '1003')

    @patch('app.services.wa_project_validation.find_project_by_code', return_value=None)
    @patch('app.services.nas_sync_service.mongo')
    @patch('app.services.nas_sync_service.nas_mount')
    @patch('app.services.nas_sync_service.nas_folder_index')
    def test_update_code_renames_nas(self, _idx, nas_mount, mongo, _find):
        pid = ObjectId()
        project = {
            '_id': pid,
            'code': '1002',
            'location': '',
            'stage': 'active',
            'status': 'active',
            'nasParentBucket': 'T-1000-2000',
        }
        nas_mount.is_available.return_value = True
        folder = MagicMock()
        folder.name = '1002'
        folder.resolve.return_value = folder
        nas_mount._resolve_project_folder.return_value = folder
        nas_mount.rename_site_folder.return_value = {
            'ok': True,
            'path': '/vol/T-1000-2000/1003',
        }
        mongo.db.wa_projects.find_one.return_value = {**project, 'code': '1003'}

        r = update_web_project(project, {'code': '1003', 'syncNas': True}, sync_nas=True)
        self.assertTrue(r['ok'])
        nas_mount.rename_site_folder.assert_called_once()
        mongo.db.wa_records.update_many.assert_called_once()
        mongo.db.pool_images.update_many.assert_called_once()

    @patch('app.services.nas_sync_service.mongo')
    @patch('app.services.nas_sync_service.nas_mount')
    def test_range_bucket_code_locked(self, nas_mount, mongo):
        project = {'_id': ObjectId(), 'code': 'PJ-2800-2899', 'stage': 'active', 'status': 'active'}
        r = update_web_project(project, {'code': 'PJ-2900-2999'}, sync_nas=False)
        self.assertFalse(r['ok'])
        nas_mount.rename_site_folder.assert_not_called()
