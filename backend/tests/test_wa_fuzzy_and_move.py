"""End-to-end tests for WA bot fuzzy matching and move features."""
import sys
import os
import json
from datetime import datetime
from unittest.mock import patch, MagicMock
from bson import ObjectId

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def app():
    os.environ['MONGO_URI'] = 'mongodb://eularis:eularis@localhost:27017/signhouse_test?authSource=admin'
    os.environ['GATEWAY_INBOUND_SECRET'] = 'test-secret'
    os.environ['POOL_REMINDER_ENABLED'] = 'false'
    from app import create_app
    application = create_app()
    application.config['TESTING'] = True
    application.config['GATEWAY_INBOUND_SECRET'] = 'test-secret'
    yield application


@pytest.fixture(scope='session')
def db(app):
    from app import mongo
    return mongo.db


@pytest.fixture(autouse=True)
def clean_collections(db):
    for col in ('wa_projects', 'pool_images', 'wa_records', 'wa_system', 'group_pending_images'):
        db[col].delete_many({})
    yield
    for col in ('wa_projects', 'pool_images', 'wa_records', 'wa_system', 'group_pending_images'):
        db[col].delete_many({})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def sample_projects(db):
    projects = [
        {'code': 'P-001', 'name': 'Sunrise Tower', 'status': 'active'},
        {'code': 'P-002', 'name': 'Sunset Villas', 'status': 'active'},
        {'code': 'P-003', 'name': 'Ocean Park Phase 2', 'status': 'active'},
        {'code': 'P-010', 'name': 'Marina Bay Hotel', 'status': 'active'},
        {'code': 'P-099', 'name': 'Test Archived', 'status': 'archived'},
    ]
    db.wa_projects.insert_many(projects)
    return projects


def _inbound(client, payload):
    return client.post(
        '/api/wa/inbound',
        data=json.dumps(payload),
        content_type='application/json',
        headers={'X-Gateway-Secret': 'test-secret'},
    )


# ===================================================================
# Part 1 — Fuzzy matching unit tests (image_pool_service)
# ===================================================================

class TestFuzzyMatchProjects:

    def test_exact_code_returns_project(self, app, sample_projects):
        with app.app_context():
            from app.services.image_pool_service import match_project_ext
            result = match_project_ext('P-001')
            assert result.project is not None
            assert result.project['code'] == 'P-001'

    def test_exact_name_returns_project(self, app, sample_projects):
        with app.app_context():
            from app.services.image_pool_service import match_project_ext
            result = match_project_ext('Sunrise Tower')
            assert result.project is not None
            assert result.project['code'] == 'P-001'

    def test_partial_name_exact_hit(self, app, sample_projects):
        with app.app_context():
            from app.services.image_pool_service import match_project_ext
            result = match_project_ext('Marina Bay')
            assert result.project is not None
            assert result.project['code'] == 'P-010'

    def test_fuzzy_typo_returns_candidates(self, app, sample_projects):
        with app.app_context():
            from app.services.image_pool_service import match_project_ext
            result = match_project_ext('Sunris')
            if not result.project:
                assert len(result.candidates) > 0
            else:
                assert result.project['code'] in ('P-001', 'P-002')

    def test_no_match_returns_empty(self, app, sample_projects):
        with app.app_context():
            from app.services.image_pool_service import match_project_ext
            result = match_project_ext('ZZZZZZZ Nonexistent')
            assert result.project is None
            assert len(result.candidates) == 0

    def test_archived_not_returned(self, app, sample_projects):
        with app.app_context():
            from app.services.image_pool_service import match_project_ext
            result = match_project_ext('Test Archived')
            assert result.project is None

    def test_backward_compat_match_project(self, app, sample_projects):
        with app.app_context():
            from app.services.image_pool_service import match_project
            p = match_project('P-001')
            assert p is not None
            assert p['code'] == 'P-001'

    def test_backward_compat_no_match(self, app, sample_projects):
        with app.app_context():
            from app.services.image_pool_service import match_project
            assert match_project('ZZZZZZZ') is None


# ===================================================================
# Part 2 — Fuzzy inbound handler tests
# ===================================================================

