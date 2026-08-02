"""Image pool service — manages private-chat image pool and project assignment."""
import logging
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
            suffix = '' if count == 1 else 's'
            is_are = 'is it' if count == 1 else 'are they'
            send_message(
                phone,
                f'\U0001f4f7 You have *{count}* unlabeled photo{suffix}.\n\n'
                f'Which project {is_are} for? Reply with the project code '
                f'(e.g. P-001) or project name.\n\n'
                f'Send *projects* to see the list.',
            )
    except Exception:
        logger.exception('[ImagePool] Failed to send scheduled reminder')


def schedule_reminder(phone: str) -> None:
    """Schedule a 30s reminder. Resets the timer on each new image."""
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


def match_project(text):
    """Match text to a project by code or name. Returns project dict or None."""
    trimmed = (text or '').strip()
    if not trimmed:
        return None

    code = extract_project_code(trimmed)
    if code:
        project = mongo.db.wa_projects.find_one({'code': code, 'status': {'$ne': 'archived'}})
        if project:
            return project

    import re
    escaped = re.escape(trimmed)
    project = mongo.db.wa_projects.find_one({
        'name': {'$regex': f'^{escaped}$', '$options': 'i'},
        'status': {'$ne': 'archived'},
    })
    if project:
        return project

    return mongo.db.wa_projects.find_one({
        'name': {'$regex': escaped, '$options': 'i'},
        'status': {'$ne': 'archived'},
    })


def save_to_pool(phone, image_path, caption, message_id, sender_name=None):
    """Save an image to the pool. Auto-assigns if caption has a project code."""
    now = datetime.utcnow()
    doc = {
        'phone': phone,
        'senderName': sender_name,
        'imagePath': image_path or None,
        'downloadFailed': not image_path,
        'caption': caption or None,
        'messageId': message_id,
        'createdAt': now,
        'updatedAt': now,
    }
    result = mongo.db.pool_images.insert_one(doc)
    pool_id = str(result.inserted_id)

    if caption:
        code = extract_project_code(caption)
        if code:
            project = mongo.db.wa_projects.find_one({'code': code, 'status': 'active'})
            if project:
                assign_images_to_project([pool_id], project, 'user')
                return {'auto_assigned': True, 'project_code': project['code']}

    schedule_reminder(phone)
    return {'auto_assigned': False}


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
    caption = next((img['caption'] for img in images if img.get('caption')), '[Pool photo]')

    ref_number = generate_reference_number()
    now = datetime.utcnow()

    record_doc = {
        'projectId': project['_id'],
        'referenceNumber': ref_number,
        'status': 'awaiting_review',
        'type': 'photo',
        'rawMessage': caption,
        'senderPhone': images[0]['phone'],
        'senderName': images[0].get('senderName'),
        'photos': photos,
        'nasPhotos': [],
        'hasMedia': True,
        'mediaType': 'image',
        'extractedFields': [],
        'followUpThread': [],
        'followUpRound': 0,
        'statusHistory': [{'from': 'incomplete', 'to': 'awaiting_review', 'timestamp': now}],
        'createdAt': now,
        'updatedAt': now,
    }

    for attempt in range(3):
        try:
            result = mongo.db.wa_records.insert_one(record_doc)
            record_id = result.inserted_id
            break
        except Exception as e:
            if hasattr(e, 'code') and e.code == 11000 and attempt < 2:
                record_doc['referenceNumber'] = generate_reference_number()
                continue
            raise
    else:
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

    if is_nas_enabled():
        import threading

        def _bg_nas():
            try:
                nas_photos = []
                for img in images:
                    if not img.get('imagePath'):
                        continue
                    r = upload_to_nas(img['imagePath'], project['code'])
                    if r['success']:
                        nas_photos.append(r['nas_path'])
                        mongo.db.pool_images.update_one(
                            {'_id': img['_id']},
                            {'$set': {'nasPath': r['nas_path']}},
                        )
                if nas_photos:
                    mongo.db.wa_records.update_one(
                        {'_id': record_id},
                        {'$set': {'nasPhotos': nas_photos}},
                    )
                    logger.info('[ImagePool] NAS upload done: %d files', len(nas_photos))
            except Exception:
                logger.exception('[ImagePool] NAS background upload error')

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
        try:
            suffix = '' if count == 1 else 's'
            send_message(
                phone,
                f'✅ {count} photo{suffix} assigned to *{project["code"]}* ({project.get("name", "")}).',
            )
        except Exception:
            logger.exception('[ImagePool] Failed to send confirmation')

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
