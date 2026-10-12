"""HTTP client for Sign House WA REST API (JWT from environment)."""
from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urljoin

import requests

from mcp_wa.context import get_request_jwt

JWT_ENV = 'SIGN_HOUSE_JWT'
INTERNAL_API_URL_ENV = 'SIGN_HOUSE_INTERNAL_API_URL'
API_URL_ENV = 'SIGN_HOUSE_API_URL'
TIMEOUT_ENV = 'SIGN_HOUSE_HTTP_TIMEOUT'
DEFAULT_API_URL = 'http://127.0.0.1:5000/api'
DEFAULT_TIMEOUT = 60.0
LONG_TIMEOUT = 300.0

JWT_EXPIRED_HINT = (
    ' JWT may be expired or missing — log in to Sign House again and update Authorization in Cursor mcp.json.'
)


class SignHouseApiError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _jwt_from_mcp_http_request() -> str | None:
    try:
        from mcp_wa.server import mcp

        ctx = mcp.get_context()
        rc = ctx.request_context
        req = getattr(rc, 'request', None) if rc else None
        if req is not None:
            auth = req.headers.get('authorization') or req.headers.get('Authorization')
            if auth and str(auth).lower().startswith('bearer '):
                return str(auth)[7:].strip()
    except Exception:
        pass
    return None


def _jwt_from_env() -> str:
    from_ctx = get_request_jwt() or _jwt_from_mcp_http_request()
    if from_ctx:
        return from_ctx
    raw = (os.environ.get(JWT_ENV) or os.environ.get('Authorization') or '').strip()
    if raw.lower().startswith('bearer '):
        raw = raw[7:].strip()
    if not raw:
        raise SignHouseApiError(
            f'{JWT_ENV} is not set. Add your login token to the MCP server env (stdio headers in McpPage).'
        )
    return raw


def internal_api_base_url() -> str:
    explicit = (os.environ.get(INTERNAL_API_URL_ENV) or '').strip().rstrip('/')
    if explicit:
        return explicit
    port = (os.environ.get('PORT') or '5000').strip()
    return f'http://127.0.0.1:{port}/api'


def api_base_url() -> str:
    if get_request_jwt():
        return internal_api_base_url()
    base = (os.environ.get(API_URL_ENV) or DEFAULT_API_URL).strip().rstrip('/')
    return base


def site_origin() -> str:
    """Origin without /api suffix (for upload URLs)."""
    base = api_base_url()
    if base.endswith('/api'):
        return base[:-4].rstrip('/')
    return base.rsplit('/api', 1)[0] if '/api' in base else base


def default_timeout() -> float:
    raw = os.environ.get(TIMEOUT_ENV, '').strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return DEFAULT_TIMEOUT


def _format_error(status_code: int, body: Any) -> str:
    if isinstance(body, dict):
        msg = body.get('error') or body.get('message') or body.get('msg')
        if msg:
            text = str(msg)
        else:
            text = json.dumps(body, ensure_ascii=False)
    elif body:
        text = str(body)
    else:
        text = f'HTTP {status_code}'

    if status_code in (401, 403):
        text += JWT_EXPIRED_HINT
    return text


class SignHouseClient:
    def __init__(self, *, timeout: float | None = None, long_timeout: float = LONG_TIMEOUT):
        self._jwt = _jwt_from_env()
        self._base = api_base_url()
        self._timeout = timeout if timeout is not None else default_timeout()
        self._long_timeout = long_timeout

    def _headers(self) -> dict[str, str]:
        return {
            'Authorization': f'Bearer {self._jwt}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

    def _url(self, path: str) -> str:
        path = path if path.startswith('/') else f'/{path}'
        return urljoin(self._base + '/', path.lstrip('/'))

    def call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        clean_params = None
        if params:
            clean_params = {k: v for k, v in params.items() if v is not None and v != ''}

        try:
            resp = requests.request(
                method.upper(),
                self._url(path),
                headers=self._headers(),
                params=clean_params,
                json=json_body,
                timeout=timeout if timeout is not None else self._timeout,
            )
        except requests.RequestException as exc:
            raise SignHouseApiError(f'Request failed: {exc}') from exc

        body: Any = None
        if resp.content:
            ct = resp.headers.get('content-type', '')
            if 'application/json' in ct:
                try:
                    body = resp.json()
                except ValueError:
                    body = resp.text
            else:
                body = resp.text

        if not resp.ok:
            raise SignHouseApiError(
                _format_error(resp.status_code, body),
                status_code=resp.status_code,
                body=body,
            )
        return body

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.call('GET', path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.call('POST', path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Any:
        return self.call('PATCH', path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.call('DELETE', path, **kwargs)

    def long_post(self, path: str, json_body: dict[str, Any] | None = None) -> Any:
        return self.call('POST', path, json_body=json_body, timeout=self._long_timeout)


def json_result(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def uploads_url(relative_path: str) -> str:
    """Turn /uploads/wa-media/foo.jpg into full API URL."""
    rel = relative_path.strip()
    if not rel:
        return ''
    if rel.startswith('http://') or rel.startswith('https://'):
        return rel
    if rel.startswith('/api/'):
        return f'{site_origin()}{rel}'
    if rel.startswith('/uploads/'):
        return f'{site_origin()}/api/wa{rel}'
    if rel.startswith('uploads/'):
        return f'{site_origin()}/api/wa/{rel}'
    return f'{site_origin()}/api/wa/uploads/{rel.lstrip("/")}'
