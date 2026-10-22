"""
Gateway process — connects to Wakka via Socket.IO, downloads media,
and forwards messages to the Flask inbound API.

Run standalone:  python -m gateway.main
"""
import os
import sys
import signal
import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional, List

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / '.env')

from gateway.wakka_client import WakkaClient, WAMessage, TYPE_MAP
from gateway.media_handler import handle_media_message
from gateway.burst_coalesce import MediaBurstCoalescer
from gateway import consumer_lease

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s %(message)s',
)
logger = logging.getLogger('gateway')

WAKKA_API_URL = os.environ.get('WAKKA_API_URL', 'https://wakka.prod.wellplay.io')
WAKKA_API_KEY = os.environ.get('WAKKA_API_KEY', '')
APP_URL = os.environ.get('APP_URL', 'http://localhost:5000')
GATEWAY_SECRET = os.environ.get('GATEWAY_INBOUND_SECRET', 'gateway-shared-secret')
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/signhouse_dev')

MEDIA_DIR = os.environ.get(
    'WA_UPLOADS_FOLDER',
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads', 'wa-media'),
)

MSG_DEDUP_MAX = 500


class LRUSet:
    """Simple LRU set for message deduplication."""
    def __init__(self, max_size: int):
        self._store: OrderedDict[str, None] = OrderedDict()
        self._max = max_size

    def contains(self, key: str) -> bool:
        if key in self._store:
            self._store.move_to_end(key)
            return True
        return False

    def add(self, key: str):
        self._store[key] = None
        if len(self._store) > self._max:
            self._store.popitem(last=False)


recent_ids = LRUSet(MSG_DEDUP_MAX)

_burst_coalescer: Optional[MediaBurstCoalescer] = None

_ALBUM_LIST_KEYS = (
    'albumItems', 'mediaItems', 'attachments', 'messages', 'files', 'items', 'mediaList', 'media',
)


def _album_raw_items(raw: dict) -> list:
    """If Wakka sends multiple media in one payload, return sub-item dicts."""
    if not isinstance(raw, dict):
        return []

    found = []

    def scan(obj):
        if not isinstance(obj, dict):
            return
        for key in _ALBUM_LIST_KEYS:
            items = obj.get(key)
            if isinstance(items, list) and len(items) > 1:
                dict_items = [i for i in items if isinstance(i, dict)]
                if len(dict_items) > 1:
                    found.append(dict_items)
        for nest in ('_data', 'message', 'msg', 'data'):
            nested = obj.get(nest)
            if isinstance(nested, dict):
                scan(nested)

    scan(raw)
    if found:
        return max(found, key=len)
    return []


def _media_parts_from_message(msg: WAMessage) -> list:
    """Build one or more pseudo-messages for media download (single or album)."""
    raw = msg.raw if isinstance(msg.raw, dict) else {}
    items = _album_raw_items(raw)
    if not items:
        return [msg]

    parts = []
    for idx, item in enumerate(items):
        item_id = item.get('id')
        if isinstance(item_id, dict) and '_serialized' in item_id:
            item_id = item_id['_serialized']
        if not item_id:
            item_id = f'{msg.id}#{idx}'

        parts.append(WAMessage(
            id=str(item_id),
            from_jid=msg.from_jid,
            from_name=msg.from_name,
            author=msg.author,
            timestamp=msg.timestamp,
            type=TYPE_MAP.get(item.get('type', msg.type), msg.type),
            text=msg.text,
            has_media=True,
            media_data=item.get('mediaData') or item.get('data'),
            media_url=item.get('mediaUrl') or item.get('url'),
            mime_type=item.get('mimetype') or msg.mime_type,
            caption=msg.caption if idx == 0 else item.get('caption'),
            has_quoted_msg=msg.has_quoted_msg,
            quoted_msg_id=msg.quoted_msg_id,
            raw=item,
        ))
    return parts


def _compact_wa_raw(raw: Optional[dict]) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    out = dict(raw)
    out.pop('mediaData', None)
    out.pop('data', None)
    data = raw.get('_data')
    if isinstance(data, dict):
        slim = dict(data)
        for k in ('mediaData', 'data', 'body'):
            slim.pop(k, None)
        if slim:
            out['_data'] = slim
    return out


