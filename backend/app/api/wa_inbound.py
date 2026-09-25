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
    return re.sub(r'@(c|s)\.us$', '', phone or '')


def _safe_send(to, text):
    try:
        send_message(to, text)
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


def _set_burst_project(group_id, sender, project):
    mongo.db.wa_system.update_one(
        {'_id': _burst_cache_id(group_id, sender)},
        {'$set': {
            'code': project['code'],
            'projectId': project['_id'],
            'at': datetime.utcnow(),
        }},
        upsert=True,
    )


def _clear_burst_project(group_id, sender):
    mongo.db.wa_system.delete_one({'_id': _burst_cache_id(group_id, sender)})


def _get_burst_project(group_id, sender, max_age_s=90):
    doc = mongo.db.wa_system.find_one({'_id': _burst_cache_id(group_id, sender)})
    if not doc or not doc.get('projectId') or not doc.get('at'):
        return None
    age = (datetime.utcnow() - doc['at']).total_seconds()
    if age > max_age_s:
        return None
    return mongo.db.wa_projects.find_one({'_id': doc['projectId'], 'status': 'active'})


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
        {'code': p['code'], 'name': p.get('name', ''), 'id': str(p['_id'])}
        for p, _score in candidates[:5]
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
    return mongo.db.wa_projects.find_one({'_id': ObjectId(choice['id']), 'status': 'active'})


def _clear_fuzzy_choice(group_id, sender):
    mongo.db.wa_system.delete_one({'_id': _fuzzy_choice_key(group_id, sender)})


def _format_fuzzy_candidates(candidates):
    """Build a numbered list string for bot reply."""
    lines = []
    for i, (proj, score) in enumerate(candidates[:5], 1):
        lines.append(f'{i}. {proj["code"]} - {proj.get("name", "")}')
    return '\n'.join(lines)


def _send_fuzzy_prompt(to, label, candidates, *, group_id=None, sender=None):
    """Send a disambiguation prompt and cache choices."""
    body = (
        f'🔍 找到多個相似專案（輸入「{label}」）：\n'
        f'{_format_fuzzy_candidates(candidates)}\n\n'
        f'回覆數字選擇，或發送完整專案編碼。'
    )
    _set_fuzzy_choice(group_id, sender or to, candidates)
    if group_id:
        try:
            send_group_message(group_id, body)
        except Exception:
            pass
    else:
        _safe_send(to, body)


def _resolve_media_project(data, sender, group_id=None):
    """WhatsApp multi-select sends separate messages; only the first has a real caption."""
    raw = (data.get('text') or data.get('caption') or '').strip()
    wa_type = data.get('type')
    caption = raw
    if caption and _looks_like_filename(caption) and wa_type in ('document', 'video', 'audio', None):
        caption = ''

    if caption:
        project = _lookup_active_project(caption)
        if project:
            return caption, project
        # User typed a caption that is not a project — do not inherit burst (e.g. "sss" after TTT batch)
        if not _looks_like_filename(raw):
            return caption, None

    burst = _get_burst_project(group_id, sender)
    if burst:
        return burst['code'], burst

    if caption:
        return caption, None
    return None, None


