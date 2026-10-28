"""Notify Mattermost (Signhouse Loomy channel) when new WA pool media needs classify."""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

DEBOUNCE_S = float(os.environ.get('LOOMY_POOL_NOTIFY_DEBOUNCE_S', '5.0'))

_lock = threading.Lock()
_timers: Dict[str, threading.Timer] = {}
_pending: Dict[str, Dict[str, Any]] = {}


def _webhook_url() -> str:
    return (os.environ.get('MATTERMOST_POOL_WEBHOOK_URL') or '').strip()


def _pending_key(*, phone: str, group_id: Optional[str], group_sender: Optional[str]) -> str:
    if group_id:
        gs = (group_sender or phone or '').strip()
        return f'g:{group_id}:{gs}'
    return f'p:{(phone or "").strip()}'


def _format_mm_text(entry: Dict[str, Any]) -> str:
    n = entry.get('count') or len(entry.get('pool_ids') or [])
    phone = entry.get('phone') or ''
    sender_name = (entry.get('sender_name') or '').strip()
    group_id = (entry.get('group_id') or '').strip()
    caption = (entry.get('caption_preview') or '').strip()
    ids: List[str] = list(entry.get('pool_ids') or [])

    who = sender_name or phone or '未知發送者'
    lines = [
        f'**WhatsApp 圖池待歸類**（{n} 個檔案）',
        f'- 發送者：{who}' + (f' (`{phone}`)' if phone and sender_name else ''),
    ]
    if group_id:
        lines.append(f'- WhatsApp 群：`{group_id}`')
    if caption:
        preview = caption if len(caption) <= 240 else caption[:237] + '…'
        lines.append(f'- 說明：{preview}')
    if ids:
        show = ids[:8]
        lines.append(f'- imageIds：`{", ".join(show)}`' + (' …' if len(ids) > 8 else ''))
    lines.append('')
    lines.append(
        '請在 Mattermost @signhouseloomy 歸類，例如：'
        '「列出未歸類圖池」→ `wa_list_pool_images` → `wa_assign_pool_images`。'
    )
    if group_id:
        lines.append(f'assign 後可用 `wa_send_group_message` 通知群 `{group_id}`。')
    return '\n'.join(lines)


def schedule_loomy_pool_notify(
    *,
    pool_ids: List[str],
    phone: str = '',
    sender_name: Optional[str] = None,
    group_id: Optional[str] = None,
    group_sender: Optional[str] = None,
    caption: Optional[str] = None,
) -> None:
    from app.services.wa_classify_mode import mattermost_pool_notify_enabled

    if not pool_ids or not mattermost_pool_notify_enabled():
        return
    if not _webhook_url():
        logger.debug('[LoomyNotify] MATTERMOST_POOL_WEBHOOK_URL not set')
        return

    key = _pending_key(phone=phone, group_id=group_id, group_sender=group_sender)
    cap = (caption or '').strip()

    with _lock:
        entry = _pending.get(key)
        if not entry:
            entry = {
                'phone': phone,
                'sender_name': sender_name,
                'group_id': group_id,
                'group_sender': group_sender,
                'caption_preview': cap,
                'pool_ids': [],
                'count': 0,
            }
            _pending[key] = entry
        entry['pool_ids'].extend(pool_ids)
        entry['count'] = len(entry['pool_ids'])
        if cap and not entry.get('caption_preview'):
            entry['caption_preview'] = cap

        existing = _timers.pop(key, None)
        if existing:
            existing.cancel()
        timer = threading.Timer(DEBOUNCE_S, _flush, args=(key,))
        timer.daemon = True
        timer.start()
        _timers[key] = timer


def _flush(key: str) -> None:
    with _lock:
        entry = _pending.pop(key, None)
        _timers.pop(key, None)
    if not entry:
        return

    url = _webhook_url()
    if not url:
        return

    text = _format_mm_text(entry)
    try:
        resp = requests.post(
            url,
            data=json.dumps({'text': text, 'username': 'Sign House WA'}),
            headers={'Content-Type': 'application/json'},
            timeout=15,
        )
        if resp.status_code >= 400:
            logger.warning('[LoomyNotify] Webhook HTTP %s: %s', resp.status_code, resp.text[:200])
        else:
            logger.info('[LoomyNotify] Posted pool notify (%d ids)', entry.get('count'))
    except Exception:
        logger.exception('[LoomyNotify] Webhook post failed')


def send_loomy_wa_ack(
    *,
    phone: Optional[str] = None,
    group_id: Optional[str] = None,
    group_sender: Optional[str] = None,
    quote_msg_id: Optional[str] = None,
    text: Optional[str] = None,
) -> None:
    """Optional one-line ack on WhatsApp when media enters pool (loomy mode)."""
    from app.services.wa_classify_mode import loomy_wa_pool_ack, wa_inbound_loomy_dispatch_enabled

    if not wa_inbound_loomy_dispatch_enabled():
        return
    body = (text or loomy_wa_pool_ack()).strip()
    if not body:
        return
    try:
        if group_id:
            from app.services.wa_send_service import send_group_message

            send_group_message(
                group_id,
                body,
                quoted_msg_id=quote_msg_id,
            )
        elif phone:
            from app.services.wa_send_service import send_message

            send_message(phone, body, quoted_msg_id=quote_msg_id)
    except Exception:
        logger.exception('[LoomyNotify] WA ack send failed')
