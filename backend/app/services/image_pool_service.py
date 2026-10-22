"""Image pool service — manages private-chat image pool and project assignment."""
import hashlib
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from bson import ObjectId

from app import mongo
from app.services.wa_send_service import send_message
from app.services.reference_number_service import generate_reference_number
from app.services.nas_upload_service import upload_to_nas, is_nas_enabled
from app.services.message_parser_service import (
    extract_project_code,
    split_classify_label_and_remark,
    trailing_classify_remark,
)
from app.services.project_number_match_service import (
    is_wa_classify_target,
    match_classify_targets_by_site_number,
    match_classify_typo_site_numbers,
    match_classify_cross_bucket_typo_suggestions,
    match_classify_sites_near_number_in_buckets,
    match_site_projects_by_number,
    find_buckets_containing_site_number,
    pj_number_from_project_code,
    primary_site_number,
)

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


_PROJECT_NUM_RE = re.compile(r'^[Pp][#\-]?(\d{1,4})$')
_HASH_NUM_RE = re.compile(r'^#(\d{1,4})$')


def _expand_project_codes(num_str):
    """Generate all possible P-xxx codes from a captured numeric string.

    E.g. "1" → {"P-1", "P-01", "P-001", "P-0001"}
    """
    codes = set()
    for width in range(len(num_str), 5):
        codes.add(f'P-{num_str.zfill(width)}')
    codes.add(f'P-{num_str}')
    return codes


def _find_projects_by_codes(codes, query):
    """Find all projects whose code matches any of the given codes."""
    regex_parts = [f'^{re.escape(c)}$' for c in codes]
    combined = '|'.join(regex_parts)
    return list(mongo.db.wa_projects.find({
        **query,
        'code': {'$regex': combined, '$options': 'i'},
    }))


def _classify_hit(project):
    if project and is_wa_classify_target(project):
        return project
    return None


def _filter_classify_candidates(candidates):
    return [(p, s) for p, s in candidates if is_wa_classify_target(p)]


def _match_project_single(trimmed, *, active_only=True):
    if not trimmed:
        return None
    query = _active_project_query() if active_only else {'status': {'$ne': 'archived'}}

    # 1. Exact code match (case insensitive)
    project = mongo.db.wa_projects.find_one({
        **query,
        'code': {'$regex': f'^{re.escape(trimmed)}$', '$options': 'i'},
    })
    if project:
        return _classify_hit(project)

    # 2. Shorthand code (P1, P01, #1 etc) — expand to all possible paddings
    for pattern in (_PROJECT_NUM_RE, _HASH_NUM_RE):
        m = pattern.match(trimmed)
        if m:
            codes = _expand_project_codes(m.group(1))
            matches = _find_projects_by_codes(codes, query)
            if len(matches) == 1:
                return _classify_hit(matches[0])
            if len(matches) > 1:
                return None  # ambiguous — let caller handle as candidates
            break

    # 3. Legacy extract_project_code (handles other patterns)
    code = extract_project_code(trimmed)
    if code:
        project = mongo.db.wa_projects.find_one({**query, 'code': code})
        if project:
            return _classify_hit(project)

    # 4. Exact NAS folder / code match (folder label on share)
    folder_or_code = list(mongo.db.wa_projects.find({
        **query,
        '$or': [
            {'code': {'$regex': f'^{re.escape(trimmed)}$', '$options': 'i'}},
            {'nasFolder': {'$regex': f'^{re.escape(trimmed)}$', '$options': 'i'}},
        ],
    }))
    if len(folder_or_code) == 1:
        return _classify_hit(folder_or_code[0])
    if len(folder_or_code) > 1:
        return None

    # 5. Partial NAS folder match (unique only)
    partial = list(mongo.db.wa_projects.find({
        **query,
        'nasFolder': {'$regex': re.escape(trimmed), '$options': 'i'},
    }))
    classify_partial = [p for p in partial if is_wa_classify_target(p)]
    if len(classify_partial) == 1:
        return classify_partial[0]
    # Bare leading number used as project code (e.g. "2899" from "2899 carpark sign")
    if trimmed.isdigit():
        project = mongo.db.wa_projects.find_one({
            **query,
            'code': {'$regex': f'^{re.escape(trimmed)}$', '$options': 'i'},
        })
        hit = _classify_hit(project)
        if hit:
            return hit
        project = mongo.db.wa_projects.find_one({
            **query,
            'code': {'$regex': f'^PJ-{re.escape(trimmed)}$', '$options': 'i'},
        })
        hit = _classify_hit(project)
        if hit:
            return hit
        codes = _expand_project_codes(trimmed)
        matches = _find_projects_by_codes(codes, query)
        classify_matches = [p for p in matches if is_wa_classify_target(p)]
        if len(classify_matches) == 1:
            return classify_matches[0]
    return None


