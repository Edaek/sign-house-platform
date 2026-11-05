"""Two NAS folders under one bucket with the same PJ site number (e.g. PJ-2937)."""
import unittest
from unittest.mock import patch

from app.services.project_number_match_service import (
    _site_number_from_project,
    match_classify_targets_by_site_number,
)


class PjSiteDuplicateFolderTests(unittest.TestCase):
    def test_site_number_from_long_nas_folder_name(self):
        proj = {
            'code': 'PJ-2937 粉嶺北(Yau Lee)_RN',
            'nasFolderName': 'PJ-2937 粉嶺北(Yau Lee)_RN',
            'nasParentBucket': 'PJ-2900-2999',
            'status': 'active',
        }
        self.assertEqual(_site_number_from_project(proj), 2937)

    def test_match_finds_stub_and_named_folder(self):
        projects = [
            {
                '_id': 'stub',
                'code': 'PJ-2937',
                'nasFolderName': 'PJ-2937',
                'nasParentBucket': 'PJ-2900-2999',
                'status': 'active',
            },
            {
                '_id': 'site',
                'code': 'PJ-2937 粉嶺北(Yau Lee)_RN',
                'nasFolderName': 'PJ-2937 粉嶺北(Yau Lee)_RN',
                'nasParentBucket': 'PJ-2900-2999',
                'status': 'active',
            },
        ]

        class FakeCol:
            def find(self, query):
                if query.get('code', {}).get('$regex'):
                    return []
                for p in projects:
                    if p.get('status') == 'active':
                        yield p

        with patch('app.services.project_number_match_service.mongo') as m:
            with patch(
                'app.services.wa_project_bucket_rules.is_bucket_container_project',
                return_value=False,
            ):
                m.db.wa_projects = FakeCol()
                hits = match_classify_targets_by_site_number('2937')
        self.assertEqual(len(hits), 2)
        ids = {h[0]['_id'] for h in hits}
        self.assertEqual(ids, {'stub', 'site'})


if __name__ == '__main__':
    unittest.main()
