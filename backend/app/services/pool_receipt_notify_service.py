"""Coalesce \"received N photos\" prompts (album bursts → one reply)."""
import hashlib
import logging
import os
import re
import threading
from datetime import datetime, timedelta
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

    now = datetime.utcnow()
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

    now = datetime.utcnow()
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


def should_skip_receipt_after_classify_reply(
    phone: Optional[str] = None,
    batch_id: Optional[str] = None,
    within_s: float = 90.0,
    *,
    group_id: Optional[str] = None,
    group_sender: Optional[str] = None,
) -> bool:
    from app import mongo

    now = datetime.utcnow()
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
    return (
        f'📷 收到 *{count}* 張照片，請回覆專案編碼或名稱進行歸類。\n'
        f'發送 *projects* 查看專案列表。'
    )


def format_pool_receipt_template() -> str:
    return (
        f'📷 收到 *{{count}}* 張照片，請回覆專案編碼或名稱進行歸類。\n'
        f'發送 *projects* 查看專案列表。'
    )


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

    now = datetime.utcnow()
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

        now = datetime.utcnow()
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

        now = datetime.utcnow()
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

    now = datetime.utcnow()
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

    now = datetime.utcnow()
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
        {'$set': {'count': count, 'at': datetime.utcnow()}},
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
    if not _flask_app:
        logger.warning('[PoolReceipt] Flask app not initialized')
        return
    try:
        from app import mongo
        from app.services.wa_send_service import send_message, send_group_message

        with _flask_app.app_context():
            doc_id = _pending_doc_id(key)
            now = datetime.utcnow()
            pending = mongo.db.wa_system.find_one({'_id': doc_id})
            if not pending:
                return
            flush_at = pending.get('flushAt')
            if flush_at and flush_at > now:
                delay = (flush_at - now).total_seconds()
                with _lock:
                    existing = _timers.pop(key, None)
                    if existing:
                        existing.cancel()
                    timer = threading.Timer(max(0.05, delay), _flush, args=(key,))
                    timer.daemon = True
                    timer.start()
                    _timers[key] = timer
                return

            if not _try_acquire_send_lock(key):
                return

            entry = mongo.db.wa_system.find_one_and_delete({'_id': doc_id})
            if not entry:
                return

            count = _resolve_count(entry)
            if count <= 0:
                logger.info('[PoolReceipt] Skip send — nothing left to classify for %s', key)
                return

            if _duplicate_send(key, count):
                return

            if entry.get('phone') and not entry.get('group_id'):
                phone = entry['phone']
                if should_skip_receipt_after_classify_reply(
                    phone, entry.get('batch_id'),
                ):
                    logger.info(
                        '[PoolReceipt] Skip receipt — classify reply just sent for %s',
                        phone,
                    )
                    return
                digits = _normalize_phone(phone)
                skip_ids = (
                    f'wa_classify_intent:p:{digits}',
                    f'wa_ai_confirm:p:{digits}',
                    f'wa_fuzzy_choice:p:{digits}',
                )
                if any(mongo.db.wa_system.find_one({'_id': sid}) for sid in skip_ids):
                    logger.info(
                        '[PoolReceipt] Skip generic receipt — classify in progress for %s',
                        digits,
                    )
                    return
                body = format_pool_receipt_body(count)
            elif entry.get('group_id'):
                gid = entry['group_id']
                gs = entry.get('group_sender') or ''
                if should_skip_receipt_after_classify_reply(
                    batch_id=entry.get('batch_id'),
                    group_id=gid,
                    group_sender=gs,
                ):
                    logger.info(
                        '[PoolReceipt] Skip group receipt — classify reply just sent for %s',
                        gid,
                    )
                    return
                custom = entry.get('body') or ''
                if '相似專案' in custom or '找不到專案' in custom:
                    body = custom.format(count=count) if '{count}' in custom else custom
                else:
                    body = format_pool_receipt_body(count)
            else:
                body = entry.get('body') or ''
                if '{count}' in body:
                    body = body.format(count=count)

            quote = entry.get('quote_msg_id')
            batch_id = entry.get('batch_id')
            if not quote and entry.get('phone'):
                quote = latest_pool_quote_id(entry['phone'], batch_id)
            if not quote and entry.get('group_id') and entry.get('group_sender'):
                quote = latest_group_quote_id(
                    entry['group_id'], entry['group_sender'], batch_id,
                )
            if entry.get('group_id'):
                img_doc = mongo.db.group_pending_images.find_one(
                    {
                        'groupId': entry['group_id'],
                        'senderPhone': entry.get('group_sender'),
                        'categorized': False,
                        **({'batchId': batch_id} if batch_id else {}),
                    },
                    sort=[('createdAt', -1)],
                    projection={'waMessageRaw': 1},
                )
                resp = send_group_message(
                    entry['group_id'],
                    body,
                    quoted_msg_id=quote,
                    quoted_payload=(img_doc or {}).get('waMessageRaw'),
                )
            elif entry.get('phone'):
                from app.services.wa_pool_nudge_service import send_private_classify_nudge

                phone = entry['phone']
                img_doc = mongo.db.pool_images.find_one(
                    {'projectId': {'$exists': False}, **phone_match_query(phone), **(
                        {'batchId': batch_id} if batch_id else {}
                    )},
                    sort=[('createdAt', -1)],
                    projection={'imagePath': 1, 'waMessageRaw': 1},
                )
                resp = send_private_classify_nudge(
                    phone,
                    body,
                    quote_msg_id=quote,
                    image_path=(img_doc or {}).get('imagePath'),
                    quoted_payload=(img_doc or {}).get('waMessageRaw'),
                )
            else:
                return

            _record_send(key, count)
            logger.info('[PoolReceipt] Sent one receipt for %s (%d file(s))', key, count)
            if resp and isinstance(resp, dict):
                _record_prompt_after_send(entry, resp)
    except Exception:
        logger.exception('[PoolReceipt] Failed to send receipt prompt')
