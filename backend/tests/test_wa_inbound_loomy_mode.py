"""Agent mode inbound bridge: Loomy scheduling without legacy bot."""
import unittest

from mcp_wa.loomy_wa_inbound_bridge import (
    loomy_agent_extra_from_data,
    loomy_followup_record_summary,
)
from mcp_wa.wa_tool_registry import is_tool_allowed


class LoomyInboundBridgeTests(unittest.TestCase):
    def test_followup_summary_includes_open_question(self):
        rec = {
            '_id': '507f1f77bcf86cd799439011',
            'referenceNumber': 'WA-99',
            'status': 'followup',
            'followUpThread': [
                {'question': '类型？', 'answer': '安装'},
                {'question': '楼层？'},
            ],
        }
        summary = loomy_followup_record_summary(rec)
        self.assertEqual(summary['record_id'], '507f1f77bcf86cd799439011')
        self.assertEqual(summary['open_followup_question'], '楼层？')

    def test_agent_extra_private_help_context(self):
        extra = loomy_agent_extra_from_data({'hasQuotedMsg': False}, group_id=None)
        self.assertEqual(extra['inbound_type'], 'private')
        self.assertIn('move_inbound_data', extra)

    def test_followup_record_in_agent_extra(self):
        rec = {'_id': 'x', 'referenceNumber': 'WA-1', 'status': 'followup', 'followUpThread': []}
        extra = loomy_agent_extra_from_data({}, active_record=rec, group_id=None)
        self.assertIn('active_wa_record', extra)
        self.assertEqual(extra['active_wa_record']['reference_number'], 'WA-1')

    def test_update_record_field_allowed_on_worker_channel(self):
        self.assertTrue(is_tool_allowed('wa_update_record_field'))
        self.assertTrue(is_tool_allowed('wa_get_record'))


if __name__ == '__main__':
    unittest.main()
