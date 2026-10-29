"""PJ-xxxxA site codes: NAS folder parse and classify matching."""
import unittest

from app.services.project_number_match_service import (
    classify_site_key_from_text,
    match_classify_targets_by_site_number,
    parse_site_folder_code,
    parse_nas_site_folder_code,
)


class SiteSuffixParseTests(unittest.TestCase):
    def test_folder_pj_3014a(self):
        self.assertEqual(
            parse_site_folder_code('PJ-3014A 橫洲B-Yau Lee (JIM)'),
            'PJ-3014A',
        )
        self.assertEqual(
            parse_nas_site_folder_code('PJ-3014A 橫洲B-Yau Lee (JIM)'),
            'PJ-3014A',
        )

    def test_folder_pj_3014_plain(self):
        self.assertEqual(parse_site_folder_code('PJ-3014 Wang Chau'), 'PJ-3014')

    def test_classify_key_3014a(self):
        self.assertEqual(classify_site_key_from_text('3014A'), '3014A')
        self.assertEqual(classify_site_key_from_text('PJ-3014A'), '3014A')


class SiteSuffixMatchTests(unittest.TestCase):
    def test_3014_excludes_a_suffix_projects(self):
        projects = [
            {'_id': '1', 'code': 'PJ-3014', 'status': 'active'},
            {'_id': '2', 'code': 'PJ-3014A', 'status': 'active'},
        ]

        def fake_find(query):
            if query.get('code', {}).get('$regex'):
                code = query['code']['$regex'].strip('^$')
                code = code.replace('\\', '')
                for p in projects:
                    if p['code'].upper() == code.upper():
                        yield p
                return
            for p in projects:
                if p.get('status') == 'active':
                    yield p

        class FakeCol:
            def find(self, query):
                return list(fake_find(query))

        from unittest.mock import patch

        with patch('app.services.project_number_match_service.mongo') as m:
            m.db.wa_projects = FakeCol()
            hits = match_classify_targets_by_site_number('3014')
            codes = {h[0]['code'] for h in hits}
            self.assertIn('PJ-3014', codes)
            self.assertNotIn('PJ-3014A', codes)

    def test_3014a_exact_only(self):
        projects = [
            {'_id': '2', 'code': 'PJ-3014A', 'status': 'active', 'nasParentBucket': 'PJ-3000-3999'},
        ]

        class FakeCol:
            def find(self, query):
                if query.get('code', {}).get('$regex'):
                    for p in projects:
                        if p['status'] == 'active':
                            yield p
                    return
                return iter([])

        from unittest.mock import patch

        with patch('app.services.project_number_match_service.mongo') as m:
            m.db.wa_projects = FakeCol()
            hits = match_classify_targets_by_site_number('3014A')
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0][0]['code'], 'PJ-3014A')


if __name__ == '__main__':
    unittest.main()
