"""MCP authentication mode: per-user Bearer (Loom/Cursor) vs server fallback."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

MCP_AUTH_MODE_ENV = 'MCP_AUTH_MODE'
JWT_ENV = 'SIGN_HOUSE_JWT'

USER_JWT_REQUIRED_MSG = (
    'Per-user JWT required (MCP_AUTH_MODE=user). Log in to Sign House, copy access_token, '
    'paste in Loom Connections → wa → Connect (or Cursor mcp.json Authorization: Bearer …). '
    'Server SIGN_HOUSE_JWT / MCP_BOT_* are not used in this mode.'
)


def mcp_auth_mode() -> str:
    raw = os.environ.get(MCP_AUTH_MODE_ENV, 'fallback').strip().lower()
    return raw if raw in ('user', 'fallback') else 'fallback'


def is_user_only_mode() -> bool:
    return mcp_auth_mode() == 'user'


def warn_if_user_mode_with_server_creds() -> None:
    if not is_user_only_mode():
        return
    has_jwt = bool(os.environ.get(JWT_ENV, '').strip())
    has_bot = bool(os.environ.get('MCP_BOT_EMAIL', '').strip()) and bool(
        os.environ.get('MCP_BOT_PASSWORD', '')
    )
    if has_jwt or has_bot:
        logger.warning(
            '[MCP] MCP_AUTH_MODE=user — SIGN_HOUSE_JWT and MCP_BOT_* are ignored; '
            'each client must send Authorization: Bearer on MCP HTTP requests.'
        )
