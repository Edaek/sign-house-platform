"""Per-user MCP server configuration for Cursor and other clients."""
import re
from datetime import datetime
from urllib.parse import urlparse

from bson import ObjectId
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app import mongo
from app.models import serialize_doc
from app.services.audit_service import log_action

mcp_bp = Blueprint('mcp', __name__)

VALID_TRANSPORTS = frozenset({'sse', 'http', 'stdio'})
import os as _os

_MCP_MOUNT = _os.environ.get('MCP_HTTP_MOUNT_PREFIX', '/mcp').rstrip('/') or '/mcp'
WA_MCP_HTTP_PATH = _MCP_MOUNT
WA_MCP_SSE_PATH = f'{_MCP_MOUNT}/sse'
_NAME_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


def _user_oid():
    return ObjectId(get_jwt_identity())


def _mask_header_value(value: str) -> str:
    if not value:
        return ''
    s = str(value)
    if len(s) <= 4:
        return '****'
    return f'{s[:2]}****{s[-2:]}'


def _mask_headers(headers: dict | None) -> dict:
    if not headers:
        return {}
    return {k: _mask_header_value(v) for k, v in headers.items() if k}


def _serialize_server(doc, *, mask_secrets: bool = True):
    out = serialize_doc(doc)
    if mask_secrets and out.get('headers'):
        out['headers'] = _mask_headers(doc.get('headers'))
    return out


def _find_owned(server_id: str, user_id: ObjectId):
    try:
        oid = ObjectId(server_id)
    except Exception:
        return None
    return mongo.db.mcp_servers.find_one({'_id': oid, 'userId': user_id})


def _validate_payload(data: dict, *, partial: bool = False) -> tuple[dict | None, str | None]:
    if not isinstance(data, dict):
        return None, 'Invalid JSON body'

    transport = (data.get('transport') or 'sse').strip().lower()
    if transport not in VALID_TRANSPORTS:
        return None, f'transport must be one of: {", ".join(sorted(VALID_TRANSPORTS))}'

    name = (data.get('name') or '').strip()
    if not partial or 'name' in data:
        if not name or not _NAME_RE.match(name):
            return None, 'name must be 1–64 chars (letters, numbers, _ -)'

    url = (data.get('url') or '').strip()
    command = (data.get('command') or '').strip()
    args = data.get('args')
    if args is not None and not isinstance(args, list):
        return None, 'args must be a list of strings'
    args = [str(a) for a in args] if args else []

    headers = data.get('headers')
    if headers is not None and not isinstance(headers, dict):
        return None, 'headers must be an object'
    headers = {str(k).strip(): str(v) for k, v in (headers or {}).items() if str(k).strip()}

    if transport in ('sse', 'http'):
        if not partial or 'url' in data:
            if not url:
                return None, 'url is required for sse/http transport'
            parsed = urlparse(url)
            if parsed.scheme not in ('http', 'https'):
                return None, 'url must start with http:// or https://'
    elif transport == 'stdio':
        if not partial or 'command' in data:
            if not command:
                return None, 'command is required for stdio transport'

    enabled = data.get('enabled', True)
    if not isinstance(enabled, bool):
        enabled = str(enabled).lower() in ('1', 'true', 'yes')

    doc = {
        'name': name,
        'transport': transport,
        'url': url or None,
        'command': command or None,
        'args': args,
        'headers': headers,
        'enabled': enabled,
    }
    return doc, None


def _cursor_server_entry(doc: dict) -> dict:
    transport = doc.get('transport') or 'sse'
    name = doc.get('name') or 'server'
    if transport == 'stdio':
        entry = {'command': doc.get('command') or '', 'args': doc.get('args') or []}
        if doc.get('headers'):
            entry['env'] = {k: v for k, v in doc['headers'].items()}
        return entry
    entry = {'url': doc.get('url') or ''}
    if doc.get('headers'):
        entry['headers'] = dict(doc['headers'])
    if transport == 'sse':
        entry['transport'] = 'sse'
    return entry


@mcp_bp.route('/hosted-wa/status', methods=['GET'])
def wa_mcp_status():
    """Check whether hosted WhatsApp MCP is mounted (not under /api/mcp/wa/* — those paths are MCP ASGI)."""
    from flask import current_app
    from werkzeug.middleware.dispatcher import DispatcherMiddleware

    from mcp_wa.auth_mode import mcp_auth_mode

    wsgi = current_app.wsgi_app
    mounted = isinstance(wsgi, DispatcherMiddleware)
    if not mounted:
        while hasattr(wsgi, 'app'):
            wsgi = wsgi.app
            if isinstance(wsgi, DispatcherMiddleware):
                mounted = True
                break
    try:
        from a2wsgi import ASGIMiddleware  # noqa: F401
        a2wsgi_ok = True
    except ImportError:
        a2wsgi_ok = False
    has_jwt = bool(_os.environ.get('SIGN_HOUSE_JWT', '').strip())
    has_bot = bool(_os.environ.get('MCP_BOT_EMAIL', '').strip()) and bool(
        _os.environ.get('MCP_BOT_PASSWORD', '')
    )
    return jsonify({
        'mounted': mounted,
        'a2wsgiInstalled': a2wsgi_ok,
        'streamableHttpPath': WA_MCP_HTTP_PATH,
        'streamableHttpUrlHint': f'{WA_MCP_HTTP_PATH}/',
        'ssePath': WA_MCP_SSE_PATH,
        'messagePath': f'{_MCP_MOUNT}/messages/',
        'mcpAuthMode': mcp_auth_mode(),
        'serverJwtFallbackConfigured': has_jwt,
        'botLoginFallbackConfigured': has_bot,
        'perUserBearerRequired': mcp_auth_mode() == 'user',
    })


