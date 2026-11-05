"""Coalesce \"received N photos\" prompts (album bursts → one reply)."""
import hashlib
import logging
import os
import re
import threading
from datetime import datetime, timedelta
from app.services.wa_time import wa_now
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

DEBOUNCE_S = float(os.environ.get('POOL_RECEIPT_DEBOUNCE_S', '4.0'))
SEND_COOLDOWN_S = float(os.environ.get('POOL_RECEIPT_COOLDOWN_S', '120.0'))

_lock = threading.Lock()
_timers: Dict[str, threading.Timer] = {}
_flask_app = None


def init_app(app) -> None:
    global _flask_app
    _flask_app = app
    with app.app_context():
        from app.services.wa_classify_mode import wa_inbound_loomy_dispatch_enabled

        if wa_inbound_loomy_dispatch_enabled():
            try:
                from app import mongo

                r = mongo.db.wa_system.delete_many(
                    {'_id': {'$regex': r'^pool_receipt_pending:'}},
                )
                logger.info(
                    '[PoolReceipt] Loomy agent: cleared %s stale pending receipt(s)',
                    r.deleted_count,
                )
            except Exception:
                logger.exception('[PoolReceipt] Failed to clear pending receipts')


def _classify_reply_sent_key(phone: str, batch_id: Optional[str] = None) -> str:
    digits = _normalize_phone(phone)
    part = _batch_key_part(batch_id) if batch_id else 'any'
    return f'pool_classify_reply_sent:p:{digits}:{part}'


def _classify_reply_sent_key_group(
    group_id: str,
    group_sender: str,
    batch_id: Optional[str] = None,
) -> str:
    digits = _normalize_phone(group_sender)
    part = _batch_key_part(batch_id) if batch_id else 'any'
    gid = re.sub(r'[^\w@.-]', '_', str(group_id).strip())
    return f'pool_classify_reply_sent:g:{gid}:{digits}:{part}'


def mark_private_classify_reply_sent(phone: str, batch_id: Optional[str] = None) -> None:
    from app import mongo

    now = wa_now()
    mongo.db.wa_system.update_one(
        {'_id': _classify_reply_sent_key(phone, batch_id)},
        {'$set': {'at': now, 'phone': phone, 'batchId': batch_id}},
        upsert=True,
    )


def mark_group_classify_reply_sent(
    group_id: str,
    group_sender: str,
    batch_id: Optional[str] = None,
) -> None:
    from app import mongo

    now = wa_now()
    mongo.db.wa_system.update_one(
        {'_id': _classify_reply_sent_key_group(group_id, group_sender, batch_id)},
        {
            '$set': {
                'at': now,
                'groupId': group_id,
                'groupSender': group_sender,
                'batchId': batch_id,
            },
        },
        upsert=True,
    )


def _classify_in_progress_key(phone: str) -> str:
    digits = _normalize_phone(phone)
    return f'wa_classify_in_progress:p:{digits}'


def mark_private_classify_in_progress(phone: str, batch_id: Optional[str] = None) -> None:
    """Block generic pool receipt while NAS/heuristics build the folder list."""
    from app import mongo

    now = wa_now()
    mongo.db.wa_system.update_one(
        {'_id': _classify_in_progress_key(phone)},
        {'$set': {'at': now, 'phone': phone, 'batchId': batch_id}},
        upsert=True,
    )


def clear_private_classify_in_progress(phone: str) -> None:
    from app import mongo

    mongo.db.wa_system.delete_one({'_id': _classify_in_progress_key(phone)})


def private_classify_in_progress(phone: str, within_s: float = 120.0) -> bool:
    from app import mongo

    doc = mongo.db.wa_system.find_one({'_id': _classify_in_progress_key(phone)})
    if not doc or not doc.get('at'):
        return False
    return (wa_now() - doc['at']).total_seconds() <= within_s


def should_skip_receipt_after_classify_reply(
    phone: Optional[str] = None,
    batch_id: Optional[str] = None,
    within_s: float = 90.0,
    *,
    group_id: Optional[str] = None,
    group_sender: Optional[str] = None,
) -> bool:
    from app import mongo

    now = wa_now()
    keys = []
    if phone:
        keys.append(_classify_reply_sent_key(phone, batch_id))
        if batch_id:
            keys.append(_classify_reply_sent_key(phone, None))
    if group_id and group_sender:
        keys.append(_classify_reply_sent_key_group(group_id, group_sender, batch_id))
        if batch_id:
            keys.append(_classify_reply_sent_key_group(group_id, group_sender, None))
    for key in keys:
        doc = mongo.db.wa_system.find_one({'_id': key})
        if not doc or not doc.get('at'):
            continue
        if (now - doc['at']).total_seconds() <= within_s:
            return True
    return False


