"""Inbound message handler — receives forwarded messages from the Gateway process."""
import os
import re
import time
import hashlib
import logging
import threading
from datetime import datetime

from flask import Blueprint, jsonify, request, current_app
from bson import ObjectId
from app import mongo
from app.services.message_parser_service import is_command
from app.services.wa_send_service import send_message, send_group_message, download_media
from app.services.image_pool_service import (
    save_to_pool, match_project, match_project_ext, assign_all_unassigned,
    assign_images_to_project, move_images_to_project, MatchResult,
)
from app.services.extraction_runner_service import run_extraction
from app.services.followup_service import handle_follow_up_reply, send_follow_up
from app.services.project_ai_resolve_service import (
    coerce_assign_to_confirm,
    resolve_classify_input,
    set_ai_confirm,
    clear_ai_confirm,
    peek_ai_confirm,
    pop_ai_confirm_project,
    is_affirmative,
    is_negative,
    is_rejection_only,
)
from app.services.project_number_match_service import classify_input_matches_full_display
from mcp_wa.loomy_wa_inbound_bridge import schedule_loomy_from_inbound as _schedule_loomy_from_inbound

logger = logging.getLogger(__name__)

wa_inbound_bp = Blueprint('wa_inbound', __name__)

_processed = {}  # type: dict
DEDUP_TTL = 300

_media_lock_guard = threading.Lock()
_media_locks = {}  # sender key -> Lock (serialize multi-PDF bursts)


def _media_lock(sender_key: str):
    with _media_lock_guard:
        if sender_key not in _media_locks:
            _media_locks[sender_key] = threading.Lock()
        return _media_locks[sender_key]


def _claim(msg_id):
    if not msg_id:
        return True
    now = time.time()
    stale = [k for k, v in _processed.items() if now - v > DEDUP_TTL]
    for k in stale:
        del _processed[k]
    if msg_id in _processed:
        return False
    _processed[msg_id] = now
    return True


def _strip_phone(phone):
    """Match gateway burst keys / pool receipt pending keys (digits-only)."""
    if not phone:
        return ''
    base = re.sub(r'@(c\.us|s\.whatsapp\.net|lid)$', '', phone, flags=re.I)
    digits = re.sub(r'\D', '', base)
    return digits or base


def _lid_digits_from_message_id(message_id):
    if not message_id:
        return ''
    m = re.search(r'(\d+)@lid', str(message_id), flags=re.I)
    return m.group(1) if m else ''


def _canonical_private_sender(sender, data):
    """Map WhatsApp @lid JIDs to the phone already stored on pool_images."""
    from app.services.pool_receipt_notify_service import phone_match_query

    digits = _strip_phone(sender)
    if not digits:
        return sender

    open_q = {'projectId': {'$exists': False}, **phone_match_query(digits)}
    if mongo.db.pool_images.count_documents(open_q) > 0:
        return digits

    lid = _lid_digits_from_message_id((data or {}).get('messageId'))
    raw_from = ((data or {}).get('from') or '').lower()
    if not lid and '@lid' in raw_from:
        lid = digits

    if lid:
        doc = mongo.db.pool_images.find_one(
            {
                'projectId': {'$exists': False},
                'messageId': {'$regex': re.escape(lid) + r'@lid', '$options': 'i'},
            },
            sort=[('createdAt', -1)],
            projection={'phone': 1},
        )
        if doc and doc.get('phone'):
            return _strip_phone(doc['phone'])

    return digits


def _safe_send(to, text, quoted_msg_id=None, chat_jid=None):
    try:
        recipient = chat_jid or to
        send_message(recipient, text, quoted_msg_id=quoted_msg_id)
    except Exception as e:
        logger.error('[Inbound] Failed to send to %s: %s', to, e)


def _lookup_active_project(text):
    return match_project(text, active_only=True)


def _group_pending_for_sender(group_id, sender):
    return mongo.db.group_pending_images.find_one(
        {'groupId': group_id, 'senderPhone': sender, 'categorized': False},
        sort=[('createdAt', -1)],
    )


def _warn_unknown_group_project(group_id, label):
    try:
        send_group_message(
            group_id,
            f'⚠️ 找不到專案「{label}」。請確認專案編碼或名稱是否正確。\n發送 *projects* 查看專案列表。',
        )
    except Exception:
        pass


def _group_batch_id(group_id, sender, now):
    last_img = mongo.db.group_pending_images.find_one(
        {'groupId': group_id, 'senderPhone': sender, 'categorized': False},
        sort=[('createdAt', -1)],
    )
    batch_id = f'{group_id}::{sender}::{int(now.timestamp() * 1000)}'
    if last_img and last_img.get('batchId') and (now - last_img['createdAt']).total_seconds() <= 5:
        batch_id = last_img['batchId']
    return batch_id


def _pool_media_kwargs(data):
    return {'wa_type': data.get('type'), 'mime_type': data.get('mimeType')}


_FILENAME_LIKE = re.compile(
    r'\.(pdf|docx?|xlsx?|pptx?|png|jpe?g|gif|webp|heic|mp4|mov|3gp|zip|rar|txt|csv)$',
    re.IGNORECASE,
)


def _looks_like_filename(label):
    s = (label or '').strip()
    if not s:
        return False
    if '/' in s or '\\' in s:
        return True
    return bool(_FILENAME_LIKE.search(s))


def _burst_cache_id(group_id, sender):
    if group_id:
        return f'wa_burst:g:{group_id}:{sender}'
    return f'wa_burst:p:{sender}'


def _burst_ttl_seconds(extended=False):
    if extended:
        try:
            return int(current_app.config.get('WA_BURST_PROJECT_TTL_S', 120))
        except RuntimeError:
            return int(os.environ.get('WA_BURST_PROJECT_TTL_S', '120'))
    return 15


def _set_burst_project(group_id, sender, project, *, extended=False):
    fields = {
        'code': project['code'],
        'projectId': project['_id'],
        'at': datetime.utcnow(),
    }
    update = {'$set': fields}
    if extended:
        update['$set']['extended'] = True
    else:
        update['$unset'] = {'extended': ''}
    mongo.db.wa_system.update_one(
        {'_id': _burst_cache_id(group_id, sender)},
        update,
        upsert=True,
    )


def _clear_burst_project(group_id, sender):
    mongo.db.wa_system.delete_one({'_id': _burst_cache_id(group_id, sender)})


def _get_burst_project(group_id, sender, max_age_s=None):
    doc = mongo.db.wa_system.find_one({'_id': _burst_cache_id(group_id, sender)})
    if not doc or not doc.get('projectId') or not doc.get('at'):
        return None
    ttl = max_age_s
    if ttl is None:
        ttl = _burst_ttl_seconds(extended=bool(doc.get('extended')))
    age = (datetime.utcnow() - doc['at']).total_seconds()
    if age > ttl:
        return None
    return mongo.db.wa_projects.find_one({'_id': doc['projectId'], 'status': 'active'})


# ---------------------------------------------------------------------------
# Classify intent — user text may arrive before pending rows / burst flush
# ---------------------------------------------------------------------------

_CLASSIFY_INTENT_TTL = 120


def _classify_intent_key(group_id, sender):
    if group_id:
        return f'wa_classify_intent:g:{group_id}:{sender}'
    return f'wa_classify_intent:p:{sender}'


def _open_pool_query(sender):
    from app.services.pool_receipt_notify_service import phone_match_query
    return {'projectId': {'$exists': False}, 'dismissed': {'$ne': True}, **phone_match_query(sender)}


def _set_classify_intent(group_id, sender, text):
    trimmed = (text or '').strip()
    if not trimmed:
        return
    mongo.db.wa_system.update_one(
        {'_id': _classify_intent_key(group_id, sender)},
        {'$set': {'text': trimmed, 'at': datetime.utcnow()}},
        upsert=True,
    )
    if not group_id:
        _cancel_scheduled_receipt(phone=sender)


def _pop_classify_intent(group_id, sender):
    key = _classify_intent_key(group_id, sender)
    doc = mongo.db.wa_system.find_one_and_delete({'_id': key})
    if not doc or not doc.get('text'):
        return None
    age = (datetime.utcnow() - doc['at']).total_seconds()
    if age > _CLASSIFY_INTENT_TTL:
        return None
    return str(doc['text']).strip()


def _peek_classify_intent(group_id, sender):
    doc = mongo.db.wa_system.find_one({'_id': _classify_intent_key(group_id, sender)})
    if not doc or not doc.get('text'):
        return None
    age = (datetime.utcnow() - doc['at']).total_seconds()
    if age > _CLASSIFY_INTENT_TTL:
        return None
    return str(doc['text']).strip()


def _clear_classify_intent(group_id, sender):
    mongo.db.wa_system.delete_one({'_id': _classify_intent_key(group_id, sender)})


def _cancel_scheduled_receipt(*, phone=None, group_id=None, group_sender=None, batch_id=None):
    from app.services.pool_receipt_notify_service import (
        cancel_pool_receipt_for_group_sender,
        cancel_pool_receipt_for_phone,
    )

    if group_id and group_sender:
        cancel_pool_receipt_for_group_sender(group_id, group_sender, batch_id=batch_id)
    elif phone:
        cancel_pool_receipt_for_phone(phone, batch_id=batch_id)


def _group_has_uncategorized(group_id, sender):
    return mongo.db.group_pending_images.count_documents({
        'groupId': group_id,
        'senderPhone': sender,
        'categorized': False,
    }) > 0


def _try_classify_group_from_burst(group_id, sender, data):
    """Text may set extended burst while forwarded album is still downloading."""
    burst_proj = _get_burst_project(group_id, sender)
    if not burst_proj or not _group_has_uncategorized(group_id, sender):
        return False
    pending = _group_pending_for_sender(group_id, sender)
    _categorize_group_image(pending, burst_proj, group_id, data, sender)
    _clear_classify_intent(group_id, sender)
    return True


def _try_apply_stored_classify_intent_group(group_id, sender, data, batch_id=None):
    """Apply text sent before group_pending existed; True if no receipt needed."""
    text = _pop_classify_intent(group_id, sender)
    if not text:
        return False
    pending = _group_pending_for_sender(group_id, sender)
    if not pending:
        _set_classify_intent(group_id, sender, text)
        return False

    project, remark, kind = _apply_classify_resolve(
        text, to=sender, group_id=group_id, sender=sender,
    )
    if kind == 'assign' and project:
        resp = _categorize_group_image(pending, project, group_id, data, sender)
        _cancel_scheduled_receipt(group_id=group_id, group_sender=sender, batch_id=batch_id)
        return resp is not None
    if kind in ('pool_ai_list', 'pool_ai_confirm', 'pool_no_match'):
        _cancel_scheduled_receipt(group_id=group_id, group_sender=sender, batch_id=batch_id)
        return True
    _set_classify_intent(group_id, sender, text)
    return False


