"""Deterministic WA classify turns for Loom MCP (site numbers, menu picks 1–9)."""
from __future__ import annotations

import re
from typing import Any, List, Optional

_MENU_PICK_RE = re.compile(r'^[1-9]$')


def _open_pool_ids(*, phone: str, group_id: Optional[str]) -> List[str]:
    from app.services.loomy_pool_batch import latest_unassigned_pool_ids

    return latest_unassigned_pool_ids(phone=phone, group_id=group_id)


def preview_classify_turn(
    user_text: str,
    *,
    phone: str,
    group_id: Optional[str] = None,
) -> dict[str, Any]:
    """Hint for Loom / workerWhatsAppPolicy — avoid Cheap_skip on 1005 or menu 2."""
    t = (user_text or '').strip()
    if not t:
        return {'intent': 'none'}

    from app.services.loomy_wa_pick_store import find_loomy_wa_pick_doc

    if _MENU_PICK_RE.match(t):
        doc = find_loomy_wa_pick_doc(phone=phone, group_id=group_id)
        n = len(doc.get('options') or []) if doc else 0
        return {
            'intent': 'menu_pick',
            'mustCallTool': 'wa_classify_inbound_text',
            'pendingPickCount': n,
            'instruction': (
                'Worker replied after a NAS path list. Call wa_classify_inbound_text with user_text '
                '(prefer full bucket/folder path; legacy digit 1–9 still accepted). Do NOT Cheap_skip.'
            ),
        }

    from app.services.loomy_wa_smart_classify import parse_assign_target

    _, target = parse_assign_target(t)
    from app.services.project_number_match_service import loomy_primary_site_number

    site = loomy_primary_site_number(t)
    if target or site or (t.isdigit() and len(t) >= 3):
        return {
            'intent': 'site_classify',
            'mustCallTool': 'wa_classify_inbound_text',
            'siteHint': site or target or t,
            'instruction': (
                'Worker sent a site / assign intent. Call wa_classify_inbound_text with user_text, '
                'then wa_list_pool_images if needed. Do NOT Cheap_skip or memory-only.'
            ),
        }

    doc = find_loomy_wa_pick_doc(phone=phone, group_id=group_id)
    if doc and doc.get('options'):
        return {
            'intent': 'path_pick',
            'mustCallTool': 'wa_classify_inbound_text',
            'pendingPickCount': len(doc['options']),
            'instruction': (
                'Worker is choosing a NAS path after disambiguation. Call wa_classify_inbound_text '
                'with the same user_text (full bucket/folder path). Do NOT Cheap_skip.'
            ),
        }
    return {'intent': 'other'}


def _assign_from_pick_choice(
    *,
    phone: str,
    group_id: Optional[str],
    choice: dict,
    pool_ids: List[str],
) -> tuple[int, Optional[dict], str]:
    from bson import ObjectId
    from bson.errors import InvalidId

    from app import mongo
    from app.services.image_pool_service import assign_images_to_project
    from app.services.loomy_wa_mongo_site_classify import _assign_success_message

    pid = (choice.get('project_id') or '').strip()
    if not pid or not pool_ids:
        return 0, None, '缺少 project 或 pool 圖，未能歸類。'
    try:
        proj = mongo.db.wa_projects.find_one({'_id': ObjectId(pid)})
    except InvalidId:
        proj = None
    if not proj:
        return 0, None, '找不到所選專案，請重新 list 1/2。'
    proj = dict(proj)
    fn = (choice.get('nas_folder_name') or choice.get('nasFolderName') or '').strip()
    pb = (choice.get('nas_parent_bucket') or choice.get('nasParentBucket') or '').strip()
    if fn:
        proj['nasFolderName'] = fn
    if pb:
        proj['nasParentBucket'] = pb
    elif not (proj.get('nasFolderName') or '').strip():
        proj['nasFolderName'] = fn or (proj.get('nasFolderName') or '').strip()

    n = assign_images_to_project(pool_ids, proj, 'loomy_mcp', group_id=group_id)
    if n <= 0:
        return 0, proj, '未能歸類（圖可能已歸類或不在 pool）。'
    return n, proj, _assign_success_message(proj, n, pool_ids=pool_ids)


