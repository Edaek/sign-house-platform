import os
import tempfile
import unittest
from unittest.mock import patch

from app.services.nas_site_remark_service import (
    delete_site_remark_txt,
    read_site_remark_txt,
    set_site_remark_txt,
    site_remark_filename,
)


class _NasDayDirMock:
    def __init__(self, day_dir: str):
        self._day_dir = day_dir

    def is_available(self):
        return True

    def resolve_photo_day_dir(self, code, day, **kw):
        return self._day_dir


class SiteRemarkTxtCrudTests(unittest.TestCase):
    def test_read_set_delete_roundtrip(self):
        with tempfile.TemporaryDirectory() as root:
            day = '2026-11-05'
            day_dir = os.path.join(root, '1009', 'Photo', day)
            os.makedirs(day_dir)
            fname = site_remark_filename(folder_name='1009', day_str=day)
            path = os.path.join(day_dir, fname)
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write('—\n')

            svc = _NasDayDirMock(day_dir)
            with patch('app.services.nas_watcher_service.nas_mount', svc):
                r = read_site_remark_txt('1009', day_str=day)
                self.assertTrue(r.get('ok'))
                self.assertIn('—', r.get('content') or '')

                w = set_site_remark_txt('1009', '真實備註', day_str=day)
                self.assertTrue(w.get('ok'))
                self.assertEqual(read_remark_txt_cached(svc, '1009', day), '真實備註')

                d = delete_site_remark_txt('1009', day_str=day)
                self.assertTrue(d.get('ok'))
                self.assertTrue(d.get('removedFile'))
                self.assertFalse(os.path.isfile(path))

    def test_empty_content_deletes(self):
        with tempfile.TemporaryDirectory() as root:
            day = '2026-11-05'
            day_dir = os.path.join(root, '1009', 'Photo', day)
            os.makedirs(day_dir)
            fname = site_remark_filename(folder_name='1009', day_str=day)
            path = os.path.join(day_dir, fname)
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write('x\n')

            svc = _NasDayDirMock(day_dir)
            with patch('app.services.nas_watcher_service.nas_mount', svc):
                r = set_site_remark_txt('1009', '   ', day_str=day)
                self.assertTrue(r.get('ok'))
                self.assertFalse(os.path.isfile(path))


def read_remark_txt_cached(svc, code, day):
    with patch('app.services.nas_watcher_service.nas_mount', svc):
        out = read_site_remark_txt(code, day_str=day)
    return (out.get('content') or '').strip()


if __name__ == '__main__':
    unittest.main()
