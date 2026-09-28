"""Ensure only one Gateway process consumes Wakka messages (MacBook vs Mini)."""
import logging
import os
import re
import socket
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

HOLDER = f'{socket.gethostname()}:{os.getpid()}'
TTL_S = int(os.environ.get('GATEWAY_LEASE_TTL_S', '45'))
RENEW_S = int(os.environ.get('GATEWAY_LEASE_RENEW_S', '15'))

_stop = threading.Event()
_renew_thread: Optional[threading.Thread] = None
_cached_active = False
_cached_at = 0.0
_CACHE_S = 3.0


def _db():
    from pymongo import MongoClient

    uri = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/signhouse_v3')
    client = MongoClient(uri, serverSelectionTimeoutMS=3000)
    name = re.sub(r'.*/', '', uri.split('?')[0]) or 'signhouse_v3'
    return client[name]


def _touch_lease() -> bool:
    try:
        db = _db()
        now = datetime.utcnow()
        doc_id = 'wakka_gateway_consumer'
        doc = db.wa_system.find_one({'_id': doc_id})
        if doc and doc.get('holder') != HOLDER:
            until = doc.get('until')
            if until and until > now:
                logger.warning(
                    '[Gateway] Wakka consumer held by %s (until %s) — this process will not forward',
                    doc.get('holder'), until.isoformat(),
                )
                return False
        db.wa_system.update_one(
            {'_id': doc_id},
            {'$set': {'holder': HOLDER, 'until': now + timedelta(seconds=TTL_S), 'updatedAt': now}},
            upsert=True,
        )
        return True
    except Exception:
        logger.exception('[Gateway] Lease check failed — allowing consume (fail-open)')
        return True


def may_consume() -> bool:
    global _cached_active, _cached_at
    now = time.time()
    if now - _cached_at < _CACHE_S:
        return _cached_active
    _cached_active = _touch_lease()
    _cached_at = now
    return _cached_active


def _renew_loop() -> None:
    while not _stop.wait(RENEW_S):
        _touch_lease()


def start() -> bool:
    global _renew_thread, _cached_active, _cached_at
    _cached_active = _touch_lease()
    _cached_at = time.time()
    if not _cached_active:
        logger.error(
            '[Gateway] Another machine holds the Wakka consumer lease — '
            'stop run.py --all on Mac Mini or wait for lease expiry',
        )
        return False
    _stop.clear()
    _renew_thread = threading.Thread(target=_renew_loop, daemon=True)
    _renew_thread.start()
    logger.info('[Gateway] Wakka consumer lease held by %s', HOLDER)
    return True


def stop() -> None:
    _stop.set()
