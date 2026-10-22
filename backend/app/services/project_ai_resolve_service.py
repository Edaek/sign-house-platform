"""AI-assisted project classification — list, suggest, confirm before assign."""
import logging
import os
import re

from bson import ObjectId

from app import mongo
from app.services.ai_extract_service import _call_ollama, _get_config, _parse_structured
from app.services.image_pool_service import match_project_ext
from app.services.message_parser_service import split_classify_label_and_remark
from app.services.project_number_match_service import (
    _normalize_classify_label,
    classify_input_matches_full_display,
    is_wa_classify_target,
    list_wa_classify_target_projects,
    primary_site_number,
    wa_classify_display_label,
    wa_classify_list_labels,
)

logger = logging.getLogger(__name__)

AI_CONFIRM_TTL_S = 600
class ClassifyResolve:
    __slots__ = (
        'action', 'project', 'candidates', 'remark', 'user_message', 'needs_confirm',
    )

    def __init__(
        self,
        action='none',
        project=None,
        candidates=None,
        remark=None,
        user_message='',
        needs_confirm=False,
    ):
        self.action = action  # assign | list | suggest | none
        self.project = project
        self.candidates = candidates or []
        self.remark = remark
        self.user_message = user_message
        self.needs_confirm = needs_confirm


def _format_candidate_lines(candidates):
    projs = []
    for item in candidates:
        projs.append(item[0] if isinstance(item, tuple) else item)
    labels = wa_classify_list_labels(projs, max_len=500)
    return '\n'.join(f'{i}. {lab}' for i, lab in enumerate(labels, 1))


def _build_classify_list_message(match_key, candidates):
    listing = _format_candidate_lines(candidates)
    return (
        f'「{match_key}」可能對應：\n{listing}\n\n'
        f'回覆數字選擇，確認後才歸類照片。'
    )


