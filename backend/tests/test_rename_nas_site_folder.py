"""Rename NAS site folder API service (Loom / MCP / Web)."""
import unittest
from unittest.mock import patch
from bson import ObjectId

from app.services.nas_sync_service import rename_nas_site_folder, sync_site_code_to_folder_name


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
        update_web.return_value = {
            'ok': True,
            'project': updated,
            'remarkTxtMergeOk': True,
            'remarkTxtMergedDays': ['2026-11-03'],
            'remarkTxtMerged': 1,
        }

        with patch('app.services.wa_project_bucket_rules.is_bucket_container_project', return_value=False):
            r = rename_nas_site_folder(
                project_id=str(pid),
                new_folder_name='kelly-v2',
            )

        self.assertTrue(r['ok'])
        self.assertEqual(r['nasFolderName'], 'kelly-v2')
        self.assertEqual(r.get('remarkTxtMergedDays'), ['2026-11-03'])
        self.assertTrue(r.get('remarkTxtMergeOk'))
        update_web.assert_called_once()
        _call_proj, call_data = update_web.call_args[0]
        self.assertEqual(call_data['nasFolderName'], 'kelly-v2')
        self.assertEqual(call_data['code'], 'KELLY-V2')

    @patch('app.services.nas_sync_service.update_web_project')
    @patch('app.services.nas_sync_service.mongo')
    def test_syncs_code_when_name_was_code(self, mongo, update_web):
        pid = ObjectId()
        project = {
            '_id': pid,
            'code': 'kelly',
            'nasParentBucket': 'KTEST',
            'nasFolderName': 'kelly',
            'status': 'active',
        }
        mongo.db.wa_projects.find_one.return_value = project
        update_web.return_value = {
            'ok': True,
            'project': {**project, 'code': 'KTEST2', 'nasFolderName': 'KTEST2'},
        }
        with patch('app.services.wa_project_bucket_rules.is_bucket_container_project', return_value=False):
            rename_nas_site_folder(project_id=str(pid), new_folder_name='KTEST2')
        call_data = update_web.call_args[0][1]
        self.assertEqual(call_data['nasFolderName'], 'KTEST2')
        self.assertEqual(call_data['code'], 'KTEST2')

    @patch('app.services.nas_sync_service.update_web_project')
    @patch('app.services.nas_sync_service.mongo')
    def test_always_syncs_code_to_new_folder_name(self, mongo, update_web):
        pid = ObjectId()
        project = {
            '_id': pid,
            'code': 'PJ-1005',
            'nasParentBucket': 'T-1000-2002',
            'nasFolderName': '1005-long-label',
            'status': 'active',
        }
        mongo.db.wa_projects.find_one.return_value = project
        update_web.return_value = {'ok': True, 'project': project}
        with patch('app.services.wa_project_bucket_rules.is_bucket_container_project', return_value=False):
            rename_nas_site_folder(project_id=str(pid), new_folder_name='1005-renamed')
        call_data = update_web.call_args[0][1]
        self.assertEqual(call_data['nasFolderName'], '1005-renamed')
        self.assertEqual(call_data['code'], '1005-RENAMED')

    @patch('app.services.nas_sync_service.update_web_project')
    @patch('app.services.nas_sync_service.mongo')
    def test_new_code_override_keeps_pj_code(self, mongo, update_web):
        pid = ObjectId()
        project = {
            '_id': pid,
            'code': 'PJ-1005',
            'nasParentBucket': 'T-1000-2002',
            'nasFolderName': '1005-long-label',
            'status': 'active',
        }
        mongo.db.wa_projects.find_one.return_value = project
        update_web.return_value = {'ok': True, 'project': project}
        with patch('app.services.wa_project_bucket_rules.is_bucket_container_project', return_value=False):
            rename_nas_site_folder(
                project_id=str(pid),
                new_folder_name='1005-renamed',
                new_code='PJ-1005',
            )
        call_data = update_web.call_args[0][1]
        self.assertEqual(call_data['nasFolderName'], '1005-renamed')
        self.assertEqual(call_data['code'], 'PJ-1005')

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


    @patch('app.services.nas_sync_service.update_web_project')
    @patch('app.services.nas_sync_service.mongo')
    def test_rename_same_folder_syncs_stale_display_name(self, mongo, update_web):
        pid = ObjectId()
        project = {
            '_id': pid,
            'code': 'KTEST2',
            'name': 'kelly',
            'nasParentBucket': 'KTEST',
            'nasFolderName': 'KTEST2',
            'status': 'active',
        }
        mongo.db.wa_projects.find_one.return_value = project
        update_web.return_value = {
            'ok': True,
            'project': {**project, 'name': 'KTEST2'},
        }
        with patch('app.services.wa_project_bucket_rules.is_bucket_container_project', return_value=False):
            r = rename_nas_site_folder(project_id=str(pid), new_folder_name='KTEST2')
        self.assertTrue(r['ok'])
        self.assertTrue(r.get('nameSynced'))
        update_web.assert_called_once()

    @patch('app.services.nas_sync_service.update_web_project')
    @patch('app.services.nas_sync_service.mongo')
    def test_rename_same_folder_syncs_stale_code(self, mongo, update_web):
        pid = ObjectId()
        project = {
            '_id': pid,
            'code': 'kelly',
            'nasParentBucket': 'KTEST',
            'nasFolderName': 'KTEST2',
            'status': 'active',
        }
        mongo.db.wa_projects.find_one.return_value = project
        update_web.return_value = {
            'ok': True,
            'project': {**project, 'code': 'KTEST2'},
        }
        with patch('app.services.wa_project_bucket_rules.is_bucket_container_project', return_value=False):
            r = rename_nas_site_folder(project_id=str(pid), new_folder_name='KTEST2')
        self.assertTrue(r['ok'])
        self.assertTrue(r.get('codeSynced'))
        call_data = update_web.call_args[0][1]
        self.assertEqual(call_data['code'], 'KTEST2')

    @patch('app.services.nas_sync_service._consolidate_remark_txts_after_site_label')
    @patch('app.services.nas_sync_service.update_web_project')
    @patch('app.services.nas_sync_service.nas_mount')
    @patch('app.services.nas_sync_service.mongo')
    def test_sync_site_code_from_folder(self, mongo, nas_mount, update_web, consolidate):
        pid = ObjectId()
        project = {
            '_id': pid,
            'code': 'kelly',
            'nasFolderName': 'KTEST2',
            'nasParentBucket': 'KTEST',
            'status': 'active',
        }
        mongo.db.wa_projects.find_one.return_value = project
        nas_mount.is_available.return_value = True
        live = type('P', (), {'name': 'KTEST2'})()
        nas_mount._folder_for_project.return_value = live
        update_web.return_value = {
            'ok': True,
            'project': {**project, 'code': 'KTEST2'},
            'remarkTxtMergeOk': True,
            'remarkTxtMergedDays': ['2026-11-03'],
            'remarkTxtMerged': 1,
        }
        consolidate.return_value = {'ok': True, 'merged': 0, 'days': []}
        with patch('app.services.wa_project_bucket_rules.is_bucket_container_project', return_value=False):
            r = sync_site_code_to_folder_name(project_id=str(pid))
        self.assertTrue(r['ok'])
        self.assertTrue(r.get('codeSynced'))
        self.assertTrue(r.get('remarkTxtMergeOk'))


if __name__ == '__main__':
    unittest.main()