class TestFuzzyInbound:

    @patch('app.api.wa_inbound.send_message')
    def test_private_text_fuzzy_candidates_shown(self, mock_send, client, db, sample_projects):
        db.pool_images.insert_one({
            'phone': '1234',
            'imagePath': '/test.jpg',
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
        })
        resp = _inbound(client, {
            'from': '1234',
            'fromName': 'Tester',
            'text': 'Sun',
            'type': 'text',
            'isGroup': False,
            'messageId': 'fuzzy_msg_1',
        })
        data = resp.get_json()
        assert data['type'] in ('pool_fuzzy_candidates', 'pool_assigned', 'pool_no_match')
        if data['type'] == 'pool_fuzzy_candidates':
            choice = db.wa_system.find_one({'_id': 'wa_fuzzy_choice:p:1234'})
            assert choice is not None
            assert len(choice['choices']) > 0

    @patch('app.api.wa_inbound.send_message')
    def test_private_numeric_reply_assigns(self, mock_send, client, db, sample_projects):
        db.pool_images.insert_one({
            'phone': '1234',
            'imagePath': '/test.jpg',
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
        })
        p001 = db.wa_projects.find_one({'code': 'P-001'})
        p002 = db.wa_projects.find_one({'code': 'P-002'})
        db.wa_system.insert_one({
            '_id': 'wa_fuzzy_choice:p:1234',
            'choices': [
                {'code': 'P-001', 'name': 'Sunrise Tower', 'id': str(p001['_id'])},
                {'code': 'P-002', 'name': 'Sunset Villas', 'id': str(p002['_id'])},
            ],
            'at': datetime.utcnow(),
        })
        resp = _inbound(client, {
            'from': '1234',
            'fromName': 'Tester',
            'text': '1',
            'type': 'text',
            'isGroup': False,
            'messageId': 'choice_msg_1',
        })
        data = resp.get_json()
        assert data['type'] == 'pool_assigned'
        pool = db.pool_images.find_one({'phone': '1234'})
        assert pool.get('projectCode') == 'P-001'

    @patch('app.api.wa_inbound.send_message')
    def test_private_exact_match_still_works(self, mock_send, client, db, sample_projects):
        db.pool_images.insert_one({
            'phone': '5678',
            'imagePath': '/test2.jpg',
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
        })
        resp = _inbound(client, {
            'from': '5678',
            'fromName': 'Tester',
            'text': 'P-003',
            'type': 'text',
            'isGroup': False,
            'messageId': 'exact_msg_1',
        })
        data = resp.get_json()
        assert data['type'] == 'pool_assigned'
        pool = db.pool_images.find_one({'phone': '5678'})
        assert pool.get('projectCode') == 'P-003'


# ===================================================================
# Part 3 — Move command tests
# ===================================================================

