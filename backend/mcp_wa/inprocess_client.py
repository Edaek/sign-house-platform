"""Sign House API client for WhatsApp Loomy agent (in-process tools + optional HTTP)."""
from __future__ import annotations

import logging
import os

from mcp_wa.client import JWT_ENV, SignHouseApiError, SignHouseClient, internal_api_base_url
from mcp_wa.wa_tool_inprocess import inprocess_tools_enabled

logger = logging.getLogger(__name__)

JWT_MISSING_MSG = (
    'Loomy 需要 API 鑑權才能使用此功能。請配置 SIGN_HOUSE_JWT，或 MCP_BOT_EMAIL + MCP_BOT_PASSWORD，'
    '或保持 LOOMY_WA_INPROCESS_TOOLS=true（預設）以使用進程內歸類工具。'
)


def wa_agent_jwt_configured() -> bool:
    raw = (os.environ.get(JWT_ENV) or os.environ.get('SIGN_HOUSE_JWT') or '').strip()
    if raw.lower().startswith('bearer '):
        raw = raw[7:].strip()
    return bool(raw)


def _bot_credentials_configured() -> bool:
    return bool(os.environ.get('MCP_BOT_EMAIL', '').strip() and os.environ.get('MCP_BOT_PASSWORD', ''))


def wa_loomy_tools_ready() -> bool:
    """WhatsApp Loomy can run without manual JWT when in-process classify tools are enabled."""
    if inprocess_tools_enabled():
        return True
    if wa_agent_jwt_configured():
        return True
    if _bot_credentials_configured():
        return True
    return False


def get_inprocess_client() -> SignHouseClient:
    """HTTP client for tools that still need /api (optional JWT or MCP_BOT auto-login)."""
    raw = (os.environ.get(JWT_ENV) or os.environ.get('SIGN_HOUSE_JWT') or '').strip()
    if raw.lower().startswith('bearer '):
        raw = raw[7:].strip()
    if raw:
        return SignHouseClient(jwt=raw, api_base=internal_api_base_url())
    return SignHouseClient(api_base=internal_api_base_url())


def try_get_inprocess_client() -> SignHouseClient | None:
    try:
        return get_inprocess_client()
    except SignHouseApiError:
        return None


def log_jwt_guard_on_startup() -> None:
    from app.services.wa_classify_mode import wa_loomy_agent_enabled

    if not wa_loomy_agent_enabled():
        return
    if inprocess_tools_enabled():
        logger.info(
            '[LoomyWA] in-process MCP tools enabled (classify/NAS/projects without SIGN_HOUSE_JWT)',
        )
    elif wa_agent_jwt_configured():
        logger.info('[LoomyWA] SIGN_HOUSE_JWT configured for MCP tool loop')
    elif _bot_credentials_configured():
        logger.info('[LoomyWA] MCP_BOT_* configured for MCP HTTP tools')
    else:
        logger.error(
            '[LoomyWA] WA_INBOUND_CLASSIFY_MODE=agent but no auth and LOOMY_WA_INPROCESS_TOOLS=false',
        )