def _sanitize_wa_reply(text, *, max_len=320):
    """Strip markdown essay output; keep short WhatsApp-friendly text."""
    if not text:
        return ''
    t = text.strip()
    t = re.sub(r'^#+\s*', '', t, flags=re.MULTILINE)
    t = re.sub(r'\*\*([^*]+)\*\*', r'\1', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    if len(t) > max_len:
        t = t[: max_len - 1].rstrip() + '…'
    return t


def _ollama_polish_message(fallback, prompt):
    if os.environ.get('PROJECT_AI_POLISH', '').lower() not in ('1', 'true', 'yes'):
        return fallback
    try:
        cfg = _get_config()
        strict = (
            f'{prompt}\n\n'
            'Rules: Reply in Traditional Chinese only. Max 2 short sentences. '
            'No markdown, no headings, no bullet lists, no English unless a project code.'
        )
        resp = _call_ollama(cfg['text_model'], strict, base_url=cfg['base_url'])
        text = _sanitize_wa_reply(resp or '')
        return text if text else fallback
    except Exception as exc:
        logger.warning('[ProjectAI] Ollama unavailable: %s', exc)
        return fallback


def _ollama_suggest_project(user_label, catalog):
    """When heuristics find nothing, ask LLM to pick best catalog row or none."""
    if not catalog:
        return None, ''
    lines = '\n'.join(
        f'- id:{p["id"]} code:{p["code"]} folder:{p.get("nasFolder", "")}' for p in catalog[:60]
    )
    prompt = f"""You help match WhatsApp photo uploads to construction project folders.

User typed: "{user_label}"

Active projects (pick at most ONE best match, or none):
{lines}

Return ONLY JSON:
{{"projectId": "<id or empty>", "correctedLabel": "<short guess>", "replyZh": "<one short Traditional Chinese sentence asking 是/確認, no markdown>"}}
If no reasonable match, leave projectId empty."""
    try:
        cfg = _get_config()
        raw = _call_ollama(cfg['text_model'], prompt, base_url=cfg['base_url'])
        data = _parse_structured(raw)
        pid = (data.get('projectId') or '').strip()
        project = None
        if pid:
            try:
                project = mongo.db.wa_projects.find_one({
                    '_id': ObjectId(pid),
                    'status': 'active',
                })
            except Exception:
                project = None
        reply = _sanitize_wa_reply(data.get('replyZh') or '')
        return project, reply
    except Exception as exc:
        logger.warning('[ProjectAI] suggest failed: %s', exc)
        return None, ''


def _suggest_single_project(match_key, project, remark=None):
    label = wa_classify_display_label(project)
    fallback = (
        f'收到「{match_key}」，是否歸入：\n{label}\n'
        f'回覆「是」或「確認」後歸類照片。'
    )
    msg = _ollama_polish_message(fallback, '')
    return ClassifyResolve(
        action='suggest',
        project=project,
        remark=remark,
        user_message=msg,
        needs_confirm=True,
    )


def _expand_candidates_for_duplicate_nas_folders(match_key, candidates):
    """Same site code, multiple physical NAS folders → list each full folder name."""
    from app.services.nas_sync_service import list_physical_site_folders
    from app.services.wa_project_validation import find_project_by_code

    folders = list_physical_site_folders(match_key)
    if len(folders) <= 1:
        return candidates

    base = candidates[0][0] if candidates else None
    if not base and folders[0].get('code'):
        base = find_project_by_code(folders[0]['code'])
    if not base:
        return candidates

    expanded = []
    for row in folders:
        proj = dict(base)
        proj['nasFolderName'] = row['folderName']
        if row.get('parentBucket'):
            proj['nasParentBucket'] = row['parentBucket']
        expanded.append((proj, 100))
    return expanded


def _resolve_assign_for_physical_folders(match_key, ext, remark):
    """Assign only when input matches exactly one physical NAS folder for this site."""
    from app.services.nas_sync_service import list_physical_site_folders
    from app.services.wa_project_validation import find_project_by_code

    physical = list_physical_site_folders(match_key)
    if not physical:
        return None

    norm_key = _normalize_classify_label(match_key)
    exact_rows = [
        r for r in physical
        if _normalize_classify_label(r.get('folderName') or '') == norm_key
    ]

    if len(physical) > 1:
        if len(exact_rows) != 1:
            return None
        row = exact_rows[0]
    elif len(exact_rows) == 1:
        row = exact_rows[0]
    elif (
        ext.project
        and is_wa_classify_target(ext.project)
        and classify_input_matches_full_display(match_key, ext.project)
    ):
        row = physical[0]
    else:
        return None

    base = ext.project if ext.project and is_wa_classify_target(ext.project) else None
    if not base:
        base = find_project_by_code(row.get('code') or '')
    if not base:
        return None

    proj = dict(base)
    proj['nasFolderName'] = row['folderName']
    if row.get('parentBucket'):
        proj['nasParentBucket'] = row['parentBucket']
    return ClassifyResolve(
        action='assign',
        project=proj,
        remark=ext.remark or remark,
        needs_confirm=False,
    )


def coerce_assign_to_confirm(resolve, match_key):
    """Inbound safety net — never assign unless input is the full NAS folder name."""
    if resolve.action != 'assign' or not resolve.project:
        return resolve
    if classify_input_matches_full_display(match_key, resolve.project):
        return resolve
    return _suggest_single_project(
        match_key,
        resolve.project,
        remark=resolve.remark,
    )


def resolve_classify_input(text, *, active_only=True):
    """Resolve user classify line with heuristics + optional Ollama copy."""
    trimmed = ' '.join((text or '').strip().split())
    if not trimmed:
        return ClassifyResolve()

    label, remark = split_classify_label_and_remark(trimmed)
    match_key = label or trimmed

    ext = match_project_ext(trimmed, active_only=active_only)
    site_num = primary_site_number(match_key)
    numeric_site = bool(site_num and match_key.strip().isdigit())

    physical_assign = _resolve_assign_for_physical_folders(match_key, ext, remark)
    if physical_assign:
        return physical_assign
    if (
        ext.project
        and is_wa_classify_target(ext.project)
        and classify_input_matches_full_display(match_key, ext.project)
    ):
        return ClassifyResolve(
            action='assign',
            project=ext.project,
            remark=ext.remark or remark,
            needs_confirm=False,
        )

    candidates = []
    if ext.candidates:
        candidates = [(p, s) for p, s in ext.candidates if is_wa_classify_target(p)]
    elif ext.project and is_wa_classify_target(ext.project):
        candidates = [(ext.project, 90)]

    candidates = _expand_candidates_for_duplicate_nas_folders(match_key, candidates)

    if len(candidates) > 1:
        msg = _build_classify_list_message(match_key, candidates)
        return ClassifyResolve(
            action='list',
            candidates=candidates,
            remark=remark or ext.remark,
            user_message=msg,
            needs_confirm=True,
        )

    if len(candidates) == 1:
        return _suggest_single_project(
            match_key,
            candidates[0][0],
            remark=remark or ext.remark,
        )

    catalog = [
        {
            'id': str(p['_id']),
            'code': p.get('code', ''),
            'nasFolder': p.get('nasFolder') or '',
        }
        for p in list_wa_classify_target_projects(active_only=True, limit=80)
    ]
    suggested, ai_reply = (None, '')
    if not numeric_site:
        suggested, ai_reply = _ollama_suggest_project(match_key, catalog)
    if suggested and is_wa_classify_target(suggested):
        code = suggested.get('code', '')
        fallback = (
            f'找不到「{match_key}」。是否指 *{code}*？\n'
            f'回覆「是」確認，或重新輸入專案編碼。'
        )
        msg = ai_reply if ai_reply and len(ai_reply) <= 200 else fallback
        return ClassifyResolve(
            action='suggest',
            project=suggested,
            remark=remark or ext.remark,
            user_message=msg,
            needs_confirm=True,
        )

    fallback = (
        f'找不到與「{match_key}」相符的專案。\n'
        f'請重新輸入專案編碼或名稱；發送 *projects* 查看列表。'
    )
    return ClassifyResolve(action='none', remark=remark, user_message=fallback)


def ai_confirm_key(group_id, sender):
    prefix = f'g:{group_id}:' if group_id else 'p:'
    return f'wa_ai_confirm:{prefix}{sender}'


def set_ai_confirm(
    group_id,
    sender,
    project,
    remark=None,
    *,
    after_list_pick=False,
    batch_id=None,
    pool_image_ids=None,
    quote_msg_id=None,
):
    from datetime import datetime
    mongo.db.wa_system.update_one(
        {'_id': ai_confirm_key(group_id, sender)},
        {'$set': {
            'projectId': str(project['_id']),
            'code': project.get('code', ''),
            'nasFolderName': (project.get('nasFolderName') or '').strip() or None,
            'nasParentBucket': (project.get('nasParentBucket') or '').strip() or None,
            'remark': remark,
            'afterListPick': after_list_pick,
            'batchId': batch_id,
            'poolImageIds': pool_image_ids or [],
            'quoteMsgId': quote_msg_id,
            'at': datetime.utcnow(),
        }},
        upsert=True,
    )


def clear_ai_confirm(group_id, sender):
    mongo.db.wa_system.delete_one({'_id': ai_confirm_key(group_id, sender)})


def pop_ai_confirm_project(group_id, sender):
    from datetime import datetime
    key = ai_confirm_key(group_id, sender)
    doc = mongo.db.wa_system.find_one_and_delete({'_id': key})
    if not doc:
        return None, None, {}
    age = (datetime.utcnow() - doc['at']).total_seconds()
    if age > AI_CONFIRM_TTL_S:
        return None, None, {}
    pid = doc.get('projectId')
    if not pid:
        return None, None, {}
    project = mongo.db.wa_projects.find_one({'_id': ObjectId(pid), 'status': 'active'})
    remark = doc.get('remark')
    pref_folder = (doc.get('nasFolderName') or '').strip()
    pref_bucket = (doc.get('nasParentBucket') or '').strip()
    if project and (pref_folder or pref_bucket):
        project = dict(project)
        if pref_folder:
            project['nasFolderName'] = pref_folder
        if pref_bucket:
            project['nasParentBucket'] = pref_bucket
    scope = {
        'batchId': doc.get('batchId'),
        'poolImageIds': doc.get('poolImageIds') or [],
        'quoteMsgId': doc.get('quoteMsgId'),
        'nasFolderName': pref_folder or None,
        'nasParentBucket': pref_bucket or None,
    }
    return project, remark, scope


def peek_ai_confirm(group_id, sender):
    from datetime import datetime
    doc = mongo.db.wa_system.find_one({'_id': ai_confirm_key(group_id, sender)})
    if not doc:
        return None
    age = (datetime.utcnow() - doc['at']).total_seconds()
    if age > AI_CONFIRM_TTL_S:
        clear_ai_confirm(group_id, sender)
        return None
    return doc


_AFFIRMATIVE = frozenset({
    '是', '是的', '好', '好的', '确认', '確認', '對', '对', 'y', 'yes', 'ok', 'okay', '1', '確定',
    '嗯', '恩', '可以', '行',
})
_NEGATIVE = frozenset({
    '否', '不', '不要', '取消', 'no', 'n', 'nope',
    '不是', '不对', '不對', '錯', '错了', '錯了', '不用', '不要了', '否認', '否认',
})


def is_negative(text):
    t = (text or '').strip().lower()
    t_plain = re.sub(r'[^\w\u4e00-\u9fff]', '', t)
    if not t_plain:
        return False
    if t_plain in _NEGATIVE or t in _NEGATIVE:
        return True
    if t_plain.startswith('不') and t_plain not in _AFFIRMATIVE:
        return True
    return False


def is_affirmative(text):
    if is_negative(text):
        return False
    t = (text or '').strip().lower()
    t_plain = re.sub(r'[^\w\u4e00-\u9fff]', '', t)
    return t_plain in _AFFIRMATIVE or t in _AFFIRMATIVE


def is_rejection_only(text):
    """Standalone no / wrong-project replies (not a new project code)."""
    t_plain = re.sub(r'[^\w\u4e00-\u9fff]', '', (text or '').strip().lower())
    if not t_plain:
        return False
    if is_negative(text):
        return len(t_plain) <= 6
    return t_plain in {'错', '錯', 'wrong'}
