"""ASGI stack for URL-based MCP (Streamable HTTP /mcp + optional SSE /sse)."""
from __future__ import annotations

import asyncio
import logging
import threading

from starlette.applications import Starlette

from mcp_wa.context import set_request_jwt
from mcp_wa.server import mcp

logger = logging.getLogger(__name__)

_asgi_app = None
_bootstrap_lock = threading.Lock()
_bootstrap_started = False


class _JwtContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http':
            await self.app(scope, receive, send)
            return
        token = None
        for name, value in scope.get('headers') or []:
            if name.lower() == b'authorization':
                text = value.decode('latin-1')
                if text.lower().startswith('bearer '):
                    token = text[7:].strip()
                break
        set_request_jwt(token or None)
        try:
            await self.app(scope, receive, send)
        finally:
            from mcp_wa.context import clear_request_jwt

            clear_request_jwt()


def _combined_mcp_starlette() -> Starlette:
    """SSE + stateless Streamable HTTP on one app (no Starlette lifespan — see bootstrap)."""
    streamable = mcp.streamable_http_app()
    sse = mcp.sse_app(mount_path='/')
    routes = list(sse.routes) + list(streamable.routes)
    return Starlette(routes=routes, debug=mcp.settings.debug)


def bootstrap_streamable_http_on_loop(loop: asyncio.AbstractEventLoop) -> None:
    """a2wsgi does not run Starlette lifespan; keep Streamable HTTP session manager alive."""
    global _bootstrap_started
    with _bootstrap_lock:
        if _bootstrap_started:
            return
        mcp.streamable_http_app()
        ready = asyncio.Event()

        async def _hold_manager() -> None:
            async with mcp.session_manager.run():
                ready.set()
                await asyncio.Event().wait()

        asyncio.run_coroutine_threadsafe(_hold_manager(), loop)
        wait = asyncio.run_coroutine_threadsafe(ready.wait(), loop)
        wait.result(timeout=30)
        _bootstrap_started = True
        logger.info('[MCP] Streamable HTTP session manager started on ASGI loop')


def build_wa_mcp_asgi():
    global _asgi_app
    if _asgi_app is not None:
        return _asgi_app
    starlette = _combined_mcp_starlette()
    _asgi_app = _JwtContextMiddleware(starlette)
    return _asgi_app