def format_pool_receipt_body(count: int) -> str:
    """Legacy auto-bot receipt removed — Loom/agent owns WhatsApp copy."""
    del count
    return ''


def format_pool_receipt_template() -> str:
    return ''


def phone_match_query(phone: str) -> dict:
    digits = _normalize_phone(phone)
    return {
        '$or': [
            {'phone': phone},
            {'phone': {'$regex': f'^{re.escape(digits)}'}},
        ],
    }


def latest_sender_name_for_phone(phone: str) -> Optional[str]:
    from app import mongo

    doc = mongo.db.pool_images.find_one(
        {'projectId': {'$exists': False}, **phone_match_query(phone)},
        sort=[('createdAt', -1)],
        projection={'senderName': 1},
    )
    name = (doc or {}).get('senderName')
    return name.strip() if isinstance(name, str) and name.strip() else None


def _batch_key_part(batch_id: Optional[str]) -> str:
    if not batch_id:
        return ''
    raw = str(batch_id).strip()
    if not raw:
        return ''
    if len(raw) > 96:
        return hashlib.sha256(raw.encode()).hexdigest()[:24]
    return re.sub(r'[^\w@.-]', '_', raw)


def latest_group_quote_id(
    group_id: str,
    group_sender: str,
    batch_id: Optional[str] = None,
) -> Optional[str]:
    from app import mongo

    query = {
        'groupId': group_id,
        'senderPhone': group_sender,
        'categorized': False,
    }
    if batch_id:
        query['batchId'] = batch_id
    doc = mongo.db.group_pending_images.find_one(
        query,
        sort=[('createdAt', -1)],
        projection={'messageId': 1},
    )
    mid = (doc or {}).get('messageId')
    return str(mid) if mid else None


def latest_pool_quote_id(phone: str, batch_id: Optional[str] = None) -> Optional[str]:
    from app import mongo

    query = {'projectId': {'$exists': False}, **phone_match_query(phone)}
    if batch_id:
        query['batchId'] = batch_id
    doc = mongo.db.pool_images.find_one(
        query,
        sort=[('createdAt', -1)],
        projection={'messageId': 1},
    )
    mid = (doc or {}).get('messageId')
    return str(mid) if mid else None


def mark_pool_images_reminded(
    phone: str,
    send_resp: Optional[dict],
    batch_id: Optional[str] = None,
) -> None:
    from app import mongo

    now = wa_now()
    update = {'$set': {'lastRemindedAt': now}, '$inc': {'reminderCount': 1}}
    if send_resp and isinstance(send_resp, dict):
        msg_id = send_resp.get('messageId') or send_resp.get('id') or ''
        variants = _quoted_id_variants(msg_id)
        if variants:
            update['$push'] = {'botReminderMsgIds': {'$each': variants}}
    query = {'projectId': {'$exists': False}, **phone_match_query(phone)}
    if batch_id:
        query['batchId'] = batch_id
    mongo.db.pool_images.update_many(query, update)


def _strip_jid(jid: Optional[str]) -> str:
    if not jid:
        return ''
    return re.sub(r'@(c\.us|s\.whatsapp\.net|lid)$', '', jid, flags=re.I)


def _normalize_phone(phone: Optional[str]) -> str:
    base = _strip_jid(phone)
    digits = re.sub(r'\D', '', base)
    return digits or base


def _quoted_id_variants(quoted_id: str):
    if not quoted_id:
        return []
    raw = str(quoted_id)
    parts = raw.split('_')
    short_id = parts[2] if len(parts) >= 3 else None
    return [i for i in [raw, short_id] if i]


