"""NAS bucket site list must not duplicate the same folder label."""
import unittest

from app.api.wa_projects import _dedupe_nas_bucket_site_rows


class NasBucketSitesDedupeTests(unittest.TestCase):
    def test_same_folder_prefers_linked_project(self):
        rows = [
            {
                'folderName': 'PJ-2999 TC114 (Yau Lee)',
                'nasFolderName': 'PJ-2999 TC114 (Yau Lee)',
                'projectId': None,
                'totalRecords': 0,
            },
            {
                'folderName': 'PJ-2999 TC114 (Yau Lee)',
                'nasFolderName': 'PJ-2999 TC114 (Yau Lee)',
                'projectId': 'abc123',
                'totalRecords': 2,
            },
        ]
        out = _dedupe_nas_bucket_site_rows(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['projectId'], 'abc123')


if __name__ == '__main__':
    unittest.main()
