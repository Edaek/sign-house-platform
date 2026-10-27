"""Mongo-only Loomy site-number classify (no NAS)."""
import unittest
from unittest.mock import patch

from app.services.loomy_wa_mongo_site_classify import try_loomy_mongo_site_classify_reply


class LoomyMongoSiteClassifyTests(unittest.TestCase):
    @patch('app.services.image_pool_service.assign_images_to_project')
    @patch('app.services.project_number_match_service.match_classify_targets_by_site_number')
    @patch('app.services.project_number_match_service.loomy_primary_site_number', return_value='1006')
    @patch('app.services.project_number_match_service.loomy_caption_site_matches_project', return_value=True)
    @patch('app.services.project_number_match_service.is_wa_classify_target', return_value=True)
    def test_single_site_assigns_without_nas(
        self,
        _target,
        _match_cap,
        _site,
        match_targets,
        assign,
    ):
        proj = {'_id': 'p1', 'code': 'PJ-1006', 'nasFolderName': '1006 Demo Site'}
        match_targets.return_value = [(proj, 100)]
        assign.return_value = 1

        msg = try_loomy_mongo_site_classify_reply(
            phone='85296364202',
            caption='1006 數據打卡健康',
            pool_ids=['pool1'],
        )
        self.assertIsNotNone(msg)
        self.assertIn('已歸類', msg)
        assign.assert_called_once()

    @patch('app.services.loomy_wa_pick_store.store_loomy_wa_pick_options')
    @patch('app.services.project_ai_resolve_service._build_classify_list_message', return_value='pick list')
    @patch('app.services.project_number_match_service.match_classify_targets_by_site_number')
    @patch('app.services.project_number_match_service.loomy_primary_site_number', return_value='1006')
    def test_multiple_sites_list_without_nas(self, _site, match_targets, build_list, _store):
        match_targets.return_value = [
            ({'code': 'PJ-1006A'}, 100),
            ({'code': 'PJ-1006B'}, 99),
        ]
        msg = try_loomy_mongo_site_classify_reply(
            phone='85296364202',
            caption='1006 remark',
            pool_ids=['pool1'],
        )
        self.assertEqual(msg, 'pick list')
        build_list.assert_called_once()

    @patch('app.services.image_pool_service.match_project_ext')
    @patch('app.services.project_number_match_service.match_classify_targets_by_site_number', return_value=[])
    @patch('app.services.project_number_match_service.loomy_primary_site_number', return_value='1006')
    def test_no_site_match_falls_back_to_fuzzy(self, _site, _match, mock_ext):
        from app.services.image_pool_service import MatchResult

        mock_ext.return_value = MatchResult()
        msg = try_loomy_mongo_site_classify_reply(
            phone='85296364202',
            caption='1006 數據打卡健康',
            pool_ids=['pool1'],
        )
        self.assertIn('1006', msg or '')
        self.assertIn('找不到', msg or '')
        mock_ext.assert_called_once()

    @patch('app.services.loomy_wa_pick_store.store_loomy_wa_pick_options')
    @patch('app.services.project_ai_resolve_service._build_classify_list_message', return_value='fuzzy list')
    @patch('app.services.image_pool_service.match_project_ext')
    @patch('app.services.project_number_match_service.match_classify_targets_by_site_number', return_value=[])
    @patch('app.services.project_number_match_service.loomy_primary_site_number', return_value='1006')
    @patch('app.services.project_number_match_service.is_wa_classify_target', return_value=True)
    def test_no_site_match_fuzzy_candidates_shown(self, _target, _site, _match, mock_ext, build_list, _store):
        from app.services.image_pool_service import MatchResult

        proj_a = {'_id': 'a', 'code': 'PJ-1005'}
        proj_b = {'_id': 'b', 'code': 'PJ-1007'}
        mock_ext.return_value = MatchResult(candidates=[(proj_a, 85), (proj_b, 82)])
        msg = try_loomy_mongo_site_classify_reply(
            phone='85296364202',
            caption='1006 數據打卡健康',
            pool_ids=['pool1'],
        )
        self.assertEqual(msg, 'fuzzy list')
        build_list.assert_called_once()


if __name__ == '__main__':
    unittest.main()
