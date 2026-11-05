"""Persist numbered classify choices for Loomy WA numeric follow-up (1–9)."""
from __future__ import annotations

import re
from datetime import datetime
from app.services.wa_time import wa_now
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
    from app.services.project_number_match_service import wa_classify_display_label_mongo_only

    opts = []
    for i, row in enumerate(candidates[:9]):
        proj = row[0] if isinstance(row, tuple) else row
        if not proj:
            continue
        from app.services.project_number_match_service import wa_classify_nas_path_line

        path_line = wa_classify_nas_path_line(proj, max_len=500)
        opts.append({
            'project_id': str(proj.get('_id', '')),
            'label': path_line,
            'code': (proj.get('code') or '').strip(),
            'nas_folder_name': (proj.get('nasFolderName') or proj.get('code') or '').strip(),
            'nas_parent_bucket': (proj.get('nasParentBucket') or '').strip(),
        })
    if not opts:
        return
    store_loomy_wa_pick_options_from_opts(
        phone=phone,
        group_id=group_id,
        options=opts,
        pool_ids=pool_ids,
        batch_key=batch_key,
    )


def store_loomy_wa_pick_options_from_opts(
    *,
    phone: str,
    group_id: Optional[str],
    options: List[dict],
    pool_ids: List[str],
    batch_key: Optional[str] = None,
) -> None:
    from app import mongo
    from app.services.loomy_pool_batch import batch_key_from_pool_ids

    if not options:
        return
    bk = (batch_key or '').strip() or batch_key_from_pool_ids(pool_ids)
    key = _pick_doc_id(phone=phone, group_id=group_id, batch_key=bk)
    mongo.db.wa_system.update_one(
        {'_id': key},
        {
            '$set': {
                'options': list(options),
                'pool_ids': list(pool_ids),
                'batch_key': bk,
                'at': wa_now(),
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


def nas_path_line_from_option(opt: dict) -> str:
    pb = (opt.get('nas_parent_bucket') or opt.get('nasParentBucket') or '').strip()
    fn = (opt.get('nas_folder_name') or opt.get('nasFolderName') or '').strip()
    if pb and fn:
        return f'{pb}/{fn}'
    return fn or pb or (opt.get('label') or '').strip()


def match_loomy_wa_pick_option(options: List[dict], user_text: str) -> Optional[dict]:
    """Match worker reply to a pending classify path (full or partial NAS path)."""
    from app.services.project_number_match_service import _normalize_classify_label

    raw = ' '.join((user_text or '').strip().split())
    if not raw or raw.isdigit():
        return None
    norm_in = _normalize_classify_label(raw)
    if not norm_in:
        return None

    exact: List[dict] = []
    partial: List[dict] = []
    for opt in options or []:
        path = nas_path_line_from_option(opt)
        norm_path = _normalize_classify_label(path)
        norm_folder = _normalize_classify_label(opt.get('nas_folder_name') or '')
        norm_label = _normalize_classify_label(opt.get('label') or '')
        if norm_in in (norm_path, norm_folder, norm_label):
            exact.append(opt)
        elif norm_path and (norm_in in norm_path or norm_path in norm_in):
            partial.append(opt)
        elif norm_folder and (norm_in in norm_folder or norm_folder in norm_in):
            partial.append(opt)
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None
    if len(partial) == 1:
        return partial[0]
    return None
