"""Image pool service — manages private-chat image pool and project assignment."""
import logging
import os
import re
import threading
from datetime import datetime

from bson import ObjectId

from app import mongo
from app.services.wa_send_service import send_message
from app.services.reference_number_service import generate_reference_number
from app.services.nas_upload_service import upload_to_nas, is_nas_enabled
from app.services.message_parser_service import extract_project_code

logger = logging.getLogger(__name__)

REMIND_AFTER_S = 30
POOL_REMINDER_ENABLED = os.environ.get('POOL_REMINDER_ENABLED', 'false').lower() == 'true'

_pending_reminders = {}  # type: dict
_reminder_lock = threading.Lock()


def _send_pool_reminder(phone: str) -> None:
    """Send a WhatsApp reminder about unassigned pool images."""
    try:
        count = mongo.db.pool_images.count_documents({
            'phone': phone,
            'projectId': {'$exists': False},
        })
        if count > 0:
            send_message(
                phone,
                f'📷 您有 *{count}* 張未標記的照片。\n\n'
                f'請回覆專案編碼（例如 P-001）或專案名稱。\n\n'
                f'發送 *projects* 查看專案列表。',
            )
    except Exception:
        logger.exception('[ImagePool] Failed to send scheduled reminder')


def schedule_reminder(phone: str) -> None:
    """Schedule a 30s reminder. Resets the timer on each new image."""
    if not POOL_REMINDER_ENABLED:
        return
    with _reminder_lock:
        existing = _pending_reminders.pop(phone, None)
        if existing:
            existing.cancel()

        timer = threading.Timer(REMIND_AFTER_S, _send_pool_reminder, args=(phone,))
        timer.daemon = True
        timer.start()
        _pending_reminders[phone] = timer


def cancel_reminder(phone: str) -> None:
    """Cancel a pending reminder (e.g. when user labels images)."""
    with _reminder_lock:
        existing = _pending_reminders.pop(phone, None)
        if existing:
            existing.cancel()


def _normalize_project_label(text):
    return ' '.join((text or '').strip().split())


def _active_project_query():
    return {'status': 'active'}


def _match_project_single(trimmed, *, active_only=True):
    if not trimmed:
        return None
    query = _active_project_query() if active_only else {'status': {'$ne': 'archived'}}

    project = mongo.db.wa_projects.find_one({
        **query,
        'code': {'$regex': f'^{re.escape(trimmed)}$', '$options': 'i'},
    })
    if project:
        return project

    code = extract_project_code(trimmed)
    if code:
        project = mongo.db.wa_projects.find_one({**query, 'code': code})
        if project:
            return project

    exact_name = list(mongo.db.wa_projects.find({
        **query,
        'name': {'$regex': f'^{re.escape(trimmed)}$', '$options': 'i'},
    }))
    if len(exact_name) == 1:
        return exact_name[0]
    if len(exact_name) > 1:
        return None

    partial = list(mongo.db.wa_projects.find({
        **query,
        'name': {'$regex': re.escape(trimmed), '$options': 'i'},
    }))
    if len(partial) == 1:
        return partial[0]
    return None


def match_project(text, *, active_only=True):
    """Match user text to a project by code or name (active projects only by default)."""
    trimmed = _normalize_project_label(text)
    if not trimmed:
        return None

    hit = _match_project_single(trimmed, active_only=active_only)
    if hit:
        return hit

    for sep in (' - ', ' – ', ' — ', '—'):
        if sep in trimmed:
            left, _, right = trimmed.partition(sep)
            for part in (left.strip(), right.strip()):
                if not part:
                    continue
                hit = _match_project_single(part, active_only=active_only)
                if hit:
                    return hit
    return None


def infer_pool_media_meta(image_path, wa_type=None, mime_type=None):
    """Classify pool item for UI (image vs document vs video)."""
    file_name = os.path.basename((image_path or '').split('?')[0]) if image_path else None
    ext = os.path.splitext(file_name or '')[1].lower()
    doc_exts = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.csv'}
    video_exts = {'.mp4', '.3gp', '.mov', '.webm'}
    image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif', '.bmp'}

    if ext in doc_exts or wa_type == 'document':
        kind = 'document'
    elif ext in video_exts or wa_type == 'video':
        kind = 'video'
    elif ext in image_exts or wa_type == 'image':
        kind = 'image'
    elif mime_type:
        if mime_type.startswith('image/'):
            kind = 'image'
        elif mime_type.startswith('video/'):
            kind = 'video'
        else:
            kind = 'document'
    else:
        kind = 'file'
    return kind, file_name


