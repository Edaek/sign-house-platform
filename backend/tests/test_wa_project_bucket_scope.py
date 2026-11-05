"""Site code (e.g. 1005) may repeat under different NAS parent buckets."""
import unittest
from unittest.mock import MagicMock, patch

from bson import ObjectId

from app.api.wa_projects import _RECORDS_SCOPE_EMPTY, _records_project_id
from app.services.wa_project_validation import (
    assert_code_available,
    find_project_by_code,
    find_project_by_nas_folder,
    normalize_code,
    project_matches_nas_folder_label,
)


class WaProjectBucketScopeTests(unittest.TestCase):
    @patch('app.services.wa_project_validation.mongo')
    def test_same_code_different_buckets_allowed(self, mock_mongo):
        t_proj = {
            '_id': '1',
            'code': '1005',
            'nasParentBucket': 'T-1000-2002',
            'status': 'active',
        }

        def find_side_effect(query):
            cursor = MagicMock()
            if query.get('code'):
                cursor.__iter__ = lambda s: iter([t_proj])
            else:
                cursor.__iter__ = lambda s: iter([])
            return cursor

        mock_mongo.db.wa_projects.find.side_effect = find_side_effect

        self.assertIsNone(
            assert_code_available('1005', parent_bucket='S-1000-2000'),
        )
        hit = find_project_by_code('1005', parent_bucket='T-1000-2002')
        self.assertIsNotNone(hit)
        self.assertEqual(normalize_code(hit['code']), '1005')

    @patch('app.services.wa_project_validation.mongo')
    def test_same_code_same_bucket_blocked(self, mock_mongo):
        proj = {
            '_id': '1',
            'code': '1005',
            'nasParentBucket': 'S-1000-2000',
            'status': 'active',
        }
        mock_mongo.db.wa_projects.find.return_value = iter([proj])

        err = assert_code_available('1005', parent_bucket='S-1000-2000')
        self.assertIn('already exists', err or '')
        self.assertIn('S-1000-2000', err or '')

    @patch('app.services.wa_project_validation.find_project_by_nas_folder')
    def test_records_project_id_scoped_by_nas_folder_name(self, mock_find):
        s_id = ObjectId()
        t_id = ObjectId()
        url_project = {'_id': s_id, 'code': '1009', 'nasParentBucket': 'S-1000-2000'}
        mock_find.return_value = {'_id': t_id, 'code': '1009', 'nasParentBucket': 'T-1000-2002'}

        req = MagicMock()
        req.args = {
            'nasFolderName': '1009',
            'nasParentBucket': 'T-1000-2002',
        }
        self.assertEqual(_records_project_id(url_project, req), t_id)
        mock_find.assert_called_once_with('1009', parent_bucket='T-1000-2002')

    @patch('app.services.wa_project_validation.find_project_by_nas_folder')
    def test_records_project_id_long_folder_not_stub(self, mock_find):
        stub_id = ObjectId()
        site_id = ObjectId()
        url_project = {'_id': stub_id, 'code': 'PJ-2937', 'nasParentBucket': 'PJ-2900-2999'}
        long_name = 'PJ-2937 粉嶺北(Yau Lee)_RN'
        mock_find.return_value = {
            '_id': site_id,
            'code': long_name,
            'nasFolderName': long_name,
            'nasParentBucket': 'PJ-2900-2999',
        }

        req = MagicMock()
        req.args = {
            'nasFolderName': long_name,
            'nasParentBucket': 'PJ-2900-2999',
        }
        self.assertEqual(_records_project_id(url_project, req), site_id)
        mock_find.assert_called_once_with(long_name, parent_bucket='PJ-2900-2999')

    def test_nas_folder_label_rejects_code_alias_when_long_name(self):
        long_name = 'PJ-2937 粉嶺北(Yau Lee)_RN'
        proj = {
            'code': 'PJ-2937',
            'nasFolderName': long_name,
            'nasParentBucket': 'PJ-2900-2999',
        }
        self.assertTrue(project_matches_nas_folder_label(proj, long_name))
        self.assertFalse(project_matches_nas_folder_label(proj, 'PJ-2937'))

    @patch('app.services.wa_project_validation.mongo')
    def test_find_nas_folder_stub_not_long_site(self, mock_mongo):
        long_name = 'PJ-2937 粉嶺北(Yau Lee)_RN'
        proj = {
            '_id': 'site',
            'code': 'PJ-2937',
            'nasFolderName': long_name,
            'nasParentBucket': 'PJ-2900-2999',
            'status': 'active',
        }
        mock_mongo.db.wa_projects.find.return_value = [proj]
        hit = find_project_by_nas_folder('PJ-2937', parent_bucket='PJ-2900-2999')
        self.assertIsNone(hit)
        hit_long = find_project_by_nas_folder(long_name, parent_bucket='PJ-2900-2999')
        self.assertIsNotNone(hit_long)

    @patch('app.services.wa_project_validation.find_project_by_nas_folder', return_value=None)
    def test_records_empty_when_stub_folder_no_mongo_row(self, _find):
        site_id = ObjectId()
        long_name = 'PJ-2937 粉嶺北(Yau Lee)_RN'
        url_project = {
            '_id': site_id,
            'code': 'PJ-2937',
            'nasFolderName': long_name,
            'nasParentBucket': 'PJ-2900-2999',
        }
        req = MagicMock()
        req.args = {
            'nasFolderName': 'PJ-2937',
            'nasParentBucket': 'PJ-2900-2999',
        }
        self.assertEqual(_records_project_id(url_project, req), _RECORDS_SCOPE_EMPTY)


if __name__ == '__main__':
    unittest.main()
