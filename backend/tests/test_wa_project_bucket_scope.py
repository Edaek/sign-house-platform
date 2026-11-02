"""Site code (e.g. 1005) may repeat under different NAS parent buckets."""
import unittest
from unittest.mock import MagicMock, patch

from app.services.wa_project_validation import (
    assert_code_available,
    find_project_by_code,
    normalize_code,
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


if __name__ == '__main__':
    unittest.main()