def forward_to_app(
    msg: WAMessage,
    photos: List[str],
    has_media: bool,
    message_ids: Optional[List[str]] = None,
    classify_text: Optional[str] = None,
):
    is_group = msg.from_jid.endswith('@g.us')
    actual_sender = (msg.author if is_group and msg.author else msg.from_jid)

    payload = {
        'messageId': msg.id,
        'from': actual_sender,
        'author': msg.author if is_group else None,
        'fromName': msg.from_name,
        'timestamp': msg.timestamp,
        'type': msg.type,
        'text': msg.text or msg.caption or classify_text or '',
        'caption': msg.caption or '',
        'classifyText': classify_text or '',
        'photos': photos,
        'hasMedia': has_media,
        'mimeType': msg.mime_type,
        'isGroup': is_group,
        'groupId': msg.from_jid if is_group else None,
        'hasQuotedMsg': msg.has_quoted_msg or False,
        'quotedMsgId': msg.quoted_msg_id,
        'waRaw': _compact_wa_raw(msg.raw),
    }
    if message_ids:
        payload['messageIds'] = message_ids

    try:
        resp = requests.post(
            f'{APP_URL}/api/wa/inbound',
            json=payload,
            headers={'Authorization': f'Bearer {GATEWAY_SECRET}'},
            timeout=90,
        )
        if resp.ok:
            logger.info('[Gateway] Forwarded message %s to app', msg.id)
        else:
            logger.error('[Gateway] Forward failed: %d %s', resp.status_code, resp.text[:200])
    except Exception as e:
        logger.error('[Gateway] Network error forwarding: %s', e)


def on_message(msg: WAMessage):
    if not consumer_lease.may_consume():
        return

    if recent_ids.contains(msg.id):
        logger.debug('[Gateway] Skipping duplicate %s', msg.id)
        return

    recent_ids.add(msg.id)
    global _burst_coalescer
    logger.info('[Gateway] %s from %s: %s', msg.type, msg.from_jid, (msg.text or '(media)')[:80])

    # WhatsApp album container — real images arrive as separate image messages.
    if msg.type in ('other', 'unknown', 'album'):
        logger.info('[Gateway] Skip container message %s (type=%s)', msg.id, msg.type)
        return

    photos: List[str] = []
    media_failed = False

    if msg.has_media:
        try:
            for part in _media_parts_from_message(msg):
                local_path = handle_media_message(part, MEDIA_DIR, WAKKA_API_URL, WAKKA_API_KEY)
                if local_path:
                    photos.append(local_path)
                else:
                    media_failed = True
        except Exception as e:
            logger.error('[Gateway] Media handling failed: %s', e)
            media_failed = True

    if media_failed and msg.from_jid.endswith('@g.us') and msg.type in ('image', 'video'):
        logger.warning('[Gateway] Skipping forward for failed media in group %s', msg.from_jid)
        return

    if msg.has_media and len(photos) > 1:
        logger.info('[Gateway] Downloaded %d media file(s) for message %s', len(photos), msg.id)

    if msg.has_media and not photos:
        logger.info('[Gateway] Skip media message %s (download produced no files)', msg.id)
        return

    is_group = msg.from_jid.endswith('@g.us')
    if msg.has_media and photos:
        # Private chat: one WhatsApp message → one inbound (do not merge spaced sends).
        if is_group and _burst_coalescer:
            _burst_coalescer.submit(msg, photos, True)
        else:
            forward_to_app(msg, photos, True)
    elif not msg.has_media or msg.type in ('chat', 'text'):
        if is_group and _burst_coalescer and _burst_coalescer.attach_classify_text(msg):
            return
        forward_to_app(msg, photos, msg.has_media)

def main():
    global _burst_coalescer

    if not WAKKA_API_KEY:
        logger.error('[Gateway] WAKKA_API_KEY is required. Set it in .env')
        sys.exit(1)

    os.makedirs(MEDIA_DIR, exist_ok=True)

    logger.info('[Gateway] Starting Wakka Socket.IO gateway...')
    logger.info('[Gateway] Wakka URL: %s', WAKKA_API_URL)
    logger.info('[Gateway] App URL:   %s', APP_URL)
    logger.info('[Gateway] Media dir: %s', MEDIA_DIR)

    client = WakkaClient(
        url=WAKKA_API_URL,
        api_key=WAKKA_API_KEY,
        app_url=APP_URL,
    )
    client.on_message(on_message)
    client.on_ready(lambda phone: logger.info('[Gateway] WhatsApp ready. Phone: %s', phone))

    _burst_coalescer = MediaBurstCoalescer(forward_to_app)
    if not consumer_lease.start():
        sys.exit(1)

    def shutdown(sig, frame):
        logger.info('[Gateway] Shutting down...')
        client.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    client.connect()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == '__main__':
    main()
