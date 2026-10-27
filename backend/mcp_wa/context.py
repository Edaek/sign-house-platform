"""Per-request JWT for HTTP MCP (stdio still uses SIGN_HOUSE_JWT env)."""
from __future__ import annotations

import threading
from contextvars import ContextVar

_request_jwt: ContextVar[str | None] = ContextVar('sign_house_mcp_jwt', default=None)
_thread_jwt = threading.local()


def set_request_jwt(token: str | None) -> None:
    _request_jwt.set(token)
    _thread_jwt.value = token


def get_request_jwt() -> str | None:
    ctx = _request_jwt.get()
    if ctx:
        return ctx
    return getattr(_thread_jwt, 'value', None)


def clear_request_jwt() -> None:
    _request_jwt.set(None)
    _thread_jwt.value = None
