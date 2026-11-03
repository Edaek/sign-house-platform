"""Rename NAS site folder API service (Loom / MCP / Web)."""
import unittest
from unittest.mock import patch
from bson import ObjectId

from app.services.nas_sync_service import rename_nas_site_folder


class RenameNasSiteFolderTests(unittest.TestCase):
    @patch('app.services.nas_sync_service.update_web_project')
    @patch('app.services.nas_sync_service.mongo')
    def test_rename_by_project_id(self, mongo, update_web):
        pid = ObjectId()
        project = {
            '_id': pid,
            'code': 'kelly',
            'nasParentBucket': 'KTEST',
            'nasFolderName': 'kelly',
            'status': 'active',
        }
        mongo.db.wa_projects.find_one.return_value = project
        updated = {**project, 'nasFolderName': 'kelly-v2', 'nasFolder': '/vol/KTEST/kelly-v2'}
        update_web.return_value = {'ok': True, 'project': updated}

        with patch('app.services.wa_project_bucket_rules.is_bucket_container_project', return_value=False):
            r = rename_nas_site_folder(
                project_id=str(pid),
                new_folder_name='kelly-v2',
            )

        self.assertTrue(r['ok'])
        self.assertEqual(r['nasFolderName'], 'kelly-v2')
        update_web.assert_called_once()
        _call_proj, call_data = update_web.call_args[0]
        self.assertEqual(call_data['nasFolderName'], 'kelly-v2')

    @patch('app.services.nas_sync_service.update_web_project')
    @patch('app.services.wa_project_validation.find_project_by_code')
    @patch('app.services.nas_sync_service.mongo')
    def test_requires_parent_when_ambiguous(self, mongo, find_proj, update_web):
        find_proj.return_value = None
        mongo.db.wa_projects.find.return_value = [
            {'_id': ObjectId(), 'code': '1005', 'nasParentBucket': 'T-1'},
            {'_id': ObjectId(), 'code': '1005', 'nasParentBucket': 'S-1'},
        ]
        with patch('app.services.wa_project_bucket_rules.is_bucket_container_project', return_value=False):
            r = rename_nas_site_folder(project_code='1005', new_folder_name='1005A')
        self.assertFalse(r['ok'])
        self.assertIn('Multiple', r['error'])
        update_web.assert_not_called()

    @patch('app.services.nas_sync_service.mongo')
    def test_rejects_bucket_container(self, mongo):
        pid = ObjectId()
        mongo.db.wa_projects.find_one.return_value = {
            '_id': pid,
            'code': 'KTEST',
            'nasParentBucket': 'KTEST',
            'status': 'active',
        }
        with patch('app.services.wa_project_bucket_rules.is_bucket_container_project', return_value=True):
            r = rename_nas_site_folder(project_id=str(pid), new_folder_name='KTEST1')
        self.assertFalse(r['ok'])
        self.assertIn('container', r['error'].lower())


if __name__ == '__main__':
    unittest.main()
