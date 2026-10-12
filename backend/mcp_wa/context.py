"""Per-request JWT for HTTP MCP (stdio still uses SIGN_HOUSE_JWT env)."""
from __future__ import annotations

from contextvars import ContextVar

_request_jwt: ContextVar[str | None] = ContextVar('sign_house_mcp_jwt', default=None)


def set_request_jwt(token: str | None) -> None:
    _request_jwt.set(token)


def get_request_jwt() -> str | None:
    return _request_jwt.get()


def clear_request_jwt() -> None:
    _request_jwt.set(None)
