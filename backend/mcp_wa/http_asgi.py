"""ASGI stack for URL-based MCP (SSE at /sse, messages at /messages/)."""
from __future__ import annotations

from mcp_wa.context import set_request_jwt
from mcp_wa.server import mcp

_asgi_app = None


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
        await self.app(scope, receive, send)


def build_wa_mcp_asgi():
    global _asgi_app
    if _asgi_app is not None:
        return _asgi_app
    starlette = mcp.sse_app(mount_path='/')
    _asgi_app = _JwtContextMiddleware(starlette)
    return _asgi_app