def _insert_group_pending_image(group_id, sender, from_name, message_id, image_path, caption, batch_id, now, wa_type=None, mime_type=None):
    from app.services.image_pool_service import infer_pool_media_meta
    media_type, file_name = infer_pool_media_meta(image_path, wa_type=wa_type, mime_type=mime_type)
    mongo.db.group_pending_images.insert_one({
        'groupId': group_id,
        'senderPhone': sender,
        'senderName': from_name,
        'messageId': message_id,
        'imagePath': image_path,
        'caption': caption,
        'batchId': batch_id,
        'categorized': False,
        'reminderCount': 0,
        'createdAt': now,
        'updatedAt': now,
    })
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
    sender = _strip_phone(data.get('from', ''))
    is_group = data.get('isGroup', False)
    group_id = data.get('groupId')

    if not sender:
        return jsonify({'handled': True, 'type': 'invalid_sender'})

    try:
        if is_group and group_id:
            return _handle_group(data, sender, from_name, group_id)
        return _handle_private(data, sender, from_name, text, photos, has_media)
    except Exception as e:
        logger.exception('[Inbound] Unhandled error')
        _safe_send(sender, '⚠️ 發生錯誤，請再試一次。')
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

    is_media = has_media and (
        data.get('type') in ('image', 'video', 'document')
        or len(final_photos) > 0
    )
    is_text = not is_media and text.strip()

    if is_media:
        with _media_lock(f'p:{sender}'):
            caption = text.strip() or None
            photo_paths = [p for p in final_photos if p]
            if not photo_paths:
                return jsonify({'handled': True, 'type': 'media_unavailable'})

            caption, project = _resolve_media_project(data, sender, group_id=None)
            base_msg_id = data.get('messageId', '') or ''
            pool_ids = []
            multi = len(photo_paths) > 1

            for idx, image_path in enumerate(photo_paths):
                msg_id = base_msg_id if idx == 0 else f'{base_msg_id}#{idx}'
                result = save_to_pool(
                    sender,
                    image_path,
                    caption,
                    msg_id,
                    from_name,
                    defer_assign=bool(project),
                    defer_reminder=bool(project or multi),
                    **_pool_media_kwargs(data),
                )
                pool_ids.append(result['pool_id'])

            if project:
                for pid in _recent_unassigned_pool_ids(sender):
                    if pid not in pool_ids:
                        pool_ids.append(pid)
                count = assign_images_to_project(pool_ids, project, 'user')
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

            if caption and not project:
                _clear_burst_project(None, sender)
                ext_result = match_project_ext(caption)
                if ext_result.candidates:
                    _safe_send(
                        sender,
                        f'📷 檔案已進入 Media Pool。\n\n'
                        f'🔍 找到多個相似專案（輸入「{caption}」）：\n'
                        f'{_format_fuzzy_candidates(ext_result.candidates)}\n\n'
                        f'回覆數字選擇，或發送完整專案編碼。',
                    )
                    _set_fuzzy_choice(None, sender, ext_result.candidates)
                else:
                    _safe_send(
                        sender,
                        f'⚠️ 找不到專案「{caption}」。檔案已進入 Media Pool，請在網頁手動歸類，'
                        f'或回覆正確的專案編碼/名稱。',
                    )

            # No caption at all — confirm receipt and ask for project
            if not caption:
                _safe_send(
                    sender,
                    f'📷 收到 *{len(pool_ids)}* 張照片，請回覆專案編碼或名稱進行歸類。\n'
                    f'發送 *projects* 查看專案列表。',
                )

            if multi:
                from app.services.image_pool_service import schedule_reminder
                schedule_reminder(sender)

            return jsonify({
                'handled': True,
                'type': 'pool_media',
                'count': len(pool_ids),
                'autoAssigned': False,
            })

    if is_text:
        trimmed_text = text.strip()

        # Check if user is replying with a number to a fuzzy-choice prompt
        if trimmed_text.isdigit():
            move_intent = _pop_move_intent(None, sender)
            choice_project = _pop_fuzzy_choice(None, sender, int(trimmed_text))
            if choice_project:
                if move_intent:
                    return _execute_move(sender, choice_project, move_intent)
                has_unassigned = mongo.db.pool_images.count_documents({
                    'phone': sender, 'projectId': {'$exists': False},
                }) > 0
                if has_unassigned:
                    assign_all_unassigned(sender, choice_project, 'user')
                    return jsonify({'handled': True, 'type': 'pool_assigned'})
                _safe_send(sender, f'✅ 已選擇專案 *{choice_project["code"]}*，但目前沒有未歸類的照片。')
                return jsonify({'handled': True, 'type': 'fuzzy_choice_no_pool'})

        has_unassigned = mongo.db.pool_images.count_documents({
            'phone': sender, 'projectId': {'$exists': False},
        }) > 0
        if has_unassigned:
            result = match_project_ext(text)
            if result.project and result.project.get('status') == 'active':
                _clear_fuzzy_choice(None, sender)
                assign_all_unassigned(sender, result.project, 'user')
                return jsonify({'handled': True, 'type': 'pool_assigned'})
            if result.candidates:
                _send_fuzzy_prompt(sender, trimmed_text, result.candidates, sender=sender)
                return jsonify({'handled': True, 'type': 'pool_fuzzy_candidates'})
            _clear_burst_project(None, sender)
            _safe_send(
                sender,
                f'⚠️ 找不到符合「{trimmed_text}」的專案。\n'
                f'請回覆專案編碼（例如 P-001）或專案名稱。\n發送 *projects* 查看專案列表。',
            )
            return jsonify({'handled': True, 'type': 'pool_no_match'})

        if trimmed_text and not is_command(trimmed_text) and not match_project(trimmed_text):
            _clear_burst_project(None, sender)

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

    if text.strip():
        _safe_send(sender, '💡 請傳送照片開始使用，或輸入 *help* 查看指令說明。')

    return jsonify({'handled': True, 'type': 'unrecognized'})