def _record_prompt_after_send(entry: dict, resp: dict) -> None:
    from app import mongo

    msg_id = resp.get('messageId') or resp.get('id') or ''
    variants = _quoted_id_variants(msg_id)
    if not variants:
        return
    if entry.get('group_id') and entry.get('group_sender'):
        q = {
            'groupId': entry['group_id'],
            'senderPhone': entry['group_sender'],
            'categorized': False,
        }
        if entry.get('batch_id'):
            q['batchId'] = entry['batch_id']
        mongo.db.group_pending_images.update_many(
            q,
            {'$push': {'botReminderMsgIds': {'$each': variants}}},
        )
    elif entry.get('phone'):
        mark_pool_images_reminded(entry['phone'], resp)


def _pending_key(
    *,
    phone=None,
    group_id=None,
    group_sender=None,
    batch_id=None,
) -> Optional[str]:
    batch_part = _batch_key_part(batch_id)
    if group_id:
        base = f'g:{group_id}:{_normalize_phone(group_sender)}'
        return f'{base}:{batch_part}' if batch_part else base
    if phone:
        digits = _normalize_phone(phone)
        if digits:
            return f'p:{digits}:{batch_part}' if batch_part else f'p:{digits}'
    return None


def _pending_doc_id(key: str) -> str:
    return f'pool_receipt_pending:{key}'


def _arm_timer(key: str) -> None:
    with _lock:
        existing = _timers.pop(key, None)
        if existing:
            existing.cancel()
        timer = threading.Timer(DEBOUNCE_S, _flush, args=(key,))
        timer.daemon = True
        timer.start()
        _timers[key] = timer


def schedule_pool_receipt_prompt(
    file_count: int,
    body: str,
    *,
    phone: Optional[str] = None,
    group_id: Optional[str] = None,
    group_sender: Optional[str] = None,
    quote_msg_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    on_sent: Optional[Callable[[dict], None]] = None,
) -> None:
    """Merge receipt prompts for the same chat; flush after DEBOUNCE_S quiet period."""
    del on_sent  # recorded in flush via _record_prompt_after_send
    from app.services.wa_classify_mode import pool_receipt_prompts_enabled

    if not pool_receipt_prompts_enabled():
        return
    if file_count <= 0 or not body.strip():
        return

    key = _pending_key(
        phone=phone, group_id=group_id, group_sender=group_sender, batch_id=batch_id,
    )
    if not key:
        return

    try:
        from flask import has_app_context
        if not has_app_context():
            logger.warning('[PoolReceipt] No app context; cannot persist pending receipt')
            return

        from app import mongo

        now = wa_now()
        flush_at = now + timedelta(seconds=DEBOUNCE_S)
        mongo.db.wa_system.update_one(
            {'_id': _pending_doc_id(key)},
            {
                '$inc': {'fileCount': file_count},
                '$set': {
                    'key': key,
                    'body': body,
                    'phone': phone,
                    'group_id': group_id,
                    'group_sender': group_sender,
                    'quote_msg_id': quote_msg_id,
                    'batch_id': batch_id,
                    'flushAt': flush_at,
                    'updatedAt': now,
                },
                '$setOnInsert': {'createdAt': now},
            },
            upsert=True,
        )
    except Exception:
        logger.exception('[PoolReceipt] Failed to update pending receipt')
        return

    _arm_timer(key)


def _phone_count_query(phone: str, since: datetime) -> dict:
    digits = _normalize_phone(phone)
    return {
        'projectId': {'$exists': False},
        'createdAt': {'$gte': since},
        '$or': [
            {'phone': phone},
            {'phone': {'$regex': f'^{re.escape(digits)}'}},
        ],
    }


def _resolve_count(entry: dict) -> int:
    """Prefer live unassigned media count so staggered inbounds still show one total."""
    try:
        from app import mongo

        now = wa_now()
        since = now - timedelta(minutes=10)
        if entry.get('group_id') and entry.get('group_sender'):
            return mongo.db.group_pending_images.count_documents({
                'groupId': entry['group_id'],
                'senderPhone': entry['group_sender'],
                'categorized': False,
                'createdAt': {'$gte': since},
            })
        phone = entry.get('phone')
        if phone:
            return mongo.db.pool_images.count_documents(_phone_count_query(phone, since))
    except Exception:
        logger.exception('[PoolReceipt] Count query failed')
    return int(entry.get('fileCount') or 0)


