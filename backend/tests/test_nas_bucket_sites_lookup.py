"""NAS bucket site list must match Mongo by folder name (e.g. KTEST1), not only PJ-/numeric code."""
import unittest
from unittest.mock import MagicMock, patch

from app.api.wa_projects import (
    _bucket_child_lookup_code,
    _build_nas_bucket_sites_payload,
    _merge_bucket_children,
)


class NasBucketSitesLookupTests(unittest.TestCase):
    def test_lookup_code_uses_folder_name_when_parse_empty(self):
        child = {'folderName': 'KTEST1', 'code': None, 'isSiteProject': False}
        self.assertEqual(_bucket_child_lookup_code(child), 'KTEST1')

    def test_lookup_skips_photo(self):
        child = {'folderName': 'Photo', 'code': None}
        self.assertIsNone(_bucket_child_lookup_code(child))

    def test_merge_drops_mongo_only_when_nas_authoritative(self):
        nas = [{'folderName': 'kelly', 'code': 'kelly'}]
        mongo_extra = [
            {'folderName': 'KTEST1', 'code': 'KTEST1'},
            {'folderName': 'K-1000', 'code': 'K-1000'},
        ]
        merged = _merge_bucket_children(nas, mongo_extra, supplement_mongo_only=False)
        names = {r['folderName'] for r in merged}
        self.assertEqual(names, {'kelly'})
        with_mongo = _merge_bucket_children(nas, mongo_extra, supplement_mongo_only=True)
        self.assertEqual(len(with_mongo), 3)

    @patch('app.api.wa_projects.mongo')
    @patch('app.api.wa_projects.serialize_doc')
    def test_payload_links_ktest1_project_by_folder_name(self, mock_ser, mock_mongo):
        proj = {
            '_id': 'abc123',
            'code': 'KTEST1',
            'nasParentBucket': 'KTEST',
            'status': 'active',
        }
        mock_mongo.db.wa_projects.find.return_value = [proj]
        mock_mongo.db.wa_records.aggregate.return_value = []
        mock_ser.return_value = {'id': 'mongo-id-1', 'code': 'KTEST1', 'status': 'active'}

        children = [{'folderName': 'KTEST1', 'code': None, 'isSiteProject': False}]
        payload = _build_nas_bucket_sites_payload('__standalone:KTEST', children, from_cache=False)

        self.assertEqual(payload['count'], 1)
        site = payload['sites'][0]
        self.assertEqual(site['projectId'], 'mongo-id-1')
        self.assertEqual(site['folderName'], 'KTEST1')


if __name__ == '__main__':
    unittest.main()
