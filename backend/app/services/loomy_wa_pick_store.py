"""Persist numbered classify choices for Loomy WA numeric follow-up (1–9)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, List, Optional, Sequence, Tuple, Union

CandidateRow = Union[Tuple[Any, int], Any]


def _pick_doc_id(*, phone: str, group_id: Optional[str], batch_key: str) -> str:
    if group_id:
        task = f'g:{group_id}:{phone}'
    else:
        task = f'p:{phone}'
    if batch_key:
        return f'loomy_wa_pick:{task}:{batch_key}'
    return f'loomy_wa_pick:{task}'


def store_loomy_wa_pick_options(
    *,
    phone: str,
    group_id: Optional[str],
    candidates: Sequence[CandidateRow],
    pool_ids: List[str],
    batch_key: Optional[str] = None,
) -> None:
    from app import mongo
    from app.services.project_number_match_service import wa_classify_display_label_mongo_only

    opts = []
    for i, row in enumerate(candidates[:9]):
        proj = row[0] if isinstance(row, tuple) else row
        if not proj:
            continue
        label = wa_classify_display_label_mongo_only(proj, max_len=500)
        opts.append({
            'project_id': str(proj.get('_id', '')),
            'label': f'{i + 1}. {label}',
            'code': (proj.get('code') or '').strip(),
        })
    if not opts:
        return

    from app.services.loomy_pool_batch import batch_key_from_pool_ids

    bk = (batch_key or '').strip() or batch_key_from_pool_ids(pool_ids)
    key = _pick_doc_id(phone=phone, group_id=group_id, batch_key=bk)
    mongo.db.wa_system.update_one(
        {'_id': key},
        {
            '$set': {
                'options': opts,
                'pool_ids': list(pool_ids),
                'batch_key': bk,
                'at': datetime.utcnow(),
            },
        },
        upsert=True,
    )


def find_loomy_wa_pick_doc(*, phone: str, group_id: Optional[str]) -> Optional[dict]:
    """Most recent numbered-pick prompt for this chat (latest upload batch first)."""
    from app import mongo

    if group_id:
        prefix = f'loomy_wa_pick:g:{group_id}:{phone}:'
        legacy = f'loomy_wa_pick:g:{group_id}:{phone}'
    else:
        prefix = f'loomy_wa_pick:p:{phone}:'
        legacy = f'loomy_wa_pick:p:{phone}'

    docs = list(
        mongo.db.wa_system.find({'_id': {'$regex': f'^{re.escape(prefix)}'}}).sort('at', -1),
    )
    if docs:
        return docs[0]
    return mongo.db.wa_system.find_one({'_id': legacy})
