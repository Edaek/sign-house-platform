import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from bson import ObjectId

from app.services.nas_sync_service import (
    _should_remove_record_after_nas_deletion,
    _site_day_dirs_missing_on_share,
)


class NasReconcileSiteDayTests(unittest.TestCase):
    def test_site_day_dirs_missing_when_photo_day_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / '1005'
            photo = site / 'Photo'
            photo.mkdir(parents=True)
            (photo / '2026-10-28').mkdir()
            self.assertFalse(
                _site_day_dirs_missing_on_share(site, {'2026-10-28'}),
            )
            self.assertTrue(
                _site_day_dirs_missing_on_share(site, {'2026-10-29'}),
            )

    @patch('app.services.nas_sync_service.mongo')
    def test_moved_record_removed_when_photo_day_gone(self, mock_mongo):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / '1005'
            (site / 'Photo' / '2026-10-28').mkdir(parents=True)

            rec_id = ObjectId()
            record = {
                '_id': rec_id,
                'status': 'moved',
                'photos': [],
                'nasPhotos': [],
                'createdAt': '2026-10-29T12:00:00',
            }
            project = {'_id': ObjectId(), 'code': '1005'}
            mock_mongo.db.pool_images.find_one.return_value = None

            self.assertTrue(
                _should_remove_record_after_nas_deletion(
                    record,
                    project,
                    nas_image_names=set(),
                    folder_missing=False,
                    site_folder=site,
                ),
            )
