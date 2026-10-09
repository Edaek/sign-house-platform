"""Tests for PJ range matching and AI classify resolve heuristics."""
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
def range_projects(db):
    db.wa_projects.insert_many([
        {'code': 'PJ-3000-3999', 'name': 'PJ-3000-3999', 'status': 'active'},
        {'code': 'PJ-2800-2899', 'name': 'PJ-2800-2899', 'status': 'active'},
        {'code': 'PJ-2900-2999', 'name': 'PJ-2900-2999', 'status': 'active'},
    ])


class TestSiteNumberMatch:

    def test_3026_only_3000_bucket(self, app, range_projects):
        with app.app_context():
            from app.services.project_number_match_service import match_projects_by_site_number
            hits = match_projects_by_site_number('3026')
            codes = {h[0]['code'] for h in hits}
            assert codes == {'PJ-3000-3999'}

    def test_2888_only_2800_bucket(self, app, range_projects):
        with app.app_context():
            from app.services.project_number_match_service import match_projects_by_site_number
            hits = match_projects_by_site_number('2888')
            codes = {h[0]['code'] for h in hits}
            assert codes == {'PJ-2800-2899'}

    def test_match_ext_returns_single_candidate_not_wrong_fuzzy(self, app, range_projects):
        with app.app_context():
            from app.services.image_pool_service import match_project_ext
            result = match_project_ext('3026')
            assert result.project is None
            assert len(result.candidates) == 1
            assert result.candidates[0][0]['code'] == 'PJ-3000-3999'


class TestResolveClassify:

    def test_suggest_single_range_needs_confirm(self, app, range_projects):
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
            assert r.project['code'] == 'PJ-3000-3999'
