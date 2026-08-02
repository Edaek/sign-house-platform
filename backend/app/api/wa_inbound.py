"""Inbound message handler — receives forwarded messages from the Gateway process."""
import os
import re
import time
import hashlib
import logging
from datetime import datetime

from flask import Blueprint, jsonify, request, current_app
from bson import ObjectId
from app import mongo
from app.services.message_parser_service import extract_project_code, is_command
from app.services.wa_send_service import send_message, send_group_message, download_media
from app.services.image_pool_service import (
    save_to_pool, match_project, assign_all_unassigned, assign_images_to_project,
)
from app.services.extraction_runner_service import run_extraction
from app.services.followup_service import handle_follow_up_reply, send_follow_up
from app.services.mini_transfer_service import is_target_group, transfer_batch_to_mini

logger = logging.getLogger(__name__)

wa_inbound_bp = Blueprint('wa_inbound', __name__)

_processed = {}  # type: dict
DEDUP_TTL = 300


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
        _safe_send(sender, '⚠️ Something went wrong. Please try again.')
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

    is_image = has_media and (data.get('type') == 'image' or len(final_photos) > 0)
    is_text = not is_image and text.strip()

    if is_image:
        caption = text.strip() or None
        image_path = final_photos[0] if final_photos else None
        result = save_to_pool(sender, image_path, caption, data.get('messageId', ''), from_name)
        if result.get('auto_assigned'):
            _safe_send(sender, f'✅ Photo saved and assigned to *{result["project_code"]}*.')
        return jsonify({'handled': True, 'type': 'pool_image', 'autoAssigned': result.get('auto_assigned', False)})

    if is_text:
        has_unassigned = mongo.db.pool_images.count_documents({
            'phone': sender, 'projectId': {'$exists': False},
        }) > 0
        if has_unassigned:
            project = match_project(text)
            if project and project.get('status') == 'active':
                assign_all_unassigned(sender, project, 'user')
                return jsonify({'handled': True, 'type': 'pool_assigned'})
            _safe_send(sender, f'⚠️ Could not find a project matching "{text.strip()}".\nReply with the project code (e.g. P-001).\nSend *projects* to see the list.')
            return jsonify({'handled': True, 'type': 'pool_no_match'})

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
            _safe_send(sender, 'OK. Record submitted (some info pending).')
            return jsonify({'handled': True, 'type': 'skip'})

        cmd = is_command(text)
        if cmd:
            _handle_command(cmd, sender)
            return jsonify({'handled': True, 'type': 'command'})

        handle_follow_up_reply(str(active_record['_id']), text)
        _safe_send(sender, '✅ Information received. Processing...')
        run_extraction(str(active_record['_id']))
        send_follow_up(str(active_record['_id']))
        return jsonify({'handled': True, 'type': 'followup_reply'})

    cmd = is_command(text)
    if cmd:
        _handle_command(cmd, sender)
        return jsonify({'handled': True, 'type': 'command'})

    if text.strip():
        _safe_send(sender, '💡 Send photos to get started, or type *help* for commands.')

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

    is_image = has_media and (data.get('type') == 'image' or len(final_photos) > 0)

    if not is_image and text.strip():
        code = extract_project_code(text.strip())

        if code:
            pending = mongo.db.group_pending_images.find_one(
                {'groupId': group_id, 'categorized': False},
                sort=[('createdAt', -1)],
            )
            if pending:
                return _categorize_group_image(pending, code, group_id, data)

        if text.strip().lower() == 'projects':
            projects = list(mongo.db.wa_projects.find({'status': 'active'}))
            lines = [f'• {p["code"]} - {p.get("name", "")}' for p in projects]
            try:
                send_group_message(group_id, ('*活跃项目列表:*\n' + '\n'.join(lines)) if lines else '暂无活跃项目。')
            except Exception:
                pass
            return jsonify({'handled': True, 'type': 'group_command'})

    if is_image:
        caption = text.strip() or None
        image_path = final_photos[0] if final_photos else None

        if caption:
            code = extract_project_code(caption)
            if code:
                project = mongo.db.wa_projects.find_one({'code': code, 'status': 'active'})
                if project:
                    save_to_pool(sender, image_path, caption, data.get('messageId', ''), from_name)
                    try:
                        send_group_message(group_id, f'✅ 图片已自动归类到项目 *{project["code"]}* ({project.get("name", "")})。')
                    except Exception:
                        pass
                    return jsonify({'handled': True, 'type': 'group_auto_assigned'})

        if not image_path:
            return jsonify({'handled': True, 'type': 'group_media_unavailable'})

        now = datetime.utcnow()
        last_img = mongo.db.group_pending_images.find_one(
            {'groupId': group_id, 'senderPhone': sender, 'categorized': False},
            sort=[('createdAt', -1)],
        )
        batch_id = f'{group_id}::{sender}::{int(now.timestamp() * 1000)}'
        if last_img and last_img.get('batchId') and (now - last_img['createdAt']).total_seconds() <= 5:
            batch_id = last_img['batchId']

        mongo.db.group_pending_images.insert_one({
            'groupId': group_id,
            'senderPhone': sender,
            'senderName': from_name,
            'messageId': data.get('messageId', ''),
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
            'downloadFailed': False,
            'caption': caption,
            'messageId': data.get('messageId', ''),
            'batchId': batch_id,
            'createdAt': now,
            'updatedAt': now,
        })

        return jsonify({'handled': True, 'type': 'group_pending_image'})

    return jsonify({'handled': True, 'type': 'group_ignored'})


