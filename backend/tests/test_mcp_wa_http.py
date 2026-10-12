"""Hosted WhatsApp MCP HTTP mount smoke tests."""
from __future__ import annotations

import json

import pytest
from werkzeug.test import Client


@pytest.fixture
def app():
    from app import create_app

    return create_app()


def _initialize_body():
    return {
        'jsonrpc': '2.0',
        'method': 'initialize',
        'params': {
            'protocolVersion': '2024-11-05',
            'capabilities': {},
            'clientInfo': {'name': 'test', 'version': '1'},
        },
        'id': 1,
    }


def test_streamable_mcp_initialize(app):
    client = Client(app)
    resp = client.post(
        '/api/mcp/wa/mcp',
        data=json.dumps(_initialize_body()),
        content_type='application/json',
        headers={
            'Authorization': 'Bearer test-token',
            'Accept': 'application/json, text/event-stream',
        },
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = json.loads(resp.get_data(as_text=True))
    assert data.get('jsonrpc') == '2.0'
    assert 'result' in data
