"""Realign Mongo parent bucket when site folder moved on NAS share."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bson import ObjectId

from app.services.nas_site_relocate_service import realign_wa_projects_with_nas


class RealignWaProjectsNasTests(unittest.TestCase):
    def test_realign_updates_stale_parent_bucket(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ktest = root / 'KTEST'
            ktest.mkdir()
            site = ktest / 'kelly'
            site.mkdir()

            pid = ObjectId()
            proj = {
                '_id': pid,
                'code': 'kelly',
                'nasParentBucket': 'KTEST2',
                'nasFolderName': 'kelly',
                'status': 'active',
            }

            class FakeMount:
                def is_available(self):
                    return True

                def _resolved_watch_dir(self):
                    return str(root)

                def _folder_for_project(self, code, project_doc=None, **kwargs):
                    return site

                def _refresh_bucket_children_caches(self):
                    pass

            with patch('app.services.nas_site_relocate_service.nas_mount', FakeMount()), patch(
                'app.services.nas_site_relocate_service.mongo',
            ) as mock_mongo, patch(
                'app.services.wa_project_bucket_rules.is_bucket_container_project',
                return_value=False,
            ), patch(
                'app.services.nas_site_relocate_service.realign_project_record_paths',
                return_value={'recordsUpdated': 2, 'poolImagesUpdated': 0},
            ), patch(
                'app.services.nas_site_remark_service.consolidate_photo_day_remark_txts',
                return_value={'ok': True, 'days': [], 'merged': 0},
            ):
                mock_mongo.db.wa_projects.find.return_value = [proj]
                mock_mongo.db.wa_projects.update_one = unittest.mock.Mock()
                r = realign_wa_projects_with_nas()

            self.assertTrue(r['ok'])
            self.assertEqual(r['projectsRealigned'], 1)
            mock_mongo.db.wa_projects.update_one.assert_called_once()
            patch_doc = mock_mongo.db.wa_projects.update_one.call_args[0][1]['$set']
            self.assertEqual(patch_doc['nasParentBucket'], 'KTEST')


if __name__ == '__main__':
    unittest.main()
