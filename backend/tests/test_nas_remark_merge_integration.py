"""High/medium-risk remark merge: update_web, consolidate, context clear."""
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from bson import ObjectId

from app.services.nas_site_remark_service import (
    consolidate_photo_day_remark_txts,
    remark_txt_paths_for_nas_photos,
    site_remark_filename,
)
from app.services.nas_sync_service import (
    _consolidate_remark_txts_after_site_label,
    update_web_project,
    rename_nas_site_folder,
)


class NasRemarkMergeIntegrationTests(unittest.TestCase):
    def test_consolidate_skips_single_canonical(self):
        with tempfile.TemporaryDirectory() as tmp:
            day_dir = os.path.join(tmp, 'Photo', '2026-11-04')
            os.makedirs(day_dir)
            name = site_remark_filename(folder_name='KTEST2', day_str='2026-11-04')
            with open(os.path.join(day_dir, name), 'w', encoding='utf-8') as fh:
                fh.write('ok\n')
            r = consolidate_photo_day_remark_txts(tmp, 'KTEST2')
            self.assertTrue(r['ok'])
            self.assertEqual(r['merged'], 0)
            self.assertEqual(r['extraFilesRemoved'], 0)

    def test_remark_paths_include_custom_txt(self):
        with tempfile.TemporaryDirectory() as root:
            day_dir = os.path.join(root, 'site', 'Photo', '2026-11-04')
            os.makedirs(day_dir)
            custom = os.path.join(day_dir, '现场.txt')
            with open(custom, 'w') as fh:
                fh.write('x')
            photo = os.path.join(day_dir, 'a.jpg')
            with open(photo, 'w') as fh:
                fh.write('b')
            paths = remark_txt_paths_for_nas_photos([photo])
            self.assertIn(custom, paths)

    @patch('app.services.nas_site_remark_service.clear_remark_filename_contexts_for_project')
    @patch('app.services.nas_site_remark_service.consolidate_photo_day_remark_txts')
    def test_consolidate_after_label_clears_context(self, consolidate, clear_ctx):
        consolidate.return_value = {
            'ok': True,
            'merged': 1,
            'days': ['2026-11-03'],
            'extraFilesRemoved': 1,
        }
        project = {'code': 'KTEST2', 'nasFolder': '/tmp/fake-site'}
        with patch('app.services.nas_sync_service.os.path.isdir', return_value=True):
            r = _consolidate_remark_txts_after_site_label(project, 'KTEST2')
        self.assertTrue(r['ok'])
        clear_ctx.assert_called_once_with('KTEST2')

    @patch('app.services.nas_sync_service._consolidate_remark_txts_after_site_label')
    @patch('app.services.nas_sync_service.nas_folder_index')
    @patch('app.services.nas_sync_service.nas_mount')
    @patch('app.services.nas_sync_service.mongo')
    def test_update_web_project_triggers_merge_on_code_change(self, mongo, nas_mount, _idx, merge):
        pid = ObjectId()
        project = {
            '_id': pid,
            'code': 'kelly',
            'nasFolderName': 'KTEST2',
            'nasParentBucket': 'KTEST',
            'status': 'active',
        }
        updated = {**project, 'code': 'KTEST2'}
        mongo.db.wa_projects.find_one.return_value = updated
        merge.return_value = {'ok': True, 'merged': 1, 'days': ['2026-11-03'], 'extraFilesRemoved': 1}
        nas_mount.is_available.return_value = False

        with patch('app.services.wa_project_validation.normalize_code', side_effect=lambda x: (x or '').upper()):
            with patch('app.services.wa_project_validation.assert_code_available', return_value=None):
                with patch('app.services.nas_sync_service.is_nas_bucket_folder_code', return_value=False):
                    with patch('app.services.nas_sync_service._is_nas_root_bucket_dir', return_value=False):
                        with patch('app.services.nas_sync_service._project_code_matches_folder_name', return_value=True):
                            r = update_web_project(
                                project,
                                {'code': 'KTEST2', 'nasFolderName': 'KTEST2'},
                                sync_nas=False,
                            )

        self.assertTrue(r['ok'])
        merge.assert_called_once()
        self.assertTrue(r.get('remarkTxtMergeOk'))

    @patch('app.services.nas_sync_service._consolidate_remark_txts_after_site_label')
    @patch('app.services.nas_sync_service.mongo')
    def test_rename_early_exit_still_consolidates(self, mongo, merge):
        pid = ObjectId()
        project = {
            '_id': pid,
            'code': 'KTEST2',
            'name': 'KTEST2',
            'nasFolderName': 'KTEST2',
            'nasParentBucket': 'KTEST',
            'status': 'active',
        }
        mongo.db.wa_projects.find_one.return_value = project
        merge.return_value = {'ok': True, 'merged': 0, 'days': [], 'extraFilesRemoved': 0}

        with patch('app.services.wa_project_bucket_rules.is_bucket_container_project', return_value=False):
            r = rename_nas_site_folder(project_id=str(pid), new_folder_name='KTEST2')

        self.assertTrue(r['ok'])
        merge.assert_called_once()
        self.assertTrue(r.get('remarkTxtMergeOk'))


if __name__ == '__main__':
    unittest.main()