def _try_apply_stored_classify_intent_private(sender, data):
    text = _pop_classify_intent(None, sender)
    if not text:
        return False
    has_unassigned = mongo.db.pool_images.count_documents(_open_pool_query(sender)) > 0
    if not has_unassigned:
        _set_classify_intent(None, sender, text)
        return False

    ctx = _latest_unassigned_pool_context(sender)
    project, remark, kind = _apply_classify_resolve(
        text,
        to=sender,
        quote_msg_id=ctx['quote'],
        batch_id=ctx['batch_id'],
        pool_image_ids=ctx['pool_ids'],
    )
    if kind == 'assign' and project:
        _assign_unassigned_for_reply(sender, project, data)
        _cancel_scheduled_receipt(phone=sender)
        return True
    if kind in ('pool_ai_list', 'pool_ai_confirm', 'pool_no_match'):
        _cancel_scheduled_receipt(phone=sender, batch_id=ctx.get('batch_id'))
        return True
    _set_classify_intent(None, sender, text)
    return False


# ---------------------------------------------------------------------------
# Fuzzy-choice pending state — when user gets a numbered list of candidates
# ---------------------------------------------------------------------------

_FUZZY_CHOICE_TTL = 120  # seconds


def _fuzzy_choice_key(group_id, sender):
    prefix = f'g:{group_id}:' if group_id else 'p:'
    return f'wa_fuzzy_choice:{prefix}{sender}'


def _set_fuzzy_choice(group_id, sender, candidates):
    """Store candidate list so the user can reply with a number."""
    choices = [
        {
            'code': p['code'],
            'nasFolder': p.get('nasFolder') or '',
            'nasFolderName': (p.get('nasFolderName') or '').strip(),
            'nasParentBucket': (p.get('nasParentBucket') or '').strip(),
            'id': str(p['_id']),
        }
        for p, _score in candidates
    ]
    mongo.db.wa_system.update_one(
        {'_id': _fuzzy_choice_key(group_id, sender)},
        {'$set': {'choices': choices, 'at': datetime.utcnow()}},
        upsert=True,
    )


def _pop_fuzzy_choice(group_id, sender, selection):
    """Resolve a numeric selection (1-based). Returns project doc or None."""
    key = _fuzzy_choice_key(group_id, sender)
    doc = mongo.db.wa_system.find_one_and_delete({'_id': key})
    if not doc or not doc.get('choices'):
        return None
    age = (datetime.utcnow() - doc['at']).total_seconds()
    if age > _FUZZY_CHOICE_TTL:
        return None
    idx = selection - 1
    if idx < 0 or idx >= len(doc['choices']):
        return None
    choice = doc['choices'][idx]
    project = mongo.db.wa_projects.find_one({'_id': ObjectId(choice['id']), 'status': 'active'})
    if not project:
        return None
    fn = (choice.get('nasFolderName') or '').strip()
    parent = (choice.get('nasParentBucket') or '').strip()
    if fn or parent:
        project = dict(project)
        if fn:
            project['nasFolderName'] = fn
        if parent:
            project['nasParentBucket'] = parent
    return project


def _clear_fuzzy_choice(group_id, sender):
    mongo.db.wa_system.delete_one({'_id': _fuzzy_choice_key(group_id, sender)})


def _format_fuzzy_candidates(candidates):
    """Build a numbered list string for bot reply."""
    from app.services.project_number_match_service import wa_classify_list_labels

    projs = [p for p, _score in candidates]
    labels = wa_classify_list_labels(projs, max_len=500)
    return '\n'.join(f'{i}. {lab}' for i, lab in enumerate(labels, 1))


def _quoted_id_variants(quoted_id):
    """Return full + short stanza forms of a WhatsApp message ID."""
    if not quoted_id:
        return []
    raw = str(quoted_id)
    parts = raw.split('_')
    short_id = parts[2] if len(parts) >= 3 else None
    return [i for i in [raw, short_id] if i]


def _record_bot_prompt_msg(group_id, sender, send_resp):
    """Remember outbound bot message IDs so quoting the bot finds pending photos."""
    if not group_id or not sender or not isinstance(send_resp, dict):
        return
    msg_id = send_resp.get('messageId') or send_resp.get('id') or ''
    if not msg_id:
        return
    variants = _quoted_id_variants(msg_id)
    if variants:
        mongo.db.group_pending_images.update_many(
            {'groupId': group_id, 'senderPhone': sender, 'categorized': False},
            {'$push': {'botReminderMsgIds': {'$each': variants}}},
        )


def _record_private_pool_prompt(phone, send_resp):
    """Register bot prompt IDs on unassigned pool rows (private chat quote-to-classify)."""
    if not phone:
        return
    from app.services.pool_receipt_notify_service import mark_pool_images_reminded

    mark_pool_images_reminded(phone, send_resp if isinstance(send_resp, dict) else None)


def _pool_msg_id(data, idx, base_msg_id):
    ids = data.get('messageIds') or []
    if idx < len(ids):
        return ids[idx]
    return base_msg_id if idx == 0 else f'{base_msg_id}#{idx}'


def _quote_msg_id(data):
    ids = data.get('messageIds') or []
    if ids:
        return ids[0]
    return data.get('messageId')


def _pool_receipt_body():
    from app.services.pool_receipt_notify_service import format_pool_receipt_template

    return format_pool_receipt_template()


def _loomy_after_pool_intake(
    pool_ids,
    *,
    phone='',
    sender_name=None,
    group_id=None,
    group_sender=None,
    caption=None,
    quote_msg_id=None,
):
    import os

    from app.services.wa_classify_mode import (
        loomy_wa_pool_ack,
        mattermost_pool_notify_enabled,
        wa_loomy_agent_enabled,
    )

    if not pool_ids or not wa_loomy_agent_enabled():
        return

    from app.services.pool_receipt_notify_service import (
        cancel_pool_receipt_for_group_sender,
        cancel_pool_receipt_for_phone,
    )

    if group_id and group_sender:
        cancel_pool_receipt_for_group_sender(group_id, group_sender or phone or '')
    elif phone or group_sender:
        cancel_pool_receipt_for_phone(phone or group_sender or '')

    from app.services.wa_send_service import send_group_message, send_message

    processing = (
        os.environ.get('LOOMY_WA_PROCESSING_ACK') or '⏳ Loomy 正在處理這張照片（專案匹配 / 歸類）…'
    ).strip()
    cap = (caption or '').strip()
    sender_phone = phone or group_sender or ''
    classify_handled = False

    if cap and pool_ids:
        try:
            from app.services.loomy_loom_platform_bridge import try_loom_platform_classify

            loom_reply = try_loom_platform_classify({
                'phone': sender_phone,
                'group_id': group_id,
                'caption': cap,
                'pool_ids': pool_ids,
                'sender_name': sender_name,
            })
            if loom_reply:
                if group_id:
                    send_group_message(group_id, loom_reply, quoted_msg_id=quote_msg_id)
                else:
                    send_message(sender_phone, loom_reply, quoted_msg_id=quote_msg_id)
                classify_handled = True
        except Exception:
            logger.exception('[Inbound] Loom platform classify failed')

    if cap and pool_ids and not classify_handled:
        try:
            import os
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

            from app.services.loomy_wa_classify_guard import mark_pool_classify_reply
            from app.services.loomy_wa_mongo_site_classify import try_loomy_mongo_site_classify_reply

            sync_timeout = float(os.environ.get('LOOMY_WA_SYNC_CLASSIFY_TIMEOUT_S', '8'))

            def _sync_classify():
                return try_loomy_mongo_site_classify_reply(
                    phone=sender_phone,
                    caption=cap,
                    pool_ids=pool_ids,
                    group_id=group_id,
                )

            reply = None
            with ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(_sync_classify)
                try:
                    reply = fut.result(timeout=sync_timeout)
                except FuturesTimeout:
                    logger.warning('[Inbound] Loomy sync classify timed out after %ss', sync_timeout)

            if reply:
                mark_pool_classify_reply(pool_ids, reply)
                if group_id:
                    send_group_message(group_id, reply, quoted_msg_id=quote_msg_id)
                else:
                    send_message(sender_phone, reply, quoted_msg_id=quote_msg_id)
                classify_handled = True
        except Exception:
            logger.exception('[Inbound] Loomy sync mongo classify failed')

    if processing and not classify_handled:
        try:
            if group_id:
                send_group_message(group_id, processing, quoted_msg_id=quote_msg_id)
            else:
                send_message(sender_phone, processing, quoted_msg_id=quote_msg_id)
        except Exception:
            logger.exception('[Inbound] Loomy processing ack failed')

    if not classify_handled:
        from app.services.loomy_wa_agent_service import schedule_loomy_wa_agent

        schedule_loomy_wa_agent(
            phone=sender_phone,
            group_id=group_id,
            caption=cap,
            pool_ids=pool_ids,
            sender_name=sender_name,
            flush_immediately=bool(cap and pool_ids),
        )

    ack = loomy_wa_pool_ack()
    if ack:
        from app.services.loomy_pool_notify_service import send_loomy_wa_ack

        send_loomy_wa_ack(
            phone=phone or None,
            group_id=group_id,
            group_sender=group_sender or phone,
            quote_msg_id=quote_msg_id,
            text=ack,
        )

    if mattermost_pool_notify_enabled():
        from app.services.loomy_pool_notify_service import schedule_loomy_pool_notify

        schedule_loomy_pool_notify(
            pool_ids=pool_ids,
            phone=phone or group_sender or '',
            sender_name=sender_name,
            group_id=group_id,
            group_sender=group_sender or phone,
            caption=caption,
        )


def _schedule_pool_receipt(
    file_count,
    body,
    *,
    phone=None,
    group_id=None,
    group_sender=None,
    quote_msg_id=None,
    batch_id=None,
    on_sent=None,
):
    from app.services.pool_receipt_notify_service import schedule_pool_receipt_prompt
    schedule_pool_receipt_prompt(
        file_count,
        body,
        phone=phone,
        group_id=group_id,
        group_sender=group_sender,
        quote_msg_id=quote_msg_id,
        batch_id=batch_id,
        on_sent=on_sent,
    )


