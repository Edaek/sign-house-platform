"""Fast, rule-based Loomy text handling (multi-batch, direct assign) — no Ollama."""
from __future__ import annotations

import re
from datetime import datetime
from app.services.wa_time import wa_now
from typing import Any, Dict, List, Optional, Tuple

_SEPARATE_RE = re.compile(
    r'分開|分开|分開進行|分开进行|分別|分别|逐張|逐张|一張一張|一张一张|单独|單獨',
    re.I,
)
_ASSIGN_TO_RE = re.compile(
    r'(?:歸類到|归类到|分到|归到|放到|assign\s+to)\s*'
    r'(PJ[-\s]?\d{1,6}|\d{3,6})',
    re.I,
)
_ASSIGN_PHRASE_RE = re.compile(
    r'(?:將|把)?(.+?)(?:歸類到|归类到|分到|归到)\s*(PJ[-\s]?\d{1,6}|\d{3,6})',
    re.I,
)
_BARE_TARGET_RE = re.compile(r'^(PJ[-\s]?\d{1,6}|\d{3,6})$', re.I)


def _task_key(*, phone: str, group_id: Optional[str]) -> str:
    if group_id:
        return f'g:{group_id}:{phone}'
    return f'p:{phone}'


def _batch_pick_id(*, phone: str, group_id: Optional[str]) -> str:
    return f'loomy_wa_batch_pick:{_task_key(phone=phone, group_id=group_id)}'


def _active_batch_id(*, phone: str, group_id: Optional[str]) -> str:
    return f'loomy_wa_active_batch:{_task_key(phone=phone, group_id=group_id)}'


def list_unassigned_batches(*, phone: str, group_id: Optional[str] = None) -> List[Dict[str, Any]]:
    from app import mongo
    from app.services.loomy_pool_batch import batch_key_for_doc, scoped_open_pool_query

    q = scoped_open_pool_query(phone=phone, group_id=group_id)
    rows = list(mongo.db.pool_images.find(q).sort('createdAt', 1))
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(batch_key_for_doc(row), []).append(row)
    out: List[Dict[str, Any]] = []
    for bk, imgs in grouped.items():
        cap = ''
        for img in imgs:
            c = (img.get('caption') or '').strip()
            if c:
                cap = c
                break
        out.append({
            'batch_key': bk,
            'pool_ids': [str(i['_id']) for i in imgs],
            'caption': cap or '（無說明）',
            'count': len(imgs),
        })
    return out