def _finish_pick_choice(
    *,
    phone: str,
    group_id: Optional[str],
    doc: dict,
    choice: dict,
) -> dict[str, Any]:
    from app import mongo

    pool_ids = list(doc.get('pool_ids') or []) or _open_pool_ids(phone=phone, group_id=group_id)
    if not pool_ids:
        return {
            'handled': True,
            'action': 'no_pool',
            'reply_zh': '而家 pool 冇待歸類圖，請先發相或確認 batch。',
        }
    n, _proj, msg = _assign_from_pick_choice(
        phone=phone,
        group_id=group_id,
        choice=choice,
        pool_ids=pool_ids,
    )
    mongo.db.wa_system.delete_one({'_id': doc['_id']})
    return {
        'handled': True,
        'action': 'assigned' if n > 0 else 'assign_failed',
        'assigned': n,
        'reply_zh': msg,
    }


def execute_pending_path_pick(
    *,
    phone: str,
    group_id: Optional[str],
    user_text: str,
) -> Optional[dict[str, Any]]:
    from app.services.loomy_wa_pick_store import (
        find_loomy_wa_pick_doc,
        match_loomy_wa_pick_option,
        nas_path_line_from_option,
    )

    doc = find_loomy_wa_pick_doc(phone=phone, group_id=group_id)
    if not doc or not doc.get('options'):
        return None
    choice = match_loomy_wa_pick_option(doc['options'], user_text)
    if not choice:
        paths = '\n'.join(nas_path_line_from_option(o) for o in doc['options'][:9])
        return {
            'handled': True,
            'action': 'path_not_matched',
            'reply_zh': (
                f'唔識別「{user_text.strip()}」。請直接回覆其中一條完整 NAS 路徑：\n{paths}'
            ),
        }
    out = _finish_pick_choice(phone=phone, group_id=group_id, doc=doc, choice=choice)
    out['intent'] = 'path_pick'
    return out


def execute_menu_pick(
    *,
    phone: str,
    group_id: Optional[str],
    digit: str,
) -> dict[str, Any]:
    from app.services.loomy_wa_pick_store import find_loomy_wa_pick_doc

    doc = find_loomy_wa_pick_doc(phone=phone, group_id=group_id)
    if not doc or not doc.get('options'):
        return {
            'handled': True,
            'action': 'no_pending_pick',
            'reply_zh': (
                '我唔記得上一輪 NAS 路徑列表（可能未寫入系統）。'
                '請再發專案號（如 1005）或完整 NAS 路徑，我重新 list。'
            ),
        }
    idx = int(digit) - 1
    opts = doc['options']
    if idx < 0 or idx >= len(opts):
        from app.services.loomy_wa_pick_store import nas_path_line_from_option

        paths = '\n'.join(nas_path_line_from_option(o) for o in opts)
        return {
            'handled': True,
            'action': 'invalid_pick',
            'reply_zh': f'請回覆其中一條完整 NAS 路徑：\n{paths}',
        }
    out = _finish_pick_choice(phone=phone, group_id=group_id, doc=doc, choice=opts[idx])
    out['intent'] = 'menu_pick'
    return out


