"""WhatsApp media-pool classify: legacy auto-bot vs in-chat Loomy agent."""
from __future__ import annotations

import os
from typing import Any, Mapping, Optional

MODE_AUTO = 'auto'
MODE_AGENT = 'agent'
# Back-compat alias — now means WhatsApp agent, not Mattermost-only
MODE_LOOMY = 'loomy'


def _cfg_val(config: Optional[Mapping[str, Any]], key: str, env_key: str, default: str) -> str:
    if config and key in config:
        raw = config.get(key)
    else:
        raw = os.environ.get(env_key, default)
    return str(raw or default).strip().lower()


def classify_mode(config: Optional[Mapping[str, Any]] = None) -> str:
    m = _cfg_val(config, 'WA_INBOUND_CLASSIFY_MODE', 'WA_INBOUND_CLASSIFY_MODE', MODE_AUTO)
    if m in (MODE_AGENT, MODE_LOOMY):
        return MODE_AGENT
    return MODE_AUTO


def wa_loomy_agent_enabled(config: Optional[Mapping[str, Any]] = None) -> bool:
    return classify_mode(config) == MODE_AGENT


def worker_auto_classify_enabled(config: Optional[Mapping[str, Any]] = None) -> bool:
    """False when Loomy agent handles pool classify on WhatsApp."""
    return not wa_loomy_agent_enabled(config)


def pool_receipt_prompts_enabled(config: Optional[Mapping[str, Any]] = None) -> bool:
    return worker_auto_classify_enabled(config)


def mattermost_pool_notify_enabled(config: Optional[Mapping[str, Any]] = None) -> bool:
    """Optional MM webhook — off by default; agent runs in WhatsApp."""
    if not wa_loomy_agent_enabled(config):
        return False
    if _cfg_val(config, 'LOOMY_MATTERMOST_NOTIFY', 'LOOMY_MATTERMOST_NOTIFY', '') in (
        '1', 'true', 'yes', 'on',
    ):
        return bool(_cfg_val(config, 'MATTERMOST_POOL_WEBHOOK_URL', 'MATTERMOST_POOL_WEBHOOK_URL', ''))
    return False


def loomy_wa_pool_ack(config: Optional[Mapping[str, Any]] = None) -> str:
    """Empty = no instant ack; agent reply replaces it."""
    return _cfg_val(config, 'LOOMY_WA_POOL_ACK', 'LOOMY_WA_POOL_ACK', '')