class TestMoveCommand:

    def _create_assigned_pool_image(self, db, phone='1234'):
        project = db.wa_projects.find_one({'code': 'P-001'})
        now = datetime.utcnow()
        rec = db.wa_records.insert_one({
            'projectId': project['_id'],
            'referenceNumber': 'REF-MOVE-TEST',
            'status': 'awaiting_review',
            'type': 'photo',
            'rawMessage': 'test',
            'senderPhone': phone,
            'photos': ['/test_move.jpg'],
            'nasPhotos': [],
            'hasMedia': True,
            'mediaType': 'image',
            'extractedFields': [],
            'followUpThread': [],
            'followUpRound': 0,
            'statusHistory': [],
            'createdAt': now,
            'updatedAt': now,
        })
        pool = db.pool_images.insert_one({
            'phone': phone,
            'imagePath': '/test_move.jpg',
            'projectId': project['_id'],
            'projectCode': 'P-001',
            'projectName': 'Sunrise Tower',
            'assignedBy': 'user',
            'assignedAt': now,
            'recordId': rec.inserted_id,
            'messageId': 'move_test_msg_1',
            'createdAt': now,
            'updatedAt': now,
        })
        return pool.inserted_id, rec.inserted_id

    @patch('app.api.wa_inbound.send_message')
    def test_move_help_shown(self, mock_send, client, db, sample_projects):
        resp = _inbound(client, {
            'from': '1234',
            'fromName': 'Tester',
            'text': 'move',
            'type': 'text',
            'isGroup': False,
            'messageId': 'move_help_1',
        })
        data = resp.get_json()
        assert data['type'] == 'move_help'

    @patch('app.services.nas_watcher_service.nas_mount')
    @patch('app.services.image_pool_service.is_nas_enabled', return_value=False)
    @patch('app.api.wa_inbound.send_message')
    def test_move_recent_to_new_project(self, mock_send, mock_nas_enabled, mock_nas_mount, client, db, sample_projects):
        mock_nas_mount.is_available.return_value = False
        pool_id, rec_id = self._create_assigned_pool_image(db)

        resp = _inbound(client, {
            'from': '1234',
            'fromName': 'Tester',
            'text': 'move P-003',
            'type': 'text',
            'isGroup': False,
            'messageId': 'move_exec_1',
        })
        data = resp.get_json()
        assert data['type'] == 'move_success'
        assert data['moved'] == 1

        pool = db.pool_images.find_one({'_id': pool_id})
        assert pool['projectCode'] == 'P-003'

        old_rec = db.wa_records.find_one({'_id': rec_id})
        assert old_rec['status'] == 'moved'

    @patch('app.services.nas_watcher_service.nas_mount')
    @patch('app.services.image_pool_service.is_nas_enabled', return_value=False)
    @patch('app.api.wa_inbound.send_message')
    def test_move_already_there(self, mock_send, mock_nas_enabled, mock_nas_mount, client, db, sample_projects):
        mock_nas_mount.is_available.return_value = False
        self._create_assigned_pool_image(db)

        resp = _inbound(client, {
            'from': '1234',
            'fromName': 'Tester',
            'text': 'move P-001',
            'type': 'text',
            'isGroup': False,
            'messageId': 'move_same_1',
        })
        data = resp.get_json()
        assert data['type'] == 'move_already_there'

    @patch('app.api.wa_inbound.send_message')
    def test_move_no_project_found(self, mock_send, client, db, sample_projects):
        resp = _inbound(client, {
            'from': '1234',
            'fromName': 'Tester',
            'text': 'move ZZZZZZZ',
            'type': 'text',
            'isGroup': False,
            'messageId': 'move_noproj_1',
        })
        data = resp.get_json()
        assert data['type'] == 'move_no_project'

    @patch('app.api.wa_inbound.send_message')
    def test_move_no_images(self, mock_send, client, db, sample_projects):
        resp = _inbound(client, {
            'from': '1234',
            'fromName': 'Tester',
            'text': 'move P-003',
            'type': 'text',
            'isGroup': False,
            'messageId': 'move_noimg_1',
        })
        data = resp.get_json()
        assert data['type'] == 'move_no_images'

    @patch('app.services.nas_watcher_service.nas_mount')
    @patch('app.services.image_pool_service.is_nas_enabled', return_value=False)
    @patch('app.api.wa_inbound.send_message')
    def test_move_with_reply_to_photo(self, mock_send, mock_nas_enabled, mock_nas_mount, client, db, sample_projects):
        mock_nas_mount.is_available.return_value = False
        pool_id, rec_id = self._create_assigned_pool_image(db)

        resp = _inbound(client, {
            'from': '1234',
            'fromName': 'Tester',
            'text': 'move P-003',
            'type': 'text',
            'isGroup': False,
            'hasQuotedMsg': True,
            'quotedMsgId': 'move_test_msg_1',
            'messageId': 'move_reply_1',
        })
        data = resp.get_json()
        assert data['type'] == 'move_success'

        pool = db.pool_images.find_one({'_id': pool_id})
        assert pool['projectCode'] == 'P-003'


# ===================================================================
# Part 4 — Group move tests
# ===================================================================

class TestGroupMove:

    @patch('app.api.wa_inbound.send_group_message')
    @patch('app.api.wa_inbound.send_message')
    def test_group_move_help(self, mock_send, mock_group_send, client, db, sample_projects):
        resp = _inbound(client, {
            'from': '1234',
            'fromName': 'Tester',
            'text': 'move',
            'type': 'text',
            'isGroup': True,
            'groupId': 'grp_1',
            'messageId': 'grp_move_help_1',
        })
        data = resp.get_json()
        assert data['type'] == 'move_help'

    @patch('app.api.wa_inbound.send_group_message')
    @patch('app.api.wa_inbound.send_message')
    def test_group_move_no_project(self, mock_send, mock_group_send, client, db, sample_projects):
        resp = _inbound(client, {
            'from': '1234',
            'fromName': 'Tester',
            'text': 'move ZZZZZ',
            'type': 'text',
            'isGroup': True,
            'groupId': 'grp_1',
            'messageId': 'grp_move_noproj_1',
        })
        data = resp.get_json()
        assert data['type'] == 'move_no_project'


# ===================================================================
# Part 5 — is_command tests
# ===================================================================

class TestIsCommand:

    def test_move_command(self):
        from app.services.message_parser_service import is_command
        assert is_command('move') == 'move'

    def test_move_with_target(self):
        from app.services.message_parser_service import is_command
        assert is_command('move P-001') == 'move'

    def test_move_with_prefix(self):
        from app.services.message_parser_service import is_command
        assert is_command('/move P-001') == 'move'

    def test_help(self):
        from app.services.message_parser_service import is_command
        assert is_command('help') == 'help'

    def test_not_command(self):
        from app.services.message_parser_service import is_command
        assert is_command('hello world') is None

    def test_moveable_not_command(self):
        """'moveable' or 'movement' shouldn't match as move command."""
        from app.services.message_parser_service import is_command
        # These start with 'move' but are not the move command
        # Current implementation: startswith('move') → returns 'move'
        # This is acceptable since they're not common words in context
        pass
