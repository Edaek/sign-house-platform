"""NAS nested range buckets and project subfolder images."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.nas_watcher_service import NasMountService
from app.services.project_number_match_service import (
    find_range_bucket_dir,
    is_range_folder_code,
    parse_nas_site_folder_code,
    parse_site_folder_code,
)


class NasFolderNamingTests(unittest.TestCase):
    def test_range_bucket_not_site(self):
        self.assertTrue(is_range_folder_code('PJ-2800-2899'))
        self.assertIsNone(parse_site_folder_code('PJ-2800-2899'))

    def test_site_folder_parses_code(self):
        self.assertEqual(parse_site_folder_code('PJ-2803 清河村'), 'PJ-2803')
        self.assertEqual(parse_site_folder_code('PJ-2800 Lohas Park'), 'PJ-2800')

    def test_numeric_site_under_t_bucket(self):
        self.assertEqual(parse_nas_site_folder_code('1002'), '1002')
        self.assertIsNone(parse_nas_site_folder_code('T-1000-2000'))

    def test_find_range_bucket(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'PJ-2800-2899').mkdir()
            (root / 'PJ-2900-2999').mkdir()
            hit = find_range_bucket_dir(root, 2803)
            self.assertEqual(hit.name, 'PJ-2800-2899')


class NasNestedLayoutTests(unittest.TestCase):
    def _svc(self, root: Path) -> NasMountService:
        svc = NasMountService()
        svc._app = MagicMock()
        svc._app.config = {'NAS_WATCH_DIR': str(root), 'NAS_SCAN_MAX_DEPTH': 6}
        return svc

    def test_list_folders_skips_range_finds_nested_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bucket = root / 'PJ-2800-2899'
            proj = bucket / 'PJ-2803 Site Name'
            sub = proj / '子文件夹'
            sub.mkdir(parents=True)
            (sub / 'a.jpg').write_bytes(b'x')

            svc = self._svc(root)
            folders = svc.list_folders()
            codes = {f['code'] for f in folders}
            names = {f['folderName'] for f in folders}
            self.assertIn('PJ-2803', codes)
            self.assertIn('PJ-2803 Site Name', names)
            self.assertFalse(any(is_range_folder_code(f['code']) for f in folders))

    def test_list_folders_finds_numeric_site_under_t_bucket(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bucket = root / 'T-1000-2000'
            site = bucket / '1002'
            site.mkdir(parents=True)

            svc = self._svc(root)
            folders = svc.list_folders()
            hit = next((f for f in folders if f.get('code') == '1002'), None)
            self.assertIsNotNone(hit)
            self.assertEqual(hit.get('parentBucket'), 'T-1000-2000')

    def test_list_folder_files_includes_subfolder_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj = root / 'PJ-2800-2899' / 'PJ-2803 Demo'
            sub = proj / 'nested'
            sub.mkdir(parents=True)
            (sub / 'photo.jpg').write_bytes(b'jpeg')

            svc = self._svc(root)
            files = svc.list_folder_files('PJ-2803')
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0]['name'], 'photo.jpg')
            self.assertTrue(files[0]['absolutePath'].endswith('nested/photo.jpg'))
            self.assertEqual(files[0]['relativePath'], 'nested/photo.jpg')

    def test_create_folder_under_range_bucket(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'PJ-2800-2899').mkdir()

            svc = self._svc(root)
            r = svc.create_folder('PJ-2810')
            self.assertTrue(r.get('ok'))
            expected = root / 'PJ-2800-2899' / 'PJ-2810'
            self.assertTrue(expected.is_dir())
            self.assertEqual(r['path'], str(expected))

    def test_create_folder_under_explicit_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'ABC').mkdir()
            (root / 'PJ-2800-2899').mkdir()

            svc = self._svc(root)
            r = svc.create_folder('PJ-9999', parent_bucket_code='ABC')
            self.assertTrue(r.get('ok'))
            self.assertTrue((root / 'ABC' / 'PJ-9999').is_dir())

            r2 = svc.create_folder('PJ-2811', parent_bucket_code='PJ-2800-2899')
            self.assertTrue(r2.get('ok'))
            self.assertTrue((root / 'PJ-2800-2899' / 'PJ-2811').is_dir())

    def test_create_folder_creates_missing_parent_at_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            svc = self._svc(root)
            r = svc.create_folder('2036', parent_bucket_code='LIGHT')
            self.assertTrue(r.get('ok'))
            self.assertTrue((root / 'LIGHT').is_dir())
            self.assertTrue((root / 'LIGHT' / '2036').is_dir())

    def test_sync_projects_to_nas_creates_missing_under_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'ABC').mkdir()

            svc = self._svc(root)
            with patch('app.services.nas_sync_service.nas_mount', svc):
                with patch('app.services.nas_sync_service.mongo') as mock_mongo:
                    mock_mongo.db.wa_projects.find.return_value = [
                        {
                            '_id': 'p1',
                            'code': 'PJ-9001',
                            'status': 'active',
                            'nasParentBucket': 'ABC',
                        },
                    ]
                    from app.services.nas_sync_service import sync_projects_to_nas

                    result = sync_projects_to_nas()
            self.assertTrue(result.get('ok'))
            self.assertIn('PJ-9001', result.get('foldersCreated', []))
            self.assertTrue((root / 'ABC' / 'PJ-9001').is_dir())

    def test_sync_projects_skips_range_creates_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bucket = root / 'PJ-2800-2899'
            (bucket / 'PJ-2803 Site').mkdir(parents=True)

            svc = self._svc(root)
            with patch('app.services.nas_sync_service.nas_mount', svc):
                with patch('app.services.nas_sync_service.mongo') as mock_mongo:
                    with patch('app.services.wa_project_validation.mongo', mock_mongo):
                        mock_mongo.db.wa_projects.find_one.return_value = None
                        mock_mongo.db.wa_projects.insert_one.return_value = MagicMock(
                            inserted_id='id1',
                        )
                        from app.services.nas_sync_service import sync_projects_from_nas

                        from bson import ObjectId

                        result = sync_projects_from_nas(ObjectId())
            self.assertTrue(result.get('ok'))
            self.assertEqual(result.get('created'), ['PJ-2803'])
            insert_doc = mock_mongo.db.wa_projects.insert_one.call_args[0][0]
            self.assertEqual(insert_doc['code'], 'PJ-2803')
            self.assertEqual(insert_doc['nasFolder'], 'PJ-2803 Site')

    def test_import_uses_absolute_path_in_subfolder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = Path(tmp) / 'media'
            media.mkdir()
            proj = root / 'PJ-2800-2899' / 'PJ-2803 Demo'
            sub = proj / '子文件夹'
            sub.mkdir(parents=True)
            img = sub / 'a.jpg'
            img.write_bytes(b'x')

            svc = self._svc(root)
            project_id = __import__('bson').ObjectId()
            project = {'_id': project_id, 'code': 'PJ-2803'}

            with patch('app.services.nas_sync_service.nas_mount', svc):
                with patch('app.services.nas_sync_service.mongo') as mock_mongo:
                    mock_mongo.db.wa_projects.find_one.return_value = project
                    mock_mongo.db.wa_records.find_one.return_value = None
                    mock_mongo.db.wa_records.insert_one.return_value = MagicMock()
                    with patch('app.services.nas_sync_service.generate_reference_number', return_value='REF1'):
                        from app.services.nas_sync_service import import_nas_files_for_project

                        result = import_nas_files_for_project(str(project_id), media_dir=str(media))

            self.assertTrue(result.get('ok'))
            self.assertEqual(result.get('created'), 1)
            record = mock_mongo.db.wa_records.insert_one.call_args[0][0]
            self.assertEqual(record['nasSourcePath'], str(img))


if __name__ == '__main__':
    unittest.main()