def get_active_batch(*, phone: str, group_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    from app import mongo

    doc = mongo.db.wa_system.find_one({'_id': _active_batch_id(phone=phone, group_id=group_id)})
    if not doc or not doc.get('pool_ids'):
        return None
    return doc


def set_active_batch(
    *,
    phone: str,
    group_id: Optional[str],
    pool_ids: List[str],
    caption: str = '',
    batch_key: str = '',
) -> None:
    from app import mongo

    mongo.db.wa_system.update_one(
        {'_id': _active_batch_id(phone=phone, group_id=group_id)},
        {
            '$set': {
                'pool_ids': list(pool_ids),
                'caption': (caption or '').strip(),
                'batch_key': batch_key,
                'at': wa_now(),
            },
        },
        upsert=True,
    )


def clear_active_batch(*, phone: str, group_id: Optional[str]) -> None:
    from app import mongo

    mongo.db.wa_system.delete_one({'_id': _active_batch_id(phone=phone, group_id=group_id)})


def store_batch_pick(*, phone: str, group_id: Optional[str], batches: List[Dict[str, Any]]) -> None:
    from app import mongo

    opts = []
    for i, b in enumerate(batches[:9]):
        cap = (b.get('caption') or '（無說明）')[:80]
        opts.append({
            'pool_ids': list(b.get('pool_ids') or []),
            'caption': cap,
            'batch_key': b.get('batch_key') or '',
            'label': f'{i + 1}. {cap}',
        })
    mongo.db.wa_system.update_one(
        {'_id': _batch_pick_id(phone=phone, group_id=group_id)},
        {'$set': {'batches': opts, 'at': wa_now()}},
        upsert=True,
    )


def find_batch_pick(*, phone: str, group_id: Optional[str]) -> Optional[dict]:
    from app import mongo

    return mongo.db.wa_system.find_one({'_id': _batch_pick_id(phone=phone, group_id=group_id)})


def clear_batch_pick(*, phone: str, group_id: Optional[str]) -> None:
    from app import mongo

    mongo.db.wa_system.delete_one({'_id': _batch_pick_id(phone=phone, group_id=group_id)})


def parse_assign_target(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (source_hint, target_token) from user text."""
    t = (text or '').strip()
    if not t:
        return None, None
    m = _ASSIGN_PHRASE_RE.search(t)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = _ASSIGN_TO_RE.search(t)
    if m:
        return None, m.group(1).strip()
    return None, None


def _normalize_target_token(token: str) -> str:
    tok = (token or '').strip().upper().replace(' ', '')
    if tok.startswith('PJ'):
        tok = tok.replace('PJ-', 'PJ-').replace('PJ', 'PJ-', 1) if not tok.startswith('PJ-') else tok
    return tok


def resolve_project_for_target(token: str):
    from app.services.project_number_match_service import (
        is_wa_classify_target,
        match_classify_targets_by_site_number,
        pj_number_from_project_code,
    )

    tok = _normalize_target_token(token)
    digits = re.sub(r'\D', '', tok)
    if digits.isdigit():
        hits = match_classify_targets_by_site_number(digits, active_only=True)
        if len(hits) == 1:
            return hits[0][0]
        if len(hits) > 1:
            return ('multi', hits)
    from app import mongo

    proj = mongo.db.wa_projects.find_one({'code': {'$regex': f'^{re.escape(tok)}$', '$options': 'i'}, 'status': 'active'})
    if proj and is_wa_classify_target(proj):
        return proj
    if digits.isdigit():
        canonical = f'PJ-{digits}'
        proj = mongo.db.wa_projects.find_one({'code': canonical, 'status': 'active'})
        if proj and is_wa_classify_target(proj):
            return proj
    return None


def _pool_ids_for_batch_hint(
    *,
    phone: str,
    group_id: Optional[str],
    source_hint: Optional[str],
    fallback_pool_ids: List[str],
) -> List[str]:
    if source_hint:
        hint = source_hint.strip().lower()
        for batch in list_unassigned_batches(phone=phone, group_id=group_id):
            cap = (batch.get('caption') or '').lower()
            if hint in cap or cap in hint:
                return list(batch.get('pool_ids') or [])
    active = get_active_batch(phone=phone, group_id=group_id)
    if active and active.get('pool_ids'):
        return list(active['pool_ids'])
    if fallback_pool_ids:
        return list(fallback_pool_ids)
    from app.services.loomy_pool_batch import latest_unassigned_pool_ids

    return latest_unassigned_pool_ids(phone=phone, group_id=group_id)


def try_dismiss_scoped(
    *,
    phone: str,
    group_id: Optional[str],
    text: str,
    quoted_msg_id: Optional[str] = None,
    has_quoted: bool = False,
) -> Optional[str]:
    from app.services.loomy_wa_deterministic_reply import is_dismiss_intent
    from app.services.loomy_pool_batch import dismiss_pool_ids, resolve_reply_pool_ids

    if not is_dismiss_intent(text):
        return None

    active = get_active_batch(phone=phone, group_id=group_id)
    active_ids = list(active['pool_ids']) if active and active.get('pool_ids') else None
    pids, clarify = resolve_reply_pool_ids(
        phone=phone,
        group_id=group_id,
        quoted_msg_id=quoted_msg_id,
        has_quoted=has_quoted,
        active_pool_ids=active_ids,
    )
    if clarify:
        return clarify
    if not pids:
        return '目前沒有待歸類的照片。'
    n = dismiss_pool_ids(pids)
    clear_active_batch(phone=phone, group_id=group_id)
    from app import mongo
    from bson import ObjectId

    cap = ''
    try:
        doc = mongo.db.pool_images.find_one({'_id': ObjectId(pids[0])}, projection={'caption': 1})
        cap = ((doc or {}).get('caption') or '')[:40]
    except Exception:
        cap = ''
    if n > 0:
        suffix = f'（{cap}）' if cap else ''
        remaining = len(list_unassigned_batches(phone=phone, group_id=group_id))
        extra = f'\n尚有 {remaining} 則待歸類。' if remaining else ''
        return f'好的，已略過此則上傳{suffix}，不進行歸類。{extra}'.strip()
    return '此則已處理或找不到待略過的照片。'


def try_implicit_batch_pick(
    phone: str,
    text: str,
    *,
    group_id: Optional[str] = None,
) -> Optional[str]:
    """When several batches are open, bare 1–9 selects a batch (if no project pick pending)."""
    t = (text or '').strip()
    if not t.isdigit() or not (1 <= int(t) <= 9):
        return None
    from app.services.loomy_wa_pick_store import find_loomy_wa_pick_doc

    if find_batch_pick(phone=phone, group_id=group_id) or find_loomy_wa_pick_doc(
        phone=phone, group_id=group_id,
    ):
        return None
    batches = list_unassigned_batches(phone=phone, group_id=group_id)
    if len(batches) < 2:
        return None
    idx = int(t) - 1
    if idx >= len(batches):
        return None
    b = batches[idx]
    pool_ids = list(b.get('pool_ids') or [])
    if not pool_ids:
        return None
    cap = (b.get('caption') or '').strip()
    set_active_batch(
        phone=phone,
        group_id=group_id,
        pool_ids=pool_ids,
        caption=cap,
        batch_key=b.get('batch_key') or '',
    )
    preview = cap[:50] if cap else '（無說明）'
    return (
        f'已選第 {t} 則：{preview}\n'
        f'請回覆專案編號，或**引用此則提醒/原圖**後再寫編號。'
    )


def try_assign_to_target(
    *,
    phone: str,
    group_id: Optional[str],
    text: str,
    pool_ids: Optional[List[str]] = None,
    quoted_msg_id: Optional[str] = None,
    has_quoted: bool = False,
) -> Optional[str]:
    from app.services.image_pool_service import assign_images_to_project
    from app.services.loomy_wa_mongo_site_classify import _assign_success_message
    from app.services.project_ai_resolve_service import _build_classify_list_message
    from app.services.loomy_wa_pick_store import store_loomy_wa_pick_options

    source_hint, target_tok = parse_assign_target(text)
    target_tok = target_tok or (text.strip() if _BARE_TARGET_RE.match(text.strip()) else None)
    if not target_tok:
        return None

    resolved = resolve_project_for_target(target_tok)
    from app.services.loomy_pool_batch import resolve_reply_pool_ids

    scoped, clarify = resolve_reply_pool_ids(
        phone=phone,
        group_id=group_id,
        quoted_msg_id=quoted_msg_id,
        has_quoted=has_quoted,
        active_pool_ids=pool_ids,
    )
    if clarify:
        return clarify

    if isinstance(resolved, tuple) and resolved[0] == 'multi':
        hits = resolved[1]
        pids = scoped or _pool_ids_for_batch_hint(
            phone=phone, group_id=group_id, source_hint=source_hint, fallback_pool_ids=pool_ids or [],
        )
        if not pids:
            return '找不到待歸類的照片。'
        store_loomy_wa_pick_options(
            phone=phone, group_id=group_id, candidates=hits, pool_ids=pids,
        )
        digits = re.sub(r'\D', '', target_tok)
        return _build_classify_list_message(digits or target_tok, hits)

    if not resolved or not isinstance(resolved, dict):
        digits = re.sub(r'\D', '', target_tok)
        return f'找不到活躍專案「{target_tok}」。請發 *projects* 查看列表。'

    pids = scoped or _pool_ids_for_batch_hint(
        phone=phone, group_id=group_id, source_hint=source_hint, fallback_pool_ids=pool_ids or [],
    )
    if not pids:
        return '找不到待歸類的照片。'

    n = assign_images_to_project(pids, resolved, 'loomy', group_id=group_id)
    if n <= 0:
        return None
    clear_active_batch(phone=phone, group_id=group_id)
    clear_batch_pick(phone=phone, group_id=group_id)
    return _assign_success_message(resolved, n)


def format_multi_batch_clarify(batches: List[Dict[str, Any]]) -> str:
    lines = [
        f'您目前有 {len(batches)} 則上傳待歸類，無法自動判斷要處理哪一則。',
        '請擇一：',
        '• **回覆（引用）** 某一則「📷 待歸類」提醒或原圖，再寫專案編號或「不用」',
        '• 或回覆數字先選則：',
    ]
    for i, b in enumerate(batches[:9], 1):
        cap = (b.get('caption') or '（無說明）')[:50]
        lines.append(f'  {i}. {cap}')
    return '\n'.join(lines)


def format_batch_picker_message(batches: List[Dict[str, Any]]) -> str:
    lines = [f'好的，目前有 {len(batches)} 則上傳待歸類，請先選要處理哪一則：']
    for i, b in enumerate(batches[:9], 1):
        cap = (b.get('caption') or '（無說明）')[:60]
        cnt = b.get('count') or len(b.get('pool_ids') or [])
        suffix = f'（{cnt} 張）' if cnt > 1 else ''
        lines.append(f'{i}. {cap}{suffix}')
    lines.append('回覆數字即可；選定後可再回覆專案編號，或說「歸類到 1005」。')
    return '\n'.join(lines)


def try_loomy_batch_numeric_pick(
    phone: str,
    text: str,
    *,
    group_id: Optional[str] = None,
) -> Optional[str]:
    t = (text or '').strip()
    if not t.isdigit() or not (1 <= int(t) <= 9):
        return None
    doc = find_batch_pick(phone=phone, group_id=group_id)
    if not doc or not doc.get('batches'):
        return None
    idx = int(t) - 1
    batches = doc['batches']
    if idx < 0 or idx >= len(batches):
        return None
    choice = batches[idx]
    pool_ids = list(choice.get('pool_ids') or [])
    if not pool_ids:
        return None
    cap = (choice.get('caption') or '').strip()
    set_active_batch(
        phone=phone,
        group_id=group_id,
        pool_ids=pool_ids,
        caption=cap,
        batch_key=(choice.get('batch_key') or ''),
    )
    clear_batch_pick(phone=phone, group_id=group_id)
    preview = cap[:50] if cap else '（無說明）'
    return (
        f'已選第 {t} 則：{preview}\n'
        f'請回覆專案編號（如 1005），或說「歸類到 1005」。'
    )


def try_loomy_smart_text(ctx: Dict[str, Any]) -> Optional[str]:
    phone = (ctx.get('phone') or '').strip()
    group_id = (ctx.get('group_id') or '').strip() or None
    user_text = (ctx.get('user_text') or '').strip()
    pool_ids = list(ctx.get('pool_ids') or [])
    quoted_msg_id = (ctx.get('quoted_msg_id') or '').strip() or None
    has_quoted = bool(ctx.get('has_quoted'))
    if not user_text or not phone:
        return None

    dismiss = try_dismiss_scoped(
        phone=phone,
        group_id=group_id,
        text=user_text,
        quoted_msg_id=quoted_msg_id,
        has_quoted=has_quoted,
    )
    if dismiss:
        return dismiss

    active = get_active_batch(phone=phone, group_id=group_id)
    if active and active.get('pool_ids'):
        pool_ids = list(active['pool_ids'])

    assign_reply = try_assign_to_target(
        phone=phone,
        group_id=group_id,
        text=user_text,
        pool_ids=pool_ids,
        quoted_msg_id=quoted_msg_id,
        has_quoted=has_quoted,
    )
    if assign_reply:
        return assign_reply

    if _SEPARATE_RE.search(user_text):
        batches = list_unassigned_batches(phone=phone, group_id=group_id)
        if len(batches) <= 1:
            if batches:
                set_active_batch(
                    phone=phone,
                    group_id=group_id,
                    pool_ids=batches[0]['pool_ids'],
                    caption=batches[0].get('caption') or '',
                    batch_key=batches[0].get('batch_key') or '',
                )
                return '目前只有 1 則待歸類，請直接回覆專案編號或「歸類到 xxx」。'
            return '目前沒有待歸類的照片。'
        store_batch_pick(phone=phone, group_id=group_id, batches=batches)
        return format_batch_picker_message(batches)

    if pool_ids and re.fullmatch(r'\d{3,6}', user_text):
        return try_assign_to_target(
            phone=phone,
            group_id=group_id,
            text=user_text,
            pool_ids=pool_ids,
            quoted_msg_id=quoted_msg_id,
            has_quoted=has_quoted,
        )

    if pool_ids and not active:
        from app.services.loomy_pool_batch import resolve_reply_pool_ids
        from app.services.loomy_wa_mongo_site_classify import try_loomy_mongo_site_classify_reply

        scoped, clarify = resolve_reply_pool_ids(
            phone=phone,
            group_id=group_id,
            quoted_msg_id=quoted_msg_id,
            has_quoted=has_quoted,
            active_pool_ids=pool_ids,
        )
        if clarify:
            return clarify
        use_ids = scoped or pool_ids
        site_reply = try_loomy_mongo_site_classify_reply(
            phone=phone,
            caption=user_text,
            pool_ids=use_ids,
            group_id=group_id,
        )
        if site_reply and not site_reply.startswith('找不到活躍專案編號'):
            return site_reply

    return None
