"""Remark txt handling when moving records between projects."""
import os
import tempfile
import unittest

from app.services.nas_site_remark_service import (
    merge_remark_texts,
    read_remark_txt_file,
    site_day_from_nas_path,
    site_remark_filename,
    strip_remark_from_txt_file,
)


class MoveRemarkTxtTests(unittest.TestCase):
    def test_site_day_from_photo_path(self):
        p = '/vol/PJ-3014 Site/Photo/2026-10-29/abc.jpg'
        self.assertEqual(site_day_from_nas_path(p), '2026-10-29')

    def test_remark_filename_for_folder(self):
        self.assertEqual(
            site_remark_filename(folder_name='1005', day_str='2026-10-28'),
            '1005_2026-10-28.txt',
        )

    def test_merge_dedupes(self):
        self.assertEqual(
            merge_remark_texts('hello', 'hello', 'world'),
            'hello\n\nworld',
        )

    def test_strip_leaves_other_paragraphs(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as fh:
            fh.write('误归类备注\n\n其他工地的备注\n')
            path = fh.name
        try:
            r = strip_remark_from_txt_file(path, '误归类备注')
            self.assertTrue(r.get('ok'))
            self.assertFalse(r.get('removedFile'))
            self.assertEqual(read_remark_txt_file(path), '其他工地的备注')
        finally:
            os.remove(path)

    def test_strip_deletes_empty_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as fh:
            fh.write('只有这一条\n')
            path = fh.name
        try:
            r = strip_remark_from_txt_file(path, '只有这一条')
            self.assertTrue(r.get('removedFile'))
            self.assertFalse(os.path.isfile(path))
        finally:
            if os.path.isfile(path):
                os.remove(path)


if __name__ == '__main__':
    unittest.main()
