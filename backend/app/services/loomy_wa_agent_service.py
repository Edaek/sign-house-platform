"""Signhouse Loomy — WhatsApp in-chat agent (MCP tool loop + debounce)."""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from app import mongo
from app.services.pool_receipt_notify_service import phone_match_query

logger = logging.getLogger(__name__)

DEBOUNCE_S = float(os.environ.get('LOOMY_WA_AGENT_DEBOUNCE_S', '3.0'))
INTAKE_DEBOUNCE_S = float(os.environ.get('LOOMY_WA_POOL_INTAKE_DEBOUNCE_S', '0.15'))
TEXT_DEBOUNCE_S = float(os.environ.get('LOOMY_WA_TEXT_DEBOUNCE_S', '0.1'))

_lock = threading.Lock()
_timers: Dict[str, threading.Timer] = {}
_pending: Dict[str, Dict[str, Any]] = {}
_running: set[str] = set()
_agent_app = None


def _task_key(*, phone: str, group_id: Optional[str]) -> str:
    if group_id:
        return f'g:{group_id}:{phone}'
    return f'p:{phone}'


def _open_pool_ids(phone: str, *, group_id: Optional[str] = None, limit: int = 20) -> List[str]:
    from app.services.loomy_pool_batch import latest_unassigned_pool_ids

    ids = latest_unassigned_pool_ids(phone=phone, group_id=group_id)
    return ids[:limit]


