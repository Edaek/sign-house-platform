"""Remove Photo/YYYY-MM-DD when migrate leaves the day folder empty."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from app.services.nas_site_remark_service import site_remark_filename
from app.services.nas_sync_service import (
    photo_day_dir_from_nas_path,
    remove_empty_photo_day_dirs,
)
from app.services.nas_watcher_service import NasMountService


class EmptyPhotoDayAfterMoveTests(unittest.TestCase):
    def test_photo_day_dir_from_paths(self):
        base = '/vol/T-1000-2002/1007/Photo/2026-10-29'
        photo = f'{base}/abc.jpg'
        txt = f'{base}/1007_2026-10-29.txt'
        self.assertEqual(photo_day_dir_from_nas_path(photo), base)
        self.assertEqual(photo_day_dir_from_nas_path(txt), base)
        self.assertIsNone(photo_day_dir_from_nas_path('/vol/other/readme.txt'))

    def test_remove_empty_day_after_files_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            day = root / 'T-1000-2002' / '1007' / 'Photo' / '2026-10-29'
            day.mkdir(parents=True)
            txt_name = site_remark_filename(folder_name='1007', day_str='2026-10-29')
            photo = day / '1793280434776-b5e256fd.jpg'
            txt = day / txt_name
            photo.write_bytes(b'\xff\xd8\xff')
            txt.write_text('remark', encoding='utf-8')
            photo.unlink()
            txt.unlink()
            svc = NasMountService()
            svc._app = MagicMock()
            svc._app.config = {'NAS_WATCH_DIR': str(root)}
            with unittest.mock.patch(
                'app.services.nas_sync_service.nas_mount',
                svc,
            ):
                removed = remove_empty_photo_day_dirs([str(photo), str(txt)])
            self.assertEqual(removed, [str(day)])
            self.assertFalse(day.is_dir())

    def test_keeps_day_when_other_files_remain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            day = root / '1007' / 'Photo' / '2026-10-29'
            day.mkdir(parents=True)
            keep = day / 'other.jpg'
            keep.write_bytes(b'\xff\xd8\xff')
            gone = day / 'moved.jpg'
            gone.write_bytes(b'\xff\xd8\xff')
            gone.unlink()
            svc = NasMountService()
            svc._app = MagicMock()
            svc._app.config = {'NAS_WATCH_DIR': str(root)}
            with unittest.mock.patch(
                'app.services.nas_sync_service.nas_mount',
                svc,
            ):
                removed = remove_empty_photo_day_dirs([str(gone)])
            self.assertEqual(removed, [])
            self.assertTrue(day.is_dir())
            self.assertTrue(keep.is_file())


if __name__ == '__main__':
    unittest.main()