@mcp_bp.route('/servers', methods=['GET'])
@jwt_required()
def list_servers():
    user_id = _user_oid()
    docs = list(mongo.db.mcp_servers.find({'userId': user_id}).sort('name', 1))
    return jsonify([_serialize_server(d) for d in docs])


@mcp_bp.route('/servers', methods=['POST'])
@jwt_required()
def create_server():
    user_id = _user_oid()
    body, err = _validate_payload(request.get_json(silent=True) or {})
    if err:
        return jsonify({'error': err}), 400

    if mongo.db.mcp_servers.find_one({'userId': user_id, 'name': body['name']}):
        return jsonify({'error': 'A server with this name already exists'}), 409

    now = datetime.utcnow()
    doc = {**body, 'userId': user_id, 'createdAt': now, 'updatedAt': now}
    result = mongo.db.mcp_servers.insert_one(doc)
    doc['_id'] = result.inserted_id

    log_action(
        user_id=str(user_id),
        action='mcp_server.create',
        resource_type='mcp_server',
        resource_id=str(result.inserted_id),
        details={'name': body['name'], 'transport': body['transport']},
    )
    return jsonify(_serialize_server(doc)), 201


@mcp_bp.route('/servers/<server_id>', methods=['PUT'])
@jwt_required()
def update_server(server_id):
    user_id = _user_oid()
    existing = _find_owned(server_id, user_id)
    if not existing:
        return jsonify({'error': 'Not found'}), 404

    raw = request.get_json(silent=True) or {}
    merged = {
        'name': raw.get('name', existing.get('name')),
        'transport': raw.get('transport', existing.get('transport', 'sse')),
        'url': raw.get('url', existing.get('url') or ''),
        'command': raw.get('command', existing.get('command') or ''),
        'args': raw.get('args', existing.get('args') or []),
        'headers': raw.get('headers', existing.get('headers') or {}),
        'enabled': raw.get('enabled', existing.get('enabled', True)),
    }
    body, err = _validate_payload(merged, partial=False)
    if err:
        return jsonify({'error': err}), 400

    if body['name'] != existing.get('name'):
        clash = mongo.db.mcp_servers.find_one({
            'userId': user_id,
            'name': body['name'],
            '_id': {'$ne': existing['_id']},
        })
        if clash:
            return jsonify({'error': 'A server with this name already exists'}), 409

    update = {**body, 'updatedAt': datetime.utcnow()}
    mongo.db.mcp_servers.update_one({'_id': existing['_id']}, {'$set': update})
    doc = mongo.db.mcp_servers.find_one({'_id': existing['_id']})

    log_action(
        user_id=str(user_id),
        action='mcp_server.update',
        resource_type='mcp_server',
        resource_id=server_id,
        details={'name': doc.get('name')},
    )
    return jsonify(_serialize_server(doc))


@mcp_bp.route('/servers/<server_id>', methods=['DELETE'])
@jwt_required()
def delete_server(server_id):
    user_id = _user_oid()
    existing = _find_owned(server_id, user_id)
    if not existing:
        return jsonify({'error': 'Not found'}), 404

    mongo.db.mcp_servers.delete_one({'_id': existing['_id']})
    log_action(
        user_id=str(user_id),
        action='mcp_server.delete',
        resource_type='mcp_server',
        resource_id=server_id,
        details={'name': existing.get('name')},
    )
    return jsonify({'ok': True})


@mcp_bp.route('/servers/<server_id>/export', methods=['GET'])
@jwt_required()
def export_server(server_id):
    user_id = _user_oid()
    doc = _find_owned(server_id, user_id)
    if not doc:
        return jsonify({'error': 'Not found'}), 404

    key = doc.get('name') or 'server'
    entry = _cursor_server_entry(doc)
    entry_only = {key: entry}
    snippet = {'mcpServers': entry_only}
    dumps = __import__('json').dumps
    return jsonify({
        'name': key,
        'entry': entry,
        'snippet': snippet,
        'json': dumps(entry_only, indent=2, ensure_ascii=False),
        'jsonFull': dumps(snippet, indent=2, ensure_ascii=False),
        'enabled': doc.get('enabled', True),
    })