def _latest_group_pending_context(group_id, sender):
    doc = mongo.db.group_pending_images.find_one(
        {'groupId': group_id, 'senderPhone': sender, 'categorized': False},
        sort=[('createdAt', -1)],
        projection={
            'messageId': 1,
            'batchId': 1,
            'imagePath': 1,
            'waMessageRaw': 1,
        },
    )
    if not doc:
        return {
            'quote': None,
            'batch_id': None,
            'wa_message_raw': None,
        }
    return {
        'quote': doc.get('messageId'),
        'batch_id': doc.get('batchId') or doc.get('messageId'),
        'wa_message_raw': doc.get('waMessageRaw'),
    }


def _send_group_prompt(
    group_id,
    sender,
    body,
    quote_msg_id=None,
    *,
    quoted_payload=None,
    batch_id=None,
    mark_classify_reply=False,
):
    """Send a group message immediately (non-batched flows)."""
    ctx = _latest_group_pending_context(group_id, sender)
    quote = quote_msg_id or ctx.get('quote')
    payload = quoted_payload if quoted_payload is not None else ctx.get('wa_message_raw')
    bid = batch_id or ctx.get('batch_id')
    try:
        resp = send_group_message(
            group_id,
            body,
            quoted_msg_id=quote,
            quoted_payload=payload,
        )
        _record_bot_prompt_msg(group_id, sender, resp)
        if mark_classify_reply:
            from app.services.pool_receipt_notify_service import mark_group_classify_reply_sent

            mark_group_classify_reply_sent(group_id, sender, bid)
            _cancel_scheduled_receipt(
                group_id=group_id, group_sender=sender, batch_id=bid,
            )
        return resp
    except Exception:
        return None


def _send_fuzzy_prompt(to, label, candidates, *, group_id=None, sender=None):
    """Send a disambiguation prompt and cache choices."""
    body = (
        f'🔍 找到多個相似專案（輸入「{label}」）：\n'
        f'{_format_fuzzy_candidates(candidates)}\n\n'
        f'回覆數字選擇，或發送完整專案編碼。'
    )
    _set_fuzzy_choice(group_id, sender or to, candidates)
    if group_id:
        _send_group_prompt(group_id, sender or to, body)
    else:
        _safe_send(to, body)


def _send_ai_confirm_prompt(group_id, sender, to, project, *, quote_msg_id=None):
    from app.services.project_number_match_service import wa_classify_display_label

    label = wa_classify_display_label(project, max_len=500)
    body = f'已選：\n{label}\n回覆「是」或「確認」後歸類照片。'
    if group_id:
        _send_group_prompt(group_id, sender or to, body, quote_msg_id=quote_msg_id)
    else:
        ctx = _latest_unassigned_pool_context(to)
        from app.services.wa_pool_nudge_service import send_private_classify_nudge

        try:
            send_private_classify_nudge(
                to,
                body,
                quote_msg_id=quote_msg_id or ctx.get('quote'),
                image_path=ctx.get('image_path'),
                quoted_payload=ctx.get('wa_message_raw'),
            )
        except Exception as exc:
            logger.error('[Inbound] AI confirm prompt failed: %s', exc)
            _safe_send(to, body, quoted_msg_id=quote_msg_id)


def _pool_ids_for_confirm_scope(sender, scope):
    """Assign only the batch/images tied to the pending AI confirm (not all pool rows)."""
    scope = scope or {}
    stored = scope.get('poolImageIds') or []
    if stored:
        object_ids = []
        for pid in stored:
            try:
                object_ids.append(ObjectId(pid))
            except Exception:
                continue
        docs = list(mongo.db.pool_images.find({
            '_id': {'$in': object_ids},
            'projectId': {'$exists': False},
        }))
        if docs:
            return [str(d['_id']) for d in docs]

    batch_id = scope.get('batchId')
    if batch_id:
        docs = list(mongo.db.pool_images.find({
            **_open_pool_query(sender),
            'projectId': {'$exists': False},
            'batchId': batch_id,
        }))
        if docs:
            return [str(d['_id']) for d in docs]

    quote = scope.get('quoteMsgId')
    if quote:
        ids = _find_unassigned_pool_ids_by_quote(quote, sender)
        if ids:
            return ids

    return _find_unassigned_pool_ids_latest_batch(sender)


def _find_unassigned_pool_ids_latest_batch(sender):
    """Most recent unassigned upload only (one WhatsApp message / batch)."""
    newest = mongo.db.pool_images.find_one(
        _open_pool_query(sender),
        sort=[('createdAt', -1)],
    )
    if not newest:
        return []
    batch_id = newest.get('batchId') or newest.get('messageId')
    if batch_id:
        docs = list(mongo.db.pool_images.find({
            **_open_pool_query(sender),
            'batchId': batch_id,
        }))
        if docs:
            return [str(d['_id']) for d in docs]
    return [str(newest['_id'])]


def _send_private_classify_prompt(
    to,
    body,
    *,
    quote_msg_id=None,
    pool_image_ids=None,
):
    from app.services.wa_classify_mode import wa_loomy_agent_enabled

    if wa_loomy_agent_enabled():
        return False

    from app.services.wa_pool_nudge_service import send_private_classify_nudge

    ctx = _latest_unassigned_pool_context(to)
    image_path = ctx.get('image_path')
    wa_raw = ctx.get('wa_message_raw')
    quote = quote_msg_id or ctx.get('quote')
    if pool_image_ids:
        try:
            doc = mongo.db.pool_images.find_one(
                {'_id': ObjectId(pool_image_ids[0])},
                projection={'imagePath': 1, 'waMessageRaw': 1},
            )
        except Exception:
            doc = None
        if doc:
            image_path = doc.get('imagePath') or image_path
            wa_raw = doc.get('waMessageRaw') or wa_raw
    try:
        send_private_classify_nudge(
            to,
            body,
            quote_msg_id=quote,
            image_path=image_path,
            quoted_payload=wa_raw,
        )
        from app.services.pool_receipt_notify_service import mark_private_classify_reply_sent

        mark_private_classify_reply_sent(to, ctx.get('batch_id'))
        _cancel_scheduled_receipt(phone=to, batch_id=ctx.get('batch_id'))
        return True
    except Exception as exc:
        logger.error('[Inbound] Classify prompt send failed: %s', exc)
        try:
            _safe_send(to, body, quoted_msg_id=quote)
            return True
        except Exception:
            return False


def _send_pool_classify_nudge(sender):
    """Show the user's latest unassigned photo with a classify caption (native quote if Wakka supports it)."""
    from app.services.wa_classify_mode import wa_loomy_agent_enabled

    if wa_loomy_agent_enabled():
        return False

    from app.services.pool_receipt_notify_service import format_pool_receipt_body
    from app.services.wa_pool_nudge_service import send_private_classify_nudge

    ctx = _latest_unassigned_pool_context(sender)
    if not ctx.get('pool_ids'):
        return False
    body = format_pool_receipt_body(len(ctx['pool_ids']))
    try:
        send_private_classify_nudge(
            sender,
            body,
            quote_msg_id=ctx.get('quote'),
            image_path=ctx.get('image_path'),
            quoted_payload=ctx.get('wa_message_raw'),
        )
        from app.services.pool_receipt_notify_service import mark_private_classify_reply_sent

        mark_private_classify_reply_sent(sender, ctx.get('batch_id'))
        _cancel_scheduled_receipt(phone=sender, batch_id=ctx.get('batch_id'))
    except Exception as exc:
        logger.error('[Inbound] Classify nudge send failed: %s', exc)
        return False
    return True


def _is_classify_noise(text):
    t = (text or '').strip()
    if not t:
        return True
    if re.fullmatch(r'[\?\!\.…。！？\s]+', t):
        return True
    if re.fullmatch(r'[?？!！。\.…]{2,}', t.replace(' ', '')):
        return True
    return False


def _is_casual_chat(text):
    """Acknowledgements / chit-chat — not a project code to remember."""
    t = (text or '').strip().lower()
    plain = re.sub(r'[^\w\u4e00-\u9fff]', '', t)
    if not plain:
        return True
    casual = {
        '好的', '好', '嗯', '恩', '哦', '喔', '行', '可以', '收到', '知道了', '明白',
        '谢谢', '謝謝', 'thanks', 'thx', 'ok', 'okay', 'hi', 'hello', '嗨',
        '哈哈', '呵呵',
    }
    if plain in casual or t in casual:
        return True
    if is_affirmative(text) or is_rejection_only(text):
        return True
    return False


def _should_store_classify_intent(text):
    """Only remember text that matches a real project (send-photo-first flow)."""
    t = (text or '').strip()
    if not t or is_command(t) or _is_classify_noise(t) or _is_casual_chat(t):
        return False
    if len(t) > 64:
        return False

    if match_project(t, active_only=True):
        return True

    ext = match_project_ext(t, active_only=True)
    if ext.project:
        return True
    if ext.candidates and ext.candidates[0][1] >= 88:
        return True

    if re.match(r'^PJ[-\s]?\d', t, re.I):
        return True

    if re.fullmatch(r'\d{3,6}', t):
        from app.services.project_number_match_service import (
            match_site_projects_by_number,
            primary_site_number,
        )

        site = primary_site_number(t)
        if site and match_site_projects_by_number(site, active_only=True):
            return True
        return False

    return False


def _should_try_classify_text(text):
    t = (text or '').strip()
    if not t or is_command(t):
        return False
    if is_rejection_only(t):
        return False
    if _is_classify_noise(t):
        return False
    # Lone 1–9 without an active fuzzy list — not a project code attempt.
    if len(t) == 1 and t.isdigit():
        return False
    return True


def _latest_unassigned_pool_context(sender):
    pool_ids = _find_unassigned_pool_ids_latest_batch(sender)
    newest = mongo.db.pool_images.find_one(
        _open_pool_query(sender),
        sort=[('createdAt', -1)],
        projection={
            'messageId': 1,
            'batchId': 1,
            'chatJid': 1,
            'imagePath': 1,
            'waMessageRaw': 1,
        },
    )
    if not newest:
        return {
            'quote': None,
            'batch_id': None,
            'pool_ids': [],
            'chat_jid': None,
            'image_path': None,
            'wa_message_raw': None,
        }
    from app.services.wa_send_service import chat_jid_from_message_id

    chat_jid = newest.get('chatJid') or chat_jid_from_message_id(newest.get('messageId'))
    return {
        'quote': newest.get('messageId'),
        'chat_jid': chat_jid,
        'batch_id': newest.get('batchId') or newest.get('messageId'),
        'pool_ids': pool_ids,
        'image_path': newest.get('imagePath'),
        'wa_message_raw': newest.get('waMessageRaw'),
    }