def _handle_group(data, sender, from_name, group_id):
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
        if trimmed.lower() == 'projects':
            projects = list(mongo.db.wa_projects.find({'status': 'active'}))
            lines = [f'• {p["code"]} - {p.get("name", "")}' for p in projects]
            try:
                send_group_message(group_id, ('*活躍專案列表：*\n' + '\n'.join(lines)) if lines else '暫無活躍專案。')
            except Exception:
                pass
            return jsonify({'handled': True, 'type': 'group_command'})

        # Move command in group
        cmd = is_command(trimmed)
        if cmd == 'move':
            return _handle_move(trimmed, sender, data, group_id=group_id)

        has_quoted = data.get('hasQuotedMsg', False)
        pending = _group_pending_for_sender(group_id, sender)

        # Numeric fuzzy-choice reply in group
        if trimmed.isdigit() and (pending or has_quoted):
            move_intent = _pop_move_intent(group_id, sender)
            choice_project = _pop_fuzzy_choice(group_id, sender, int(trimmed))
            if choice_project:
                if move_intent:
                    return _execute_move(sender, choice_project, move_intent, group_id=group_id)
                return _categorize_group_image(pending, choice_project, group_id, data, sender)

        project = _lookup_active_project(trimmed)

        if project and (pending or has_quoted):
            _clear_fuzzy_choice(group_id, sender)
            return _categorize_group_image(pending, project, group_id, data, sender)

        # Fuzzy matching — only engage when there are pending images or a quoted msg
        if not project and not is_command(trimmed) and (pending or has_quoted):
            ext_result = match_project_ext(trimmed, active_only=True)
            if ext_result.project:
                _clear_fuzzy_choice(group_id, sender)
                return _categorize_group_image(pending, ext_result.project, group_id, data, sender)
            if ext_result.candidates:
                _send_fuzzy_prompt(None, trimmed, ext_result.candidates, group_id=group_id, sender=sender)
                return jsonify({'handled': True, 'type': 'group_fuzzy_candidates'})
            _warn_unknown_group_project(group_id, trimmed)
            return jsonify({'handled': True, 'type': 'group_no_match'})

        if has_quoted and not project and not is_command(trimmed):
            _warn_unknown_group_project(group_id, trimmed)
            return jsonify({'handled': True, 'type': 'group_no_match'})
        if pending:
            return jsonify({'handled': True, 'type': 'group_pending_silent'})

    if is_media:
        with _media_lock(f'g:{group_id}:{sender}'):
            return _handle_group_media(
                data, sender, from_name, group_id, final_photos,
            )

    return jsonify({'handled': True, 'type': 'group_ignored'})


