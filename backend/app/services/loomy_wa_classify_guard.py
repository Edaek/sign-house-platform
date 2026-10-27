"""Track Loomy classify in-flight so reminders do not overlap agent replies."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import List, Optional

from bson import ObjectId


def _guard_key(*, phone: str, group_id: Optional[str]) -> str:
    if group_id:
        return f'loomy_wa_classify:g:{group_id}:{phone}'
    return f'loomy_wa_classify:p:{phone}'


def mark_loomy_classify_running(*, phone: str, group_id: Optional[str], pool_ids: Optional[List[str]] = None) -> None:
    from app import mongo

    now = datetime.utcnow()
    ttl_s = float(os.environ.get('LOOMY_WA_CLASSIFY_GUARD_TTL_S', '150'))
    mongo.db.wa_system.update_one(
        {'_id': _guard_key(phone=phone, group_id=group_id)},
        {'$set': {'running': True, 'at': now, 'until': now + timedelta(seconds=ttl_s), 'pool_ids': pool_ids or []}},
        upsert=True,
    )


def clear_loomy_classify_running(*, phone: str, group_id: Optional[str]) -> None:
    from app import mongo

    mongo.db.wa_system.delete_one({'_id': _guard_key(phone=phone, group_id=group_id)})


def loomy_classify_running(*, phone: str, group_id: Optional[str]) -> bool:
    from app import mongo

    doc = mongo.db.wa_system.find_one({'_id': _guard_key(phone=phone, group_id=group_id)})
    if not doc or not doc.get('running'):
        return False
    until = doc.get('until')
    if until and until < datetime.utcnow():
        mongo.db.wa_system.delete_one({'_id': doc['_id']})
        return False
    return True


def mark_pool_classify_reply(pool_ids: List[str], reply: str) -> None:
    """Record that Loomy already sent a classify-related reply for these pool rows."""
    if not pool_ids:
        return
    from app import mongo

    now = datetime.utcnow()
    oids = []
    for pid in pool_ids:
        try:
            oids.append(ObjectId(pid))
        except Exception:
            continue
    if not oids:
        return
    preview = (reply or '')[:200]
    mongo.db.pool_images.update_many(
        {'_id': {'$in': oids}},
        {'$set': {'loomyLastClassifyReplyAt': now, 'loomyLastClassifyReplyPreview': preview, 'updatedAt': now}},
    )