def _try_fast_site_folder_list(site_num, sender, *, quote_msg_id=None, pool_image_ids=None):
    """Fast NAS bucket scan → numbered folder list (duplicate PJ-xxxx dirs)."""
    from app.services.nas_sync_service import list_physical_site_folders
    from app.services.project_ai_resolve_service import _build_classify_list_message
    from app.services.wa_project_validation import find_project_by_code

    folders = list_physical_site_folders(str(site_num))
    if len(folders) <= 1:
        return False
    code = (folders[0].get('code') or '').strip() or f'PJ-{site_num}'
    base = find_project_by_code(code)
    if not base:
        return False
    candidates = []
    for row in folders:
        proj = dict(base)
        proj['nasFolderName'] = row['folderName']
        if row.get('parentBucket'):
            proj['nasParentBucket'] = row['parentBucket']
        candidates.append((proj, 100))
    body = _build_classify_list_message(str(site_num), candidates)
    _set_fuzzy_choice(None, sender, candidates)
    sent = _send_private_classify_prompt(
        sender,
        body,
        quote_msg_id=quote_msg_id,
        pool_image_ids=pool_image_ids,
    )
    if sent:
        from app.services.pool_receipt_notify_service import (
            cancel_pool_receipt_for_phone,
            mark_private_classify_reply_sent,
        )

        mark_private_classify_reply_sent(sender)
        cancel_pool_receipt_for_phone(sender)
    return sent


def _apply_classify_resolve(
    text,
    *,
    to,
    group_id=None,
    sender=None,
    quote_msg_id=None,
    batch_id=None,
    pool_image_ids=None,
):
    """Heuristic + Ollama classify. Returns (project|None, remark, json type)."""
    from app.services.wa_classify_mode import worker_auto_classify_enabled

    if not worker_auto_classify_enabled():
        return None, None, 'none'

    from app.services.message_parser_service import split_classify_label_and_remark

    trimmed = ' '.join((text or '').strip().split())
    label, _ = split_classify_label_and_remark(trimmed)
    match_key = label or trimmed
    resolve = coerce_assign_to_confirm(
        resolve_classify_input(text, active_only=True),
        match_key,
    )
    remark = resolve.remark
    key_sender = sender or to

    if resolve.action == 'assign' and resolve.project:
        clear_ai_confirm(group_id, key_sender)
        _clear_fuzzy_choice(group_id, key_sender)
        return resolve.project, remark, 'assign'

    if resolve.action == 'list':
        body = resolve.user_message
        if group_id:
            _send_group_prompt(
                group_id,
                key_sender,
                body,
                quote_msg_id=quote_msg_id,
                batch_id=batch_id,
                mark_classify_reply=True,
            )
        elif not _send_private_classify_prompt(
            to, body, quote_msg_id=quote_msg_id, pool_image_ids=pool_image_ids,
        ):
            return None, remark, 'pool_send_failed'
        _set_fuzzy_choice(group_id, key_sender, resolve.candidates)
        return None, remark, 'pool_ai_list'

    if resolve.action == 'suggest' and resolve.project:
        body = resolve.user_message
        if group_id:
            _send_group_prompt(
                group_id,
                key_sender,
                body,
                quote_msg_id=quote_msg_id,
                batch_id=batch_id,
                mark_classify_reply=True,
            )
        elif not _send_private_classify_prompt(
            to, body, quote_msg_id=quote_msg_id, pool_image_ids=pool_image_ids,
        ):
            return None, remark, 'pool_send_failed'
        set_ai_confirm(
            group_id,
            key_sender,
            resolve.project,
            remark,
            batch_id=batch_id,
            pool_image_ids=pool_image_ids,
            quote_msg_id=quote_msg_id,
        )
        return None, remark, 'pool_ai_confirm'

    body = (resolve.user_message or '').strip()
    if not body:
        body = (
            f'找不到與「{(text or "").strip()}」相符的專案。\n'
            f'請重新輸入專案編碼或名稱；發送 *projects* 查看列表。'
        )
    if group_id:
        _send_group_prompt(
            group_id,
            key_sender,
            body,
            quote_msg_id=quote_msg_id,
            batch_id=batch_id,
            mark_classify_reply=True,
        )
    else:
        try:
            _send_private_classify_prompt(
                to, body, quote_msg_id=quote_msg_id, pool_image_ids=pool_image_ids,
            )
        except Exception as exc:
            logger.error('[Inbound] pool_no_match prompt failed: %s', exc)
            _safe_send(to, body, quoted_msg_id=quote_msg_id)
    return None, remark, 'pool_no_match'


def _try_ai_confirm_assign(group_id, sender, to, text, data, *, pending=None):
    """If user confirmed AI suggestion, assign and return Flask response."""
    key_sender = sender or to
    confirm_doc = peek_ai_confirm(group_id, key_sender)
    if not confirm_doc:
        return None
    trimmed = (text or '').strip()
    quote = confirm_doc.get('quoteMsgId')
    rejected_code = confirm_doc.get('code') or ''

    if is_negative(trimmed) or is_rejection_only(trimmed):
        clear_ai_confirm(group_id, key_sender)
        _clear_fuzzy_choice(group_id, key_sender)
        if group_id:
            msg = (
                f'好的，未歸入 *{rejected_code}*。\n'
                f'請回覆正確的專案編碼或名稱。'
            )
            _send_group_prompt(group_id, key_sender, msg, quote_msg_id=quote)
        else:
            _send_pool_classify_nudge(to)
        return jsonify({'handled': True, 'type': 'ai_confirm_cancelled'})

    if not is_affirmative(trimmed):
        # User is typing a different project — close confirm and re-classify below.
        clear_ai_confirm(group_id, key_sender)
        return None

    project, remark, scope = pop_ai_confirm_project(group_id, key_sender)
    if not project:
        return None
    if remark and data is not None:
        data = dict(data)
        data['text'] = remark
        data['caption'] = remark

    if group_id and pending is not None:
        return _categorize_group_image(pending, project, group_id, data or {}, sender)

    ids = _pool_ids_for_confirm_scope(key_sender, scope)
    if ids:
        n = assign_images_to_project(ids, project, 'user', remark=remark)
        if n > 0:
            from app.services.assignment_notify_service import schedule_assignment_confirmation
            schedule_assignment_confirmation(project, n, phone=to)
            _clear_classify_intent(None, key_sender)
            _cancel_scheduled_receipt(phone=to)
        return jsonify({'handled': True, 'type': 'pool_assigned_ai_confirm', 'count': n})
    if group_id:
        _send_group_prompt(
            group_id, key_sender,
            f'✅ 已選定專案 *{project["code"]}*，但目前沒有未歸類的照片。',
        )
    else:
        _clear_classify_intent(None, key_sender)
        _clear_fuzzy_choice(group_id, key_sender)
        _safe_send(
            to,
            f'專案 *{project["code"]}* 已確認，但沒有待歸類的照片（可能已歸類完成）。',
        )
    return jsonify({'handled': True, 'type': 'ai_confirm_no_pool'})


def _resolve_media_project(data, sender, group_id=None):
    """WhatsApp multi-select sends separate messages; only the first has a real caption."""
    from app.services.message_parser_service import split_classify_label_and_remark

    raw = (data.get('text') or data.get('caption') or data.get('classifyText') or '').strip()
    wa_type = data.get('type')
    caption = raw
    if caption and _looks_like_filename(caption) and wa_type in ('document', 'video', 'audio', None):
        caption = ''

    if caption:
        ext = match_project_ext(caption, active_only=True)
        if ext.project:
            lab, _ = split_classify_label_and_remark(caption)
            key = lab or caption
            if classify_input_matches_full_display(key, ext.project):
                return ext.remark or caption, ext.project
        if not _looks_like_filename(raw):
            # Full line for pool + classify; resolver splits leading code vs remark.
            return raw, None

    burst = _get_burst_project(group_id, sender)
    if burst:
        return None, burst

    if caption:
        return raw, None
    return None, None


def _classify_remark_from_data(data):
    from app.services.message_parser_service import trailing_classify_remark

    text = (data.get('text') or data.get('caption') or '').strip()
    if not text:
        return None
    ext = match_project_ext(text, active_only=True)
    if ext.remark:
        return ext.remark
    return trailing_classify_remark(text)


def _insert_group_pending_image(
    group_id, sender, from_name, message_id, image_path, caption, batch_id, now,
    wa_type=None, mime_type=None, sender_jid=None, wa_message_raw=None,
):
    from app.services.image_pool_service import infer_pool_media_meta
    media_type, file_name = infer_pool_media_meta(image_path, wa_type=wa_type, mime_type=mime_type)
    pending_doc = {
        'groupId': group_id,
        'senderPhone': sender,
        'senderJid': sender_jid,
        'senderName': from_name,
        'messageId': message_id,
        'imagePath': image_path,
        'caption': caption,
        'batchId': batch_id,
        'categorized': False,
        'reminderCount': 0,
        'createdAt': now,
        'updatedAt': now,
    }
    if isinstance(wa_message_raw, dict):
        pending_doc['waMessageRaw'] = wa_message_raw
    mongo.db.group_pending_images.insert_one(pending_doc)
    mongo.db.pool_images.insert_one({
        'phone': sender,
        'senderName': from_name,
        'imagePath': image_path,
        'fileName': file_name,
        'mediaType': media_type,
        'mimeType': mime_type,
        'downloadFailed': not image_path,
        'caption': caption,
        'messageId': message_id,
        'batchId': batch_id,
        'createdAt': now,
        'updatedAt': now,
    })


def _send_group_assigned_message(group_id, project, count):
    from app.services.assignment_notify_service import schedule_assignment_confirmation
    schedule_assignment_confirmation(project, count, group_id=group_id)


def _recent_unassigned_pool_ids(sender, *, seconds=120):
    """Pool items from the same sender sent shortly before a caption (multi-PDF burst)."""
    from datetime import timedelta
    since = datetime.utcnow() - timedelta(seconds=seconds)
    docs = list(mongo.db.pool_images.find({
        'phone': sender,
        'projectId': {'$exists': False},
        'imagePath': {'$exists': True, '$nin': [None, '']},
        'createdAt': {'$gte': since},
    }).sort('createdAt', 1))
    return [str(d['_id']) for d in docs]


def _notify_group_media_failed(group_id):
    try:
        send_group_message(group_id, '⚠️ 無法下載檔案，請稍後重試或重新發送。')
    except Exception:
        pass


