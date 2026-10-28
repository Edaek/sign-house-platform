"""NAS on-site layout: Photo/YYYY-MM-DD/ images + <site-folder>_<date>.txt remarks."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from app import mongo

logger = logging.getLogger(__name__)

HK = ZoneInfo('Asia/Hong_Kong')
PHOTO_SUBDIR = 'Photo'


def hk_today_str() -> str:
    return datetime.now(HK).date().isoformat()


def site_folder_name_from_day_dir(day_dir: str) -> str:
    """…/<site-folder>/Photo/YYYY-MM-DD → site-folder basename."""
    return os.path.basename(os.path.dirname(os.path.dirname(day_dir)))


def site_remark_filename(
    *,
    folder_name: str,
    day_str: Optional[str] = None,
) -> str:
    """Remark file name = NAS site folder label + date (no PJ- prefix normalization)."""
    stem = (folder_name or '').strip()
    for ch in '/\\:*?"<>|':
        stem = stem.replace(ch, '_')
    if not stem:
        stem = 'site'
    day = day_str or hk_today_str()
    return f'{stem}_{day}.txt'


def _remark_context_key(group_id: Optional[str], sender: str) -> str:
    digits = ''.join(c for c in (sender or '') if c.isdigit()) or sender
    if group_id:
        gid = str(group_id).strip()
        return f'nas_site_remark_ctx:g:{gid}:{digits}'
    return f'nas_site_remark_ctx:p:{digits}'


def set_site_remark_context(
    sender: str,
    project_code: str,
    *,
    group_id: Optional[str] = None,
    day_str: Optional[str] = None,
    nas_folder_name: Optional[str] = None,
    nas_parent_bucket: Optional[str] = None,
) -> None:
    day = day_str or hk_today_str()
    payload = {
        'projectCode': project_code,
        'day': day,
        'at': datetime.utcnow(),
        'groupId': group_id,
        'sender': sender,
    }
    fn = (nas_folder_name or '').strip()
    pb = (nas_parent_bucket or '').strip()
    if fn:
        payload['nasFolderName'] = fn
    if pb:
        payload['nasParentBucket'] = pb
    mongo.db.wa_system.update_one(
        {'_id': _remark_context_key(group_id, sender)},
        {'$set': payload},
        upsert=True,
    )


def get_site_remark_context(group_id: Optional[str], sender: str) -> Optional[dict]:
    doc = mongo.db.wa_system.find_one({'_id': _remark_context_key(group_id, sender)})
    if not doc:
        return None
    if doc.get('day') != hk_today_str():
        return None
    return doc


def append_site_remark_to_nas(
    project_code: str,
    text: str,
    *,
    day_str: Optional[str] = None,
    preferred_folder_name: Optional[str] = None,
    preferred_parent_bucket: Optional[str] = None,
) -> dict:
    """Append remark text to Photo/YYYY-MM-DD/<site-folder>_YYYY-MM-DD.txt on NAS mount."""
    body = (text or '').strip()
    if not body:
        return {'ok': True, 'skipped': True}

    from app.services.nas_watcher_service import nas_mount

    if not nas_mount.is_available():
        return {'ok': False, 'error': 'NAS mount not available'}

    day = day_str or hk_today_str()
    pref = (preferred_folder_name or '').strip() or None
    bucket = (preferred_parent_bucket or '').strip() or None
    try:
        day_dir = nas_mount.ensure_photo_day_dir(
            project_code,
            day,
            preferred_folder_name=pref,
            preferred_parent_bucket=bucket,
        )
        if not day_dir:
            return {'ok': False, 'error': 'project folder not found on NAS'}
        folder_label = site_folder_name_from_day_dir(day_dir)
        fname = site_remark_filename(folder_name=folder_label, day_str=day)
        path = os.path.join(day_dir, fname)
        prefix = ''
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            prefix = '\n\n'
        with open(path, 'a', encoding='utf-8') as fh:
            if prefix:
                fh.write(prefix)
            fh.write(body)
            fh.write('\n')
        logger.info('[NAS] Appended site remark → %s', path)
        return {'ok': True, 'path': path}
    except OSError as exc:
        logger.error('[NAS] Site remark write failed: %s', exc)
        return {'ok': False, 'error': str(exc)}


def try_append_followup_site_remark(
    sender: str,
    text: str,
    *,
    group_id: Optional[str] = None,
) -> bool:
    """After photos were filed today, treat free text as on-site notes (not project codes)."""
    trimmed = (text or '').strip()
    if not trimmed:
        return False

    ctx = get_site_remark_context(group_id, sender)
    if not ctx or not ctx.get('projectCode'):
        return False

    from app.services.image_pool_service import match_project_ext
    from app.services.project_number_match_service import primary_site_number

    if primary_site_number(trimmed) and trimmed.replace(' ', '').isdigit():
        return False
    ext = match_project_ext(trimmed, active_only=True)
    if ext.project or ext.candidates:
        return False

    result = append_site_remark_to_nas(
        ctx['projectCode'],
        trimmed,
        day_str=ctx.get('day'),
        preferred_folder_name=ctx.get('nasFolderName'),
        preferred_parent_bucket=ctx.get('nasParentBucket'),
    )
    if not result.get('ok'):
        return False

    _merge_remark_into_latest_record(sender, trimmed, ctx['projectCode'], group_id=group_id)
    return True


def _merge_remark_into_latest_record(
    sender: str,
    text: str,
    project_code: str,
    *,
    group_id: Optional[str] = None,
) -> None:
    """Keep web UI remark in sync when user adds notes after photos."""
    since = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    query = {
        'senderPhone': sender,
        'createdAt': {'$gte': since},
    }
    proj = mongo.db.wa_projects.find_one({'code': project_code, 'status': 'active'})
    if proj:
        query['projectId'] = proj['_id']
    rec = mongo.db.wa_records.find_one(query, sort=[('createdAt', -1)])
    if not rec:
        return
    prev = (rec.get('rawMessage') or '').strip()
    if prev and prev.lower() == '[pool media]':
        prev = ''
    merged = f'{prev}\n\n{text}'.strip() if prev else text
    mongo.db.wa_records.update_one(
        {'_id': rec['_id']},
        {'$set': {'rawMessage': merged, 'updatedAt': datetime.utcnow()}},
    )
