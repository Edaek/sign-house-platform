"""Wakka WhatsApp REST API client."""
import logging
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

def send_message(to, text, quoted_msg_id=None):
    body = {'to': normalize_phone(to), 'message': text}
    if quoted_msg_id:
        body['quotedMessageId'] = quoted_msg_id
    return _wakka_request('/api/v1/messages/send', 'POST', body)

def send_media(to, media_url, caption=None, filename=None):
    body = {'to': normalize_phone(to), 'mediaUrl': media_url}
    if caption: body['caption'] = caption
    if filename: body['filename'] = filename
    return _wakka_request('/api/v1/messages/send-media', 'POST', body)

def send_group_message(group_id, text, media_data_uri=None, quoted_msg_id=None):
    body = {'message': text}
    if media_data_uri:
        body['mediaUrl'] = media_data_uri
    if quoted_msg_id:
        body['quotedMessageId'] = quoted_msg_id
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