def _categorize_group_image(pending, code, group_id, data):
    project = mongo.db.wa_projects.find_one({'code': code, 'status': 'active'})
    if not project:
        try:
            send_group_message(group_id, f'⚠️ 找不到项目 "{code}"。请输入正确的项目编码。\n发送 *projects* 查看项目列表。')
        except Exception:
            pass
        return jsonify({'handled': True, 'type': 'group_no_match'})

    quoted_id = data.get('quotedMsgId')
    has_quoted = data.get('hasQuotedMsg', False)

    if has_quoted and quoted_id:
        parts = quoted_id.split('_')
        short_id = parts[2] if len(parts) >= 3 else None
        possible_ids = [i for i in [quoted_id, short_id] if i]
        claim_filter = {'botReminderMsgIds': {'$in': possible_ids}, 'categorized': False}
    else:
        claim_filter = {'groupId': group_id, 'senderPhone': pending['senderPhone'], 'categorized': False}

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
                'caption': code,
                'messageId': m['messageId'],
                'createdAt': now,
                'updatedAt': now,
            })
            pool_ids.append(str(r.inserted_id))

    if pool_ids:
        assign_images_to_project(pool_ids, project, 'user')

    if is_target_group(group_id):
        paths = [img['imagePath'] for img in claimed if img.get('imagePath')]
        if paths:
            import threading
            from flask import current_app
            app = current_app._get_current_object()
            p_code = project['code']

            def _do_transfer():
                with app.app_context():
                    transfer_batch_to_mini(paths, p_code)

            threading.Thread(target=_do_transfer, daemon=True).start()

    count = len(claimed)
    msg = f'✅ {count} 张图片已归类到项目 *{project["code"]}* ({project.get("name", "")})。' if count > 1 else f'✅ 图片已归类到项目 *{project["code"]}* ({project.get("name", "")})。'
    try:
        send_group_message(group_id, msg)
    except Exception:
        pass

    return jsonify({'handled': True, 'type': 'group_categorized'})


def _handle_command(cmd, sender):
    if cmd == 'help':
        _safe_send(sender,
            '*Field Reporting Guide*\n\n'
            '*FORMAT:* Project ID + Type + Description + Photos\n\n'
            '*COMMANDS:* help | keywords | projects | skip (during follow-up)')
    elif cmd == 'keywords':
        keywords = list(mongo.db.wa_keywords.find({'type': 'type_keyword', 'isActive': True}))
        lines = [f'• {k["term"]}' for k in keywords]
        _safe_send(sender, ('*Available Type Keywords:*\n' + '\n'.join(lines)) if lines else 'No keywords configured.')
    elif cmd == 'projects':
        projects = list(mongo.db.wa_projects.find({'status': 'active'}))
        lines = [f'• {p["code"]} - {p.get("name", "")}' for p in projects]
        _safe_send(sender, ('*Active Projects:*\n' + '\n'.join(lines)) if lines else 'No active projects.')
