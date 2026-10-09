"""NAS Photo/YYYY-MM-DD layout and site remark txt naming."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.nas_site_remark_service import site_remark_filename, hk_today_str
from app.services.nas_watcher_service import NasMountService


class SiteRemarkFilenameTests(unittest.TestCase):
    def test_pj_code_and_date(self):
        self.assertEqual(site_remark_filename('PJ-3009', '2026-10-09'), 'PJ-3009_2026-10-09.txt')

    def test_numeric_code_expanded(self):
        self.assertTrue(site_remark_filename('3009', '2026-10-09').startswith('PJ-3009_'))


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
            txt = Path(day_dir) / site_remark_filename('PJ-3010', '2026-10-09')
            content = txt.read_text(encoding='utf-8')
            self.assertIn('第一行备注', content)
            self.assertIn('第二行备注', content)


if __name__ == '__main__':
    unittest.main()