def handle_classify_inbound_text(
    *,
    phone: str,
    group_id: Optional[str] = None,
    user_text: str,
    pool_ids: Optional[List[str]] = None,
) -> dict[str, Any]:
    """Run Sign House classify logic; Loom sends returned reply_zh as the one WA message."""
    t = (user_text or '').strip()
    if not t:
        return {'handled': False, 'reason': 'empty_text'}

    from app.services.loomy_wa_pick_store import find_loomy_wa_pick_doc

    pending = find_loomy_wa_pick_doc(phone=phone, group_id=group_id)
    if pending and pending.get('options'):
        if _MENU_PICK_RE.match(t):
            return execute_menu_pick(phone=phone, group_id=group_id, digit=t)
        path_out = execute_pending_path_pick(phone=phone, group_id=group_id, user_text=t)
        if path_out:
            return path_out

    pids = list(pool_ids or []) or _open_pool_ids(phone=phone, group_id=group_id)

    from app.services.loomy_wa_smart_classify import try_assign_to_target

    assign_reply = try_assign_to_target(
        phone=phone,
        group_id=group_id,
        text=t,
        pool_ids=pids or None,
    )
    if assign_reply:
        return {
            'handled': True,
            'intent': 'site_classify',
            'action': 'assign_or_list',
            'reply_zh': assign_reply,
            'pickStored': 'NAS 路徑' in assign_reply or '可能對應' in assign_reply,
        }

    from app.services.project_number_match_service import loomy_primary_site_number
    from app.services.loomy_wa_mongo_site_classify import try_loomy_mongo_site_classify_reply

    site = loomy_primary_site_number(t)
    if site and pids:
        site_reply = try_loomy_mongo_site_classify_reply(
            phone=phone,
            caption=t,
            pool_ids=pids,
            group_id=group_id,
        )
        if site_reply:
            return {
                'handled': True,
                'intent': 'site_classify',
                'action': 'assign_or_list',
                'reply_zh': site_reply,
            }

    if site or t.isdigit():
        return {
            'handled': True,
            'intent': 'site_classify',
            'action': 'need_pool_or_clarity',
            'reply_zh': (
                f'收到「{t}」。而家未見到你待歸類嘅相喺 pool；'
                f'請先發相，或引用嗰批相再講一次專案號。'
            ),
        }

    return {'handled': False, 'reason': 'not_classify_intent'}


def store_classify_choices(
    *,
    phone: str,
    group_id: Optional[str],
    choices: List[dict],
    pool_ids: List[str],
) -> dict[str, Any]:
    """Loom calls after listing NAS paths so follow-up path reply assigns correctly."""
    from app import mongo
    from bson import ObjectId
    from bson.errors import InvalidId

    if not choices or not pool_ids:
        return {'ok': False, 'error': 'choices and pool_ids required'}

    opts = []
    for i, row in enumerate(choices[:9]):
        if not isinstance(row, dict):
            continue
        pid = (row.get('project_id') or row.get('projectId') or '').strip()
        code = (row.get('code') or '').strip()
        fn = (row.get('nas_folder_name') or row.get('nasFolderName') or '').strip()
        pb = (row.get('nas_parent_bucket') or row.get('nasParentBucket') or '').strip()
        proj = None
        if pid:
            try:
                proj = mongo.db.wa_projects.find_one({'_id': ObjectId(pid)})
            except InvalidId:
                proj = None
            if proj:
                fn = fn or (proj.get('nasFolderName') or proj.get('code') or '').strip()
                pb = pb or (proj.get('nasParentBucket') or '').strip()
                code = code or (proj.get('code') or '').strip()
        label = (row.get('label') or '').strip()
        if re.match(r'^\d+\.\s', label):
            label = label.split('.', 1)[-1].strip()
        if not label and proj:
            from app.services.project_number_match_service import wa_classify_nas_path_line

            label = wa_classify_nas_path_line(proj, max_len=500)
        elif not label and pb and fn:
            label = f'{pb}/{fn}'
        if not pid:
            continue
        opts.append({
            'project_id': pid,
            'label': label,
            'code': code,
            'nas_folder_name': fn,
            'nas_parent_bucket': pb,
        })
    if not opts:
        return {'ok': False, 'error': 'no valid choices'}

    from app.services.loomy_wa_pick_store import store_loomy_wa_pick_options_from_opts

    store_loomy_wa_pick_options_from_opts(
        phone=phone,
        group_id=group_id,
        options=opts,
        pool_ids=pool_ids,
    )
    return {'ok': True, 'stored': len(opts)}