def _try_acquire_send_lock(key: str) -> bool:
    from app import mongo
    from pymongo import ReturnDocument

    now = wa_now()
    lock_id = f'pool_receipt_sent:{key}'
    cooldown_until = now + timedelta(seconds=SEND_COOLDOWN_S)
    prev = mongo.db.wa_system.find_one_and_update(
        {
            '_id': lock_id,
            '$or': [
                {'until': {'$lte': now}},
                {'until': {'$exists': False}},
            ],
        },
        {'$set': {'until': cooldown_until, 'at': now}},
        upsert=True,
        return_document=ReturnDocument.BEFORE,
    )
    if prev and prev.get('until') and prev['until'] > now:
        logger.info('[PoolReceipt] Send cooldown active for %s', key)
        return False
    return True


def _duplicate_send(key: str, count: int) -> bool:
    from app import mongo

    now = wa_now()
    doc_id = f'pool_receipt_last:{key}'
    last = mongo.db.wa_system.find_one({'_id': doc_id})
    if not last:
        return False
    if last.get('count') != count:
        return False
    at = last.get('at')
    if at and (now - at).total_seconds() < SEND_COOLDOWN_S:
        logger.info('[PoolReceipt] Skip duplicate receipt for %s (count=%s)', key, count)
        return True
    return False


def _record_send(key: str, count: int) -> None:
    from app import mongo

    mongo.db.wa_system.update_one(
        {'_id': f'pool_receipt_last:{key}'},
        {'$set': {'count': count, 'at': wa_now()}},
        upsert=True,
    )


def _cancel_receipt_key(key: str) -> None:
    """Drop pending receipt timer/doc for one coalesce key."""
    if not key:
        return
    with _lock:
        existing = _timers.pop(key, None)
        if existing:
            existing.cancel()
    try:
        from app import mongo

        mongo.db.wa_system.delete_one({'_id': _pending_doc_id(key)})
    except Exception:
        logger.exception('[PoolReceipt] Failed to delete pending receipt %s', key)


def cancel_pool_receipt_prompt(
    *,
    phone: Optional[str] = None,
    group_id: Optional[str] = None,
    group_sender: Optional[str] = None,
    batch_id: Optional[str] = None,
) -> None:
    key = _pending_key(
        phone=phone, group_id=group_id, group_sender=group_sender, batch_id=batch_id,
    )
    if key:
        _cancel_receipt_key(key)


def cancel_pool_receipt_for_group_sender(
    group_id: str,
    group_sender: str,
    batch_id: Optional[str] = None,
) -> None:
    """Cancel scheduled receipt(s) for a group sender (optional batch)."""
    if batch_id:
        cancel_pool_receipt_prompt(
            group_id=group_id, group_sender=group_sender, batch_id=batch_id,
        )
    try:
        from app import mongo

        digits = _normalize_phone(group_sender)
        prefix = f'pool_receipt_pending:g:{group_id}:{digits}'
        for doc in mongo.db.wa_system.find({'_id': {'$regex': f'^{re.escape(prefix)}'}}):
            k = doc.get('key')
            if not k and doc['_id'].startswith('pool_receipt_pending:'):
                k = doc['_id'][len('pool_receipt_pending:'):]
            if k:
                _cancel_receipt_key(k)
    except Exception:
        logger.exception('[PoolReceipt] Failed to cancel group receipts for %s', group_id)


def cancel_pool_receipt_for_phone(phone: str, batch_id: Optional[str] = None) -> None:
    if batch_id:
        cancel_pool_receipt_prompt(phone=phone, batch_id=batch_id)
    try:
        from app import mongo

        digits = _normalize_phone(phone)
        prefix = f'pool_receipt_pending:p:{digits}'
        for doc in mongo.db.wa_system.find({'_id': {'$regex': f'^{re.escape(prefix)}'}}):
            k = doc.get('key')
            if not k and doc['_id'].startswith('pool_receipt_pending:'):
                k = doc['_id'][len('pool_receipt_pending:'):]
            if k:
                _cancel_receipt_key(k)
    except Exception:
        logger.exception('[PoolReceipt] Failed to cancel private receipts for %s', phone)


def _flush(key: str) -> None:
    """Drop stale pending receipt docs — WhatsApp copy is Loom-only."""
    if not _flask_app:
        return
    try:
        from app import mongo

        with _flask_app.app_context():
            with _lock:
                _timers.pop(key, None)
            mongo.db.wa_system.delete_one({'_id': _pending_doc_id(key)})
    except Exception:
        logger.exception('[PoolReceipt] Pending cleanup failed for %s', key)