def _match_project_code_candidates(trimmed, *, active_only=True):
    """Return multiple projects matching ambiguous shorthand codes like 'P1'."""
    query = _active_project_query() if active_only else {'status': {'$ne': 'archived'}}
    for pattern in (_PROJECT_NUM_RE, _HASH_NUM_RE):
        m = pattern.match(trimmed)
        if m:
            codes = _expand_project_codes(m.group(1))
            matches = _find_projects_by_codes(codes, query)
            if len(matches) > 1:
                return _filter_classify_candidates([(p, 100) for p in matches])
    return []


FUZZY_HIGH = 88
FUZZY_MID = 78


def _fuzzy_code_score(text_lower, code, folder_name=''):
    """Text classify — avoid digit-only partial matches (1007 ≠ PJ-3007)."""
    from rapidfuzz import fuzz

    if not text_lower:
        return 0
    code_l = (code or '').lower()
    folder_l = (folder_name or '').lower()
    if text_lower.isdigit():
        return 0
    if text_lower in code_l or text_lower in folder_l:
        return 95
    ratio_code = fuzz.ratio(text_lower, code_l)
    ratio_folder = fuzz.ratio(text_lower, folder_l) if folder_l else 0
    token_code = fuzz.token_set_ratio(text_lower, code_l)
    token_folder = fuzz.token_set_ratio(text_lower, folder_l) if folder_l else 0
    best = max(ratio_code, ratio_folder, token_code, token_folder)
    if len(text_lower) <= 4:
        partial_code = fuzz.partial_ratio(text_lower, code_l)
        partial_folder = fuzz.partial_ratio(text_lower, folder_l) if folder_l else 0
        if partial_code >= 90 or partial_folder >= 90:
            best = max(best, partial_code, partial_folder)
    return best


def _fuzzy_match_projects(text, *, active_only=True):
    """Score classify-target projects; returns all hits above threshold (no cap)."""
    query = _active_project_query() if active_only else {'status': {'$ne': 'archived'}}
    projects = list(mongo.db.wa_projects.find(query))
    if not projects:
        return []

    text_lower = text.strip().lower()
    if text_lower.isdigit():
        return []

    scored = []
    for proj in projects:
        if not is_wa_classify_target(proj):
            continue
        code = proj.get('code') or ''
        folder = (proj.get('nasFolder') or '')
        if folder:
            folder = Path(folder).name
        best = _fuzzy_code_score(text_lower, code, folder)
        if best >= FUZZY_MID:
            scored.append((proj, best))

    scored.sort(key=lambda t: t[1], reverse=True)
    return scored


class MatchResult:
    """Wrapper returned by :func:`match_project_ext` to carry fuzzy candidates."""

    __slots__ = ('project', 'candidates', 'remark')

    def __init__(self, project=None, candidates=None, remark=None):
        self.project = project
        self.candidates = candidates or []
        self.remark = remark

    def __bool__(self):
        return self.project is not None


