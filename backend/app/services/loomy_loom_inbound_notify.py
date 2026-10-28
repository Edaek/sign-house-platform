"""Push WhatsApp inbound to Loom runtime (HTTP) when WA_INBOUND_CLASSIFY_MODE=loom."""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_pending: Dict[str, Dict[str, Any]] = {}
_timers: Dict[str, threading.Timer] = {}

DEBOUNCE_S = float(os.environ.get('LOOM_WA_INBOUND_NOTIFY_DEBOUNCE_S', '0.2'))


def _task_key(*, phone: str, group_id: Optional[str]) -> str:
    gid = (group_id or '').strip()
    return f'g:{gid}' if gid else f'p:{phone}'


def _send_wa(phone: str, group_id: Optional[str], text: str, *, quoted_msg_id: Optional[str] = None) -> None:
    if not (text or '').strip():
        return
    from app.services.wa_send_service import send_group_message, send_message

    if group_id:
        send_group_message(group_id, text.strip(), quoted_msg_id=quoted_msg_id)
    else:
        send_message(phone, text.strip(), quoted_msg_id=quoted_msg_id)


def _run_notify_sync(ctx: Dict[str, Any]) -> None:
    from app.services.loomy_loom_platform_bridge import try_loom_inbound_turn

    phone = (ctx.get('phone') or '').strip()
    group_id = (ctx.get('group_id') or '').strip() or None
    reply = try_loom_inbound_turn(ctx)
    if reply:
        _send_wa(
            phone,
            group_id,
            reply,
            quoted_msg_id=(ctx.get('quoted_msg_id') or '').strip() or None,
        )
        logger.info('[LoomNotify] Sent WA reply for %s', _task_key(phone=phone, group_id=group_id))
    else:
        logger.info('[LoomNotify] No WA reply from Loom for %s', _task_key(phone=phone, group_id=group_id))


def _flush(key: str) -> None:
    with _lock:
        ctx = _pending.pop(key, None)
        _timers.pop(key, None)
    if not ctx:
        return

    from app import create_app

    app = create_app(os.environ.get('FLASK_CONFIG', 'development'))
    with app.app_context():
        try:
            _run_notify_sync(ctx)
        except Exception:
            logger.exception('[LoomNotify] inbound notify failed for %s', key)


def schedule_loom_runtime_inbound(
    *,
    phone: str,
    user_text: str = '',
    caption: str = '',
    pool_ids: Optional[List[str]] = None,
    group_id: Optional[str] = None,
    sender_name: Optional[str] = None,
    quoted_msg_id: Optional[str] = None,
    has_quoted: bool = False,
    flush_immediately: bool = True,
) -> bool:
    """
    Debounced POST to Loom notify URL. Returns True if scheduled (URL configured + loom mode).
    """
    from app.services.loomy_loom_platform_bridge import wa_loom_runtime_notify_configured

    if not wa_loom_runtime_notify_configured():
        return False

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
                'quoted_msg_id': quoted_msg_id or '',
                'has_quoted': has_quoted,
                'at': datetime.utcnow(),
            }
            _pending[key] = entry
        if user_text.strip():
            entry['user_text'] = user_text.strip()
        if caption.strip():
            entry['caption'] = caption.strip()
        if pool_ids:
            entry['pool_ids'] = list(pool_ids)
        if sender_name:
            entry['sender_name'] = sender_name
        if quoted_msg_id:
            entry['quoted_msg_id'] = quoted_msg_id
        entry['has_quoted'] = has_quoted

        existing = _timers.pop(key, None)
        if existing:
            existing.cancel()

        delay = 0.0 if flush_immediately else DEBOUNCE_S
        if delay <= 0:
            threading.Thread(target=_flush, args=(key,), daemon=True, name=f'loom-notify-{key[:20]}').start()
        else:
            timer = threading.Timer(delay, _flush, args=(key,))
            timer.daemon = True
            timer.start()
            _timers[key] = timer
    return True


def log_loom_runtime_notify_on_startup() -> None:
    from app.services.wa_classify_mode import wa_loom_runtime_brain_enabled
    from app.services.loomy_loom_platform_bridge import loom_inbound_notify_url

    if not wa_loom_runtime_brain_enabled():
        return
    url = loom_inbound_notify_url()
    if url:
        logger.info('[LoomNotify] WA inbound → Loom runtime at %s', url.split('?')[0][:120])
    else:
        logger.warning(
            '[LoomNotify] WA_INBOUND_CLASSIFY_MODE=loom but LOOM_WA_INBOUND_NOTIFY_URL '
            '(or LOOM_PLATFORM_CHAT_URL) is unset — WhatsApp will not auto-reply',
        )