def _handle_group_media(data, sender, from_name, group_id, final_photos):
    caption, project = _resolve_media_project(data, sender, group_id=group_id)
    base_msg_id = data.get('messageId', '')
    photo_paths = [p for p in final_photos if p]

    if project and photo_paths:
        pool_ids = []
        for idx, image_path in enumerate(photo_paths):
            msg_id = base_msg_id if idx == 0 else f'{base_msg_id}#{idx}'
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
        assign_images_to_project(pool_ids, project, 'user')
        _set_burst_project(group_id, sender, project)
        now = datetime.utcnow()
        mongo.db.group_pending_images.update_many(
            {'groupId': group_id, 'senderPhone': sender, 'categorized': False},
            {'$set': {'categorized': True, 'updatedAt': now}},
        )
        _send_group_assigned_message(group_id, project, len(pool_ids))
        return jsonify({'handled': True, 'type': 'group_auto_assigned', 'count': len(pool_ids)})

    if not photo_paths:
        if project:
            _notify_group_media_failed(group_id)
        return jsonify({'handled': True, 'type': 'group_media_unavailable'})

    now = datetime.utcnow()
    batch_id = _group_batch_id(group_id, sender, now)
    pending_caption = caption if caption and project is None and not _looks_like_filename(caption or '') else None
    for idx, image_path in enumerate(photo_paths):
        msg_id = base_msg_id if idx == 0 else f'{base_msg_id}#{idx}'
        _insert_group_pending_image(
            group_id, sender, from_name, msg_id, image_path, pending_caption, batch_id, now,
            wa_type=data.get('type'), mime_type=data.get('mimeType'),
        )

    # Always reply in group when photos are received
    count = len(photo_paths)
    if caption and not project:
        ext_result = match_project_ext(caption)
        if ext_result.candidates:
            body = (
                f'📷 收到 *{count}* 張照片。\n\n'
                f'🔍 找到多個相似專案（輸入「{caption}」）：\n'
                f'{_format_fuzzy_candidates(ext_result.candidates)}\n\n'
                f'回覆數字選擇，或發送完整專案編碼。'
            )
            _set_fuzzy_choice(group_id, sender, ext_result.candidates)
            try:
                send_group_message(group_id, body)
            except Exception:
                pass
        else:
            try:
                send_group_message(
                    group_id,
                    f'📷 收到 *{count}* 張照片，但找不到專案「{caption}」。\n'
                    f'請回覆正確的專案編碼或名稱。\n發送 *projects* 查看專案列表。',
                )
            except Exception:
                pass
    else:
        try:
            send_group_message(
                group_id,
                f'📷 收到 *{count}* 張照片，請回覆專案編碼或名稱進行歸類。',
            )
        except Exception:
            pass

    return jsonify({
        'handled': True,
        'type': 'group_pending_image',
        'count': count,
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

    if has_quoted and quoted_id:
        parts = quoted_id.split('_')
        short_id = parts[2] if len(parts) >= 3 else None
        possible_ids = [i for i in [quoted_id, short_id] if i]
        claim_filter = {'botReminderMsgIds': {'$in': possible_ids}, 'categorized': False}
    else:
        claim_filter = {
            'groupId': group_id,
            'senderPhone': (pending or {}).get('senderPhone') or sender,
            'categorized': False,
        }

    now = datetime.utcnow()
    result = mongo.db.group_pending_images.update_many(
        claim_filter,
        {'$set': {'categorized': True, 'projectCode': project['code'], 'projectId': project['_id'], 'updatedAt': now}},
    )

    if result.modified_count == 0:
        return jsonify({'handled': True, 'type': 'group_already_categorized'})

    claimed = list(mongo.db.group_pending_images.find(
        {'groupId': group_id, 'projectCode': project['code'], 'categorized': True},
    ).sort('updatedAt', -1).limit(result.modified_count))

    msg_ids = [img['messageId'] for img in claimed]
    pool_imgs = list(mongo.db.pool_images.find({'messageId': {'$in': msg_ids}, 'projectId': {'$exists': False}}))
    pool_by_msg = {p['messageId']: str(p['_id']) for p in pool_imgs}

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
                'caption': project.get('code'),
                'messageId': m['messageId'],
                'createdAt': now,
                'updatedAt': now,
            })
            pool_ids.append(str(r.inserted_id))

    assigned = 0
    if pool_ids:
        assigned = assign_images_to_project(pool_ids, project, 'user')

    notify_count = assigned if assigned > 0 else len(claimed)
    if notify_count > 0:
        from app.services.assignment_notify_service import schedule_assignment_confirmation
        schedule_assignment_confirmation(project, notify_count, group_id=group_id)

    return jsonify({'handled': True, 'type': 'group_categorized'})


