"""WhatsApp inbound: Loom runtime or local Loomy agent (legacy auto-bot removed)."""
from __future__ import annotations

import logging
import os
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

MODE_AGENT = 'agent'
# Loom runtime / Platform HTTP as sole brain — no local Ollama MCP agent
MODE_LOOM = 'loom'
# Back-compat alias — local in-chat Ollama agent (Sign House)
MODE_LOOMY = 'loomy'


def _cfg_val(config: Optional[Mapping[str, Any]], key: str, env_key: str, default: str) -> str:
    if config and key in config:
        raw = config.get(key)
    else:
        raw = os.environ.get(env_key, default)
    return str(raw or default).strip().lower()


def classify_mode(config: Optional[Mapping[str, Any]] = None) -> str:
    m = _cfg_val(config, 'WA_INBOUND_CLASSIFY_MODE', 'WA_INBOUND_CLASSIFY_MODE', MODE_LOOM)
    if m in ('auto', 'legacy', ''):
        logger.warning(
            'WA_INBOUND_CLASSIFY_MODE=%r is deprecated; use loom or agent',
            m or 'auto',
        )
        return MODE_LOOM
    if m == MODE_LOOM:
        return MODE_LOOM
    if m in (MODE_AGENT, MODE_LOOMY):
        return MODE_AGENT
    logger.warning('Unknown WA_INBOUND_CLASSIFY_MODE=%r — defaulting to loom', m)
    return MODE_LOOM


def wa_loomy_agent_enabled(config: Optional[Mapping[str, Any]] = None) -> bool:
    """Local Sign House Ollama + in-process MCP tools."""
    return classify_mode(config) == MODE_AGENT


def wa_loom_runtime_brain_enabled(config: Optional[Mapping[str, Any]] = None) -> bool:
    """Loom runtime owns replies (per-user Bearer → /mcp); Sign House intake only."""
    return classify_mode(config) == MODE_LOOM


def wa_inbound_loomy_dispatch_enabled(config: Optional[Mapping[str, Any]] = None) -> bool:
    """Inbound schedules Loomy worker (local agent or Loom Platform brain)."""
    return wa_loomy_agent_enabled(config) or wa_loom_runtime_brain_enabled(config)


def worker_auto_classify_enabled(config: Optional[Mapping[str, Any]] = None) -> bool:
    """Legacy auto-bot removed — always False."""
    return False


def pool_receipt_prompts_enabled(config: Optional[Mapping[str, Any]] = None) -> bool:
    return False


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
