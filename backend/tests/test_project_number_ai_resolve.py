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
            assert result.project is None
            assert len(result.candidates) == 1
            assert result.candidates[0][0]['code'] == 'PJ-3026'

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

    def test_numeric_only_buckets_yields_projects_hint(self, app, range_only):
        with app.app_context():
            from app.services.project_ai_resolve_service import resolve_classify_input
            r = resolve_classify_input('3026')
            assert r.action == 'none'
            assert 'projects' in (r.user_message or '').lower()


class TestClassifyTarget:

    def test_is_wa_classify_target_excludes_range(self, app):
        with app.app_context():
            from app.services.project_number_match_service import is_wa_classify_target
            assert not is_wa_classify_target({'code': 'PJ-2800-2899', 'status': 'active'})
            assert is_wa_classify_target({'code': 'PJ-2803', 'status': 'active'})
