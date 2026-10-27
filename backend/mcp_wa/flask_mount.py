"""Mount WhatsApp MCP Streamable HTTP (default public path /mcp on this host)."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

MOUNT_PREFIX = os.environ.get('MCP_HTTP_MOUNT_PREFIX', '/mcp').rstrip('/') or '/mcp'


def mount_wa_mcp_http(app) -> None:
    try:
        from a2wsgi import ASGIMiddleware
    except ImportError as exc:
        logger.warning('[MCP] a2wsgi not installed; URL MCP at %s disabled (%s)', MOUNT_PREFIX, exc)
        return

    from mcp_wa.http_asgi import bootstrap_streamable_http_on_loop, build_wa_mcp_asgi
    from werkzeug.middleware.dispatcher import DispatcherMiddleware

    from mcp_wa.wsgi_middleware import McpExactPathMiddleware

    asgi = build_wa_mcp_asgi()
    branch = ASGIMiddleware(asgi)
    bootstrap_streamable_http_on_loop(branch.loop)
    app.wsgi_app = McpExactPathMiddleware(
        DispatcherMiddleware(app.wsgi_app, {MOUNT_PREFIX: branch}),
        mount_prefix=MOUNT_PREFIX,
    )
    logger.info(
        '[MCP] WhatsApp MCP mounted at %s (Streamable HTTP) and %s/sse (SSE; single-worker only)',
        MOUNT_PREFIX,
        MOUNT_PREFIX,
    )
    from mcp_wa.auth_mode import warn_if_user_mode_with_server_creds

    warn_if_user_mode_with_server_creds()
