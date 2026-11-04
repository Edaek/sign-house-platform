import os
import tempfile
import unittest
from unittest.mock import patch

from app.services.nas_site_remark_service import (
    normalize_remark_txt_basename,
    rename_site_remark_txt,
    site_remark_filename,
)


class TestNormalizeRemarkTxtBasename(unittest.TestCase):
    def test_adds_txt_extension(self):
        self.assertEqual(normalize_remark_txt_basename('工地备注')[0], '工地备注.txt')

    def test_rejects_empty(self):
        self.assertIsNotNone(normalize_remark_txt_basename('')[1])


class TestRenameSiteRemarkTxt(unittest.TestCase):
    def test_rename_custom_name(self):
        with tempfile.TemporaryDirectory() as root:
            day = '2026-11-04'
            day_dir = os.path.join(root, 'KTEST2', 'Photo', day)
            os.makedirs(day_dir)
            old = site_remark_filename(folder_name='KTEST2', day_str=day)
            with open(os.path.join(day_dir, old), 'w', encoding='utf-8') as fh:
                fh.write('note\n')

            class Svc:
                def is_available(self):
                    return True

                def resolve_photo_day_dir(self, code, d, **kw):
                    return day_dir

            with patch('app.services.nas_watcher_service.nas_mount', Svc()):
                r = rename_site_remark_txt('KTEST2', '现场A', day_str=day)
            self.assertTrue(r.get('ok'))
            self.assertEqual(r.get('fileName'), '现场A.txt')
            self.assertTrue(os.path.isfile(os.path.join(day_dir, '现场A.txt')))
            self.assertFalse(os.path.isfile(os.path.join(day_dir, old)))

    def test_duplicate_name_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            day = '2026-11-04'
            day_dir = os.path.join(root, 'site', 'Photo', day)
            os.makedirs(day_dir)
            for name in ('a.txt', 'b.txt'):
                with open(os.path.join(day_dir, name), 'w', encoding='utf-8') as fh:
                    fh.write('x\n')

            class Svc:
                def is_available(self):
                    return True

                def resolve_photo_day_dir(self, *_a, **_k):
                    return day_dir

            with patch('app.services.nas_watcher_service.nas_mount', Svc()):
                r = rename_site_remark_txt(
                    'site',
                    'b',
                    day_str=day,
                    old_filename='a.txt',
                )
            self.assertFalse(r.get('ok'))
            self.assertEqual(r.get('error'), 'duplicate_remark_txt')
            self.assertIn('message', r)


if __name__ == '__main__':
    unittest.main()
