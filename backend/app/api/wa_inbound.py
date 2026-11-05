"""Inbound message handler — receives forwarded messages from the Gateway process."""
import os
import re
import time
import hashlib
import logging
import threading
from datetime import datetime
from app.services.wa_time import wa_now

from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required
from bson import ObjectId
from app import mongo
from app.services.message_parser_service import is_command
from app.services.wa_send_service import download_media
from app.services.image_pool_service import (
    save_to_pool, match_project, match_project_ext, assign_all_unassigned,
    assign_images_to_project,
)
from app.services.project_ai_resolve_service import (
    clear_ai_confirm,
    is_affirmative,
    is_rejection_only,
)
from app.services.project_number_match_service import classify_input_matches_full_display
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
        'at': wa_now(),
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
    age = (wa_now() - doc['at']).total_seconds()
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
        {'$set': {'text': trimmed, 'at': wa_now()}},
        upsert=True,
    )
    if not group_id:
        _cancel_scheduled_receipt(phone=sender)


def _pop_classify_intent(group_id, sender):
    key = _classify_intent_key(group_id, sender)
    doc = mongo.db.wa_system.find_one_and_delete({'_id': key})
    if not doc or not doc.get('text'):
        return None
    age = (wa_now() - doc['at']).total_seconds()
    if age > _CLASSIFY_INTENT_TTL:
        return None
    return str(doc['text']).strip()


def _peek_classify_intent(group_id, sender):
    doc = mongo.db.wa_system.find_one({'_id': _classify_intent_key(group_id, sender)})
    if not doc or not doc.get('text'):
        return None
    age = (wa_now() - doc['at']).total_seconds()
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
        {'$set': {'choices': choices, 'at': wa_now()}},
        upsert=True,
    )


def _pop_fuzzy_choice(group_id, sender, selection):
    """Resolve a numeric selection (1-based). Returns project doc or None."""
    key = _fuzzy_choice_key(group_id, sender)
    doc = mongo.db.wa_system.find_one_and_delete({'_id': key})
    if not doc or not doc.get('choices'):
        return None
    age = (wa_now() - doc['at']).total_seconds()
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

    return schedule_loom_runtime_inbound(**kwargs)


def _loom_text_inbound_response(
    *,
    phone: str,
    user_text: str,
    group_id=None,
    sender_name=None,
    quoted_msg_id=None,
    inbound_message_id=None,
    has_quoted: bool = False,
    pool_ids=None,
):
    """Sign House WA text: intake only — Loom Turn owns replies (no local agent/commands)."""
    from app.services.wa_classify_mode import (
        wa_loom_runtime_brain_enabled,
        wa_loomy_agent_enabled,
    )

    if wa_loomy_agent_enabled():
        logger.warning(
            '[Inbound] SIGNHOUSE_WA_BRAIN=agent local WA is not supported in sign-house-v3; '
            'use SIGNHOUSE_WA_BRAIN=loom + Loom Turn, or sign-house-v3-mcp for local Ollama.',
        )
        return jsonify({'handled': True, 'type': 'agent_mode_not_supported_here'})
    if not wa_loom_runtime_brain_enabled():
        return jsonify({'handled': True, 'type': 'ignored_silent'})
    anchor = (inbound_message_id or quoted_msg_id or '').strip()
    notified = _schedule_loom_runtime_inbound(
        phone=phone,
        group_id=group_id,
        user_text=user_text,
        sender_name=sender_name,
        quoted_msg_id=quoted_msg_id,
        inbound_message_id=anchor or None,
        has_quoted=has_quoted,
        pool_ids=list(pool_ids or []),
        flush_immediately=bool((user_text or '').strip()),
    )
    if not notified and (user_text or '').strip():
        logger.info(
            '[Inbound] text intake only (Wakka→Loom Turn); Sign House does not forward text. text=%r',
            (user_text or '')[:80],
        )
    return jsonify({
        'handled': True,
        'type': 'loom_runtime_notify_scheduled' if notified else 'loom_runtime_deferred',
    })