def _run_agent_sync(ctx: Dict[str, Any]) -> None:
    from app.services.loomy_wa_mcp_agent import run_mcp_agent

    phone = ctx.get('phone') or ''
    group_id = (ctx.get('group_id') or '').strip() or None
    user_text = (ctx.get('user_text') or '').strip()
    caption = (ctx.get('caption') or '').strip()
    pool_ids = list(ctx.get('pool_ids') or [])
    sender_name = (ctx.get('sender_name') or '').strip()

    if not pool_ids:
        pool_ids = _open_pool_ids(phone, group_id=group_id)

    agent_extra = ctx.get('agent_extra') if isinstance(ctx.get('agent_extra'), dict) else {}
    ctx = {
        'phone': phone,
        'group_id': group_id,
        'user_text': user_text,
        'caption': caption,
        'pool_ids': pool_ids,
        'sender_name': sender_name,
        **agent_extra,
    }
    if not (user_text or caption or pool_ids):
        return

    from app.services.wa_classify_mode import wa_loom_runtime_brain_enabled

    if wa_loom_runtime_brain_enabled():
        ctx_for_loom = {
            **ctx,
            'quoted_msg_id': ctx.get('quoted_msg_id') or '',
            'has_quoted': bool(ctx.get('has_quoted')),
        }
        from app.services.loomy_loom_platform_bridge import (
            loom_platform_fallback_local,
            try_loom_platform_classify,
        )

        loom = try_loom_platform_classify(ctx_for_loom)
        if loom:
            if pool_ids:
                from app.services.loomy_wa_classify_guard import mark_pool_classify_reply

                mark_pool_classify_reply(pool_ids, loom)
            _send_wa(phone, group_id, loom)
            return
        if loom_platform_fallback_local():
            logger.warning(
                '[LoomyWA] WA_INBOUND_CLASSIFY_MODE=loom: platform had no reply; '
                'local Ollama fallback is disabled (use agent mode for local brain)',
            )
        _send_wa(phone, group_id, 'Loom 暫時無法回應，請稍後再試或聯絡管理員。')
        return

    from app.services.loomy_wa_smart_classify import get_active_batch, try_loomy_smart_text

    active = get_active_batch(phone=phone, group_id=group_id)
    if active and active.get('pool_ids'):
        pool_ids = list(active['pool_ids'])
        ctx['pool_ids'] = pool_ids

    if not ctx.get('loom_classify_attempted'):
        from app.services.loomy_loom_platform_bridge import try_loom_platform_classify

        ctx_for_loom = {
            **ctx,
            'quoted_msg_id': ctx.get('quoted_msg_id') or '',
            'has_quoted': bool(ctx.get('has_quoted')),
        }
        loom = try_loom_platform_classify(ctx_for_loom)
        if loom:
            if pool_ids:
                from app.services.loomy_wa_classify_guard import mark_pool_classify_reply

                mark_pool_classify_reply(pool_ids, loom)
            _send_wa(phone, group_id, loom)
            return

    if user_text:
        smart = try_loomy_smart_text(ctx)
        if smart:
            from app.services.loomy_wa_classify_guard import mark_pool_classify_reply

            if pool_ids:
                mark_pool_classify_reply(pool_ids, smart)
            _send_wa(phone, group_id, smart)
            return

    if user_text and pool_ids:
        from app.services.loomy_wa_deterministic_reply import dismiss_open_pool, is_dismiss_intent

        if is_dismiss_intent(user_text):
            from app.services.loomy_wa_smart_classify import try_dismiss_scoped

            dismiss_reply = try_dismiss_scoped(
                phone=phone,
                group_id=group_id,
                text=user_text,
                quoted_msg_id=(ctx.get('quoted_msg_id') or '').strip() or None,
                has_quoted=bool(ctx.get('has_quoted')),
            )
            if dismiss_reply:
                _send_wa(phone, group_id, dismiss_reply)
            return

    classify_caption = caption or (user_text if pool_ids else '')
    if classify_caption and pool_ids:
        from app.services.loomy_wa_mongo_site_classify import try_loomy_mongo_site_classify_reply

        mongo_reply = try_loomy_mongo_site_classify_reply(
            phone=phone,
            caption=classify_caption,
            pool_ids=pool_ids,
            group_id=group_id,
        )
        if mongo_reply:
            from app.services.loomy_wa_classify_guard import mark_pool_classify_reply

            mark_pool_classify_reply(pool_ids, mongo_reply)
            _send_wa(phone, group_id, mongo_reply)
            return

        fast = _try_fast_classify_timed(
            phone=phone,
            caption=classify_caption,
            pool_ids=pool_ids,
            group_id=group_id,
        )
        if fast:
            from app.services.loomy_wa_classify_guard import mark_pool_classify_reply

            mark_pool_classify_reply(pool_ids, fast)
            _send_wa(phone, group_id, fast)
            return

    if user_text or caption:
        from app.services.loomy_wa_deterministic_reply import try_deterministic_loomy_reply

        det = try_deterministic_loomy_reply(ctx)
        if det:
            _send_wa(phone, group_id, det)
            return

    run_mcp_agent(ctx, send_wa=_send_wa)


def _try_fast_classify_timed(
    *,
    phone: str,
    caption: str,
    pool_ids: List[str],
    group_id: Optional[str],
) -> Optional[str]:
    import os
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    from app.services.loomy_wa_fast_classify import try_loomy_fast_classify_reply

    timeout_s = float(os.environ.get('LOOMY_WA_FAST_CLASSIFY_TIMEOUT_S', '12'))
    from flask import current_app

    app = current_app._get_current_object()

    def _run() -> Optional[str]:
        with app.app_context():
            return try_loomy_fast_classify_reply(
                phone=phone,
                caption=caption,
                pool_ids=pool_ids,
                group_id=group_id,
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_run)
        try:
            return fut.result(timeout=timeout_s)
        except FuturesTimeout:
            logger.warning('[LoomyWA] fast classify timed out after %ss (NAS slow?)', timeout_s)
            return None
        except Exception:
            logger.exception('[LoomyWA] fast classify failed')
            return None


def _send_wa(phone: str, group_id: Optional[str], text: str) -> None:
    body = (text or '').strip()
    if not body:
        return
    try:
        from app.services.wa_send_service import (
            send_chat_presence,
            send_group_message,
            send_message,
        )

        send_chat_presence(phone, 'paused', group_id=group_id)
        if group_id:
            send_group_message(group_id, body)
        elif phone:
            send_message(phone, body)
    except Exception:
        logger.exception('[LoomyWA] send failed')


