"""Tests for Loom deterministic classify turns (site numbers, menu 1–9)."""
from unittest.mock import MagicMock, patch

import pytest

from app.services.loomy_wa_classify_turn_service import (
    execute_menu_pick,
    handle_classify_inbound_text,
    preview_classify_turn,
)


class TestPreviewClassifyTurn:
    def test_menu_digit(self):
        with patch(
            'app.services.loomy_wa_pick_store.find_loomy_wa_pick_doc',
            return_value={'options': [{}, {}]},
        ):
            out = preview_classify_turn('2', phone='85290000000')
        assert out['intent'] == 'menu_pick'
        assert out['mustCallTool'] == 'wa_classify_inbound_text'

    def test_site_number(self):
        out = preview_classify_turn('1005', phone='85290000000')
        assert out['intent'] == 'site_classify'

    def test_other(self):
        with patch(
            'app.services.loomy_wa_pick_store.find_loomy_wa_pick_doc',
            return_value=None,
        ):
            out = preview_classify_turn('hello', phone='85290000000')
        assert out['intent'] == 'other'


class TestExecuteMenuPick:
    @patch('app.services.loomy_wa_classify_turn_service._assign_from_pick_choice')
    @patch('app.services.loomy_wa_pick_store.find_loomy_wa_pick_doc')
    @patch('app.mongo')
    def test_assigns_and_clears_pick(self, mock_mongo, mock_find, mock_assign):
        mock_find.return_value = {
            '_id': 'loomy_wa_pick:p:852:batch1',
            'options': [
                {'project_id': 'a', 'label': '1. x'},
                {'project_id': 'b', 'label': '2. y', 'nas_folder_name': '1005', 'nas_parent_bucket': 'S-1000-2000'},
            ],
            'pool_ids': ['img1'],
        }
        mock_assign.return_value = (1, {}, 'OK SUB-1')
        out = execute_menu_pick(phone='852', group_id=None, digit='2')
        assert out['action'] == 'assigned'
        assert out['reply_zh'] == 'OK SUB-1'
        mock_mongo.db.wa_system.delete_one.assert_called_once()


class TestHandleClassifyInboundText:
    @patch('app.services.loomy_wa_pick_store.find_loomy_wa_pick_doc')
    @patch('app.services.loomy_wa_classify_turn_service.execute_menu_pick')
    def test_delegates_menu(self, mock_menu, mock_find):
        mock_find.return_value = {'options': [{}, {}]}
        mock_menu.return_value = {
            'handled': True,
            'action': 'assigned',
            'reply_zh': 'done',
            'intent': 'menu_pick',
        }
        out = handle_classify_inbound_text(phone='852', user_text='2')
        assert out['intent'] == 'menu_pick'
        mock_menu.assert_called_once()

    @patch('app.services.loomy_wa_pick_store.find_loomy_wa_pick_doc', return_value=None)
    @patch(
        'app.services.loomy_wa_smart_classify.try_assign_to_target',
        return_value='T-1000-2002/1005\nS-1000-2000/1005',
    )
    @patch('app.services.loomy_wa_classify_turn_service._open_pool_ids', return_value=['p1'])
    def test_assign_path(self, _pool, _try, _find):
        out = handle_classify_inbound_text(phone='852', user_text='帮我归类到1005', pool_ids=['p1'])
        assert out['handled'] is True
        assert '1005' in out['reply_zh']
