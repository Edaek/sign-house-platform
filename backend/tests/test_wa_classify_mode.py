"""WA classify mode: loom runtime vs local Loomy agent."""
import unittest

from app.services.wa_classify_mode import (
    MODE_AGENT,
    MODE_LOOM,
    classify_mode,
    mattermost_pool_notify_enabled,
    signhouse_whatsapp_outbound_allowed,
    wa_inbound_loomy_dispatch_enabled,
    wa_loom_runtime_brain_enabled,
    wa_loomy_agent_enabled,
    worker_auto_classify_enabled,
)


class WaClassifyModeTests(unittest.TestCase):
    def test_auto_env_maps_to_loom(self):
        cfg = {'WA_INBOUND_CLASSIFY_MODE': 'auto'}
        self.assertEqual(classify_mode(cfg), MODE_LOOM)
        self.assertFalse(worker_auto_classify_enabled(cfg))
        self.assertTrue(wa_inbound_loomy_dispatch_enabled(cfg))

    def test_agent_disables_legacy_bot(self):
        cfg = {'WA_INBOUND_CLASSIFY_MODE': MODE_AGENT}
        self.assertFalse(worker_auto_classify_enabled(cfg))
        self.assertTrue(wa_loomy_agent_enabled(cfg))

    def test_loomy_alias_is_agent(self):
        cfg = {'WA_INBOUND_CLASSIFY_MODE': 'loomy'}
        self.assertEqual(classify_mode(cfg), MODE_AGENT)

    def test_loom_mode_delegates_without_local_agent(self):
        cfg = {'WA_INBOUND_CLASSIFY_MODE': MODE_LOOM}
        self.assertEqual(classify_mode(cfg), MODE_LOOM)
        self.assertFalse(wa_loomy_agent_enabled(cfg))
        self.assertTrue(wa_loom_runtime_brain_enabled(cfg))
        self.assertTrue(wa_inbound_loomy_dispatch_enabled(cfg))
        self.assertFalse(worker_auto_classify_enabled(cfg))
        self.assertFalse(signhouse_whatsapp_outbound_allowed(cfg))

    def test_loom_signhouse_send_opt_in(self):
        cfg = {
            'SIGNHOUSE_WA_BRAIN': 'loom',
            'LOOMY_WA_SIGNHOUSE_SEND': 'true',
        }
        self.assertTrue(signhouse_whatsapp_outbound_allowed(cfg))

    def test_signhouse_wa_brain_overrides_legacy(self):
        cfg = {
            'SIGNHOUSE_WA_BRAIN': 'loom',
            'WA_INBOUND_CLASSIFY_MODE': 'agent',
        }
        self.assertEqual(classify_mode(cfg), MODE_LOOM)
        self.assertFalse(wa_loomy_agent_enabled(cfg))

    def test_signhouse_wa_brain_agent(self):
        cfg = {'SIGNHOUSE_WA_BRAIN': 'agent'}
        self.assertEqual(classify_mode(cfg), MODE_AGENT)
        self.assertTrue(wa_loomy_agent_enabled(cfg))

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
