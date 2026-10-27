"""WA classify mode: legacy auto-bot vs WhatsApp Loomy agent."""
import unittest

from app.services.wa_classify_mode import (
    MODE_AGENT,
    classify_mode,
    mattermost_pool_notify_enabled,
    wa_loomy_agent_enabled,
    worker_auto_classify_enabled,
)


class WaClassifyModeTests(unittest.TestCase):
    def test_default_is_auto(self):
        cfg = {'WA_INBOUND_CLASSIFY_MODE': 'auto'}
        self.assertTrue(worker_auto_classify_enabled(cfg))
        self.assertFalse(wa_loomy_agent_enabled(cfg))

    def test_agent_disables_legacy_bot(self):
        cfg = {'WA_INBOUND_CLASSIFY_MODE': MODE_AGENT}
        self.assertFalse(worker_auto_classify_enabled(cfg))
        self.assertTrue(wa_loomy_agent_enabled(cfg))

    def test_loomy_alias_is_agent(self):
        cfg = {'WA_INBOUND_CLASSIFY_MODE': 'loomy'}
        self.assertEqual(classify_mode(cfg), MODE_AGENT)

    def test_mattermost_notify_opt_in(self):
        cfg = {
            'WA_INBOUND_CLASSIFY_MODE': 'agent',
            'MATTERMOST_POOL_WEBHOOK_URL': 'https://mm/hooks/x',
        }
        self.assertFalse(mattermost_pool_notify_enabled(cfg))
        cfg['LOOMY_MATTERMOST_NOTIFY'] = 'true'
        self.assertTrue(mattermost_pool_notify_enabled(cfg))


if __name__ == '__main__':
    unittest.main()
