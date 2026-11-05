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

# Primary demo/prod knob (overrides WA_INBOUND_CLASSIFY_MODE when set): loom | agent | loomy
ENV_WA_BRAIN = 'SIGNHOUSE_WA_BRAIN'


def _cfg_val(config: Optional[Mapping[str, Any]], key: str, env_key: str, default: str) -> str:
    if config and key in config:
        raw = config.get(key)
    else:
        raw = os.environ.get(env_key, default)
    return str(raw or default).strip().lower()


def _normalize_mode_token(m: str) -> Optional[str]:
    m = (m or '').strip().lower()
    if m in ('auto', 'legacy', ''):
        return MODE_LOOM
    if m == MODE_LOOM:
        return MODE_LOOM
    if m in (MODE_AGENT, MODE_LOOMY):
        return MODE_AGENT
    return None


def _raw_classify_mode(config: Optional[Mapping[str, Any]] = None) -> str:
    if config is not None:
        brain_raw = config.get(ENV_WA_BRAIN)
        if brain_raw is None:
            brain_raw = config.get('signhouse_wa_brain')
        brain = str(brain_raw or '').strip().lower()
        if brain:
            normalized = _normalize_mode_token(brain)
            if normalized:
                legacy_raw = config.get('WA_INBOUND_CLASSIFY_MODE')
                if legacy_raw:
                    leg = _normalize_mode_token(str(legacy_raw))
                    if leg and leg != normalized:
                        logger.warning(
                            '%s=%r overrides WA_INBOUND_CLASSIFY_MODE=%r → effective %r',
                            ENV_WA_BRAIN,
                            brain,
                            legacy_raw,
                            normalized,
                        )
                return normalized
            logger.warning('Unknown %s=%r — falling back to WA_INBOUND_CLASSIFY_MODE', ENV_WA_BRAIN, brain)
        m = str(config.get('WA_INBOUND_CLASSIFY_MODE') or MODE_LOOM).strip().lower()
        normalized = _normalize_mode_token(m)
        if normalized:
            return normalized
        logger.warning('Unknown WA_INBOUND_CLASSIFY_MODE=%r — defaulting to loom', m)
        return MODE_LOOM

    brain = _cfg_val(None, ENV_WA_BRAIN, ENV_WA_BRAIN, '')
    if brain:
        normalized = _normalize_mode_token(brain)
        if normalized:
            legacy = (os.environ.get('WA_INBOUND_CLASSIFY_MODE') or '').strip().lower()
            if legacy:
                leg = _normalize_mode_token(legacy)
                if leg and leg != normalized:
                    logger.warning(
                        '%s=%r overrides WA_INBOUND_CLASSIFY_MODE=%r → effective %r',
                        ENV_WA_BRAIN,
                        brain,
                        legacy,
                        normalized,
                    )
            return normalized
        logger.warning('Unknown %s=%r — falling back to WA_INBOUND_CLASSIFY_MODE', ENV_WA_BRAIN, brain)

    m = _cfg_val(None, 'WA_INBOUND_CLASSIFY_MODE', 'WA_INBOUND_CLASSIFY_MODE', MODE_LOOM)
    normalized = _normalize_mode_token(m)
    if normalized:
        if m in ('auto', 'legacy'):
            logger.warning(
                'WA_INBOUND_CLASSIFY_MODE=%r is deprecated; use %s=loom or agent',
                m,
                ENV_WA_BRAIN,
            )
        return normalized
    logger.warning('Unknown WA_INBOUND_CLASSIFY_MODE=%r — defaulting to loom', m)
    return MODE_LOOM


def classify_mode(config: Optional[Mapping[str, Any]] = None) -> str:
    return _raw_classify_mode(config)


def log_wa_brain_on_startup() -> None:
    mode = classify_mode()
    brain = (os.environ.get(ENV_WA_BRAIN) or '').strip()
    legacy = (os.environ.get('WA_INBOUND_CLASSIFY_MODE') or '').strip()
    if mode == MODE_LOOM:
        hint = 'Loom Turn + /mcp/ (Sign House 不跑本机 Ollama 回复)'
    else:
        hint = 'Sign House Ollama Loomy agent (本机 MCP 工具环)'
    logger.info(
        '[WA] brain=%s (%s) SIGNHOUSE_WA_BRAIN=%r WA_INBOUND_CLASSIFY_MODE=%r — %s',
        mode,
        'loom' if mode == MODE_LOOM else 'agent',
        brain or '(unset)',
        legacy or '(unset)',
        hint,
    )


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