def _save_media_buffer(data, msg_type):
    """Save raw bytes to the WA media folder. Returns web path or None."""
    media_dir = current_app.config.get('WA_UPLOADS_FOLDER', 'uploads/wa-media')
    os.makedirs(media_dir, exist_ok=True)
    ext_map = {'image': '.jpg', 'video': '.mp4', 'audio': '.ogg', 'document': '.pdf'}
    ext = ext_map.get(msg_type, '.bin')
    fname = f'{int(time.time() * 1000)}-{hashlib.md5(os.urandom(8)).hexdigest()[:8]}{ext}'
    fpath = os.path.join(media_dir, fname)
    with open(fpath, 'wb') as f:
        f.write(data)
    return f'/uploads/wa-media/{fname}'


@wa_inbound_bp.route('/inbound', methods=['POST'])
def handle_inbound():
    """Receive messages from the Gateway process. Authenticated by shared secret."""
    secret = current_app.config.get('GATEWAY_INBOUND_SECRET')
    auth = request.headers.get('X-Gateway-Secret', '')
    if not auth:
        bearer = request.headers.get('Authorization', '')
        if bearer.startswith('Bearer '):
            auth = bearer[7:]
    if not secret or auth != secret:
        if not secret:
            logger.warning('[Inbound] GATEWAY_INBOUND_SECRET is empty — rejecting request')
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data'}), 400

    if not _claim(data.get('messageId')):
        return jsonify({'handled': True, 'type': 'duplicate'})

    text = data.get('text', '')
    photos = data.get('photos', [])
    from_name = data.get('fromName')
    has_media = data.get('hasMedia', False)
    raw_from = (data.get('from') or '').strip()
    is_group = data.get('isGroup', False)
    group_id = data.get('groupId')
    sender_jid = raw_from if is_group and '@' in raw_from else None
    sender = _strip_phone(raw_from)
    if is_group and not sender_jid and data.get('author'):
        author = str(data.get('author')).strip()
        if '@' in author:
            sender_jid = author

    if not sender:
        return jsonify({'handled': True, 'type': 'invalid_sender'})

    if not is_group:
        sender = _canonical_private_sender(sender, data)

    try:
        if is_group and group_id:
            return _handle_group(data, sender, from_name, group_id, sender_jid=sender_jid)
        return _handle_private(data, sender, from_name, text, photos, has_media)
    except Exception as e:
        logger.exception('[Inbound] Unhandled error')
        return jsonify({'handled': True, 'type': 'error', 'error': str(e)})


def _handle_private(data, sender, from_name, text, photos, has_media):
    final_photos = list(photos)
    if has_media and not final_photos and data.get('messageId'):
        try:
            buf = download_media(data['messageId'])
            if buf:
                local = _save_media_buffer(buf, data.get('type', 'image'))
                if local:
                    final_photos = [local]
        except Exception as e:
            logger.error('[Inbound] Media download failed: %s', e)

    msg_type = data.get('type') or ''
    if msg_type == 'other' and not final_photos:
        return jsonify({'handled': True, 'type': 'album_shell_skipped'})

    is_media = has_media and (
        msg_type in ('image', 'video', 'document')
        or len(final_photos) > 0
    )
    is_text = not is_media and text.strip()

    if is_media:
        with _media_lock(f'p:{sender}'):
            classify_hint = (data.get('classifyText') or '').strip()
            caption = text.strip() or classify_hint or None
            photo_paths = [p for p in final_photos if p]
            if not photo_paths:
                return jsonify({'handled': True, 'type': 'media_unavailable'})

            caption, project = _resolve_media_project(data, sender, group_id=None)
            base_msg_id = data.get('messageId', '') or ''
            inbound_batch_id = _quote_msg_id(data) or base_msg_id
            pool_ids = []
            multi = len(photo_paths) > 1

            from app.services.wa_classify_mode import worker_auto_classify_enabled

            site_num_early = None
            if caption and not project and worker_auto_classify_enabled():
                from app.services.project_number_match_service import primary_site_number
                from app.services.pool_receipt_notify_service import (
                    mark_private_classify_in_progress,
                )

                site_num_early = primary_site_number(caption)
                if site_num_early:
                    mark_private_classify_in_progress(sender, inbound_batch_id)
                    _cancel_scheduled_receipt(
                        phone=sender, batch_id=inbound_batch_id or None,
                    )

            for idx, image_path in enumerate(photo_paths):
                msg_id = _pool_msg_id(data, idx, base_msg_id)
                result = save_to_pool(
                    sender,
                    image_path,
                    caption,
                    msg_id,
                    from_name,
                    defer_assign=bool(project),
                    defer_reminder=True,
                    batch_id=inbound_batch_id or None,
                    chat_jid=(data.get('from') or '').strip() or None,
                    wa_message_raw=data.get('waRaw') if isinstance(data.get('waRaw'), dict) else None,
                    **_pool_media_kwargs(data),
                )
                pool_ids.append(result['pool_id'])

            if project and worker_auto_classify_enabled():
                for pid in _recent_unassigned_pool_ids(sender):
                    if pid not in pool_ids:
                        pool_ids.append(pid)
                remark = _classify_remark_from_data(data)
                count = assign_images_to_project(pool_ids, project, 'user', remark=remark)
                _set_burst_project(None, sender, project)
                if count > 0:
                    from app.services.assignment_notify_service import schedule_assignment_confirmation
                    schedule_assignment_confirmation(project, count, phone=sender)
                return jsonify({
                    'handled': True,
                    'type': 'pool_assigned_batch',
                    'count': count,
                    'projectCode': project['code'],
                })

            if caption and not project and worker_auto_classify_enabled():
                from app.services.project_number_match_service import primary_site_number

                _clear_burst_project(None, sender)
                _cancel_scheduled_receipt(phone=sender, batch_id=inbound_batch_id or None)
                classify_kwargs = dict(
                    to=sender,
                    quote_msg_id=_quote_msg_id(data),
                    batch_id=inbound_batch_id or None,
                    pool_image_ids=pool_ids,
                )
                _CLASSIFY_DONE = frozenset({
                    'pool_ai_list', 'pool_ai_confirm', 'assign', 'pool_send_failed',
                })
                site_num = primary_site_number(caption)
                kind = None
                if site_num and _try_fast_site_folder_list(
                    site_num,
                    sender,
                    quote_msg_id=classify_kwargs.get('quote_msg_id'),
                    pool_image_ids=pool_ids,
                ):
                    from app.services.pool_receipt_notify_service import (
                        clear_private_classify_in_progress,
                    )

                    clear_private_classify_in_progress(sender)
                    return jsonify({
                        'handled': True,
                        'type': 'pool_ai_list',
                        'count': len(pool_ids),
                    })
                if site_num:
                    _proj, _remark, kind = _apply_classify_resolve(
                        str(site_num),
                        **classify_kwargs,
                    )
                    if kind in _CLASSIFY_DONE:
                        from app.services.pool_receipt_notify_service import (
                            clear_private_classify_in_progress,
                        )

                        clear_private_classify_in_progress(sender)
                        return jsonify({
                            'handled': True,
                            'type': kind,
                            'count': len(pool_ids),
                        })
                if kind not in _CLASSIFY_DONE:
                    _proj, _remark, kind = _apply_classify_resolve(
                        caption,
                        **classify_kwargs,
                    )
                    if kind in _CLASSIFY_DONE:
                        from app.services.pool_receipt_notify_service import (
                            clear_private_classify_in_progress,
                        )

                        clear_private_classify_in_progress(sender)
                        return jsonify({
                            'handled': True,
                            'type': kind,
                            'count': len(pool_ids),
                        })

            if not caption and not project:
                from app.services.wa_classify_mode import wa_loomy_agent_enabled

                if not wa_loomy_agent_enabled():
                    if _try_apply_stored_classify_intent_private(sender, data):
                        return jsonify({
                            'handled': True,
                            'type': 'pool_assigned_from_intent',
                            'count': len(pool_ids),
                        })
                    still_open = mongo.db.pool_images.count_documents(_open_pool_query(sender))
                    if still_open <= 0:
                        return jsonify({
                            'handled': True,
                            'type': 'pool_already_assigned',
                            'count': len(pool_ids),
                        })
                    if _peek_classify_intent(None, sender):
                        return jsonify({
                            'handled': True,
                            'type': 'pool_waiting_classify_intent',
                            'count': len(pool_ids),
                        })
                    # Private: no instant receipt text — user replies with project code, or PoolReminder later.

            if site_num_early:
                from app.services.pool_receipt_notify_service import (
                    clear_private_classify_in_progress,
                )

                clear_private_classify_in_progress(sender)

            _loomy_after_pool_intake(
                pool_ids,
                phone=sender,
                sender_name=data.get('fromName') or data.get('senderName'),
                caption=caption,
                quote_msg_id=_quote_msg_id(data),
            )

            return jsonify({
                'handled': True,
                'type': 'pool_media',
                'count': len(pool_ids),
                'autoAssigned': False,
            })

    if is_text:
        trimmed_text = text.strip()

        from app.services.wa_classify_mode import wa_loomy_agent_enabled

        if wa_loomy_agent_enabled():
            from app.services.loomy_wa_agent_service import (
                try_loomy_inbound_text_reply,
                try_loomy_numeric_pick,
            )

            ctx = _latest_unassigned_pool_context(sender)
            fast = try_loomy_inbound_text_reply(
                sender, trimmed_text, pool_ids=ctx.get('pool_ids'), data=data,
            )
            if fast:
                _safe_send(sender, fast, quoted_msg_id=data.get('quotedMsgId'))
                return jsonify({'handled': True, 'type': 'loomy_wa_smart_text'})

            if try_loomy_numeric_pick(sender, trimmed_text):
                return jsonify({'handled': True, 'type': 'loomy_wa_pick'})
            cmd = is_command(trimmed_text)
            if cmd:
                resp = _handle_command(cmd, sender, text=trimmed_text, data=data)
                return resp or jsonify({'handled': True, 'type': 'command'})

        ai_resp = None if wa_loomy_agent_enabled() else _try_ai_confirm_assign(
            None, sender, sender, trimmed_text, data,
        )
        if ai_resp is not None:
            return ai_resp

        # Fuzzy list selection: 1–9 only (not project numbers like 3026)
        if not wa_loomy_agent_enabled() and trimmed_text.isdigit():
            n = int(trimmed_text)
            fuzzy_doc = mongo.db.wa_system.find_one({'_id': _fuzzy_choice_key(None, sender)})
            if fuzzy_doc and fuzzy_doc.get('choices') and 1 <= n <= len(fuzzy_doc['choices']) <= 9:
                move_intent = _pop_move_intent(None, sender)
                choice_project = _pop_fuzzy_choice(None, sender, n)
                if choice_project:
                    if move_intent:
                        return _execute_move(sender, choice_project, move_intent)
                    n = _assign_unassigned_for_reply(sender, choice_project, data)
                    if n <= 0:
                        _safe_send(
                            sender,
                            '找不到待歸類的照片；若剛已歸類完成可忽略。若要改專案請再發照片。',
                        )
                    return jsonify({'handled': True, 'type': 'pool_assigned', 'count': n})

        has_unassigned = mongo.db.pool_images.count_documents(_open_pool_query(sender)) > 0

        if not wa_loomy_agent_enabled() and has_unassigned and _is_classify_noise(trimmed_text):
            if _send_pool_classify_nudge(sender):
                return jsonify({'handled': True, 'type': 'pool_classify_nudge'})
            return jsonify({'handled': True, 'type': 'ignored_silent'})

        if not wa_loomy_agent_enabled() and has_unassigned and len(trimmed_text) == 1 and trimmed_text.isdigit():
            if _send_pool_classify_nudge(sender):
                return jsonify({'handled': True, 'type': 'pool_classify_nudge'})
            return jsonify({'handled': True, 'type': 'ignored_silent'})

        if not wa_loomy_agent_enabled() and has_unassigned and is_rejection_only(trimmed_text):
            if _send_pool_classify_nudge(sender):
                return jsonify({'handled': True, 'type': 'pool_classify_nudge'})
            return jsonify({'handled': True, 'type': 'ignored_silent'})

        if not wa_loomy_agent_enabled() and has_unassigned and _should_try_classify_text(trimmed_text):
            _clear_fuzzy_choice(None, sender)
            _cancel_scheduled_receipt(phone=sender)
            ctx = _latest_unassigned_pool_context(sender)
            from app.services.project_number_match_service import primary_site_number

            site_num = primary_site_number(trimmed_text)
            if site_num and _try_fast_site_folder_list(
                site_num,
                sender,
                quote_msg_id=ctx['quote'],
                pool_image_ids=ctx['pool_ids'],
            ):
                return jsonify({'handled': True, 'type': 'pool_ai_list'})
            project, _remark, kind = _apply_classify_resolve(
                trimmed_text,
                to=sender,
                quote_msg_id=ctx['quote'],
                batch_id=ctx['batch_id'],
                pool_image_ids=ctx['pool_ids'],
            )
            if kind == 'assign' and project:
                n = _assign_unassigned_for_reply(sender, project, data)
                if n <= 0:
                    _safe_send(
                        sender,
                        f'找不到待歸類的照片；若剛已歸類完成可忽略。若要改專案請再發照片。',
                    )
                return jsonify({'handled': True, 'type': 'pool_assigned', 'count': n})
            return jsonify({
                'handled': True,
                'type': kind,
            })

        if not wa_loomy_agent_enabled() and trimmed_text and not is_command(trimmed_text) and not has_unassigned:
            from app.services.nas_site_remark_service import try_append_followup_site_remark

            if try_append_followup_site_remark(sender, trimmed_text):
                return jsonify({'handled': True, 'type': 'site_remark_appended'})
            _clear_classify_intent(None, sender)
            _clear_burst_project(None, sender)
            return jsonify({'handled': True, 'type': 'ignored_silent'})

        if not wa_loomy_agent_enabled() and trimmed_text and not is_command(trimmed_text) and has_unassigned:
            if _send_pool_classify_nudge(sender):
                return jsonify({'handled': True, 'type': 'pool_classify_nudge'})
            return jsonify({'handled': True, 'type': 'ignored_silent'})

        if wa_loomy_agent_enabled() and trimmed_text:
            active = list(mongo.db.wa_records.find({
                'senderPhone': sender, 'status': 'followup',
            }).sort('updatedAt', -1))
            if len(active) > 1:
                now = datetime.utcnow()
                for stale in active[1:]:
                    mongo.db.wa_records.update_one(
                        {'_id': stale['_id']},
                        {'$set': {'status': 'awaiting_review'},
                         '$push': {'statusHistory': {'from': 'followup', 'to': 'awaiting_review', 'timestamp': now, 'reason': 'Superseded'}}},
                    )
            active_record = active[0] if active else None
            if active_record and trimmed_text.lower() == 'skip':
                now = datetime.utcnow()
                mongo.db.wa_records.update_one(
                    {'_id': active_record['_id']},
                    {'$set': {'status': 'awaiting_review'},
                     '$push': {'statusHistory': {'from': 'followup', 'to': 'awaiting_review', 'timestamp': now, 'reason': 'Worker skipped'}}},
                )
                _safe_send(sender, '好的，紀錄已提交（部分資訊待補）。')
                return jsonify({'handled': True, 'type': 'skip'})
            ctx = _latest_unassigned_pool_context(sender)
            from app.services.loomy_loom_platform_bridge import (
                is_pool_classify_turn,
                wa_loom_platform_classify_enabled,
            )

            loom_ctx = {
                'phone': sender,
                'user_text': trimmed_text,
                'pool_ids': ctx.get('pool_ids'),
            }
            _schedule_loomy_from_inbound(
                phone=sender,
                user_text=trimmed_text,
                pool_ids=ctx.get('pool_ids'),
                sender_name=data.get('fromName') or data.get('senderName'),
                data=data,
                active_record=active_record,
                loom_classify_attempted=(
                    wa_loom_platform_classify_enabled() and is_pool_classify_turn(loom_ctx)
                ),
            )
            return jsonify({'handled': True, 'type': 'loomy_wa_agent'})

    if not is_text:
        return jsonify({'handled': True, 'type': 'ignored_silent'})

    from app.services.wa_classify_mode import wa_loomy_agent_enabled

    if wa_loomy_agent_enabled():
        return jsonify({'handled': True, 'type': 'ignored_silent'})

    active = list(mongo.db.wa_records.find({
        'senderPhone': sender, 'status': 'followup',
    }).sort('updatedAt', -1))

    if len(active) > 1:
        now = datetime.utcnow()
        for stale in active[1:]:
            mongo.db.wa_records.update_one(
                {'_id': stale['_id']},
                {'$set': {'status': 'awaiting_review'},
                 '$push': {'statusHistory': {'from': 'followup', 'to': 'awaiting_review', 'timestamp': now, 'reason': 'Superseded'}}},
            )

    active_record = active[0] if active else None

    if active_record:
        lower = text.strip().lower()
        if lower == 'skip':
            now = datetime.utcnow()
            mongo.db.wa_records.update_one(
                {'_id': active_record['_id']},
                {'$set': {'status': 'awaiting_review'},
                 '$push': {'statusHistory': {'from': 'followup', 'to': 'awaiting_review', 'timestamp': now, 'reason': 'Worker skipped'}}},
            )
            _safe_send(sender, '好的，紀錄已提交（部分資訊待補）。')
            return jsonify({'handled': True, 'type': 'skip'})

        cmd = is_command(text)
        if cmd:
            resp = _handle_command(cmd, sender, text=text, data=data)
            return resp or jsonify({'handled': True, 'type': 'command'})

        handle_follow_up_reply(str(active_record['_id']), text)
        _safe_send(sender, '✅ 已收到資訊，處理中…')
        run_extraction(str(active_record['_id']))
        send_follow_up(str(active_record['_id']))
        return jsonify({'handled': True, 'type': 'followup_reply'})

    cmd = is_command(text)
    if cmd:
        resp = _handle_command(cmd, sender, text=text, data=data)
        return resp or jsonify({'handled': True, 'type': 'command'})

    return jsonify({'handled': True, 'type': 'ignored_silent'})