def _flush(key: str) -> None:
    import os
    from app import create_app

    with _lock:
        if key in _running:
            timer = threading.Timer(DEBOUNCE_S, _flush, args=(key,))
            timer.daemon = True
            timer.start()
            _timers[key] = timer
            return
        ctx = _pending.pop(key, None)
        _timers.pop(key, None)
        if ctx:
            _running.add(key)
    if not ctx:
        with _lock:
            _running.discard(key)
        return
    global _agent_app
    if _agent_app is None:
        _agent_app = create_app(os.environ.get('FLASK_CONFIG', 'development'))
    app = _agent_app
    agent_timeout = float(os.environ.get('LOOMY_WA_AGENT_RUN_TIMEOUT_S', '120'))

    phone = ctx.get('phone') or ''
    group_id = (ctx.get('group_id') or '').strip() or None
    from app.services.loomy_wa_classify_guard import clear_loomy_classify_running, mark_loomy_classify_running

    mark_loomy_classify_running(phone=phone, group_id=group_id, pool_ids=ctx.get('pool_ids'))

    def _worker() -> None:
        with app.app_context():
            _run_agent_sync(ctx)

    worker = threading.Thread(target=_worker, daemon=True, name=f'loomy-wa-{key[:24]}')
    worker.start()
    worker.join(timeout=agent_timeout)
    with app.app_context():
        try:
            if worker.is_alive():
                logger.warning('[LoomyWA] agent run timed out after %ss', agent_timeout)
                _send_wa(
                    phone,
                    group_id,
                    'Loomy 處理逾時（可能 NAS 或 AI 較慢）。請稍後再試，或直接在 Media Pool 手動 assign。',
                )
        except Exception:
            logger.exception('[LoomyWA] agent run failed')
        finally:
            clear_loomy_classify_running(phone=phone, group_id=group_id)
            with _lock:
                _running.discard(key)


def schedule_loomy_wa_agent(
    *,
    phone: str,
    user_text: str = '',
    caption: str = '',
    pool_ids: Optional[List[str]] = None,
    group_id: Optional[str] = None,
    sender_name: Optional[str] = None,
    agent_extra: Optional[Dict[str, Any]] = None,
    flush_immediately: bool = False,
) -> None:
    from app.services.wa_classify_mode import wa_inbound_loomy_dispatch_enabled

    if not wa_inbound_loomy_dispatch_enabled():
        return

    key = _task_key(phone=phone, group_id=group_id)
    with _lock:
        entry = _pending.get(key)
        if not entry:
            entry = {
                'phone': phone,
                'group_id': group_id,
                'user_text': '',
                'caption': '',
                'pool_ids': [],
                'sender_name': sender_name,
                'at': datetime.utcnow(),
            }
            _pending[key] = entry
        if user_text.strip():
            entry['user_text'] = user_text.strip()
        if caption.strip():
            entry['caption'] = caption.strip()
        if pool_ids:
            # One intake = one batch; do not merge earlier unassigned uploads.
            entry['pool_ids'] = list(pool_ids)
        if sender_name:
            entry['sender_name'] = sender_name
        if agent_extra:
            prev = entry.get('agent_extra') if isinstance(entry.get('agent_extra'), dict) else {}
            merged = {**prev, **agent_extra}
            entry['agent_extra'] = merged

        existing = _timers.pop(key, None)
        if existing:
            existing.cancel()
        if flush_immediately and user_text.strip():
            delay = TEXT_DEBOUNCE_S
        elif flush_immediately:
            delay = INTAKE_DEBOUNCE_S
        else:
            delay = DEBOUNCE_S
        if flush_immediately and delay <= 0:
            timer = None
            threading.Thread(target=_flush, args=(key,), daemon=True, name=f'loomy-wa-flush-{key[:16]}').start()
        else:
            timer = threading.Timer(delay, _flush, args=(key,))
            timer.daemon = True
            timer.start()
            _timers[key] = timer