def _merge_scored_candidates(*groups):
    """Dedupe by project id; keep highest score."""
    by_id = {}
    order = []
    for group in groups:
        for proj, score in group:
            if not is_wa_classify_target(proj):
                continue
            pid = str(proj.get('_id', proj.get('code', '')))
            if pid not in by_id:
                order.append(pid)
                by_id[pid] = (proj, score)
            else:
                prev_proj, prev_score = by_id[pid]
                if score > prev_score:
                    by_id[pid] = (prev_proj, score)
    out = [by_id[pid] for pid in order]
    out.sort(key=lambda t: t[1], reverse=True)
    return out


def match_project_ext(text, *, active_only=True):
    """Extended project match — returns a :class:`MatchResult`.

    * ``result.project`` is set when a single confident match is found (exact
      or high-score fuzzy).
    * ``result.candidates`` lists all confident fuzzy / numeric suggestions.
    * ``result.remark`` is set when input is ``<project label> <remark>`` (e.g.
      ``2899 carpark sign`` → match on ``2899``, remark ``carpark sign``).
    """
    trimmed = _normalize_project_label(text)
    if not trimmed:
        return MatchResult()

    label, remark = split_classify_label_and_remark(trimmed)
    match_key = label or trimmed
    label_only = bool(remark)

    def _result(project=None, candidates=None):
        return MatchResult(project=project, candidates=candidates, remark=remark or None)

    hit = _match_project_single(match_key, active_only=active_only)
    if hit:
        return _result(project=hit)

    # Ambiguous shorthand codes like "P1" matching both P-001 and P-0001
    code_candidates = _match_project_code_candidates(match_key, active_only=active_only)
    if code_candidates:
        return _result(candidates=code_candidates)

    if not label_only:
        for sep in (' - ', ' – ', ' — ', '—'):
            if sep in trimmed:
                left, _, right = trimmed.partition(sep)
                for part in (left.strip(), right.strip()):
                    if not part:
                        continue
                    hit = _match_project_single(part, active_only=active_only)
                    if hit:
                        return _result(project=hit)

    fuzzy_text = match_key if label_only else trimmed
    site_num = primary_site_number(match_key)
    digit_input = bool(match_key.strip().isdigit() and site_num)

    if digit_input and site_num:
        try:
            site_n_int = int(site_num)
        except ValueError:
            site_n_int = None

        numeric_scored = []
        bucket_codes = []
        if site_n_int is not None:
            bucket_codes = find_buckets_containing_site_number(site_n_int, active_only=active_only)
            if bucket_codes:
                numeric_scored = match_classify_sites_near_number_in_buckets(
                    site_num, bucket_codes, active_only=active_only,
                )

        if not numeric_scored:
            numeric_scored = _merge_scored_candidates(
                match_classify_targets_by_site_number(site_num, active_only=active_only),
                [(p, s) for p, s, _ in match_site_projects_by_number(site_num, active_only=active_only)],
            )
        cross_typo = match_classify_cross_bucket_typo_suggestions(
            site_num,
            bucket_codes,
            active_only=active_only,
            max_distance=2,
            limit=2,
        )
        numeric_scored = _merge_scored_candidates(numeric_scored, cross_typo)
        if numeric_scored:
            return _result(candidates=numeric_scored)

    fuzzy_scored = _fuzzy_match_projects(fuzzy_text, active_only=active_only)
    if fuzzy_scored:
        high_hits = [(p, s) for p, s in fuzzy_scored if s >= FUZZY_HIGH]
        if len(high_hits) == 1:
            return _result(project=high_hits[0][0])
        mid_hits = [(p, s) for p, s in fuzzy_scored if s >= FUZZY_MID]
        if mid_hits:
            return _result(candidates=mid_hits)

    return MatchResult()


