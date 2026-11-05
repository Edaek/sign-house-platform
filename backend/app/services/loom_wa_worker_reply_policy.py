"""Gate worker-visible WhatsApp: no interim「收到/我去 pool」before MCP (brain=loom).

Works with Wakka→Loom Turn only — does not require LOOM_WA_INBOUND_NOTIFY_URL.
Gateway pool intake registers「图已在 Pool」; Loom must call wa_list_pool_images (or
wa_inbound_reply_policy) before workerWhatsAppPolicy.allowWorkerWhatsAppNow becomes true.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.services.wa_time import wa_now

logger = logging.getLogger(__name__)

SESSION_TTL_S = 600
_DOC_KIND = 'loom_wa_reply_gate'


def _session_id(*, phone: str, group_id: Optional[str] = None) -> str:
    p = (phone or '').strip()
    gid = (group_id or '').strip()
    if gid:
        return f'wa:reply_gate:g:{gid}:{p}'
    return f'wa:reply_gate:p:{p}'


def _open_unassigned_count(*, phone: str, group_id: Optional[str] = None) -> int:
    from app.services.pool_receipt_notify_service import phone_match_query

    if not (phone or '').strip():
        return 0
    try:
        from app import mongo

        q: dict[str, Any] = {
            'projectId': {'$exists': False},
            'dismissed': {'$ne': True},
            **phone_match_query(phone),
        }
        if group_id and '@g.us' in group_id:
            q['chatJid'] = group_id.strip()
        return mongo.db.pool_images.count_documents(q)
    except Exception:
        logger.debug('[WAReplyPolicy] pool count failed', exc_info=True)
        return 0


def register_gateway_pool_intake(
    *,
    phone: str,
    group_id: Optional[str] = None,
    inbound_message_id: Optional[str] = None,
) -> None:
    """Call after Gateway writes pool_images (图已在 Media Pool)."""
    if not (phone or '').strip():
        return
    sid = _session_id(phone=phone, group_id=group_id)
    now = wa_now()
    try:
        from app import mongo

        mongo.db.wa_system.update_one(
            {'_id': sid},
            {
                '$set': {
                    'kind': _DOC_KIND,
                    'phone': phone.strip(),
                    'groupId': (group_id or '').strip() or None,
                    'poolIntakeAt': now,
                    'inboundMessageId': (inbound_message_id or '').strip() or None,
                    'listPoolCalledAt': None,
                    'updatedAt': now,
                },
            },
            upsert=True,
        )
        logger.info('[WAReplyPolicy] Pool intake registered for %s', sid[:64])
    except Exception:
        logger.debug('[WAReplyPolicy] register intake failed', exc_info=True)


def mark_list_pool_called(*, phone: str, group_id: Optional[str] = None) -> None:
    if not (phone or '').strip():
        return
    sid = _session_id(phone=phone, group_id=group_id)
    now = wa_now()
    try:
        from app import mongo

        mongo.db.wa_system.update_one(
            {'_id': sid},
            {
                '$set': {'listPoolCalledAt': now, 'updatedAt': now},
                '$setOnInsert': {
                    'kind': _DOC_KIND,
                    'phone': phone.strip(),
                    'groupId': (group_id or '').strip() or None,
                },
            },
            upsert=True,
        )
    except Exception:
        logger.debug('[WAReplyPolicy] mark list_pool failed', exc_info=True)


def _session_row(*, phone: str, group_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    try:
        from app import mongo

        sid = _session_id(phone=phone, group_id=group_id)
        return mongo.db.wa_system.find_one({'_id': sid})
    except Exception:
        return None


def build_worker_whatsapp_policy(
    *,
    phone: str,
    group_id: Optional[str] = None,
    list_pool_just_called: bool = False,
    duplicate_inbound_turn: bool = False,
) -> dict[str, Any]:
    from app.services.wa_classify_mode import wa_loom_runtime_brain_enabled

    if not wa_loom_runtime_brain_enabled():
        return {}

    if list_pool_just_called:
        mark_list_pool_called(phone=phone, group_id=group_id)

    row = _session_row(phone=phone, group_id=group_id) or {}
    open_pool = _open_unassigned_count(phone=phone, group_id=group_id)
    list_at = row.get('listPoolCalledAt')
    pool_intake_at = row.get('poolIntakeAt')
    pool_already = bool(pool_intake_at) or open_pool > 0

    # Chit-chat / no open pool: one WA after any MCP is fine.
    if duplicate_inbound_turn:
        allow = False
        reason = 'duplicate_inbound_turn'
    elif open_pool <= 0:
        allow = True
        reason = 'no_open_pool'
    else:
        allow = bool(list_at)
        reason = 'list_pool_required' if not allow else 'list_pool_done'

    instruction = (
        'Call wa_list_pool_images (or wa_inbound_reply_policy) BEFORE any worker WhatsApp. '
        'Do NOT send interim lines like「收到」「我去 pool 睇下」— the image is already in Media Pool if Gateway ran. '
        'When allowWorkerWhatsAppNow is true, send exactly ONE 繁中 message with the result.'
    )
    if duplicate_inbound_turn:
        instruction = 'duplicateInboundTurn — SILENCE; do not send any WhatsApp this turn.'
    elif allow:
        instruction = (
            'allowWorkerWhatsAppNow=true — send exactly ONE WhatsApp message (繁中) with MCP facts. '
            'Do not send a second bubble or a separate「收到/正在做」.'
        )
    elif pool_already and not list_at:
        instruction = (
            'Media Pool already has unassigned images for this sender. '
            'SILENCE on WhatsApp until wa_list_pool_images returns — never say「我去 pool 睇下」.'
        )

    return {
        'workerWhatsAppPolicy': {
            'maxMessagesPerInbound': 1,
            'allowWorkerWhatsAppNow': allow,
            'forbidInterimBeforeMcp': True,
            'poolAlreadyInMediaPool': bool(pool_intake_at),
            'openUnassignedPoolCount': open_pool,
            'reason': reason,
            'requiredBeforeFirstWorkerSend': (
                [] if allow else ['wa_list_pool_images']
            ),
            'forbiddenInterimExamples': [
                '收到，我去 pool 睇下',
                '收到 1005 呢張',
                '正在查 pool',
            ],
            'instruction': instruction,
            'notifyUrlNotRequired': True,
            'architectureNote': (
                'Wakka→Loom Turn + Sign House Gateway for pool only is supported; '
                'LOOM_WA_INBOUND_NOTIFY_URL is optional.'
            ),
        },
    }


def merge_policy_into_payload(
    payload: dict[str, Any],
    *,
    phone: str,
    group_id: Optional[str] = None,
    list_pool_just_called: bool = False,
) -> dict[str, Any]:
    policy = build_worker_whatsapp_policy(
        phone=phone,
        group_id=group_id,
        list_pool_just_called=list_pool_just_called,
        duplicate_inbound_turn=bool(payload.get('duplicateInboundTurn')),
    )
    if policy:
        payload.update(policy)
    return payload