def save_to_pool(
    phone,
    image_path,
    caption,
    message_id,
    sender_name=None,
    *,
    defer_assign=False,
    defer_reminder=False,
    wa_type=None,
    mime_type=None,
):
    """Save media to the pool. Auto-assigns if caption matches project code or name."""
    now = datetime.utcnow()
    media_type, file_name = infer_pool_media_meta(image_path, wa_type=wa_type, mime_type=mime_type)
    doc = {
        'phone': phone,
        'senderName': sender_name,
        'imagePath': image_path or None,
        'fileName': file_name,
        'mediaType': media_type,
        'mimeType': mime_type,
        'downloadFailed': not image_path,
        'caption': caption or None,
        'messageId': message_id,
        'createdAt': now,
        'updatedAt': now,
    }
    result = mongo.db.pool_images.insert_one(doc)
    pool_id = str(result.inserted_id)

    if caption and not defer_assign:
        project = match_project(caption)
        if project and project.get('status') == 'active':
            assign_images_to_project([pool_id], project, 'user')
            return {'auto_assigned': True, 'project_code': project['code'], 'pool_id': pool_id}

    if not defer_reminder:
        schedule_reminder(phone)
    return {'auto_assigned': False, 'pool_id': pool_id}


def assign_images_to_project(image_ids, project, assigned_by='operator'):
    """Assign pool images to a project. Creates a WA record with all photos."""
    object_ids = [ObjectId(i) for i in image_ids]
    images = list(mongo.db.pool_images.find({
        '_id': {'$in': object_ids},
        'projectId': {'$exists': False},
    }))

    if not images:
        return 0

    photos = [img['imagePath'] for img in images if img.get('imagePath')]
    caption = next((img['caption'] for img in images if img.get('caption')), '[Pool media]')
    kinds = {img.get('mediaType') or infer_pool_media_meta(img.get('imagePath'))[0] for img in images}
    if kinds <= {'image'}:
        rec_type, rec_media = 'photo', 'image'
    elif kinds <= {'document'}:
        rec_type, rec_media = 'document', 'document'
    else:
        rec_type, rec_media = 'photo', 'mixed'

    ref_number = generate_reference_number()
    now = datetime.utcnow()

    record_doc = {
        'projectId': project['_id'],
        'referenceNumber': ref_number,
        'status': 'awaiting_review',
        'type': rec_type,
        'rawMessage': caption,
        'senderPhone': images[0]['phone'],
        'senderName': images[0].get('senderName'),
        'photos': photos,
        'nasPhotos': [],
        'hasMedia': True,
        'mediaType': rec_media,
        'extractedFields': [],
        'followUpThread': [],
        'followUpRound': 0,
        'statusHistory': [{'from': 'incomplete', 'to': 'awaiting_review', 'timestamp': now}],
        'createdAt': now,
        'updatedAt': now,
    }

    from pymongo.errors import DuplicateKeyError

    record_id = None
    for attempt in range(8):
        try:
            result = mongo.db.wa_records.insert_one(record_doc)
            record_id = result.inserted_id
            break
        except DuplicateKeyError:
            record_doc['referenceNumber'] = generate_reference_number()
            if attempt >= 7:
                raise
    if not record_id:
        return 0

    mongo.db.pool_images.update_many(
        {'_id': {'$in': object_ids}},
        {'$set': {
            'projectId': project['_id'],
            'projectCode': project['code'],
            'projectName': project.get('name', ''),
            'assignedBy': assigned_by,
            'assignedAt': now,
            'recordId': record_id,
        }},
    )

    cancel_reminder(images[0]['phone'])

    msg_ids = [img['messageId'] for img in images if img.get('messageId')]
    if msg_ids:
        mongo.db.group_pending_images.update_many(
            {'messageId': {'$in': msg_ids}, 'categorized': False},
            {'$set': {
                'categorized': True,
                'projectCode': project['code'],
                'projectId': project['_id'],
                'updatedAt': now,
                'assignedVia': assigned_by,
            }},
        )

    # Copy to NAS — prefer local mount, fall back to SFTP
    from app.services.nas_watcher_service import nas_mount
    use_local = nas_mount.is_available()
    use_sftp = not use_local and is_nas_enabled()

    if use_local or use_sftp:
        import threading
        import os
        from flask import current_app
        _app = current_app._get_current_object()
        _record_id = record_id
        _images = list(images)
        _project_code = project['code']
        _media_dir = current_app.config.get('WA_UPLOADS_FOLDER', 'uploads/wa-media')
        _use_local = use_local

        def _bg_nas():
            with _app.app_context():
                try:
                    nas_photos = []
                    expected = sum(1 for img in _images if img.get('imagePath'))
                    for img in _images:
                        if not img.get('imagePath'):
                            continue

                        if _use_local:
                            web_path = img['imagePath']
                            relative = web_path.lstrip('/').replace('uploads/', '', 1)
                            if relative.startswith('wa-media/'):
                                relative = relative[len('wa-media/'):]
                            local_file = os.path.join(_media_dir, relative)
                            if not os.path.isfile(local_file):
                                logger.warning('[ImagePool] File not found for NAS copy: %s', local_file)
                                mongo.db.pool_images.update_one(
                                    {'_id': img['_id']},
                                    {'$set': {'nasSyncStatus': 'failed', 'nasSyncError': 'local file missing'}},
                                )
                                continue
                            r = nas_mount.copy_file_to_project(local_file, _project_code)
                            if r.get('ok'):
                                nas_photos.append(r['path'])
                                mongo.db.pool_images.update_one(
                                    {'_id': img['_id']},
                                    {'$set': {'nasPath': r['path'], 'nasSyncStatus': 'synced'}},
                                )
                            else:
                                mongo.db.pool_images.update_one(
                                    {'_id': img['_id']},
                                    {'$set': {
                                        'nasSyncStatus': 'failed',
                                        'nasSyncError': r.get('error', 'copy failed'),
                                    }},
                                )
                        else:
                            r = upload_to_nas(img['imagePath'], _project_code)
                            if r['success']:
                                nas_photos.append(r['nas_path'])
                                mongo.db.pool_images.update_one(
                                    {'_id': img['_id']},
                                    {'$set': {'nasPath': r['nas_path'], 'nasSyncStatus': 'synced'}},
                                )
                            else:
                                mongo.db.pool_images.update_one(
                                    {'_id': img['_id']},
                                    {'$set': {
                                        'nasSyncStatus': 'failed',
                                        'nasSyncError': r.get('error', 'upload failed'),
                                    }},
                                )

                    if expected == 0:
                        sync_status = 'skipped'
                    elif len(nas_photos) >= expected:
                        sync_status = 'synced'
                    elif nas_photos:
                        sync_status = 'partial'
                    else:
                        sync_status = 'failed'

                    update = {
                        'nasPhotos': nas_photos,
                        'nasSyncStatus': sync_status,
                        'nasSyncExpected': expected,
                        'nasSyncActual': len(nas_photos),
                        'nasSyncUpdatedAt': datetime.utcnow(),
                    }
                    if sync_status == 'failed' and expected:
                        update['nasSyncError'] = 'NAS copy/upload failed for all files'

                    mongo.db.wa_records.update_one({'_id': _record_id}, {'$set': update})
                    logger.info(
                        '[ImagePool] NAS %s %s: %d/%d files',
                        'copy' if _use_local else 'upload',
                        sync_status,
                        len(nas_photos),
                        expected,
                    )
                except Exception:
                    logger.exception('[ImagePool] NAS background error')
                    mongo.db.wa_records.update_one(
                        {'_id': _record_id},
                        {'$set': {
                            'nasSyncStatus': 'failed',
                            'nasSyncError': 'background task error',
                            'nasSyncUpdatedAt': datetime.utcnow(),
                        }},
                    )

        threading.Thread(target=_bg_nas, daemon=True).start()

    return len(images)