def _handle_group(data, sender, from_name, group_id, *, sender_jid=None):
    text = data.get('text', '')
    photos = data.get('photos', [])
    has_media = data.get('hasMedia', False)

    final_photos = list(photos)
    if has_media and not final_photos and data.get('messageId'):
        try:
            buf = download_media(data['messageId'])
            if buf:
                local = _save_media_buffer(buf, data.get('type', 'image'))
                if local:
                    final_photos = [local]
        except Exception as e:
            logger.error('[Inbound:Group] Media download failed: %s', e)

    is_media = has_media and (
        data.get('type') in ('image', 'video', 'document')
        or len(final_photos) > 0
    )

    if not is_media and text.strip():
        trimmed = text.strip()
        from app.services.wa_classify_mode import wa_loomy_agent_enabled

        if wa_loomy_agent_enabled():
            from app.services.loomy_wa_agent_service import (
                try_loomy_inbound_text_reply,
                try_loomy_numeric_pick,
            )
            from app.services.loomy_pool_batch import latest_unassigned_pool_ids

            pids = latest_unassigned_pool_ids(phone=sender, group_id=group_id)
            fast = try_loomy_inbound_text_reply(
                sender, trimmed, group_id=group_id, pool_ids=pids, data=data,
            )
            if fast:
                from app.services.wa_send_service import send_group_message

                send_group_message(group_id, fast, quoted_msg_id=data.get('quotedMsgId'))
                return jsonify({'handled': True, 'type': 'loomy_wa_smart_text'})

            if try_loomy_numeric_pick(sender, trimmed, group_id=group_id):
                return jsonify({'handled': True, 'type': 'loomy_wa_pick'})
            cmd = is_command(trimmed)
            if cmd:
                resp = _handle_command(cmd, sender, text=trimmed, data=data, group_id=group_id)
                return resp or jsonify({'handled': True, 'type': 'group_command'})
            from app.services.loomy_loom_platform_bridge import (
                is_pool_classify_turn,
                wa_loom_platform_classify_enabled,
            )

            loom_ctx = {
                'phone': sender,
                'group_id': group_id,
                'user_text': trimmed,
                'pool_ids': pids,
            }
            _schedule_loomy_from_inbound(
                phone=sender,
                group_id=group_id,
                user_text=trimmed,
                sender_name=from_name,
                data=data,
                loom_classify_attempted=(
                    wa_loom_platform_classify_enabled() and is_pool_classify_turn(loom_ctx)
                ),
            )
            return jsonify({'handled': True, 'type': 'loomy_wa_agent'})

        if trimmed.lower() == 'projects':
            from app.services.project_number_match_service import (
                list_wa_classify_target_projects,
                wa_classify_display_label,
            )
            from app.services.nas_sync_service import enrich_wa_projects_display

            projects = list_wa_classify_target_projects(active_only=True)
            enrich_wa_projects_display(projects)
            lines = [f'• {wa_classify_display_label(p, max_len=500)}' for p in projects]
            try:
                send_group_message(group_id, ('*活躍專案列表：*\n' + '\n'.join(lines)) if lines else '暫無活躍專案。')
            except Exception:
                pass
            return jsonify({'handled': True, 'type': 'group_command'})

        cmd = is_command(trimmed)
        if cmd == 'move':
            return _handle_move(trimmed, sender, data, group_id=group_id)

        has_quoted = data.get('hasQuotedMsg', False)
        pending = _group_pending_for_sender(group_id, sender)

        ai_resp = _try_ai_confirm_assign(
            group_id, sender, sender, trimmed, data, pending=pending,
        )
        if ai_resp is not None:
            return ai_resp

        if pending and not has_quoted:
            stored = _peek_classify_intent(group_id, sender)
            if stored and stored == trimmed:
                _pop_classify_intent(group_id, sender)
                gctx = _latest_group_pending_context(group_id, sender)
                proj, _remark, kind = _apply_classify_resolve(
                    stored,
                    to=sender,
                    group_id=group_id,
                    sender=sender,
                    quote_msg_id=_quote_msg_id(data) or gctx.get('quote'),
                    batch_id=gctx.get('batch_id'),
                )
                if kind == 'assign' and proj:
                    return _categorize_group_image(pending, proj, group_id, data, sender)
                return jsonify({'handled': True, 'type': kind})

        # Numeric fuzzy-choice reply in group
        if trimmed.isdigit() and (pending or has_quoted):
            n = int(trimmed)
            fuzzy_doc = mongo.db.wa_system.find_one({'_id': _fuzzy_choice_key(group_id, sender)})
            if fuzzy_doc and fuzzy_doc.get('choices') and 1 <= n <= len(fuzzy_doc['choices']) <= 9:
                move_intent = _pop_move_intent(group_id, sender)
                choice_project = _pop_fuzzy_choice(group_id, sender, n)
                if choice_project:
                    if move_intent:
                        return _execute_move(sender, choice_project, move_intent, group_id=group_id)
                    pending = _group_pending_for_sender(group_id, sender)
                    if pending:
                        return _categorize_group_image(
                            pending, choice_project, group_id, data, sender,
                        )
                    return jsonify({'handled': True, 'type': 'group_no_pending'})

        project = _lookup_active_project(trimmed)

        # Classify — only when there are pending images or a quoted msg
        if not is_command(trimmed) and (pending or has_quoted):
            gctx = _latest_group_pending_context(group_id, sender)
            proj, _remark, kind = _apply_classify_resolve(
                trimmed,
                to=sender,
                group_id=group_id,
                sender=sender,
                quote_msg_id=_quote_msg_id(data) or gctx.get('quote'),
                batch_id=gctx.get('batch_id'),
            )
            if kind == 'assign' and proj:
                return _categorize_group_image(pending, proj, group_id, data, sender)
            return jsonify({'handled': True, 'type': kind})

        if has_quoted and not project and not is_command(trimmed):
            _warn_unknown_group_project(group_id, trimmed)
            return jsonify({'handled': True, 'type': 'group_no_match'})
        if pending and is_command(trimmed):
            return jsonify({'handled': True, 'type': 'group_pending_silent'})

        if not is_command(trimmed) and not pending:
            from app.services.nas_site_remark_service import try_append_followup_site_remark

            if try_append_followup_site_remark(sender, trimmed, group_id=group_id):
                return jsonify({'handled': True, 'type': 'group_site_remark_appended'})
            _clear_classify_intent(group_id, sender)
            return jsonify({'handled': True, 'type': 'ignored_silent'})

    if is_media:
        with _media_lock(f'g:{group_id}:{sender}'):
            return _handle_group_media(
                data, sender, from_name, group_id, final_photos, sender_jid=sender_jid,
            )

    return jsonify({'handled': True, 'type': 'group_ignored'})


