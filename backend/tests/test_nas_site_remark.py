"""NAS Photo/YYYY-MM-DD layout and site remark txt naming."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.nas_site_remark_service import site_remark_filename, hk_today_str
from app.services.nas_watcher_service import NasMountService


class SiteRemarkFilenameTests(unittest.TestCase):
    def test_folder_name_and_date(self):
        self.assertEqual(
            site_remark_filename(folder_name='1005', day_str='2026-10-28'),
            '1005_2026-10-28.txt',
        )
        self.assertEqual(
            site_remark_filename(folder_name='PJ-3010 Test', day_str='2026-10-09'),
            'PJ-3010 Test_2026-10-09.txt',
        )


class NasLayoutTests(unittest.TestCase):
    def test_resolve_nested_project_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bucket = root / 'PJ-3000-3999'
            proj = bucket / 'PJ-3009 Demo Site Name'
            proj.mkdir(parents=True)
            svc = NasMountService()
            svc._app = MagicMock()
            svc._app.config = {'NAS_WATCH_DIR': str(root)}
            found = svc._resolve_project_folder('PJ-3009')
            self.assertIsNotNone(found)
            self.assertEqual(found.name, proj.name)

    def test_photo_day_dir_and_remark_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj = root / 'PJ-3010 Test'
            proj.mkdir()
            svc = NasMountService()
            svc._app = MagicMock()
            svc._app.config = {'NAS_WATCH_DIR': str(root)}
            day_dir = svc.ensure_photo_day_dir('PJ-3010', '2026-10-09')
            self.assertTrue(day_dir.endswith(os.path.join('Photo', '2026-10-09')))
            from app.services.nas_site_remark_service import append_site_remark_to_nas

            with patch('app.services.nas_site_remark_service.nas_mount', svc):
                r1 = append_site_remark_to_nas('PJ-3010', '第一行备注', day_str='2026-10-09')
                self.assertTrue(r1.get('ok'))
                r2 = append_site_remark_to_nas('PJ-3010', '第二行备注', day_str='2026-10-09')
                self.assertTrue(r2.get('ok'))
            txt = Path(day_dir) / site_remark_filename(
                folder_name='PJ-3010 Test', day_str='2026-10-09',
            )
            content = txt.read_text(encoding='utf-8')
            self.assertIn('第一行备注', content)
            self.assertIn('第二行备注', content)

    def test_remark_uses_preferred_physical_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bucket = root / 'PJ-3000-3999'
            bare = bucket / 'PJ-3051'
            long_name = bucket / 'PJ-3051 唐人新村_Hanison (SC)'
            bare.mkdir(parents=True)
            long_name.mkdir(parents=True)
            svc = NasMountService()
            svc._app = MagicMock()
            svc._app.config = {'NAS_WATCH_DIR': str(root)}
            day_bare = svc.ensure_photo_day_dir(
                'PJ-3051', '2026-10-22', preferred_folder_name='PJ-3051',
            )
            from app.services.nas_site_remark_service import append_site_remark_to_nas

            with patch('app.services.nas_site_remark_service.nas_mount', svc):
                r = append_site_remark_to_nas(
                    'PJ-3051',
                    '驗樓用 Foamboard',
                    day_str='2026-10-22',
                    preferred_folder_name='PJ-3051',
                )
                self.assertTrue(r.get('ok'), r)
            txt_bare = Path(day_bare) / site_remark_filename(
                folder_name='PJ-3051', day_str='2026-10-22',
            )
            self.assertTrue(txt_bare.is_file(), 'txt should sit beside photos in bare folder')
            self.assertIn('驗樓用 Foamboard', txt_bare.read_text(encoding='utf-8'))
            txt_long = long_name / 'Photo' / '2026-10-22' / site_remark_filename(
                folder_name='PJ-3051 唐人新村_Hanison (SC)', day_str='2026-10-22',
            )
            self.assertFalse(txt_long.is_file(), 'must not write remark to the other physical folder')

    def test_list_txt_under_range_bucket_photo_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = root / 'T-1000-2002' / '1007'
            day = site / 'Photo' / '2026-10-29'
            day.mkdir(parents=True)
            txt_name = site_remark_filename(folder_name='1007', day_str='2026-10-29')
            (day / txt_name).write_text('site note', encoding='utf-8')
            (day / 'photo.jpg').write_bytes(b'\xff\xd8\xff')
            svc = NasMountService()
            svc._app = MagicMock()
            svc._app.config = {'NAS_WATCH_DIR': str(root)}
            doc = {'code': '1007', 'nasFolderName': '1007', 'nasParentBucket': 'T-1000-2002'}
            files = svc._list_project_txt_files_sync('1007', project_doc=doc)
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0]['name'], txt_name)
            self.assertEqual(files[0]['relativePath'], f'Photo/2026-10-29/{txt_name}'.replace('/', os.sep))
            browse = svc._list_folder_files_sync('1007', project_doc=doc)
            names = {f['name'] for f in browse}
            self.assertIn(txt_name, names)
            self.assertIn('photo.jpg', names)


if __name__ == '__main__':
    unittest.main()
