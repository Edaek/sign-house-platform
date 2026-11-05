"""Dedup parallel Loom Turns that list the same unassigned pool batch.

When Wakka feeds both Gateway and Loom (or Loom fires two turns for one photo),
each Turn calls wa_list_pool_images. The first claim wins; a later list of the
same image ids within the TTL is marked duplicateInboundTurn so Persona can SILENCE.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from typing import Any, Iterable

logger = logging.getLogger(__name__)

_mem_lock = threading.Lock()
_mem: dict[str, float] = {}

SAME_TURN_GRACE_S = float(os.environ.get('LOOM_WA_TURN_CLAIM_GRACE_S', '2'))
CLAIM_TTL_S = float(os.environ.get('LOOM_WA_TURN_CLAIM_TTL_S', '90'))


def _claim_key(image_ids: Iterable[str]) -> str:
    ids = sorted({str(x).strip() for x in image_ids if str(x).strip()})
    digest = hashlib.sha256('|'.join(ids).encode()).hexdigest()[:24]
    return f'loom_pool_turn:{digest}'


def _age_s(claimed_at: float) -> float:
    return max(0.0, time.time() - claimed_at)


def _claim_memory(key: str) -> bool:
    """Return True if this is a duplicate (later) turn."""
    now = time.time()
    with _mem_lock:
        stale = [k for k, ts in _mem.items() if now - ts > CLAIM_TTL_S]
        for k in stale:
            _mem.pop(k, None)
        prev = _mem.get(key)
        if prev is None:
            _mem[key] = now
            return False
        age = _age_s(prev)
        if age < SAME_TURN_GRACE_S:
            return False
        return True


def _claim_mongo(key: str) -> bool | None:
    """True=duplicate, False=first/same-turn, None=mongo unavailable."""
    try:
        from app import mongo
        from pymongo.errors import DuplicateKeyError

        from app.services.wa_time import wa_now

        now = wa_now()
        try:
            mongo.db.wa_system.insert_one({'_id': key, 'claimedAt': now, 'kind': 'loom_pool_turn'})
            return False
        except DuplicateKeyError:
            doc = mongo.db.wa_system.find_one({'_id': key}, {'claimedAt': 1})
            claimed = (doc or {}).get('claimedAt')
            if claimed is None:
                return True
            try:
                age = (now - claimed).total_seconds()
            except TypeError:
                return True
            if age > CLAIM_TTL_S:
                mongo.db.wa_system.update_one(
                    {'_id': key},
                    {'$set': {'claimedAt': now}},
                )
                return False
            if age < SAME_TURN_GRACE_S:
                return False
            return True
    except Exception:
        logger.debug('[LoomClaim] Mongo claim unavailable — using memory', exc_info=True)
        return None


def claim_pool_classify_turn(image_ids: Iterable[str]) -> dict[str, Any]:
    ids = [str(x).strip() for x in image_ids if str(x).strip()]
    if not ids:
        return {
            'duplicateInboundTurn': False,
            'classifyTurnClaim': 'skipped_no_ids',
        }
    key = _claim_key(ids)
    mongo_hit = _claim_mongo(key)
    duplicate = _claim_memory(key) if mongo_hit is None else mongo_hit
    if duplicate:
        logger.info('[LoomClaim] Duplicate pool-list turn for %s (%d ids)', key, len(ids))
    return {
        'duplicateInboundTurn': bool(duplicate),
        'classifyTurnClaim': 'duplicate' if duplicate else 'acquired',
        'duplicateInboundMessage': (
            'Another Loom turn already listed these pool images. '
            'SILENCE — do not send WhatsApp. The other turn owns the worker reply.'
            if duplicate
            else ''
        ),
    }