def _handle_group_media(data, sender, from_name, group_id, final_photos, *, sender_jid=None):
    caption, project = _resolve_media_project(data, sender, group_id=group_id)
    base_msg_id = data.get('messageId', '')
    photo_paths = [p for p in final_photos if p]

    from app.services.wa_classify_mode import worker_auto_classify_enabled

    if project and photo_paths and worker_auto_classify_enabled():
        pool_ids = []
        for idx, image_path in enumerate(photo_paths):
            msg_id = _pool_msg_id(data, idx, base_msg_id)
            result = save_to_pool(
                sender,
                image_path,
                caption,
                msg_id,
                from_name,
                defer_assign=True,
                defer_reminder=True,
                **_pool_media_kwargs(data),
            )
            pool_ids.append(result['pool_id'])
        for pid in _recent_unassigned_pool_ids(sender):
            if pid not in pool_ids:
                pool_ids.append(pid)
        remark = _classify_remark_from_data(data)
        if not remark:
            stored = _peek_classify_intent(group_id, sender)
            if stored:
                from app.services.message_parser_service import split_classify_label_and_remark
                _, remark = split_classify_label_and_remark(stored)
        assign_images_to_project(
            pool_ids, project, 'user', remark=remark or None, group_id=group_id,
        )
        _set_burst_project(group_id, sender, project)
        _clear_classify_intent(group_id, sender)
        now = datetime.utcnow()
        mongo.db.group_pending_images.update_many(
            {'groupId': group_id, 'senderPhone': sender, 'categorized': False},
            {'$set': {'categorized': True, 'updatedAt': now}},
        )
        _cancel_scheduled_receipt(group_id=group_id, group_sender=sender)
        _send_group_assigned_message(group_id, project, len(pool_ids))
        return jsonify({'handled': True, 'type': 'group_auto_assigned', 'count': len(pool_ids)})

    if not photo_paths:
        if project:
            _notify_group_media_failed(group_id)
        return jsonify({'handled': True, 'type': 'group_media_unavailable'})

    now = datetime.utcnow()
    batch_id = _group_batch_id(group_id, sender, now)
    pending_caption = caption if caption and project is None and not _looks_like_filename(caption or '') else None

    from app.services.wa_classify_mode import wa_loomy_agent_enabled as _loomy_on

    if not _loomy_on():
        for idx, image_path in enumerate(photo_paths):
            msg_id = _pool_msg_id(data, idx, base_msg_id)
            _insert_group_pending_image(
                group_id, sender, from_name, msg_id, image_path, pending_caption, batch_id, now,
                wa_type=data.get('type'), mime_type=data.get('mimeType'), sender_jid=sender_jid,
                wa_message_raw=data.get('waRaw') if isinstance(data.get('waRaw'), dict) else None,
            )

    if not _loomy_on():
        if _try_classify_group_from_burst(group_id, sender, data):
            return jsonify({
                'handled': True,
                'type': 'group_categorized_from_burst',
                'count': len(photo_paths),
            })

        if _try_apply_stored_classify_intent_group(group_id, sender, data, batch_id=batch_id):
            return jsonify({
                'handled': True,
                'type': 'group_categorized_from_intent',
                'count': len(photo_paths),
            })

    # Loomy mode skips group_pending_images — do not gate intake on that collection.
    if not _loomy_on() and not _group_has_uncategorized(group_id, sender):
        return jsonify({
            'handled': True,
            'type': 'group_already_categorized',
            'count': len(photo_paths),
        })

    quote_id = _quote_msg_id(data)

    if caption and not project and worker_auto_classify_enabled():
        _cancel_scheduled_receipt(
            group_id=group_id, group_sender=sender, batch_id=batch_id,
        )
        _apply_classify_resolve(
            caption,
            to=sender,
            group_id=group_id,
            sender=sender,
            quote_msg_id=quote_id,
            batch_id=batch_id,
        )

    loomy_pool_ids = []
    from app.services.wa_classify_mode import classify_mode

    from app.services.wa_classify_mode import wa_loomy_agent_enabled

    if wa_loomy_agent_enabled() and photo_paths:
        for idx, image_path in enumerate(photo_paths):
            msg_id = _pool_msg_id(data, idx, base_msg_id)
            r = save_to_pool(
                sender,
                image_path,
                caption,
                msg_id,
                from_name,
                defer_assign=True,
                defer_reminder=True,
                batch_id=base_msg_id or None,
                chat_jid=(group_id or '').strip() or None,
                wa_message_raw=data.get('waRaw') if isinstance(data.get('waRaw'), dict) else None,
                **_pool_media_kwargs(data),
            )
            loomy_pool_ids.append(r['pool_id'])
        _loomy_after_pool_intake(
            loomy_pool_ids,
            phone=sender,
            sender_name=from_name,
            group_id=group_id,
            group_sender=sender,
            caption=caption,
            quote_msg_id=quote_id,
        )

    return jsonify({
        'handled': True,
        'type': 'group_pending_image',
        'count': len(photo_paths),
    })


