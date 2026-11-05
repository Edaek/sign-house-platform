"""NAS assign/move must not duplicate files already in target Photo/day folder."""
import os
from unittest.mock import patch

import pytest


class TestNasCopyDedupe:

    def test_copy_skips_identical_existing_dest(self, tmp_path):
        from app.services.nas_watcher_service import NasMountService

        day = tmp_path / 'site' / 'Photo' / '2026-11-05'
        day.mkdir(parents=True)
        src = tmp_path / 'uploads' / '1793883125306-fb164872.jpg'
        src.parent.mkdir(parents=True)
        src.write_bytes(b'jpeg-bytes')
        dest = day / '1793883125306-fb164872.jpg'
        dest.write_bytes(b'jpeg-bytes')

        svc = NasMountService()
        with patch.object(svc, 'is_available', return_value=True), patch.object(
            svc,
            'ensure_photo_day_dir',
            return_value=str(day),
        ):
            r = svc.copy_file_to_project(
                str(src),
                'PJ-2937',
                day_str='2026-11-05',
                existing_nas_path=str(dest),
            )
        assert r.get('ok') is True
        assert r.get('path') == str(dest)
        assert r.get('deduped') in ('identical', 'relocate_same_path')
        assert not any(
            p.name.startswith('1793883125306-fb164872_') for p in day.iterdir()
        )
