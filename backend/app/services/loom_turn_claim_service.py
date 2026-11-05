"""Dedup parallel Loom Turns for the same WhatsApp inbound message.

When Wakka feeds both Gateway and Loom (or notify HTTP + Wakka), two Turns can
start for one worker message. The first claim on wa message id or pool batch wins;
later paths see duplicateInboundTurn so Persona can SILENCE.
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

_DUP_MSG = (
    'Another Loom turn already owns this WhatsApp message. '
    'SILENCE — do not send WhatsApp. The other turn owns the worker reply.'
)


def _claim_key(image_ids: Iterable[str]) -> str:
    ids = sorted({str(x).strip() for x in image_ids if str(x).strip()})
    digest = hashlib.sha256('|'.join(ids).encode()).hexdigest()[:24]
    return f'loom_pool_turn:{digest}'


def _wa_message_claim_key(message_id: str) -> str:
    mid = str(message_id or '').strip()
    if not mid:
        return ''
    digest = hashlib.sha256(mid.encode()).hexdigest()[:24]
    return f'loom_wa_msg_turn:{digest}'


def pool_image_ids_for_turn_claim(images: Iterable[dict[str, Any]]) -> list[str]:
    """Claim only the newest WA batch on this list page, not every open pool row."""
    rows = list(images)
    if not rows:
        return []
    newest = rows[0]
    batch_key = newest.get('batchId') or newest.get('messageId')
    if not batch_key:
        return [str(newest['_id'])]
    ids: list[str] = []
    for img in rows:
        bk = img.get('batchId') or img.get('messageId')
        if bk == batch_key:
            ids.append(str(img['_id']))
    return ids or [str(newest['_id'])]


def pool_inbound_turn_anchor_ids(images: Iterable[dict[str, Any]]) -> list[str]:
    """One anchor per worker WA message (batchId preferred for multi-photo bursts)."""
    rows = list(images)
    if not rows:
        return []
    newest = rows[0]
    batch = str(newest.get('batchId') or '').strip()
    if batch:
        return [batch]
    mid = str(newest.get('messageId') or '').strip()
    return [mid] if mid else []


def _age_s(claimed_at: float) -> float:
    return max(0.0, time.time() - claimed_at)


def _claim_memory(key: str) -> bool:
    """Return True if this is a duplicate (later) turn."""
    if not key:
        return False
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


def _claim_mongo(key: str, *, kind: str) -> bool | None:
    """True=duplicate, False=first/same-turn, None=mongo unavailable."""
    if not key:
        return False
    try:
        from app import mongo
        from pymongo.errors import DuplicateKeyError

        from app.services.wa_time import wa_now

        now = wa_now()
        try:
            mongo.db.wa_system.insert_one({'_id': key, 'claimedAt': now, 'kind': kind})
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
            return True
    except Exception:
        logger.debug('[LoomClaim] Mongo claim unavailable — using memory', exc_info=True)
        return None


def _claim_resource(key: str, *, kind: str) -> bool:
    mongo_hit = _claim_mongo(key, kind=kind)
    return _claim_memory(key) if mongo_hit is None else mongo_hit


def claim_wa_inbound_message_turn(message_ids: Iterable[str]) -> dict[str, Any]:
    anchors = [str(x).strip() for x in message_ids if str(x).strip()]
    if not anchors:
        return {
            'duplicateInboundTurn': False,
            'classifyTurnClaim': 'skipped_no_message_id',
        }
    primary = anchors[0]
    key = _wa_message_claim_key(primary)
    duplicate = _claim_resource(key, kind='loom_wa_msg_turn')
    if duplicate:
        logger.info('[LoomClaim] Duplicate WA message turn for %s', primary[:48])
    return {
        'duplicateInboundTurn': bool(duplicate),
        'classifyTurnClaim': 'duplicate' if duplicate else 'acquired',
        'inboundMessageAnchor': primary,
        'duplicateInboundMessage': _DUP_MSG if duplicate else '',
    }


def claim_pool_classify_turn(image_ids: Iterable[str]) -> dict[str, Any]:
    ids = [str(x).strip() for x in image_ids if str(x).strip()]
    if not ids:
        return {
            'duplicateInboundTurn': False,
            'classifyTurnClaim': 'skipped_no_ids',
        }
    key = _claim_key(ids)
    duplicate = _claim_resource(key, kind='loom_pool_turn')
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


def claim_loom_inbound_turn(
    *,
    image_ids: Iterable[str] | None = None,
    wa_message_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Unified claim for MCP list_pool and Loom notify (same worker message)."""
    msg_out = claim_wa_inbound_message_turn(wa_message_ids or [])
    if msg_out.get('duplicateInboundTurn'):
        return msg_out
    pool_out = claim_pool_classify_turn(image_ids or [])
    if pool_out.get('duplicateInboundTurn'):
        pool_out['duplicateInboundMessage'] = _DUP_MSG
    elif msg_out.get('inboundMessageAnchor'):
        pool_out['inboundMessageAnchor'] = msg_out['inboundMessageAnchor']
    return pool_out


def loom_notify_should_skip_duplicate(inbound_message_id: str) -> bool:
    """True → do not POST Loom notify (another turn already owns this message)."""
    if not (inbound_message_id or '').strip():
        return False
    return bool(claim_wa_inbound_message_turn([inbound_message_id])['duplicateInboundTurn'])