def _parse_move_target(text):
    """Extract the project label from ``move <project>`` text."""
    m = re.match(r'^[\/!]?\s*move\s+(.+)$', (text or '').strip(), re.IGNORECASE)
    return m.group(1).strip() if m else None


def _find_pool_images_by_quoted_msg(quoted_msg_id, sender):
    """Find pool_images that match a quoted messageId for a sender."""
    if not quoted_msg_id:
        return []
    parts = quoted_msg_id.split('_')
    short_id = parts[2] if len(parts) >= 3 else None
    possible_ids = [i for i in [quoted_msg_id, short_id] if i]
    images = list(mongo.db.pool_images.find({
        'messageId': {'$in': possible_ids},
        'phone': sender,
        'projectId': {'$exists': True},
    }))
    if not images and short_id:
        images = list(mongo.db.pool_images.find({
            'messageId': {'$regex': re.escape(short_id)},
            'phone': sender,
            'projectId': {'$exists': True},
        }))
    return images


def _find_recent_assigned_pool_images(sender, limit=20):
    """Find the most recently assigned pool_images for this sender."""
    return list(mongo.db.pool_images.find(
        {'phone': sender, 'projectId': {'$exists': True}},
    ).sort('assignedAt', -1).limit(limit))


def _handle_move(text, sender, data, *, group_id=None):
    """Process a 'move <project>' command. Returns a Flask response."""
    target_label = _parse_move_target(text)
    if not target_label:
        msg = (
            '📦 *搬移照片指令*\n\n'
            '用法：回覆一張照片並輸入 *move <專案名稱>*\n'
            '或直接輸入 *move <專案名稱>* 搬移最近歸類的照片。\n\n'
            '範例：move P-001'
        )
        if group_id:
            try:
                send_group_message(group_id, msg)
            except Exception:
                pass
        else:
            _safe_send(sender, msg)
        return jsonify({'handled': True, 'type': 'move_help'})

    result = match_project_ext(target_label, active_only=True)
    new_project = result.project

    if not new_project and result.candidates:
        _send_fuzzy_prompt(
            sender, target_label, result.candidates,
            group_id=group_id, sender=sender,
        )
        # Store move intent so after choosing a number, we continue the move
        _set_move_intent(group_id, sender, data)
        return jsonify({'handled': True, 'type': 'move_fuzzy_candidates'})

    if not new_project:
        err = f'⚠️ 找不到專案「{target_label}」，無法搬移。\n發送 *projects* 查看專案列表。'
        if group_id:
            try:
                send_group_message(group_id, err)
            except Exception:
                pass
        else:
            _safe_send(sender, err)
        return jsonify({'handled': True, 'type': 'move_no_project'})

    return _execute_move(sender, new_project, data, group_id=group_id)


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
    if cmd == 'help':
        _safe_send(sender,
            '*現場回報指南*\n\n'
            '*格式：* 專案編號 + 類型 + 說明 + 照片\n\n'
            '*指令：* help | keywords | projects | move | skip（追問時可用 skip）')
    elif cmd == 'keywords':
        keywords = list(mongo.db.wa_keywords.find({'type': 'type_keyword', 'isActive': True}))
        lines = [f'• {k["term"]}' for k in keywords]
        _safe_send(sender, ('*可用類型關鍵字：*\n' + '\n'.join(lines)) if lines else '尚未設定關鍵字。')
    elif cmd == 'projects':
        projects = list(mongo.db.wa_projects.find({'status': 'active'}))
        lines = [f'• {p["code"]} - {p.get("name", "")}' for p in projects]
        _safe_send(sender, ('*活躍專案列表：*\n' + '\n'.join(lines)) if lines else '暫無活躍專案。')
    elif cmd == 'move':
        return _handle_move(text, sender, data or {}, group_id=group_id)