def assign_all_unassigned(phone, project, assigned_by='user'):
    """Assign all unassigned pool images from a phone to a project."""
    cancel_reminder(phone)

    unassigned = list(mongo.db.pool_images.find({
        'phone': phone,
        'projectId': {'$exists': False},
    }))

    if not unassigned:
        return 0

    ids = [str(img['_id']) for img in unassigned]
    count = assign_images_to_project(ids, project, assigned_by)

    if assigned_by == 'user' and count > 0:
        from app.services.assignment_notify_service import schedule_assignment_confirmation
        schedule_assignment_confirmation(project, count, phone=phone)

    return count


def get_pool_stats():
    total_unassigned = mongo.db.pool_images.count_documents({'projectId': {'$exists': False}})
    total_assigned = mongo.db.pool_images.count_documents({'projectId': {'$exists': True}})

    by_sender = list(mongo.db.pool_images.aggregate([
        {'$match': {'projectId': {'$exists': False}}},
        {'$group': {
            '_id': '$phone',
            'count': {'$sum': 1},
            'senderName': {'$first': '$senderName'},
            'latestAt': {'$max': '$createdAt'},
        }},
        {'$sort': {'latestAt': -1}},
    ]))

    return {
        'totalUnassigned': total_unassigned,
        'totalAssigned': total_assigned,
        'bySender': by_sender,
    }