def match_project(text, *, active_only=True):
    """Match user text to a project by code or name (active projects only by default).

    Backward-compatible wrapper — returns a single project dict or ``None``.
    """
    result = match_project_ext(text, active_only=active_only)
    return result.project


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
    batch_id=None,
    chat_jid=None,
    wa_message_raw=None,
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
    if batch_id:
        doc['batchId'] = batch_id
    if chat_jid and '@' in str(chat_jid):
        doc['chatJid'] = str(chat_jid).strip()
    if isinstance(wa_message_raw, dict) and wa_message_raw:
        doc['waMessageRaw'] = wa_message_raw
    result = mongo.db.pool_images.insert_one(doc)
    pool_id = str(result.inserted_id)

    if caption and not defer_assign:
        from app.services.project_ai_resolve_service import resolve_classify_input

        resolved = resolve_classify_input(caption, active_only=True)
        if resolved.action == 'assign' and resolved.project:
            assign_images_to_project([pool_id], resolved.project, 'user', remark=resolved.remark)
            return {
                'auto_assigned': True,
                'project_code': resolved.project['code'],
                'pool_id': pool_id,
            }

    if not defer_reminder:
        schedule_reminder(phone)
    return {'auto_assigned': False, 'pool_id': pool_id}


_POOL_MEDIA_PLACEHOLDER = '[Pool media]'


def resolve_record_remark(record):
    """Display remark for UI: rawMessage or pool image caption (WhatsApp classify note)."""
    msg = (record.get('rawMessage') or '').strip()
    if msg and msg.lower() != _POOL_MEDIA_PLACEHOLDER.lower():
        remark = trailing_classify_remark(msg)
        if remark:
            return remark
        label, _ = split_classify_label_and_remark(msg)
        if label and msg == label:
            from app.services.message_parser_service import _first_token_is_classify_code

            if _first_token_is_classify_code(label.split()[0] if label else ''):
                return ''
        return msg
    rid = record.get('_id')
    if rid:
        img = mongo.db.pool_images.find_one(
            {
                'recordId': rid,
                'caption': {'$exists': True, '$nin': [None, '']},
            },
            projection={'caption': 1},
        )
        cap = (img or {}).get('caption')
        if cap and str(cap).strip():
            cap_s = str(cap).strip()
            remark = trailing_classify_remark(cap_s)
            if remark:
                return remark
            label, _ = split_classify_label_and_remark(cap_s)
            if label and cap_s == label:
                from app.services.message_parser_service import _first_token_is_classify_code

                if _first_token_is_classify_code(label.split()[0] if label else ''):
                    return ''
            return cap_s
    return msg or ''


def _local_media_path_for_pool(web_path, media_dir):
    """Resolve pool imagePath to an on-disk file under WA_UPLOADS_FOLDER."""
    if not web_path:
        return None
    wp = str(web_path).strip()
    if os.path.isabs(wp) and os.path.isfile(wp):
        return wp
    rel = wp.lstrip('/')
    if rel.startswith('uploads/'):
        rel = rel[len('uploads/'):]
    if rel.startswith('wa-media/'):
        rel = rel[len('wa-media/'):]
    fname = os.path.basename(rel) or os.path.basename(wp)
    candidates = [
        os.path.join(media_dir, rel),
        os.path.join(media_dir, fname),
    ]
    try:
        from flask import current_app

        root = current_app.root_path
        candidates.append(os.path.join(root, media_dir, fname))
        candidates.append(os.path.join(root, 'uploads', 'wa-media', fname))
    except RuntimeError:
        pass
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def _save_pool_media_bytes(data: bytes, media_dir, *, ext='.jpg'):
    os.makedirs(media_dir, exist_ok=True)
    fname = f'{int(time.time() * 1000)}-{hashlib.md5(os.urandom(8)).hexdigest()[:8]}{ext}'
    fpath = os.path.join(media_dir, fname)
    with open(fpath, 'wb') as fh:
        fh.write(data)
    return fpath, f'/uploads/wa-media/{fname}'


