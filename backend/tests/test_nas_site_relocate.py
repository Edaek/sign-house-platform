"""NAS site folder relocate between bucket parents."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.nas_site_relocate_service import (
    _rewrite_path_prefix,
    relocate_site_folder_between_buckets,
)


class RewritePathPrefixTests(unittest.TestCase):
    def test_rewrites_under_root(self):
        old = Path('/vol/KTEST2/kelly')
        new = Path('/vol/KTEST/kelly')
        self.assertEqual(
            _rewrite_path_prefix('/vol/KTEST2/kelly/Photo/a.jpg', old, new),
            '/vol/KTEST/kelly/Photo/a.jpg',
        )


class RelocateSiteFolderTests(unittest.TestCase):
    def test_moves_folder_and_updates_mongo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ktest2 = root / 'KTEST2'
            ktest = root / 'KTEST'
            ktest2.mkdir()
            ktest.mkdir()
            site = ktest2 / 'kelly'
            site.mkdir()
            (site / 'Photo').mkdir()

            class FakeMount:
                def is_available(self):
                    return True

                def _resolve_bucket_dir(self, name):
                    p = root / name
                    return p if p.is_dir() else None

                def _find_dir_named(self, parent, folder_name):
                    return parent / folder_name if (parent / folder_name).is_dir() else None

                def refresh_bucket_children_cache_for(self, _code):
                    pass

            proj = {'_id': __import__('bson').ObjectId(), 'code': 'kelly', 'nasParentBucket': 'KTEST2'}

            with patch('app.services.nas_site_relocate_service.nas_mount', FakeMount()), patch(
                'app.services.nas_site_relocate_service.mongo',
            ) as mock_mongo, patch(
                'app.services.nas_site_relocate_service.find_project_by_code',
                return_value=None,
            ), patch(
                'app.services.nas_site_relocate_service._projects_for_site_folder',
                return_value=[proj],
            ), patch(
                'app.services.nas_site_relocate_service._update_records_nas_paths',
                return_value=0,
            ) as upd_rec, patch(
                'app.services.nas_site_relocate_service._update_pool_images_nas_paths',
                return_value=0,
            ):
                mock_mongo.db.wa_projects.update_one = unittest.mock.Mock()
                r = relocate_site_folder_between_buckets(
                    'kelly',
                    'KTEST2',
                    'KTEST',
                    dry_run=False,
                )

            self.assertTrue(r['ok'])
            self.assertTrue((ktest / 'kelly').is_dir())
            self.assertFalse(site.exists())
            mock_mongo.db.wa_projects.update_one.assert_called_once()
            upd_rec.assert_called_once()


if __name__ == '__main__':
    unittest.main()