def _categorize_group_image(pending, project, group_id, data, sender):
    if not project:
        _warn_unknown_group_project(group_id, str(project))
        return jsonify({'handled': True, 'type': 'group_no_match'})
    if isinstance(project, str):
        project = mongo.db.wa_projects.find_one({'code': project, 'status': 'active'})
    if not project:
        _warn_unknown_group_project(group_id, str(project))
        return jsonify({'handled': True, 'type': 'group_no_match'})

    quoted_id = data.get('quotedMsgId')
    has_quoted = data.get('hasQuotedMsg', False)

    sender_fallback = {
        'groupId': group_id,
        'senderPhone': (pending or {}).get('senderPhone') or sender,
        'categorized': False,
    }

    claim_filter = sender_fallback  # default: all pending for this sender

    if has_quoted and quoted_id:
        variants = _quoted_id_variants(quoted_id)
        # Try botReminderMsgIds first, then photo's own messageId
        quote_filter = {
            'groupId': group_id,
            'senderPhone': sender,
            'categorized': False,
            '$or': [
                {'botReminderMsgIds': {'$in': variants}},
                {'messageId': {'$in': variants}},
            ],
        }
        if mongo.db.group_pending_images.count_documents(quote_filter) > 0:
            claim_filter = quote_filter
        # else: quote didn't match any known photo/prompt → fall back to sender's batch

    now = datetime.utcnow()
    result = mongo.db.group_pending_images.update_many(
        claim_filter,
        {'$set': {'categorized': True, 'projectCode': project['code'], 'projectId': project['_id'], 'updatedAt': now}},
    )

    if result.modified_count == 0:
        return jsonify({'handled': True, 'type': 'group_already_categorized'})

    _clear_classify_intent(group_id, sender)
    _cancel_scheduled_receipt(group_id=group_id, group_sender=sender)

    claimed = list(mongo.db.group_pending_images.find(
        {'groupId': group_id, 'projectCode': project['code'], 'categorized': True},
    ).sort('updatedAt', -1).limit(result.modified_count))

    msg_ids = [img['messageId'] for img in claimed]
    pool_imgs = list(mongo.db.pool_images.find({'messageId': {'$in': msg_ids}, 'projectId': {'$exists': False}}))
    pool_by_msg = {p['messageId']: str(p['_id']) for p in pool_imgs}

    remark = _classify_remark_from_data(data)

    pool_ids = []
    missing = []
    for img in claimed:
        pid = pool_by_msg.get(img['messageId'])
        if pid:
            pool_ids.append(pid)
        else:
            missing.append(img)

    if missing:
        for m in missing:
            r = mongo.db.pool_images.insert_one({
                'phone': m['senderPhone'],
                'senderName': m.get('senderName'),
                'imagePath': m.get('imagePath'),
                'downloadFailed': not m.get('imagePath'),
                'caption': remark or project.get('code'),
                'messageId': m['messageId'],
                'createdAt': now,
                'updatedAt': now,
            })
            pool_ids.append(str(r.inserted_id))

    if remark and pool_ids:
        mongo.db.pool_images.update_many(
            {'_id': {'$in': [ObjectId(i) for i in pool_ids]}},
            {'$set': {'caption': remark, 'updatedAt': now}},
        )
        mongo.db.group_pending_images.update_many(
            {'messageId': {'$in': msg_ids}},
            {'$set': {'caption': remark, 'updatedAt': now}},
        )

    assigned = 0
    if pool_ids:
        assigned = assign_images_to_project(
            pool_ids, project, 'user', remark=remark, group_id=group_id,
        )

    notify_count = assigned if assigned > 0 else len(claimed)
    if notify_count > 0:
        from app.services.assignment_notify_service import schedule_assignment_confirmation
        schedule_assignment_confirmation(project, notify_count, group_id=group_id)

    return jsonify({'handled': True, 'type': 'group_categorized'})


def _parse_move_target(text):
    """Extract the project label from ``move <project>`` text."""
    m = re.match(r'^[\/!]?\s*move\s+(.+)$', (text or '').strip(), re.IGNORECASE)
    return m.group(1).strip() if m else None


def _assign_unassigned_for_reply(sender, project, data):
    """Assign pool files; if user quoted the bot receipt, only that batch."""
    remark = _classify_remark_from_data(data)

    def _after_assign(n):
        _clear_classify_intent(None, sender)
        clear_ai_confirm(None, sender)
        _clear_fuzzy_choice(None, sender)
        if n <= 0:
            return n
        from app.services.assignment_notify_service import schedule_assignment_confirmation
        schedule_assignment_confirmation(project, n, phone=sender)
        _cancel_scheduled_receipt(phone=sender)
        return n

    quoted = data.get('quotedMsgId') if data.get('hasQuotedMsg') else None
    if quoted:
        ids = _find_unassigned_pool_ids_by_quote(quoted, sender)
        if ids:
            n = assign_images_to_project(ids, project, 'user', remark=remark)
            return _after_assign(n)
    ids = _find_unassigned_pool_ids_latest_batch(sender)
    if not ids:
        return _after_assign(0)
    n = assign_images_to_project(ids, project, 'user', remark=remark)
    return _after_assign(n)


def _find_unassigned_pool_ids_by_quote(quoted_msg_id, sender):
    """Unassigned pool image ids when user quotes the bot's receipt (or their media msg)."""
    if not quoted_msg_id:
        return []
    variants = _quoted_id_variants(quoted_msg_id)
    docs = list(mongo.db.pool_images.find({
        **_open_pool_query(sender),
        '$or': [
            {'messageId': {'$in': variants}},
            {'botReminderMsgIds': {'$in': variants}},
        ],
    }))
    if not docs:
        for qid in variants:
            docs = list(mongo.db.pool_images.find({
                **_open_pool_query(sender),
                'messageId': {'$regex': re.escape(qid)},
            }))
            if docs:
                break
    return [str(d['_id']) for d in docs]


def _find_pool_images_by_quoted_msg(quoted_msg_id, sender):
    """Find pool_images that match a quoted messageId for a sender."""
    if not quoted_msg_id:
        return []
    possible_ids = _quoted_id_variants(quoted_msg_id)
    images = list(mongo.db.pool_images.find({
        'messageId': {'$in': possible_ids},
        'phone': sender,
        'projectId': {'$exists': True},
    }))
    if not images:
        for qid in possible_ids:
            images = list(mongo.db.pool_images.find({
                'messageId': {'$regex': re.escape(qid)},
                'phone': sender,
                'projectId': {'$exists': True},
            }))
            if images:
                break
    return images


def _find_recent_assigned_pool_images(sender, limit=20):
    """Find the most recently assigned pool_images for this sender."""
    return list(mongo.db.pool_images.find(
        {'phone': sender, 'projectId': {'$exists': True}},
    ).sort('assignedAt', -1).limit(limit))


def _handle_move(text, sender, data, *, group_id=None):
    """Process a 'move <project>' command. Returns a Flask response."""
    from app.services.wa_move_intent_service import execute_move_intent, parse_move_target

    target_label = parse_move_target(text)
    msg = execute_move_intent(sender, target_label or '', data, group_id=group_id)
    if group_id:
        try:
            send_group_message(group_id, msg)
        except Exception:
            pass
    else:
        _safe_send(sender, msg)
    return jsonify({'handled': True, 'type': 'move_loomy_legacy_path'})


def _execute_move(sender, new_project, data, *, group_id=None):
    """Find images (from quoted msg or recent) and move them."""
    has_quoted = data.get('hasQuotedMsg', False)
    quoted_id = data.get('quotedMsgId')

    if has_quoted and quoted_id:
        images = _find_pool_images_by_quoted_msg(quoted_id, sender)
    else:
        images = _find_recent_assigned_pool_images(sender, limit=20)
        if images:
            last_record_id = images[0].get('recordId')
            if last_record_id:
                images = [img for img in images if img.get('recordId') == last_record_id]
            else:
                images = images[:1]

    if not images:
        err = '⚠️ 找不到可搬移的照片。請回覆要搬移的照片再試一次。'
        if group_id:
            try:
                send_group_message(group_id, err)
            except Exception:
                pass
        else:
            _safe_send(sender, err)
        return jsonify({'handled': True, 'type': 'move_no_images'})

    already_target = all(img.get('projectCode') == new_project['code'] for img in images)
    if already_target:
        msg = f'ℹ️ 這些照片已經在專案 *{new_project["code"]}* 中，無需搬移。'
        if group_id:
            try:
                send_group_message(group_id, msg)
            except Exception:
                pass
        else:
            _safe_send(sender, msg)
        return jsonify({'handled': True, 'type': 'move_already_there'})

    old_codes = list({img.get('projectCode', '?') for img in images})
    image_ids = [str(img['_id']) for img in images]
    result = move_images_to_project(image_ids, new_project, moved_by='user')

    if result['moved'] > 0:
        old_label = ', '.join(old_codes)
        msg = (
            f'✅ 已成功搬移 *{result["moved"]}* 張照片\n'
            f'從 *{old_label}* → *{new_project["code"]}*'
        )
        if group_id:
            try:
                send_group_message(group_id, msg)
            except Exception:
                pass
        else:
            _safe_send(sender, msg)
        return jsonify({'handled': True, 'type': 'move_success', 'moved': result['moved']})

    err_detail = '；'.join(result.get('errors', []))
    msg = f'❌ 搬移失敗：{err_detail or "未知錯誤"}' 
    if group_id:
        try:
            send_group_message(group_id, msg)
        except Exception:
            pass
    else:
        _safe_send(sender, msg)
    return jsonify({'handled': True, 'type': 'move_failed', 'errors': result.get('errors', [])})


def _move_intent_key(group_id, sender):
    prefix = f'g:{group_id}:' if group_id else 'p:'
    return f'wa_move_intent:{prefix}{sender}'


def _set_move_intent(group_id, sender, data):
    """Cache the move intent so numeric fuzzy-choice reply continues the move."""
    mongo.db.wa_system.update_one(
        {'_id': _move_intent_key(group_id, sender)},
        {'$set': {
            'hasQuotedMsg': data.get('hasQuotedMsg', False),
            'quotedMsgId': data.get('quotedMsgId'),
            'at': datetime.utcnow(),
        }},
        upsert=True,
    )


def _pop_move_intent(group_id, sender):
    """Return saved move intent data or None."""
    key = _move_intent_key(group_id, sender)
    doc = mongo.db.wa_system.find_one_and_delete({'_id': key})
    if not doc or not doc.get('at'):
        return None
    age = (datetime.utcnow() - doc['at']).total_seconds()
    if age > _FUZZY_CHOICE_TTL:
        return None
    return doc


def _handle_command(cmd, sender, *, text='', data=None, group_id=None):
    """Handle bot commands. *text* is the full raw message; *data* is the
    inbound payload dict (needed for move's quoted-message context)."""

    def _cmd_reply(body: str) -> None:
        if group_id:
            try:
                send_group_message(group_id, body)
            except Exception as e:
                logger.error('[Inbound] Group command reply failed: %s', e)
        else:
            _safe_send(sender, body)

    if cmd == 'help':
        _cmd_reply(
            '*現場回報指南*\n\n'
            '*格式：* 專案編號 + 類型 + 說明 + 照片\n\n'
            '*指令：* help | keywords | projects | move | skip（追問時可用 skip）',
        )
    elif cmd == 'keywords':
        keywords = list(mongo.db.wa_keywords.find({'type': 'type_keyword', 'isActive': True}))
        lines = [f'• {k["term"]}' for k in keywords]
        _cmd_reply(
            ('*可用類型關鍵字：*\n' + '\n'.join(lines)) if lines else '尚未設定關鍵字。',
        )
    elif cmd == 'projects':
        from app.services.project_number_match_service import (
            list_wa_classify_target_projects,
            wa_classify_display_label,
        )
        from app.services.nas_sync_service import enrich_wa_projects_display

        projects = list_wa_classify_target_projects(active_only=True)
        enrich_wa_projects_display(projects)
        lines = [f'• {wa_classify_display_label(p, max_len=500)}' for p in projects]
        _cmd_reply(
            ('*活躍專案列表：*\n' + '\n'.join(lines)) if lines else '暫無活躍專案。',
        )
    elif cmd == 'move':
        return _handle_move(text, sender, data or {}, group_id=group_id)