def _ensure_pool_image_file(img, media_dir):
    """Return absolute path to media file, re-downloading from Wakka if needed."""
    local = _local_media_path_for_pool(img.get('imagePath'), media_dir)
    if local:
        return local
    message_id = (img.get('messageId') or '').strip()
    if not message_id:
        return None
    from app.services.wa_send_service import download_media

    buf = download_media(message_id)
    if not buf:
        return None
    wa_type = img.get('mediaType') or 'image'
    ext_map = {'image': '.jpg', 'video': '.mp4', 'document': '.pdf'}
    ext = ext_map.get(wa_type, '.jpg')
    fpath, web_path = _save_pool_media_bytes(buf, media_dir, ext=ext)
    mongo.db.pool_images.update_one(
        {'_id': img['_id']},
        {'$set': {
            'imagePath': web_path,
            'downloadFailed': False,
            'updatedAt': datetime.utcnow(),
        }},
    )
    img['imagePath'] = web_path
    return fpath


def assign_images_to_project(
    image_ids,
    project,
    assigned_by='operator',
    *,
    remark=None,
    group_id=None,
):
    """Assign pool images to a project. Creates a WA record with all photos."""
    object_ids = [ObjectId(i) for i in image_ids]
    images = list(mongo.db.pool_images.find({
        '_id': {'$in': object_ids},
        'projectId': {'$exists': False},
    }))

    if not images:
        return 0

    remark = (remark or '').strip() or None
    if remark:
        remark = trailing_classify_remark(remark) or remark.strip() or None
    if not remark:
        for img in images:
            cap = (img.get('caption') or '').strip()
            if cap:
                remark = trailing_classify_remark(cap)
                if remark:
                    break
    remark = (remark or '').strip() or None
    if remark:
        mongo.db.pool_images.update_many(
            {'_id': {'$in': object_ids}},
            {'$set': {'caption': remark, 'updatedAt': datetime.utcnow()}},
        )
        for img in images:
            img['caption'] = remark

    photos = [img['imagePath'] for img in images if img.get('imagePath')]
    caption = remark or _POOL_MEDIA_PLACEHOLDER
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

    from app.services.nas_site_remark_service import (
        hk_today_str,
        set_site_remark_context,
    )

    assign_day = hk_today_str()
    phone = images[0].get('phone') or ''
    set_site_remark_context(
        phone, project['code'], group_id=group_id, day_str=assign_day,
    )

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
        _pref_folder = (project.get('nasFolderName') or '').strip() or None
        _pref_bucket = (project.get('nasParentBucket') or '').strip() or None
        _media_dir = current_app.config.get('WA_UPLOADS_FOLDER', 'uploads/wa-media')
        _use_local = use_local
        _assign_day = assign_day
        _assign_remark = remark

        def _bg_nas():
            with _app.app_context():
                try:
                    nas_photos = []
                    expected = len(_images)
                    for img in _images:
                        if _use_local:
                            local_file = _ensure_pool_image_file(img, _media_dir)
                            if not local_file:
                                logger.warning(
                                    '[ImagePool] No local file for NAS copy (pool=%s msg=%s)',
                                    img.get('_id'),
                                    img.get('messageId'),
                                )
                                mongo.db.pool_images.update_one(
                                    {'_id': img['_id']},
                                    {'$set': {
                                        'nasSyncStatus': 'failed',
                                        'nasSyncError': 'local file missing',
                                    }},
                                )
                                continue
                            r = nas_mount.copy_file_to_project(
                                local_file,
                                _project_code,
                                day_str=_assign_day,
                                preferred_folder_name=_pref_folder,
                                preferred_parent_bucket=_pref_bucket,
                            )
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
                            if not img.get('imagePath'):
                                _ensure_pool_image_file(img, _media_dir)
                            r = upload_to_nas(
                                img['imagePath'], _project_code, day_str=_assign_day,
                            )
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
                    if _assign_remark and (nas_photos or expected == 0):
                        from app.services.nas_site_remark_service import append_site_remark_to_nas

                        append_site_remark_to_nas(
                            _project_code, _assign_remark, day_str=_assign_day,
                        )
                    if expected > 0 and len(nas_photos) == 0:
                        phone = (_images[0].get('phone') or '').strip()
                        if phone:
                            try:
                                send_message(
                                    phone,
                                    '⚠️ 專案已歸類，但照片未能寫入 NAS（檔案缺失或複製失敗）。'
                                    '請到「媒體池」重試下載，或重新發送照片。',
                                )
                            except Exception:
                                logger.exception('[ImagePool] NAS failure notify send failed')
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

    _schedule_record_extraction(record_id)

    return len(images)


