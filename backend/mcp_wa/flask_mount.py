"""Mount WhatsApp MCP Streamable HTTP under /api/mcp/wa on the Flask app."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

MOUNT_PREFIX = '/api/mcp/wa'


def mount_wa_mcp_http(app) -> None:
    try:
        from a2wsgi import ASGIMiddleware
    except ImportError as exc:
        logger.warning('[MCP] a2wsgi not installed; URL MCP at %s disabled (%s)', MOUNT_PREFIX, exc)
        return

    from mcp_wa.http_asgi import build_wa_mcp_asgi
    from werkzeug.middleware.dispatcher import DispatcherMiddleware

    asgi = build_wa_mcp_asgi()
    branch = ASGIMiddleware(asgi)
    from mcp_wa.http_asgi import bootstrap_streamable_http_on_loop

    bootstrap_streamable_http_on_loop(branch.loop)
    app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {MOUNT_PREFIX: branch})
    logger.info(
        '[MCP] WhatsApp MCP mounted at %s/mcp (Streamable HTTP) and %s/sse (SSE; single-worker only)',
        MOUNT_PREFIX,
        MOUNT_PREFIX,
    )
