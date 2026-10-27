"""MCP WSGI path normalization."""
from __future__ import annotations

import json

import pytest
from werkzeug.test import Client


@pytest.fixture
def app():
    from app import create_app

    return create_app()


def test_post_mcp_without_trailing_slash_no_redirect(app):
    """POST /mcp should not 307 (Authorization would be dropped on follow)."""
    client = Client(app)
    body = {
        'jsonrpc': '2.0',
        'method': 'initialize',
        'params': {
            'protocolVersion': '2024-11-05',
            'capabilities': {},
            'clientInfo': {'name': 'test', 'version': '1'},
        },
        'id': 1,
    }
    resp = client.post(
        '/mcp',
        data=json.dumps(body),
        content_type='application/json',
        headers={
            'Authorization': 'Bearer test-token',
            'Accept': 'application/json, text/event-stream',
        },
    )
    assert resp.status_code != 307, resp.headers.get('Location')
    if resp.status_code == 404:
        pytest.skip('a2wsgi not installed — MCP HTTP mount disabled in this env')
    assert resp.status_code == 200, resp.get_data(as_text=True)