def _schedule_record_extraction(record_id):
    """Run Ollama field extraction after pool assign (background)."""
    if not record_id:
        return
    try:
        from flask import current_app
        app = current_app._get_current_object()
    except RuntimeError:
        return

    rid = str(record_id)

    def _run():
        with app.app_context():
            try:
                from app.services.extraction_runner_service import run_extraction
                run_extraction(rid)
            except Exception:
                logger.exception('[ImagePool] Post-assign extraction failed for %s', rid)

    threading.Thread(target=_run, daemon=True).start()


def assign_all_unassigned(phone, project, assigned_by='user', *, remark=None):
    """Assign all unassigned pool images from a phone to a project."""
    cancel_reminder(phone)

    unassigned = list(mongo.db.pool_images.find({
        'phone': phone,
        'projectId': {'$exists': False},
    }))

    if not unassigned:
        return 0

    ids = [str(img['_id']) for img in unassigned]
    count = assign_images_to_project(ids, project, assigned_by, remark=remark)

    if assigned_by == 'user' and count > 0:
        from app.services.assignment_notify_service import schedule_assignment_confirmation
        schedule_assignment_confirmation(project, count, phone=phone)

    return count


def move_images_to_project(image_ids, new_project, moved_by='user'):
    """Move already-assigned pool images to a different project.

    Steps:
    1. For each pool_image, remove it from its current wa_record (pull photo
       from the ``photos`` array; delete the record if it becomes empty).
    2. Reset pool_image assignment fields so it looks unassigned.
    3. Call :func:`assign_images_to_project` to create a new wa_record under
       *new_project* and trigger NAS copy.

    Returns ``{'moved': int, 'errors': list[str]}``.
    """
    object_ids = [ObjectId(i) for i in image_ids]
    images = list(mongo.db.pool_images.find({'_id': {'$in': object_ids}}))
    if not images:
        return {'moved': 0, 'errors': ['找不到指定的照片']}

    errors = []
    now = datetime.utcnow()

    for img in images:
        old_record_id = img.get('recordId')
        if old_record_id:
            img_path = img.get('imagePath')
            if img_path:
                mongo.db.wa_records.update_one(
                    {'_id': old_record_id},
                    {'$pull': {'photos': img_path, 'nasPhotos': {'$regex': re.escape(os.path.basename(img_path))}}},
                )
            rec = mongo.db.wa_records.find_one({'_id': old_record_id})
            if rec and not rec.get('photos'):
                mongo.db.wa_records.update_one(
                    {'_id': old_record_id},
                    {'$set': {'status': 'moved', 'updatedAt': now},
                     '$push': {'statusHistory': {
                         'from': rec.get('status', 'unknown'),
                         'to': 'moved',
                         'timestamp': now,
                         'reason': f'All photos moved to {new_project["code"]}',
                     }}},
                )

        mongo.db.pool_images.update_one(
            {'_id': img['_id']},
            {'$unset': {
                'projectId': '',
                'projectCode': '',
                'projectName': '',
                'assignedBy': '',
                'assignedAt': '',
                'recordId': '',
                'nasPath': '',
                'nasSyncStatus': '',
                'nasSyncError': '',
            },
             '$set': {'updatedAt': now, 'movedFrom': img.get('projectCode', 'unknown')}},
        )

    reset_ids = [str(img['_id']) for img in images]
    count = assign_images_to_project(reset_ids, new_project, moved_by)

    if count == 0:
        errors.append('重新歸類失敗，請檢查照片狀態')

    return {'moved': count, 'errors': errors}


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
