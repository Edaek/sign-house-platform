"""Tests for PJ site matching and AI classify resolve heuristics."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest


@pytest.fixture(scope='module')
def app():
    os.environ['MONGO_URI'] = 'mongodb://eularis:eularis@localhost:27017/signhouse_test?authSource=admin'
    from app import create_app
    application = create_app()
    application.config['TESTING'] = True
    yield application


@pytest.fixture
def db(app):
    from app import mongo
    db = mongo.db
    db.wa_projects.delete_many({})
    yield db
    db.wa_projects.delete_many({})


@pytest.fixture
def nested_projects(db):
    db.wa_projects.insert_many([
        {'code': 'PJ-3000-3999', 'nasFolder': 'PJ-3000-3999', 'status': 'active'},
        {'code': 'PJ-2800-2899', 'nasFolder': 'PJ-2800-2899', 'status': 'active'},
        {
            'code': 'PJ-3026',
            'nasFolder': 'PJ-3026 示例站点',
            'nasParentBucket': 'PJ-3000-3999',
            'status': 'active',
        },
        {
            'code': 'PJ-2888',
            'nasFolder': 'PJ-2888',
            'nasParentBucket': 'PJ-2800-2899',
            'status': 'active',
        },
    ])


@pytest.fixture
def range_only(db):
    db.wa_projects.insert_many([
        {'code': 'PJ-3000-3999', 'name': 'PJ-3000-3999', 'status': 'active'},
        {'code': 'PJ-2800-2899', 'name': 'PJ-2800-2899', 'status': 'active'},
    ])


class TestSiteNumberMatch:

    def test_match_site_projects_by_number_finds_site(self, app, nested_projects):
        with app.app_context():
            from app.services.project_number_match_service import match_site_projects_by_number
            hits = match_site_projects_by_number('3026')
            codes = {h[0]['code'] for h in hits}
            assert codes == {'PJ-3026'}

    def test_range_match_legacy_not_used_for_classify(self, app, range_only):
        with app.app_context():
            from app.services.project_number_match_service import (
                match_projects_by_site_number,
                match_site_projects_by_number,
            )
            assert match_site_projects_by_number('3026') == []
            range_hits = match_projects_by_site_number('3026')
            assert {h[0]['code'] for h in range_hits} == {'PJ-3000-3999'}


class TestMatchExt:

    def test_numeric_input_prefers_site_not_bucket(self, app, nested_projects):
        with app.app_context():
            from app.services.image_pool_service import match_project_ext
            result = match_project_ext('3026')
            assert result.project is not None
            assert result.project['code'] == 'PJ-3026'

    def test_digit_site_number_letter_bucket_neighbors_and_cross_typo(self, app, db):
        db.wa_projects.insert_many([
            {'code': 'T-1000-2000', 'status': 'active'},
            {'code': '1005', 'nasParentBucket': 'T-1000-2000', 'status': 'active'},
            {'code': '1002', 'nasParentBucket': 'T-1000-2000', 'status': 'active'},
            {'code': 'PJ-3007', 'nasParentBucket': 'PJ-3000-3999', 'status': 'active'},
            {'code': 'PJ-3002', 'nasParentBucket': 'PJ-3000-3999', 'status': 'active'},
            {'code': 'PJ-2807', 'nasParentBucket': 'PJ-2800-2899', 'status': 'active'},
        ])
        with app.app_context():
            from app.services.image_pool_service import match_project_ext
            from app.services.project_number_match_service import (
                find_buckets_containing_site_number,
                match_classify_cross_bucket_typo_suggestions,
            )
            buckets = find_buckets_containing_site_number(1007)
            assert 'T-1000-2000' in buckets
            cross = match_classify_cross_bucket_typo_suggestions('1007', buckets, limit=3)
            cross_codes = [p['code'] for p, _ in cross]
            assert 'PJ-3002' in cross_codes
            assert 'PJ-3007' not in cross_codes
            assert 'PJ-2807' not in cross_codes

            result = match_project_ext('1007')
            codes = []
            if result.project:
                codes.append(result.project['code'])
            codes.extend(p['code'] for p, _ in result.candidates)
            assert '1005' in codes
            assert '1002' in codes
            assert 'PJ-3002' in codes
            assert 'PJ-3007' not in codes
            assert 'PJ-2807' not in codes
            hit = match_project_ext('3007')
            assert hit.project and hit.project['code'] == 'PJ-3007'

    def test_s_range_bucket_neighbors_by_site_number(self, app, db):
        db.wa_projects.insert_many([
            {'code': 'S-1000-2000', 'status': 'active'},
            {'code': '1005', 'nasParentBucket': 'S-1000-2000', 'status': 'active'},
            {'code': '1002', 'nasParentBucket': 'S-1000-2000', 'status': 'active'},
        ])
        with app.app_context():
            from app.services.image_pool_service import match_project_ext
            from app.services.project_number_match_service import find_buckets_containing_site_number

            assert 'S-1000-2000' in find_buckets_containing_site_number(1007)
            result = match_project_ext('1007')
            codes = [p['code'] for p, _ in result.candidates]
            assert '1005' in codes
            assert '1002' in codes

    def test_exact_pj_code_assigns_without_confirm_path(self, app, nested_projects):
        with app.app_context():
            from app.services.image_pool_service import match_project_ext
            result = match_project_ext('PJ-3026')
            assert result.project is not None
            assert result.project['code'] == 'PJ-3026'


class TestResolveClassify:

    def test_suggest_site_not_range_bucket(self, app, nested_projects):
        with app.app_context():
            from app.services.project_ai_resolve_service import resolve_classify_input
            from unittest.mock import patch
            with patch(
                'app.services.project_ai_resolve_service._ollama_polish_message',
                side_effect=lambda fb, _p: fb,
            ):
                r = resolve_classify_input('3026')
            assert r.action == 'suggest'
            assert r.needs_confirm is True
            assert r.project['code'] == 'PJ-3026'

    def test_partial_pj_code_requires_confirm(self, app, nested_projects):
        with app.app_context():
            from app.services.project_ai_resolve_service import resolve_classify_input
            from unittest.mock import patch
            with patch(
                'app.services.project_ai_resolve_service._ollama_polish_message',
                side_effect=lambda fb, _p: fb,
            ):
                r = resolve_classify_input('PJ-3026')
            assert r.action == 'suggest'
            assert r.needs_confirm is True

    def test_full_nas_folder_name_assigns(self, app, nested_projects):
        with app.app_context():
            from app.services.project_ai_resolve_service import resolve_classify_input
            r = resolve_classify_input('PJ-3026 示例站点')
            assert r.action == 'assign'
            assert r.project['code'] == 'PJ-3026'
            assert r.needs_confirm is False

    def test_pj_code_only_not_full_display(self, app, db):
        db.wa_projects.insert_one({
            'code': 'PJ-3003',
            'nasFolder': 'PJ-3003 高鐵站地牢供裝臨時 3M Film_Sanfield (JM)',
            'status': 'active',
        })
        with app.app_context():
            from app.services.project_number_match_service import classify_input_matches_full_display
            proj = db.wa_projects.find_one({'code': 'PJ-3003'})
            assert not classify_input_matches_full_display('3003', proj)
            assert not classify_input_matches_full_display('PJ-3003', proj)
            assert classify_input_matches_full_display(
                'PJ-3003 高鐵站地牢供裝臨時 3M Film_Sanfield (JM)',
                proj,
            )

    def test_shorthand_pj_number_requires_confirm(self, app, db):
        db.wa_projects.insert_many([
            {'code': 'PJ-3000-3999', 'status': 'active'},
            {
                'code': 'PJ-3002',
                'nasFolder': 'PJ-3002 中醫院_ Cyber World (JW)',
                'nasParentBucket': 'PJ-3000-3999',
                'status': 'active',
            },
        ])
        with app.app_context():
            from app.services.project_ai_resolve_service import resolve_classify_input
            from unittest.mock import patch
            with patch(
                'app.services.project_ai_resolve_service._ollama_polish_message',
                side_effect=lambda fb, _p: fb,
            ):
                r = resolve_classify_input('3002')
            assert r.action == 'suggest'
            assert r.project['code'] == 'PJ-3002'

    def test_numeric_only_buckets_yields_projects_hint(self, app, range_only):
        with app.app_context():
            from app.services.project_ai_resolve_service import resolve_classify_input
            r = resolve_classify_input('3026')
            assert r.action == 'none'
            assert 'projects' in (r.user_message or '').lower()


class TestDuplicateNasFolderLabels:

    def test_enrich_keeps_bare_and_full_names_for_same_site(self, app):
        with app.app_context():
            from unittest.mock import patch

            from app.services.nas_sync_service import enrich_wa_projects_display
            from app.services.project_number_match_service import wa_classify_display_label

            idx = {
                'PJ-3051': {
                    'folderName': 'PJ-3051 唐人新村_Hanison (SC)',
                    'code': 'PJ-3051',
                },
            }
            cands = [
                ({'code': 'PJ-3051', 'nasFolderName': 'PJ-3051'}, 100),
                (
                    {
                        'code': 'PJ-3051',
                        'nasFolderName': 'PJ-3051 唐人新村_Hanison (SC)',
                    },
                    100,
                ),
            ]
            with patch('app.services.nas_sync_service.nas_folder_index', return_value=idx):
                enrich_wa_projects_display(cands)
            assert cands[0][0]['nasFolderName'] == 'PJ-3051'
            assert cands[1][0]['nasFolderName'] == 'PJ-3051 唐人新村_Hanison (SC)'
            labels = [
                wa_classify_display_label(cands[0][0]),
                wa_classify_display_label(cands[1][0]),
            ]
            assert labels == ['PJ-3051', 'PJ-3051 唐人新村_Hanison (SC)']

    def test_list_labels_append_bucket_when_names_collide(self, app):
        with app.app_context():
            from app.services.project_number_match_service import wa_classify_list_labels

            projs = [
                {
                    'code': 'PJ-3051',
                    'nasFolderName': 'PJ-3051 唐人新村_Hanison (SC)',
                    'nasParentBucket': 'PJ-3000-3999',
                },
                {
                    'code': 'PJ-3051',
                    'nasFolderName': 'PJ-3051 唐人新村_Hanison (SC)',
                    'nasParentBucket': 'PJ-2800-2899',
                },
            ]
            labels = wa_classify_list_labels(projs, max_len=500)
            assert '[PJ-3000-3999]' in labels[0]
            assert '[PJ-2800-2899]' in labels[1]


class TestClassifyTarget:

    def test_is_wa_classify_target_excludes_range(self, app):
        with app.app_context():
            from app.services.project_number_match_service import is_wa_classify_target
            assert not is_wa_classify_target({'code': 'PJ-2800-2899', 'status': 'active'})
            assert is_wa_classify_target({'code': 'PJ-2803', 'status': 'active'})
