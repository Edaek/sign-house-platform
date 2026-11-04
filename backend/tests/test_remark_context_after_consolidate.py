import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.services.nas_site_remark_service import (
    append_site_remark_to_nas,
    clear_remark_filename_contexts_for_project,
    site_remark_filename,
)


class RemarkContextAfterConsolidateTests(unittest.TestCase):
    @patch('app.services.nas_site_remark_service.mongo')
    def test_clear_remark_filename_contexts(self, mongo):
        mongo.db.wa_system.update_many.return_value = MagicMock(modified_count=2)
        n = clear_remark_filename_contexts_for_project('KTEST2')
        self.assertEqual(n, 2)
        mongo.db.wa_system.update_many.assert_called_once()

    def test_append_falls_back_to_canonical_when_custom_missing(self):
        with tempfile.TemporaryDirectory() as root:
            day = '2026-11-04'
            day_dir = os.path.join(root, 'KTEST2', 'Photo', day)
            os.makedirs(day_dir)
            canonical = site_remark_filename(folder_name='KTEST2', day_str=day)
            with open(os.path.join(day_dir, canonical), 'w', encoding='utf-8') as fh:
                fh.write('merged\n')

            class Svc:
                def is_available(self):
                    return True

                def ensure_photo_day_dir(self, code, d, **kw):
                    return day_dir

            with patch('app.services.nas_watcher_service.nas_mount', Svc()):
                r = append_site_remark_to_nas(
                    'KTEST2',
                    'follow up',
                    day_str=day,
                    preferred_remark_filename='现场记录.txt',
                    fallback_to_canonical_if_missing=True,
                )
            self.assertTrue(r.get('ok'))
            self.assertTrue(r.get('path', '').endswith(canonical))
            body = open(r['path'], encoding='utf-8').read()
            self.assertIn('follow up', body)


if __name__ == '__main__':
    unittest.main()
