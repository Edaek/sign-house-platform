"""Scope Loomy pool classify/remind to one WhatsApp upload batch (not all open rows)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional, Tuple

from bson import ObjectId
from bson.errors import InvalidId


def _quoted_id_variants(quoted_id: str) -> List[str]:
    if not quoted_id:
        return []
    raw = str(quoted_id).strip()
    parts = raw.split('_')
    short_id = parts[-1] if len(parts) >= 3 else None
    return [i for i in [raw, short_id] if i]


def batch_key_for_doc(doc: dict) -> str:
    if not doc:
        return ''
    bid = (doc.get('batchId') or '').strip()
    if bid:
        return bid
    mid = (doc.get('messageId') or '').strip()
    if mid:
        return mid
    return str(doc.get('_id', ''))


def scoped_open_pool_query(*, phone: str, group_id: Optional[str] = None) -> dict:
    from app.services.pool_receipt_notify_service import phone_match_query

    q: dict = {'projectId': {'$exists': False}, 'dismissed': {'$ne': True}}
    if phone:
        q.update(phone_match_query(phone))
    if group_id:
        q['chatJid'] = {'$regex': group_id.replace('+', r'\+'), '$options': 'i'}
    return q


def latest_unassigned_pool_ids(*, phone: str, group_id: Optional[str] = None) -> List[str]:
    from app import mongo

    q = scoped_open_pool_query(phone=phone, group_id=group_id)
    newest = mongo.db.pool_images.find_one(q, sort=[('createdAt', -1)])
    if not newest:
        return []
    return pool_ids_same_batch_as(newest, q=q)


def pool_ids_same_batch_as(anchor: dict, *, q: Optional[dict] = None) -> List[str]:
    from app import mongo

    if q is None:
        q = {'projectId': {'$exists': False}, 'dismissed': {'$ne': True}}
    batch = batch_key_for_doc(anchor)
    if not batch:
        return [str(anchor['_id'])]
    if anchor.get('batchId'):
        docs = list(
            mongo.db.pool_images.find({**q, 'batchId': anchor['batchId']}).sort('createdAt', 1),
        )
    else:
        docs = list(
            mongo.db.pool_images.find({**q, 'messageId': anchor.get('messageId')}).sort('createdAt', 1),
        )
        if not docs:
            docs = [anchor]
    return [str(d['_id']) for d in docs]


def batch_key_from_pool_ids(pool_ids: List[str]) -> str:
    if not pool_ids:
        return ''
    from app import mongo

    try:
        oid = ObjectId(pool_ids[0])
    except (InvalidId, TypeError):
        return pool_ids[0]
    doc = mongo.db.pool_images.find_one({'_id': oid})
    return batch_key_for_doc(doc or {})


def find_pool_ids_by_quote(
    *,
    phone: str,
    group_id: Optional[str],
    quoted_msg_id: str,
) -> List[str]:
    from app import mongo

    variants = _quoted_id_variants(quoted_msg_id)
    if not variants:
        return []
    q = scoped_open_pool_query(phone=phone, group_id=group_id)
    docs = list(mongo.db.pool_images.find({
        **q,
        '$or': [
            {'messageId': {'$in': variants}},
            {'botReminderMsgIds': {'$in': variants}},
        ],
    }))
    if not docs:
        for qid in variants:
            docs = list(mongo.db.pool_images.find({
                **q,
                'messageId': {'$regex': re.escape(qid)},
            }))
            if docs:
                break
    if not docs:
        return []
    anchor = docs[0]
    return pool_ids_same_batch_as(anchor, q=scoped_open_pool_query(phone=phone, group_id=group_id))


def resolve_reply_pool_ids(
    *,
    phone: str,
    group_id: Optional[str] = None,
    quoted_msg_id: Optional[str] = None,
    has_quoted: bool = False,
    active_pool_ids: Optional[List[str]] = None,
) -> Tuple[List[str], Optional[str]]:
    """
    Which pool row(s) a free-form reply applies to.
    Returns (pool_ids, clarify_message). clarify_message set → do not guess.
    """
    from app.services.loomy_wa_smart_classify import (
        format_multi_batch_clarify,
        get_active_batch,
        list_unassigned_batches,
    )

    batches = list_unassigned_batches(phone=phone, group_id=group_id)
    if not batches:
        return [], None

    if has_quoted and quoted_msg_id:
        pids = find_pool_ids_by_quote(
            phone=phone, group_id=group_id, quoted_msg_id=quoted_msg_id,
        )
        if pids:
            return pids, None
        return [], '找不到與引用消息對應的照片。請引用**該則提醒**或**原圖**後再回覆。'

    if active_pool_ids:
        return list(active_pool_ids), None

    active = get_active_batch(phone=phone, group_id=group_id)
    if active and active.get('pool_ids'):
        return list(active['pool_ids']), None

    if len(batches) == 1:
        return list(batches[0].get('pool_ids') or []), None

    return [], format_multi_batch_clarify(batches)


def dismiss_pool_ids(pool_ids: List[str]) -> int:
    from app import mongo

    if not pool_ids:
        return 0
    oids = []
    for pid in pool_ids:
        try:
            oids.append(ObjectId(pid))
        except (InvalidId, TypeError):
            continue
    if not oids:
        return 0
    now = datetime.utcnow()
    result = mongo.db.pool_images.update_many(
        {'_id': {'$in': oids}},
        {'$set': {'dismissed': True, 'dismissedAt': now, 'updatedAt': now}},
    )
    return result.modified_count


def mark_loomy_reminder_bot_ids(pool_ids: List[str], send_resp: Optional[dict]) -> None:
    from app import mongo

    if not pool_ids or not send_resp or not isinstance(send_resp, dict):
        return
    msg_id = send_resp.get('messageId') or send_resp.get('id') or ''
    variants = _quoted_id_variants(msg_id)
    if not variants:
        return
    oids = []
    for pid in pool_ids:
        try:
            oids.append(ObjectId(pid))
        except (InvalidId, TypeError):
            continue
    if not oids:
        return
    now = datetime.utcnow()
    mongo.db.pool_images.update_many(
        {'_id': {'$in': oids}},
        {
            '$set': {'loomyLastRemindedAt': now, 'updatedAt': now},
            '$push': {'botReminderMsgIds': {'$each': variants}},
            '$inc': {'loomyReminderCount': 1},
        },
    )


def dismiss_latest_unassigned_batch(*, phone: str, group_id: Optional[str] = None) -> int:
    from datetime import datetime

    from app import mongo

    ids = latest_unassigned_pool_ids(phone=phone, group_id=group_id)
    if not ids:
        return 0
    oids = []
    for pid in ids:
        try:
            oids.append(ObjectId(pid))
        except (InvalidId, TypeError):
            continue
    if not oids:
        return 0
    now = datetime.utcnow()
    result = mongo.db.pool_images.update_many(
        {'_id': {'$in': oids}},
        {'$set': {'dismissed': True, 'dismissedAt': now, 'updatedAt': now}},
    )
    return result.modified_count


def sender_bucket_key(*, phone: str, chat_jid: str) -> str:
    digits = re.sub(r'\D', '', phone or '')
    is_group = '@g.us' in (chat_jid or '')
    if is_group:
        return f'g:{chat_jid}:{digits or phone}'
    return f'p:{digits or phone}'


class PoolAssignScopeError(ValueError):
    """Pool images cannot be merged into one WA record (group / sender scope)."""


def _group_jid_matches(stored: str, group_id: str) -> bool:
    a = (stored or '').strip().lower()
    b = (group_id or '').strip().lower()
    if not a or not b:
        return True
    if a == b:
        return True
    a_base = a.split('@')[0]
    b_base = b.split('@')[0]
    return a_base == b_base or a_base in b or b_base in a


def assert_pool_images_assignable(images: list, *, group_id: Optional[str] = None) -> None:
    """
    Block cross-user (or cross-batch in groups) assign — the main group-chat bug class.
    Private chat: all rows must share the same phone bucket (p:…).
    Group chat: same sender bucket and, when multiple files, the same upload batch.
    """
    if not images:
        return

    buckets: set[str] = set()
    batch_keys: set[str] = set()
    group_jids: set[str] = set()
    for img in images:
        phone = (img.get('phone') or '').strip()
        chat = (img.get('chatJid') or '').strip()
        buckets.add(sender_bucket_key(phone=phone, chat_jid=chat))
        bk = batch_key_for_doc(img)
        if bk:
            batch_keys.add(bk)
        if chat and '@g.us' in chat:
            group_jids.add(chat.lower())

    if len(buckets) > 1:
        raise PoolAssignScopeError(
            'Cannot assign pool images from different senders in one request '
            '(group chat: use wa_list_pool_images with phone= that user, then assign only their ids).',
        )

    if group_id and group_jids:
        for gj in group_jids:
            if not _group_jid_matches(gj, group_id):
                raise PoolAssignScopeError(
                    'groupId does not match the chatJid on these pool images.',
                )

    is_group = bool(group_jids) or ('@g.us' in (group_id or ''))
    if is_group and len(images) > 1 and len(batch_keys) > 1:
        raise PoolAssignScopeError(
            'Cannot assign multiple upload batches in one group-chat assign — '
            'classify each batch separately (quote the reminder or send project code per batch).',
        )
