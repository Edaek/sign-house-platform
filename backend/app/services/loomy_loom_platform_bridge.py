"""WhatsApp pool classify via Loom platform HTTP (server token; workers need no JWT)."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_CLASSIFY_HINT = re.compile(
    r'歸類|归类|專案|项目|projects?|PJ[-\s]?\d|\d{3,6}|不用|分開|分开|assign',
    re.I,
)


def wa_loom_platform_classify_enabled() -> bool:
    """Optional Jeff HTTP bridge — not used by WA_INBOUND_CLASSIFY_MODE=loom (MCP per-user JWT)."""
    raw = (os.environ.get('LOOMY_WA_LOOM_PLATFORM_CLASSIFY') or '').strip().lower()
    if raw not in ('1', 'true', 'yes', 'on'):
        return False
    return bool((os.environ.get('LOOM_PLATFORM_CHAT_URL') or '').strip())


def loom_platform_fallback_local() -> bool:
    raw = (os.environ.get('LOOMY_WA_LOOM_PLATFORM_FALLBACK_LOCAL') or 'true').strip().lower()
    return raw not in ('0', 'false', 'no', 'off')


def loom_platform_all_turns_enabled() -> bool:
    """Route every WhatsApp agent turn to Loom Platform (same brain as Mattermost), not only pool classify."""
    raw = (os.environ.get('LOOMY_WA_LOOM_PLATFORM_ALL_TURNS') or '').strip().lower()
    return raw in ('1', 'true', 'yes', 'on')


def should_use_loom_platform(ctx: Dict[str, Any]) -> bool:
    if not wa_loom_platform_classify_enabled():
        return False
    if loom_platform_all_turns_enabled():
        return bool(
            (ctx.get('user_text') or ctx.get('caption') or '').strip()
            or ctx.get('pool_ids')
        )
    return is_pool_classify_turn(ctx)


def is_pool_classify_turn(ctx: Dict[str, Any]) -> bool:
    """Only route pool/media classify to Loom — not general chit-chat."""
    if ctx.get('pool_ids'):
        return True
    if (ctx.get('caption') or '').strip():
        return True
    text = (ctx.get('user_text') or '').strip()
    if not text:
        return False
    from app.services.message_parser_service import is_command

    if is_command(text):
        return False
    if _CLASSIFY_HINT.search(text):
        return True
    phone = (ctx.get('phone') or '').strip()
    group_id = (ctx.get('group_id') or '').strip() or None
    from app.services.loomy_wa_deterministic_reply import _open_pool_count

    return _open_pool_count(phone, group_id) > 0


def _session_id(ctx: Dict[str, Any]) -> str:
    phone = (ctx.get('phone') or '').strip()
    group_id = (ctx.get('group_id') or '').strip()
    if group_id:
        return f'wa:g:{group_id}:{phone}'
    return f'wa:p:{phone}'


def loom_inbound_notify_url() -> str:
    """Loom runtime webhook (inbound push). Falls back to LOOM_PLATFORM_CHAT_URL."""
    return (
        (os.environ.get('LOOM_WA_INBOUND_NOTIFY_URL') or '').strip()
        or (os.environ.get('LOOM_PLATFORM_CHAT_URL') or '').strip()
    )


def wa_loom_runtime_notify_configured() -> bool:
    from app.services.wa_classify_mode import wa_loom_runtime_brain_enabled

    return wa_loom_runtime_brain_enabled() and bool(loom_inbound_notify_url())


def _auth_headers() -> dict:
    token = (
        (os.environ.get('LOOM_WA_INBOUND_NOTIFY_BEARER') or '').strip()
        or (os.environ.get('LOOM_PLATFORM_SERVICE_TOKEN') or '').strip()
        or (os.environ.get('LOOM_PLATFORM_API_KEY') or '').strip()
    )
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def _extract_reply(body: Any) -> str:
    if body is None:
        return ''
    if isinstance(body, str):
        return body.strip()
    if not isinstance(body, dict):
        return ''
    path = (os.environ.get('LOOM_PLATFORM_REPLY_JSON_PATH') or '').strip()
    if path:
        cur: Any = body
        for part in path.split('.'):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                cur = None
                break
        if isinstance(cur, str) and cur.strip():
            return cur.strip()
    reply_obj = body.get('reply')
    if isinstance(reply_obj, dict):
        for key in ('zh', 'text', 'reply_zh'):
            val = reply_obj.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    for key in ('reply_zh', 'message', 'text', 'content'):
        val = body.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    if isinstance(reply_obj, str) and reply_obj.strip():
        return reply_obj.strip()
    data = body.get('data')
    if isinstance(data, dict):
        for key in ('reply_zh', 'reply', 'message', 'text'):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return ''


def _extract_actions(body: dict) -> List[dict]:
    actions = body.get('actions') or body.get('tool_calls') or []
    if isinstance(body.get('data'), dict):
        actions = actions or body['data'].get('actions') or []
    if not isinstance(actions, list):
        return []
    out = []
    for row in actions:
        if not isinstance(row, dict):
            continue
        name = (row.get('tool') or row.get('name') or '').strip()
        args = row.get('arguments') or row.get('args') or {}
        if name:
            out.append({'name': name, 'arguments': args if isinstance(args, dict) else {}})
    return out


def _run_loom_actions(actions: List[dict], ctx: Dict[str, Any]) -> None:
    if not actions:
        return
    from mcp_wa.wa_tool_registry import execute_tool, is_tool_allowed

    phone = ctx.get('phone') or ''
    group_id = (ctx.get('group_id') or '').strip() or None
    pool_ids = list(ctx.get('pool_ids') or [])
    for act in actions[:5]:
        name = act.get('name') or ''
        args = dict(act.get('arguments') or {})
        if not is_tool_allowed(name):
            logger.warning('[LoomPlatform] Skipped disallowed tool %s', name)
            continue
        if name == 'wa_assign_pool_images':
            args.setdefault('phone', phone)
            if group_id:
                args.setdefault('group_id', group_id)
            if pool_ids and not args.get('image_ids') and not args.get('pool_image_ids'):
                args['image_ids'] = pool_ids
            args.setdefault('notify_whatsapp', True)
        if name == 'wa_list_pool_images' and phone and 'phone' not in args:
            args['phone'] = phone
        try:
            result = execute_tool(name, args)
            logger.info('[LoomPlatform] Tool %s → %s', name, (result or '')[:200])
        except Exception:
            logger.exception('[LoomPlatform] Tool %s failed', name)


def fetch_project_catalogue_for_loom() -> List[Dict[str, str]]:
    """
    Fresh Mongo project list for Loom classify (no Loom-side cache; no MCP hop).
    Each row: {code, name} for active/non-archived wa_projects.
    """
    from app import mongo

    max_rows = int(os.environ.get('LOOMY_WA_PROJECT_CATALOGUE_MAX', '0') or '0')
    cursor = mongo.db.wa_projects.find(
        {'status': {'$ne': 'archived'}},
        {'code': 1, 'name': 1, '_id': 0},
    ).sort([('code', 1)])
    if max_rows > 0:
        cursor = cursor.limit(max_rows)
    out: List[Dict[str, str]] = []
    for row in cursor:
        code = (row.get('code') or '').strip()
        if not code:
            continue
        name = (row.get('name') or '').strip()
        out.append({'code': code, 'name': name})
    return out


def _include_project_catalogue() -> bool:
    raw = (os.environ.get('LOOMY_WA_PROJECT_CATALOGUE') or 'true').strip().lower()
    return raw not in ('0', 'false', 'no', 'off')


def _pool_ids_for_request(ctx: Dict[str, Any]) -> List[str]:
    phone = (ctx.get('phone') or '').strip()
    group_id = (ctx.get('group_id') or '').strip() or None
    ids = list(ctx.get('pool_ids') or [])[:30]
    if ids:
        return ids
    from app.services.loomy_loom_pending_state import get_pending_assignment

    pending = get_pending_assignment(phone=phone, group_id=group_id)
    if pending and pending.get('poolImageIds'):
        return list(pending['poolImageIds'])[:30]
    return []


def build_loom_classify_payload(ctx: Dict[str, Any]) -> dict:
    phone = (ctx.get('phone') or '').strip()
    group_id = (ctx.get('group_id') or '').strip() or None
    pool_ids = _pool_ids_for_request(ctx)
    from app.services.loomy_loom_pending_state import get_pending_assignment

    pending = get_pending_assignment(phone=phone, group_id=group_id)

    from app.services.wa_classify_mode import wa_loom_runtime_brain_enabled

    channel = (os.environ.get('LOOM_PLATFORM_WA_CHANNEL') or '').strip()
    if not channel:
        if wa_loom_runtime_brain_enabled() or loom_platform_all_turns_enabled():
            channel = 'whatsapp_chat'
        else:
            channel = 'whatsapp_pool_classify'
    intent = 'general' if channel == 'whatsapp_chat' else 'pool_classify'

    payload: Dict[str, Any] = {
        'bot': (os.environ.get('LOOM_PLATFORM_BOT_ID') or 'signhouseloomy').strip(),
        'channel': channel,
        'session_id': _session_id(ctx),
        'message': (ctx.get('user_text') or ctx.get('caption') or '').strip(),
        'poolImageIds': pool_ids,
        'context': {
            'intent': intent,
            'phone': phone,
            'group_id': group_id,
            'sender_name': ctx.get('sender_name') or '',
            'caption': ctx.get('caption') or '',
            'pool_image_ids': pool_ids,
            'quoted_msg_id': ctx.get('quoted_msg_id') or '',
            'has_quoted': bool(ctx.get('has_quoted')),
        },
    }
    if pending:
        payload['pendingAssignment'] = pending
        payload['context']['pendingAssignment'] = pending
    if _include_project_catalogue():
        catalogue = fetch_project_catalogue_for_loom()
        payload['projectCatalogue'] = catalogue
        payload['context']['projectCatalogue'] = catalogue
    if wa_loom_runtime_brain_enabled():
        payload['event'] = 'wa_inbound'
        payload['context']['event'] = 'wa_inbound'
    return payload


def _apply_loom_response_state(body: dict, ctx: Dict[str, Any], *, assigned: bool) -> None:
    phone = (ctx.get('phone') or '').strip()
    group_id = (ctx.get('group_id') or '').strip() or None
    from app.services.loomy_loom_pending_state import (
        clear_pending_assignment,
        set_pending_assignment,
    )

    if assigned:
        clear_pending_assignment(phone=phone, group_id=group_id)
        return

    pending = body.get('pendingAssignment')
    if not isinstance(pending, dict):
        data = body.get('data')
        if isinstance(data, dict):
            pending = data.get('pendingAssignment')
    if not isinstance(pending, dict):
        return

    pids = pending.get('poolImageIds') or pending.get('pool_image_ids') or []
    if pids:
        set_pending_assignment(
            phone=phone,
            group_id=group_id,
            pool_image_ids=[str(x) for x in pids],
            previous_decision=str(pending.get('previousDecision') or pending.get('previous_decision') or ''),
        )


def _loom_chat_timeout_s() -> float:
    raw = (os.environ.get('LOOM_WA_INBOUND_NOTIFY_TIMEOUT_S') or '').strip()
    if raw:
        return float(raw)
    return float(os.environ.get('LOOM_PLATFORM_CHAT_TIMEOUT_S', '90'))


def _process_loom_chat_response(body: Any, ctx: Dict[str, Any]) -> Optional[str]:
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return body.strip() or None

    body_dict = body if isinstance(body, dict) else {}
    actions = _extract_actions(body_dict)
    assigned = False
    if actions:
        for act in actions:
            if (act.get('name') or '') == 'wa_assign_pool_images':
                assigned = True
                break
    _run_loom_actions(actions, ctx)
    _apply_loom_response_state(body_dict, ctx, assigned=assigned)

    reply = _extract_reply(body)
    if reply:
        pool_ids = _pool_ids_for_request(ctx)
        if pool_ids and not assigned:
            from app.services.loomy_loom_pending_state import get_pending_assignment, set_pending_assignment

            if not get_pending_assignment(
                phone=(ctx.get('phone') or '').strip(),
                group_id=(ctx.get('group_id') or '').strip() or None,
            ):
                set_pending_assignment(
                    phone=(ctx.get('phone') or '').strip(),
                    group_id=(ctx.get('group_id') or '').strip() or None,
                    pool_image_ids=pool_ids,
                    previous_decision=reply,
                )
        if pool_ids:
            from app.services.loomy_wa_classify_guard import mark_pool_classify_reply

            mark_pool_classify_reply(pool_ids, reply)
        return reply

    if actions:
        return '已依 Loom 指示處理歸類，請稍候確認訊息。'
    return None


def _post_loom_chat_turn(ctx: Dict[str, Any], *, runtime_inbound: bool) -> Optional[str]:
    url = loom_inbound_notify_url() if runtime_inbound else (os.environ.get('LOOM_PLATFORM_CHAT_URL') or '').strip()
    if not url:
        return None
    timeout = _loom_chat_timeout_s()
    payload = build_loom_classify_payload(ctx)
    try:
        resp = requests.post(url, headers=_auth_headers(), json=payload, timeout=timeout)
        resp.raise_for_status()
        body = resp.json() if resp.content else {}
    except requests.Timeout:
        logger.warning('[LoomPlatform] Chat API timed out after %ss', timeout)
        if runtime_inbound:
            return None
        return None if loom_platform_fallback_local() else 'Loom 歸類服務逾時，請稍後再試。'
    except Exception:
        logger.exception('[LoomPlatform] Chat API request failed')
        if runtime_inbound:
            return None
        return None if loom_platform_fallback_local() else 'Loom 歸類服務暫不可用。'

    reply = _process_loom_chat_response(body, ctx)
    if reply:
        return reply
    if runtime_inbound:
        return None
    return None if loom_platform_fallback_local() else 'Loom 未返回可發送的回覆。'


def try_loom_inbound_turn(ctx: Dict[str, Any]) -> Optional[str]:
    """Push WA inbound to Loom runtime (loom mode); return reply text for WhatsApp if any."""
    if not wa_loom_runtime_notify_configured():
        return None
    if not (
        (ctx.get('user_text') or ctx.get('caption') or '').strip()
        or ctx.get('pool_ids')
    ):
        return None
    return _post_loom_chat_turn(ctx, runtime_inbound=True)


def try_loom_platform_classify(ctx: Dict[str, Any]) -> Optional[str]:
    """
    POST to Loom platform chat API (agent mode + LOOMY_WA_LOOM_PLATFORM_CLASSIFY).
    Returns WhatsApp reply text, or None to fall back to local classify.
    """
    if not should_use_loom_platform(ctx):
        return None
    return _post_loom_chat_turn(ctx, runtime_inbound=False)
