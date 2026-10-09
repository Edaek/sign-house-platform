"""Wakka WhatsApp REST API client."""
import json
import logging
import re
import time
import requests
from flask import current_app

logger = logging.getLogger(__name__)

def _wakka_request(path, method='GET', json_data=None):
    """Make authenticated request to Wakka API."""
    url = current_app.config['WAKKA_API_URL']
    key = current_app.config['WAKKA_API_KEY']
    if not url or not key:
        raise RuntimeError('Wakka API not configured')
    headers = {'Content-Type': 'application/json', 'x-api-key': key}
    resp = requests.request(method, f'{url}{path}', headers=headers, json=json_data, timeout=15)
    if not resp.ok:
        data = resp.json() if resp.headers.get('content-type','').startswith('application/json') else {}
        msg = data.get('error', f'Wakka API error {resp.status_code}')
        raise RuntimeError(f'[Wakka] {msg} ({resp.status_code})')
    return resp.json()

def normalize_phone(phone):
    if '@' in phone:
        return phone
    digits = ''.join(c for c in phone if c.isdigit())
    return f'{digits}@c.us'


def normalize_recipient(to):
    """Preserve @lid JIDs; digits-only values become @c.us."""
    if not to:
        return to
    s = str(to).strip()
    if '@' in s:
        return s
    return normalize_phone(s)


def quote_ids_for_send(quoted_msg_id):
    """Wakka/Green-style APIs expect stanza id; full serialized id is fallback."""
    if not quoted_msg_id:
        return []
    raw = str(quoted_msg_id).strip()
    if not raw:
        return []
    parts = raw.split('_')
    stanza = parts[-1] if len(parts) >= 3 else None
    out = []
    if stanza and stanza != raw:
        out.append(stanza)
    if raw not in out:
        out.append(raw)
    return out


def chat_jid_from_message_id(message_id):
    if not message_id:
        return None
    m = re.search(r'_(\d+@(?:lid|c\.us))_', str(message_id), flags=re.I)
    return m.group(1) if m else None


def wakka_private_recipient(phone):
    """Wakka /messages/send only accepts @c.us (sending to @lid returns 500)."""
    if not phone:
        return normalize_phone('')
    s = str(phone).strip()
    if s.endswith('@c.us'):
        return s
    if s.endswith('@lid'):
        digits = re.sub(r'\D', '', s.split('@')[0])
        return f'{digits}@c.us' if digits else normalize_phone(s)
    digits = re.sub(r'\D', '', s)
    return f'{digits}@c.us' if digits else normalize_phone(s)


def _quote_body_fields(quoted_msg_id, quoted_payload=None):
    fields = {}
    if quoted_payload is not None:
        if isinstance(quoted_payload, str):
            fields['quotedMsgPayload'] = quoted_payload
        else:
            fields['quotedMsgPayload'] = json.dumps(
                quoted_payload, ensure_ascii=False, default=str,
            )
    if not quoted_msg_id:
        return fields
    raw = str(quoted_msg_id).strip()
    parts = raw.split('_')
    stanza = parts[-1] if len(parts) >= 3 else raw
    fields['quotedMsg'] = raw
    # Wakka/WPP: full serialized id; Green-style APIs often use stanza — send both.
    fields['quotedMessageId'] = raw
    fields['quotedStanzaId'] = stanza
    return fields


def send_message(to, text, quoted_msg_id=None, quoted_payload=None):
    recipient = wakka_private_recipient(to)
    body = {'to': recipient, 'message': text}
    body.update(_quote_body_fields(quoted_msg_id, quoted_payload))
    return _wakka_request('/api/v1/messages/send', 'POST', body)

def send_media(to, media_url, caption=None, filename=None):
    body = {'to': wakka_private_recipient(to), 'mediaUrl': media_url}
    if caption: body['caption'] = caption
    if filename: body['filename'] = filename
    return _wakka_request('/api/v1/messages/send-media', 'POST', body)

def send_group_message(
    group_id,
    text,
    media_data_uri=None,
    quoted_msg_id=None,
    quoted_payload=None,
):
    body = {'message': text}
    if media_data_uri:
        body['mediaUrl'] = media_data_uri
    body.update(_quote_body_fields(quoted_msg_id, quoted_payload))
    return _wakka_request(f'/api/v1/groups/{requests.utils.quote(group_id, safe="")}/send', 'POST', body)

def get_token_usage():
    return _wakka_request('/api/v1/account/usage')

def download_media(message_id, max_retries=3):
    url = current_app.config['WAKKA_API_URL']
    key = current_app.config['WAKKA_API_KEY']
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(f'{url}/api/v1/messages/{requests.utils.quote(message_id, safe="")}/media',
                              headers={'x-api-key': key}, timeout=15)
            if resp.status_code == 404:
                return None
            if not resp.ok:
                if resp.status_code >= 500 and attempt < max_retries:
                    time.sleep(attempt * 2)
                    continue
                return None
            return resp.content
        except requests.Timeout:
            logger.error('[Wakka] Media download timed out')
            if attempt < max_retries:
                time.sleep(attempt * 2)
                continue
            return None
        except Exception as e:
            logger.error(f'[Wakka] Media download error: {e}')
            if attempt < max_retries:
                time.sleep(attempt * 2)
                continue
            return None
    return None

def get_gateway_status():
    try:
        session = _wakka_request('/api/v1/session/status/key')
        try:
            usage = get_token_usage()
        except Exception:
            usage = None
        result = dict(session)
        if usage:
            result['tokenBalance'] = usage.get('tokenBalance')
            result['plan'] = usage.get('plan')
        return result
    except Exception:
        return {'connected': False, 'status': 'unreachable'}
