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

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / '.env')

from gateway.wakka_client import WakkaClient, WAMessage
from gateway.media_handler import handle_media_message
from gateway.group_reminder import GroupReminderScheduler

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

reminder: GroupReminderScheduler | None = None


def forward_to_app(msg: WAMessage, photos: list[str], has_media: bool):
    is_group = msg.from_jid.endswith('@g.us')
    actual_sender = (msg.author if is_group and msg.author else msg.from_jid)

    payload = {
        'messageId': msg.id,
        'from': actual_sender,
        'fromName': msg.from_name,
        'timestamp': msg.timestamp,
        'type': msg.type,
        'text': msg.text or msg.caption or '',
        'caption': msg.caption or '',
        'photos': photos,
        'hasMedia': has_media,
        'mimeType': msg.mime_type,
        'isGroup': is_group,
        'groupId': msg.from_jid if is_group else None,
        'hasQuotedMsg': msg.has_quoted_msg or False,
        'quotedMsgId': msg.quoted_msg_id,
    }

    try:
        resp = requests.post(
            f'{APP_URL}/api/wa/inbound',
            json=payload,
            headers={'Authorization': f'Bearer {GATEWAY_SECRET}'},
            timeout=15,
        )
        if resp.ok:
            logger.info('[Gateway] Forwarded message %s to app', msg.id)
        else:
            logger.error('[Gateway] Forward failed: %d %s', resp.status_code, resp.text[:200])
    except Exception as e:
        logger.error('[Gateway] Network error forwarding: %s', e)


def on_message(msg: WAMessage):
    if recent_ids.contains(msg.id):
        logger.debug('[Gateway] Skipping duplicate %s', msg.id)
        return

    recent_ids.add(msg.id)
    logger.info('[Gateway] %s from %s: %s', msg.type, msg.from_jid, (msg.text or '(media)')[:80])

    photos: list[str] = []
    media_failed = False

    if msg.has_media:
        try:
            local_path = handle_media_message(msg, MEDIA_DIR, WAKKA_API_URL, WAKKA_API_KEY)
            if local_path:
                photos = [local_path]
            else:
                media_failed = True
        except Exception as e:
            logger.error('[Gateway] Media handling failed: %s', e)
            media_failed = True

    if media_failed and msg.from_jid.endswith('@g.us') and msg.type in ('image', 'video'):
        logger.warning('[Gateway] Skipping forward for failed media in group %s', msg.from_jid)
        return

    forward_to_app(msg, photos, msg.has_media)

    if msg.has_media and msg.from_jid.endswith('@g.us') and msg.author and reminder:
        reminder.trigger(msg.from_jid, msg.author)


def main():
    global reminder

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

    reminder = GroupReminderScheduler(
        mongo_uri=MONGO_URI,
        wakka_url=WAKKA_API_URL,
        wakka_key=WAKKA_API_KEY,
        media_dir=MEDIA_DIR,
    )

    def shutdown(sig, frame):
        logger.info('[Gateway] Shutting down...')
        reminder.stop()
        client.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    client.connect()
    reminder.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == '__main__':
    main()
