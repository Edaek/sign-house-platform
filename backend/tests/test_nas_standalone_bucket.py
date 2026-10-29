import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from app.services.nas_bucket_code import (
    bucket_lookup_keys,
    nas_path_from_web_bucket,
    web_bucket_key_for_nas_root,
)
from app.services.nas_watcher_service import NasMountService


class NasStandaloneBucketTests(unittest.TestCase):
    def test_nas_path_from_web_bucket(self):
        self.assertEqual(nas_path_from_web_bucket('__standalone:LIGHT'), 'LIGHT')
        self.assertEqual(nas_path_from_web_bucket('PJ-3000-3999'), 'PJ-3000-3999')
        self.assertEqual(web_bucket_key_for_nas_root('T-1000-2002'), 'T-1000-2002')
        self.assertEqual(web_bucket_key_for_nas_root('LIGHT'), '__standalone:LIGHT')
        keys = bucket_lookup_keys('__standalone:LIGHT')
        self.assertIn('__standalone:light', keys)
        self.assertIn('light', keys)

    def test_list_bucket_children_under_standalone_bucket(self):
        with tempfile.TemporaryDirectory() as watch:
            root = Path(watch)
            light = root / 'LIGHT'
            light.mkdir()
            (light / 'xxxxx').mkdir()
            (light / 'PJ-3014 Remark').mkdir()

            svc = NasMountService()
            svc._app = MagicMock()
            svc._app.config = {'NAS_WATCH_DIR': str(root)}

            rows = svc._list_bucket_child_folders_sync('__standalone:LIGHT')
            names = {r['folderName'] for r in rows}
            self.assertIn('xxxxx', names)
            self.assertTrue(any(r['folderName'].startswith('PJ-3014') for r in rows))
            self.assertEqual(svc._resolve_bucket_dir('__standalone:LIGHT'), light)

    def test_sync_bucket_imports_plain_child_folder(self):
        from unittest.mock import MagicMock, patch
        from bson import ObjectId

        with tempfile.TemporaryDirectory() as watch:
            root = Path(watch)
            light = root / 'LIGHT'
            light.mkdir()
            (light / 'xxxxx').mkdir()

            svc = NasMountService()
            svc._app = MagicMock()
            svc._app.config = {'NAS_WATCH_DIR': str(root)}

            with patch('app.services.nas_sync_service.nas_mount', svc):
                with patch('app.services.nas_sync_service.mongo') as mock_mongo:
                    with patch('app.services.wa_project_validation.mongo', mock_mongo):
                        mock_mongo.db.wa_projects.find_one.return_value = None
                        mock_mongo.db.wa_projects.insert_one.return_value = MagicMock(
                            inserted_id='id1',
                        )
                        from app.services.nas_sync_service import sync_bucket_site_projects_from_nas

                        result = sync_bucket_site_projects_from_nas(
                            '__standalone:LIGHT',
                            ObjectId(),
                        )
            self.assertTrue(result.get('ok'))
            self.assertIn('xxxxx', result.get('created') or [])
            insert_doc = mock_mongo.db.wa_projects.insert_one.call_args[0][0]
            self.assertEqual(insert_doc['nasParentBucket'], 'LIGHT')