def _loomy_after_pool_intake(
    pool_ids,
    *,
    phone='',
    sender_name=None,
    group_id=None,
    group_sender=None,
    caption=None,
    quote_msg_id=None,
    inbound_message_id=None,
):
    from app.services.wa_classify_mode import (
        wa_inbound_loomy_dispatch_enabled,
        wa_loom_runtime_brain_enabled,
        wa_loomy_agent_enabled,
    )

    if not pool_ids or not wa_inbound_loomy_dispatch_enabled():
        return

    if wa_loomy_agent_enabled():
        logger.warning(
            '[Inbound] Local agent pool classify removed from sign-house-v3; use brain=loom.',
        )
        return

    if not wa_loom_runtime_brain_enabled():
        return

    from app.services.pool_receipt_notify_service import (
        cancel_pool_receipt_for_group_sender,
        cancel_pool_receipt_for_phone,
    )

    if group_id and group_sender:
        cancel_pool_receipt_for_group_sender(group_id, group_sender or phone or '')
    elif phone or group_sender:
        cancel_pool_receipt_for_phone(phone or group_sender or '')

    cap = (caption or '').strip()
    sender_phone = phone or group_sender or ''
    from app.services.loom_wa_worker_reply_policy import register_gateway_pool_intake

    register_gateway_pool_intake(
        phone=sender_phone,
        group_id=group_id,
        inbound_message_id=(inbound_message_id or quote_msg_id or '').strip() or None,
    )
    anchor = (inbound_message_id or quote_msg_id or '').strip()
    _schedule_loom_runtime_inbound(
        phone=sender_phone,
        group_id=group_id,
        caption=cap,
        pool_ids=pool_ids,
        sender_name=sender_name,
        quoted_msg_id=quote_msg_id,
        inbound_message_id=anchor or None,
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
    since = wa_now() - timedelta(seconds=seconds)
    docs = list(mongo.db.pool_images.find({
        'phone': sender,
        'projectId': {'$exists': False},
        'imagePath': {'$exists': True, '$nin': [None, '']},
        'createdAt': {'$gte': since},
    }).sort('createdAt', 1))
    return [str(d['_id']) for d in docs]


def _notify_group_media_failed(group_id):
    logger.warning('[Inbound] Group media download failed for %s (Loom should explain if needed)', group_id)


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


@wa_inbound_bp.route('/loom/worker-reply-policy', methods=['GET'])
@jwt_required()
def wa_loom_worker_reply_policy():
    """MCP/Loom: whether worker WhatsApp is allowed this turn (no interim before list_pool)."""
    phone = (request.args.get('phone') or '').strip()
    group_id = (request.args.get('group_id') or request.args.get('groupId') or '').strip() or None
    inbound_mid = (
        request.args.get('inbound_message_id')
        or request.args.get('inboundMessageId')
        or ''
    ).strip()
    user_text = (request.args.get('user_text') or request.args.get('userText') or '').strip()
    if not phone:
        return jsonify({'error': 'phone required'}), 400
    from app.services.loom_turn_claim_service import claim_loom_inbound_turn
    from app.services.loom_wa_worker_reply_policy import build_worker_whatsapp_policy

    claim = claim_loom_inbound_turn(active_inbound_message_id=inbound_mid or None)
    payload = build_worker_whatsapp_policy(
        phone=phone,
        group_id=group_id,
        duplicate_inbound_turn=bool(claim.get('duplicateInboundTurn')),
        inbound_message_id=inbound_mid or None,
    )
    if user_text:
        from app.services.loomy_wa_classify_turn_service import preview_classify_turn

        preview = preview_classify_turn(user_text, phone=phone, group_id=group_id)
        if preview.get('intent') not in (None, 'none', 'other'):
            payload['classifyTurn'] = preview
            pol = payload.get('workerWhatsAppPolicy') or {}
            pol['mustCallClassifyTool'] = preview.get('mustCallTool')
            pol['instruction'] = (
                (pol.get('instruction') or '')
                + ' '
                + (preview.get('instruction') or '')
            ).strip()
            payload['workerWhatsAppPolicy'] = pol
    if inbound_mid:
        payload.update(claim)
    return jsonify(payload)


@wa_inbound_bp.route('/loom/classify-inbound-text', methods=['POST'])
@jwt_required()
def wa_loom_classify_inbound_text():
    """Deterministic site number / menu pick 1–9 for Loom (avoids Cheap_skip)."""
    data = request.get_json(silent=True) or {}
    phone = (data.get('phone') or request.args.get('phone') or '').strip()
    group_id = (data.get('group_id') or data.get('groupId') or '').strip() or None
    user_text = (data.get('user_text') or data.get('userText') or '').strip()
    pool_ids = data.get('pool_ids') or data.get('poolIds') or []
    if isinstance(pool_ids, str):
        pool_ids = [pool_ids]
    if not phone or not user_text:
        return jsonify({'error': 'phone and user_text required'}), 400
    from app.services.loomy_wa_classify_turn_service import handle_classify_inbound_text

    return jsonify(handle_classify_inbound_text(
        phone=phone,
        group_id=group_id,
        user_text=user_text,
        pool_ids=list(pool_ids) if pool_ids else None,
    ))


@wa_inbound_bp.route('/loom/store-classify-choices', methods=['POST'])
@jwt_required()
def wa_loom_store_classify_choices():
    data = request.get_json(silent=True) or {}
    phone = (data.get('phone') or '').strip()
    group_id = (data.get('group_id') or data.get('groupId') or '').strip() or None
    choices = data.get('choices') or []
    pool_ids = data.get('pool_ids') or data.get('poolIds') or []
    if isinstance(pool_ids, str):
        pool_ids = [pool_ids]
    if not phone or not choices or not pool_ids:
        return jsonify({'error': 'phone, choices, and pool_ids required'}), 400
    from app.services.loomy_wa_classify_turn_service import store_classify_choices

    return jsonify(store_classify_choices(
        phone=phone,
        group_id=group_id,
        choices=choices,
        pool_ids=list(pool_ids),
    ))


@wa_inbound_bp.route('/brain/status', methods=['GET'])
def wa_brain_status():
    """Ops: which WA brain is active and common double-reply misconfig flags."""
    import os

    from app.services.loomy_loom_platform_bridge import (
        _platform_chat_notify_fallback_allowed,
        explicit_loom_inbound_notify_url,
        loom_inbound_notify_url,
        loom_platform_all_turns_enabled,
        wa_loom_runtime_notify_configured,
        wa_loom_platform_classify_enabled,
    )
    from app.services.wa_classify_mode import (
        classify_mode,
        signhouse_executes_loom_http_actions,
        signhouse_inbound_auto_assign_enabled,
        signhouse_whatsapp_outbound_allowed,
        wa_loom_runtime_brain_enabled,
        wa_loomy_agent_enabled,
    )

    gateway_on = os.environ.get('SIGNHOUSE_WA_GATEWAY', 'true').strip().lower() not in (
        '0',
        'false',
        'no',
        'off',
    )
    notify_explicit = bool(explicit_loom_inbound_notify_url())
    notify_schedules = wa_loom_runtime_notify_configured()
    notify_resolved_url = bool(loom_inbound_notify_url())
    platform_chat = bool((os.environ.get('LOOM_PLATFORM_CHAT_URL') or '').strip())
    platform_fallback = _platform_chat_notify_fallback_allowed()
    relay_raw = (os.environ.get('LOOM_WA_RELAY_WHATSAPP_REPLY') or '').strip()
    relay_on = relay_raw.lower() in ('1', 'true', 'yes', 'on')
    hints: list[str] = []
    if wa_loomy_agent_enabled():
        hints.append('brain=agent: Sign House local Ollama may send WA (not Loom-only).')
    if wa_loom_runtime_brain_enabled() and not signhouse_whatsapp_outbound_allowed():
        hints.append(
            'brain=loom: Sign House will not send or relay WhatsApp (Loom Turn + MCP only; '
            'relay only if LOOM_WA_RELAY_WHATSAPP_REPLY=true).',
        )
    if gateway_on and notify_schedules:
        hints.append(
            'Gateway POSTs Loom HTTP (LOOM_WA_INBOUND_NOTIFY_URL): disable Loom Wakka inbound on the same number '
            'or you get two Turns per message.',
        )
    if platform_chat and platform_fallback and not notify_explicit:
        hints.append(
            'LOOM_WA_INBOUND_NOTIFY_ALLOW_PLATFORM_FALLBACK + LOOM_PLATFORM_CHAT_URL can POST Gateway→Loom HTTP '
            'while Loom Turn also runs — high double-bubble risk.',
        )
    double_reply_risk = 'low'
    if wa_loomy_agent_enabled() or signhouse_whatsapp_outbound_allowed():
        double_reply_risk = 'high'
    elif relay_on and notify_schedules:
        double_reply_risk = 'high'
    elif notify_schedules and gateway_on:
        double_reply_risk = 'high'
    elif platform_chat and platform_fallback and gateway_on and wa_loom_runtime_brain_enabled():
        double_reply_risk = 'high'
    elif wa_loom_platform_classify_enabled() or loom_platform_all_turns_enabled():
        double_reply_risk = 'high'
    if gateway_on and not notify_schedules and wa_loom_runtime_brain_enabled():
        hints.append(
            'Expected Demo: Gateway pool only + Wakka→Loom Turn. Sign House does NOT forward text and does NOT '
            'send WhatsApp in brain=loom. If workers still see two bubbles, grep Mini logs for '
            '[Wakka] Sign House → (must be 0) and check NOps Turn outbound count (must be 1).',
        )
    if wa_loom_runtime_brain_enabled() and wa_loom_platform_classify_enabled():
        hints.append(
            'LOOMY_WA_LOOM_PLATFORM_CLASSIFY is for agent-mode bridge; with brain=loom it should stay off.',
        )
    if loom_platform_all_turns_enabled():
        hints.append('LOOMY_WA_LOOM_PLATFORM_ALL_TURNS routes extra HTTP turns — risk of duplicate with Loom Turn.')
    inprocess = os.environ.get('LOOMY_WA_INPROCESS_TOOLS', 'true').strip().lower() not in (
        '0',
        'false',
        'no',
        'off',
    )
    return jsonify({
        'brain': classify_mode(),
        'localAgentEnabled': wa_loomy_agent_enabled(),
        'loomRuntimeBrain': wa_loom_runtime_brain_enabled(),
        'signhouseInboundAutoAssign': signhouse_inbound_auto_assign_enabled(),
        'signhouseExecutesLoomHttpActions': signhouse_executes_loom_http_actions(),
        'loomMcpInProcessTools': inprocess,
        'signhouseWaGatewayExpected': gateway_on,
        'loomInboundNotifyUrlConfigured': notify_schedules,
        'loomInboundNotifyExplicit': notify_explicit,
        'loomInboundNotifyResolvedUrl': notify_resolved_url,
        'loomPlatformChatFallbackAllowed': platform_fallback,
        'textInboundForwardsToLoom': notify_schedules,
        'loomPlatformChatUrlConfigured': platform_chat,
        'loomPlatformClassifyBridge': wa_loom_platform_classify_enabled(),
        'loomPlatformAllTurns': loom_platform_all_turns_enabled(),
        'relayWhatsappReplyEnv': relay_raw or None,
        'mcpBlockDirectSendInLoomMode': os.environ.get(
            'LOOMY_WA_MCP_BLOCK_DIRECT_SEND', 'true',
        ).strip().lower() not in ('0', 'false', 'no', 'off'),
        'signhouseWhatsappOutboundAllowed': signhouse_whatsapp_outbound_allowed(),
        'doubleReplyRisk': double_reply_risk,
        'wakkaConsumerChecklist': [
            'Wakka webhook/subscription → Sign House Gateway only (run.py --all)',
            'NOps: disable Loom Wakka inbound for the same WhatsApp number',
            'Set LOOM_WA_INBOUND_NOTIFY_URL (+ BEARER) when SIGNHOUSE_WA_GATEWAY=true',
            'Do not run sign-house-v3-mcp run.py --all on the same WAKKA_API_KEY',
            'LOOM_WA_RELAY_WHATSAPP_REPLY=false; Loom Persona: one WA bubble after MCP',
        ],
        'duplicateReplyHints': hints,
        'doubleReplyAudit': {
            'signHouseCanSendWhatsapp': signhouse_whatsapp_outbound_allowed(),
            'signHouseRelayEnabled': relay_on,
            'gatewaySchedulesLoomHttpPost': notify_schedules,
            'mcpWaSendBlockedInLoomMode': os.environ.get(
                'LOOMY_WA_MCP_BLOCK_DIRECT_SEND', 'true',
            ).strip().lower() not in ('0', 'false', 'no', 'off'),
            'assignNotifyWhatsappDisabledInLoom': wa_loom_runtime_brain_enabled(),
            'ifTwoBubblesSameTimestamp': [
                'Mini backend log: must NOT contain [Wakka] Sign House → (loom blocks all outbound)',
                'Mini backend log: [LoomNotify] Sent WA reply only if LOOM_WA_INBOUND_NOTIFY_URL is set',
                'NOps Turn: 1 inbound → must be 1 WhatsApp outbound; if 2, Loom channel sent twice (streaming/MCP)',
                'Loom Persona: inbound_message_id on wa_inbound_reply_policy / wa_list_pool_images each turn',
                'Same-turn short+long status = merge to ONE message after all MCP tools',
            ],
        },
    })


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
            resp = _handle_group(data, sender, from_name, group_id, sender_jid=sender_jid)
        else:
            resp = _handle_private(data, sender, from_name, text, photos, has_media)
        try:
            body = resp.get_json(silent=True) if resp else None
            if isinstance(body, dict):
                logger.info(
                    '[Inbound] msg=%s is_group=%s handled_type=%s',
                    data.get('messageId'),
                    is_group,
                    body.get('type'),
                )
        except Exception:
            pass
        return resp
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
            from app.services.wa_classify_mode import signhouse_inbound_auto_assign_enabled

            if not signhouse_inbound_auto_assign_enabled():
                project = None
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
                inbound_message_id=(data.get('messageId') or '').strip() or None,
            )

            return jsonify({
                'handled': True,
                'type': 'pool_media',
                'count': len(pool_ids),
                'autoAssigned': False,
            })

    if is_text:
        trimmed_text = text.strip()
        from app.services.wa_classify_mode import wa_inbound_loomy_dispatch_enabled

        if wa_inbound_loomy_dispatch_enabled():
            ctx = _latest_unassigned_pool_context(sender)
            return _loom_text_inbound_response(
                phone=sender,
                user_text=trimmed_text,
                sender_name=data.get('fromName') or data.get('senderName'),
                quoted_msg_id=data.get('quotedMsgId'),
                inbound_message_id=(data.get('messageId') or '').strip() or None,
                has_quoted=bool(data.get('hasQuotedMsg')),
                pool_ids=ctx.get('pool_ids'),
            )

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
        from app.services.loomy_pool_batch import latest_unassigned_pool_ids

        if wa_inbound_loomy_dispatch_enabled():
            pids = latest_unassigned_pool_ids(phone=sender, group_id=group_id)
            return _loom_text_inbound_response(
                phone=sender,
                user_text=trimmed,
                group_id=group_id,
                sender_name=from_name,
                quoted_msg_id=data.get('quotedMsgId'),
                inbound_message_id=(data.get('messageId') or '').strip() or None,
                has_quoted=bool(data.get('hasQuotedMsg')),
                pool_ids=pids,
            )
        return jsonify({'handled': True, 'type': 'group_ignored'})

    if is_media:
        with _media_lock(f'g:{group_id}:{sender}'):
            return _handle_group_media(
                data, sender, from_name, group_id, final_photos, sender_jid=sender_jid,
            )

    return jsonify({'handled': True, 'type': 'group_ignored'})


def _handle_group_media(data, sender, from_name, group_id, final_photos, *, sender_jid=None):
    caption, project = _resolve_media_project(data, sender, group_id=group_id)
    from app.services.wa_classify_mode import signhouse_inbound_auto_assign_enabled

    if not signhouse_inbound_auto_assign_enabled():
        project = None
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
        inbound_message_id=(base_msg_id or '').strip() or None,
    )

    return jsonify({
        'handled': True,
        'type': 'group_pool_media',
        'count': len(photo_paths),
    })
