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
    assign_images_to_project, move_images_to_project,
)
from app.services.project_ai_resolve_service import (
    clear_ai_confirm,
    is_affirmative,
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


def _schedule_loom_runtime_inbound(**kwargs):
    from app.services.loomy_loom_inbound_notify import schedule_loom_runtime_inbound

    return schedule_loom_runtime_inbound(flush_immediately=True, **kwargs)


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
        wa_inbound_loomy_dispatch_enabled,
        wa_loom_runtime_brain_enabled,
        wa_loomy_agent_enabled,
    )

    if not pool_ids or not wa_inbound_loomy_dispatch_enabled():
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

    if wa_loomy_agent_enabled():
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
    elif wa_loom_runtime_brain_enabled():
        _schedule_loom_runtime_inbound(
            phone=sender_phone,
            group_id=group_id,
            caption=cap,
            pool_ids=pool_ids,
            sender_name=sender_name,
            quoted_msg_id=quote_msg_id,
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
                msg_id = (data.get('messageId') or '').strip()
                if has_media and msg_id:
                    from app.services.image_pool_service import save_to_pool

                    saved = save_to_pool(
                        sender,
                        None,
                        caption,
                        msg_id,
                        from_name,
                        defer_assign=True,
                        defer_reminder=True,
                        wa_type=data.get('type'),
                        mime_type=data.get('mimeType'),
                        chat_jid=(data.get('from') or '').strip() or None,
                        wa_message_raw=data.get('waRaw') if isinstance(data.get('waRaw'), dict) else None,
                    )
                    return jsonify({
                        'handled': True,
                        'type': 'pool_media_pending',
                        'pool_id': saved.get('pool_id'),
                    })
                return jsonify({'handled': True, 'type': 'media_unavailable'})

            caption, project = _resolve_media_project(data, sender, group_id=None)
            base_msg_id = data.get('messageId', '') or ''
            inbound_batch_id = _quote_msg_id(data) or base_msg_id
            pool_ids = []
            multi = len(photo_paths) > 1

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

            if project:
                for pid in _recent_unassigned_pool_ids(sender):
                    if pid not in pool_ids:
                        pool_ids.append(pid)
                remark = _classify_remark_from_data(data)
                count = assign_images_to_project(pool_ids, project, 'user', remark=remark)
                _set_burst_project(None, sender, project)
                return jsonify({
                    'handled': True,
                    'type': 'pool_assigned_batch',
                    'count': count,
                    'projectCode': project['code'],
                })

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

        from app.services.wa_classify_mode import (
            wa_inbound_loomy_dispatch_enabled,
            wa_loomy_agent_enabled,
        )

        if wa_inbound_loomy_dispatch_enabled():
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
            if wa_loomy_agent_enabled():
                ctx = _latest_unassigned_pool_context(sender)
                from app.services.loomy_loom_platform_bridge import should_use_loom_platform

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
                    loom_classify_attempted=should_use_loom_platform(loom_ctx),
                )
                return jsonify({'handled': True, 'type': 'loomy_wa_agent'})
            notified = _schedule_loom_runtime_inbound(
                phone=sender,
                user_text=trimmed_text,
                sender_name=data.get('fromName') or data.get('senderName'),
                quoted_msg_id=data.get('quotedMsgId'),
                has_quoted=bool(data.get('hasQuotedMsg')),
            )
            return jsonify({
                'handled': True,
                'type': 'loom_runtime_notify_scheduled' if notified else 'loom_runtime_deferred',
            })

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
        from app.services.wa_classify_mode import wa_inbound_loomy_dispatch_enabled

        if wa_inbound_loomy_dispatch_enabled():
            from app.services.wa_classify_mode import wa_loomy_agent_enabled
            from app.services.loomy_pool_batch import latest_unassigned_pool_ids

            pids = latest_unassigned_pool_ids(phone=sender, group_id=group_id)
            if wa_loomy_agent_enabled():
                from app.services.loomy_wa_agent_service import (
                    try_loomy_inbound_text_reply,
                    try_loomy_numeric_pick,
                )

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
            if wa_loomy_agent_enabled():
                from app.services.loomy_loom_platform_bridge import should_use_loom_platform

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
                    loom_classify_attempted=should_use_loom_platform(loom_ctx),
                )
                return jsonify({'handled': True, 'type': 'loomy_wa_agent'})
            notified = _schedule_loom_runtime_inbound(
                phone=sender,
                group_id=group_id,
                user_text=trimmed,
                sender_name=from_name,
                quoted_msg_id=data.get('quotedMsgId'),
                has_quoted=bool(data.get('hasQuotedMsg')),
            )
            return jsonify({
                'handled': True,
                'type': 'loom_runtime_notify_scheduled' if notified else 'loom_runtime_deferred',
            })

        from app.services.nas_site_remark_service import try_append_followup_site_remark

        if try_append_followup_site_remark(sender, trimmed, group_id=group_id):
            return jsonify({'handled': True, 'type': 'group_site_remark_appended'})
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
    quote_id = _quote_msg_id(data)

    if not photo_paths:
        msg_id = (data.get('messageId') or '').strip()
        if data.get('hasMedia') and msg_id:
            saved = save_to_pool(
                sender,
                None,
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
            return jsonify({
                'handled': True,
                'type': 'pool_media_pending',
                'pool_id': saved.get('pool_id'),
            })
        if project:
            _notify_group_media_failed(group_id)
        return jsonify({'handled': True, 'type': 'group_media_unavailable'})

    if project:
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
                batch_id=base_msg_id or None,
                chat_jid=(group_id or '').strip() or None,
                wa_message_raw=data.get('waRaw') if isinstance(data.get('waRaw'), dict) else None,
                **_pool_media_kwargs(data),
            )
            pool_ids.append(result['pool_id'])
        for pid in _recent_unassigned_pool_ids(sender):
            if pid not in pool_ids:
                pool_ids.append(pid)
        remark = _classify_remark_from_data(data)
        assign_images_to_project(
            pool_ids, project, 'user', remark=remark or None, group_id=group_id,
        )
        _set_burst_project(group_id, sender, project)
        _clear_classify_intent(group_id, sender)
        return jsonify({'handled': True, 'type': 'group_pool_assigned', 'count': len(pool_ids)})

    loomy_pool_ids = []
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
        'type': 'group_pool_media',
        'count': len(photo_paths),
    })


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
