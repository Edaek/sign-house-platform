"""Loomy scheduling helpers for wa_inbound (importable without Flask app factory)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def loomy_followup_record_summary(record: dict) -> dict:
    if not record:
        return {}
    thread = record.get('followUpThread') or []
    open_q = ''
    for item in reversed(thread):
        if not item.get('answer'):
            open_q = (item.get('question') or '').strip()
            break
    return {
        'record_id': str(record['_id']),
        'reference_number': record.get('referenceNumber') or '',
        'status': record.get('status') or '',
        'open_followup_question': open_q,
        'follow_up_round': record.get('followUpRound', 0),
    }


def loomy_agent_extra_from_data(data, *, active_record=None, group_id=None) -> Dict[str, Any]:
    payload = data or {}
    extra: Dict[str, Any] = {
        'quoted_msg_id': payload.get('quotedMsgId') or '',
        'has_quoted': bool(payload.get('hasQuotedMsg')),
        'inbound_type': 'group' if group_id else 'private',
        'move_inbound_data': {
            'hasQuotedMsg': bool(payload.get('hasQuotedMsg')),
            'quotedMsgId': payload.get('quotedMsgId') or '',
        },
    }
    if active_record:
        extra['active_wa_record'] = loomy_followup_record_summary(active_record)
    return extra


def schedule_loomy_from_inbound(
    *,
    phone: str,
    user_text: str = '',
    caption: str = '',
    pool_ids: Optional[List[str]] = None,
    group_id: Optional[str] = None,
    sender_name: Optional[str] = None,
    data=None,
    active_record=None,
    loom_classify_attempted: bool = False,
) -> None:
    from app.services.loomy_wa_agent_service import schedule_loomy_wa_agent

    extra = loomy_agent_extra_from_data(data, active_record=active_record, group_id=group_id)
    if loom_classify_attempted:
        extra['loom_classify_attempted'] = True

    schedule_loomy_wa_agent(
        phone=phone,
        group_id=group_id,
        user_text=user_text,
        caption=caption,
        pool_ids=pool_ids,
        sender_name=sender_name,
        agent_extra=extra,
        flush_immediately=bool((user_text or caption or '').strip()),
    )