def try_loomy_inbound_text_reply(
    phone: str,
    text: str,
    *,
    group_id: Optional[str] = None,
    pool_ids: Optional[List[str]] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Synchronous Loomy text handling (batch pick, direct assign) — returns WA body if handled."""
    from app.services.loomy_wa_smart_classify import (
        get_active_batch,
        try_implicit_batch_pick,
        try_loomy_batch_numeric_pick,
        try_loomy_smart_text,
    )

    payload = data or {}
    quoted = (payload.get('quotedMsgId') or '').strip() or None
    has_quoted = bool(payload.get('hasQuotedMsg'))

    batch_reply = try_loomy_batch_numeric_pick(phone, text, group_id=group_id)
    if batch_reply:
        return batch_reply

    from app.services.loomy_loom_platform_bridge import should_use_loom_platform, try_loom_platform_classify

    loom_ctx = {
        'phone': phone,
        'group_id': group_id,
        'user_text': text,
        'pool_ids': list(pool_ids or []),
        'quoted_msg_id': quoted,
        'has_quoted': has_quoted,
    }
    if should_use_loom_platform(loom_ctx):
        loom_reply = try_loom_platform_classify(loom_ctx)
        if loom_reply:
            return loom_reply

    implicit = try_implicit_batch_pick(phone, text, group_id=group_id)
    if implicit:
        return implicit

    active = get_active_batch(phone=phone, group_id=group_id)
    pids = list(active['pool_ids']) if active and active.get('pool_ids') else list(pool_ids or [])
    if not pids:
        pids = _open_pool_ids(phone, group_id=group_id)

    return try_loomy_smart_text({
        'phone': phone,
        'group_id': group_id,
        'user_text': text,
        'pool_ids': pids,
        'quoted_msg_id': quoted,
        'has_quoted': has_quoted,
    })


def try_loomy_numeric_pick(
    phone: str,
    text: str,
    *,
    group_id: Optional[str] = None,
) -> bool:
    """If user replies 1-9 after agent ask, map to last agent options stored in wa_system."""
    t = (text or '').strip()
    if not t.isdigit() or not (1 <= int(t) <= 9):
        return False

    from app.services.loomy_wa_smart_classify import find_batch_pick

    if find_batch_pick(phone=phone, group_id=group_id):
        return False

    from app.services.loomy_wa_pick_store import find_loomy_wa_pick_doc

    doc = find_loomy_wa_pick_doc(phone=phone, group_id=group_id)
    if not doc or not doc.get('options'):
        return False
    idx = int(t) - 1
    opts = doc['options']
    if idx < 0 or idx >= len(opts):
        return False
    choice = opts[idx]
    pool_ids = list(doc.get('pool_ids') or [])
    pid = (choice.get('project_id') or '').strip()
    if pid and pool_ids:
        from bson import ObjectId
        from bson.errors import InvalidId

        from app.services.image_pool_service import assign_images_to_project
        from app.services.loomy_wa_mongo_site_classify import _assign_success_message

        try:
            proj = mongo.db.wa_projects.find_one({'_id': ObjectId(pid)})
        except InvalidId:
            proj = None
        if proj:
            n = assign_images_to_project(
                pool_ids,
                proj,
                'loomy',
                group_id=group_id,
            )
            if n > 0:
                mongo.db.wa_system.delete_one({'_id': doc['_id']})
                _send_wa(phone, group_id, _assign_success_message(proj, n))
                return True
    schedule_loomy_wa_agent(
        phone=phone,
        group_id=group_id,
        user_text=choice.get('label') or choice.get('code') or t,
        pool_ids=pool_ids,
    )
    mongo.db.wa_system.delete_one({'_id': doc['_id']})
    return True
