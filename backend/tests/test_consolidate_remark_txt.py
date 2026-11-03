"""Merge same-day NAS remark txt files after site folder relocate."""
import os
import tempfile
import unittest

from app.services.nas_site_remark_service import (
    consolidate_photo_day_remark_txts,
    read_remark_txt_file,
    site_remark_filename,
)


class ConsolidateRemarkTxtTests(unittest.TestCase):
    def test_merges_two_txts_same_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            day_dir = os.path.join(tmp, 'Photo', '2026-11-03')
            os.makedirs(day_dir)
            legacy = os.path.join(day_dir, 'KTEST2_2026-11-03.txt')
            with open(legacy, 'w', encoding='utf-8') as fh:
                fh.write('蛇口推荐榜')
            other = os.path.join(day_dir, 'kelly_2026-11-03.txt')
            with open(other, 'w', encoding='utf-8') as fh:
                fh.write('extra note')

            r = consolidate_photo_day_remark_txts(tmp, 'kelly')
            self.assertTrue(r['ok'])
            self.assertEqual(r['merged'], 1)
            canonical = os.path.join(day_dir, site_remark_filename(folder_name='kelly', day_str='2026-11-03'))
            self.assertTrue(os.path.isfile(canonical))
            body = read_remark_txt_file(canonical)
            self.assertIn('蛇口推荐榜', body)
            self.assertIn('extra note', body)
            self.assertFalse(os.path.isfile(legacy))
            self.assertTrue(os.path.isfile(canonical))


if __name__ == '__main__':
    unittest.main()
