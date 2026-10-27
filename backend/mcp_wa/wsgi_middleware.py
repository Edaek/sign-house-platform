"""WSGI helpers for hosted MCP (path + reverse-proxy scheme)."""
from __future__ import annotations


class McpExactPathMiddleware:
    """Rewrite ``/mcp`` → ``/mcp/`` internally (no HTTP 307).

    Clients hitting ``/mcp`` without a trailing slash otherwise get a redirect;
    many stacks emit ``Location: http://…`` and browsers drop ``Authorization``
    on cross-scheme redirect follow.
    """

    def __init__(self, app, *, mount_prefix: str = '/mcp'):
        self.app = app
        self._prefix = (mount_prefix or '/mcp').rstrip('/') or '/mcp'
        self._prefix_slash = f'{self._prefix}/'

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO') or ''
        if path == self._prefix:
            environ['PATH_INFO'] = self._prefix_slash
        return self.app(environ, start_response)
