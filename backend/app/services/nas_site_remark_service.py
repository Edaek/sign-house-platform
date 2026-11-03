"""NAS on-site layout: Photo/YYYY-MM-DD/ images + <site-folder>_<date>.txt remarks."""
from __future__ import annotations

import logging
import os
import re
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


def site_day_from_nas_path(relative_path: str) -> Optional[str]:
    normalized = (relative_path or '').replace('\\', '/')
    in_photo = re.search(r'/Photo/(\d{4}-\d{2}-\d{2})(?:/|$)', normalized, re.I)
    if in_photo:
        return in_photo.group(1)
    in_txt = re.search(r'_(\d{4}-\d{2}-\d{2})\.txt$', normalized, re.I)
    if in_txt:
        return in_txt.group(1)
    return None


def read_remark_txt_file(path: str) -> str:
    p = (path or '').strip()
    if not p or not os.path.isfile(p):
        return ''
    try:
        with open(p, encoding='utf-8') as fh:
            return fh.read().strip()
    except OSError:
        return ''


def remark_txt_paths_for_nas_photos(nas_photo_paths) -> list[str]:
    """Photo paths under Photo/YYYY-MM-DD/ → sibling day remark txt paths."""
    out = []
    seen = set()
    for photo_path in nas_photo_paths or []:
        p = (photo_path or '').strip()
        if not p:
            continue
        day = site_day_from_nas_path(p)
        if not day:
            continue
        day_dir = os.path.dirname(p)
        if not day_dir or not os.path.isdir(day_dir):
            continue
        folder = site_folder_name_from_day_dir(day_dir)
        txt = os.path.join(day_dir, site_remark_filename(folder_name=folder, day_str=day))
        if txt not in seen:
            seen.add(txt)
            out.append(txt)
    return out


def merge_remark_texts(*parts: str) -> str:
    blocks = []
    seen_norm = set()
    for part in parts:
        t = (part or '').strip()
        if not t:
            continue
        key = t.casefold()
        if key in seen_norm:
            continue
        seen_norm.add(key)
        blocks.append(t)
    return '\n\n'.join(blocks)


def _remark_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r'\n\s*\n', (text or '').strip()) if p.strip()]


def strip_remark_from_txt_file(path: str, text_to_remove: str) -> dict:
    """Remove matching remark paragraph(s) from a day txt; delete file only if empty."""
    p = (path or '').strip()
    remove = (text_to_remove or '').strip()
    if not p or not remove:
        return {'ok': True, 'skipped': True}
    if not os.path.isfile(p):
        return {'ok': True, 'skipped': True}

    current = read_remark_txt_file(p)
    if not current:
        return {'ok': True, 'skipped': True}

    remove_keys = {b.casefold() for b in _remark_paragraphs(remove)}
    remove_keys.add(remove.casefold())
    kept = [para for para in _remark_paragraphs(current) if para.casefold() not in remove_keys]

    if not kept and remove.casefold() in current.casefold():
        trimmed = current
        for block in _remark_paragraphs(remove):
            trimmed = re.sub(re.escape(block), '', trimmed, flags=re.I).strip()
        trimmed = re.sub(r'\n{3,}', '\n\n', trimmed).strip()
        if trimmed:
            kept = _remark_paragraphs(trimmed)

    try:
        if not kept:
            os.remove(p)
            logger.info('[NAS] Removed empty remark txt after strip → %s', p)
            return {'ok': True, 'removedFile': True, 'path': p}
        new_body = '\n\n'.join(kept) + '\n'
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write(new_body)
        logger.info('[NAS] Stripped remark from txt → %s', p)
        return {'ok': True, 'path': p, 'removedFile': False}
    except OSError as exc:
        logger.error('[NAS] Strip remark txt failed %s: %s', p, exc)
        return {'ok': False, 'error': str(exc), 'path': p}


def strip_remark_from_txt_files(paths, text_to_remove: str) -> list[dict]:
    return [strip_remark_from_txt_file(p, text_to_remove) for p in (paths or [])]


def collect_move_remark_bundle(old_records, nas_photo_paths) -> dict:
    """Gather remark to move (record-scoped) and old NAS txt paths to strip — not whole-file delete."""
    txt_paths = remark_txt_paths_for_nas_photos(nas_photo_paths)
    for rec in old_records or []:
        rp = (rec.get('nasRemarkPath') or '').strip()
        if rp and rp not in txt_paths:
            txt_paths.append(rp)
    record_texts = []
    try:
        from app.services.image_pool_service import resolve_record_remark

        for rec in old_records or []:
            record_texts.append(resolve_record_remark(rec))
    except Exception:
        pass
    text_to_move = merge_remark_texts(*record_texts)
    days = []
    for p in nas_photo_paths or []:
        d = site_day_from_nas_path(p)
        if d and d not in days:
            days.append(d)
    days.sort()
    return {
        'text': text_to_move,
        'stripText': text_to_move,
        'days': days,
        'oldTxtPaths': txt_paths,
    }


def consolidate_photo_day_remark_txts(site_root: str, folder_label: str) -> dict:
    """
    Merge all .txt files under Photo/YYYY-MM-DD/ into one canonical remark file per day.

    Used after relocating a site folder (e.g. KTEST2/kelly → KTEST/kelly) when legacy
    names left multiple txts for the same date (KTEST2_2026-11-03.txt + kelly_2026-11-03.txt).
    """
    root = (site_root or '').strip()
    label = (folder_label or '').strip() or 'site'
    if not root or not os.path.isdir(root):
        return {'ok': True, 'days': [], 'merged': 0}

    photo = os.path.join(root, PHOTO_SUBDIR)
    if not os.path.isdir(photo):
        return {'ok': True, 'days': [], 'merged': 0}

    merged_days: list[str] = []
    try:
        for day_name in sorted(os.listdir(photo)):
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', day_name):
                continue
            day_dir = os.path.join(photo, day_name)
            if not os.path.isdir(day_dir):
                continue
            txts = sorted(
                os.path.join(day_dir, f)
                for f in os.listdir(day_dir)
                if f.lower().endswith('.txt') and os.path.isfile(os.path.join(day_dir, f))
            )
            if not txts:
                continue
            canonical = os.path.join(day_dir, site_remark_filename(folder_name=label, day_str=day_name))
            parts = [read_remark_txt_file(p) for p in txts]
            body = merge_remark_texts(*parts)
            if not body:
                for p in txts:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
                continue
            with open(canonical, 'w', encoding='utf-8') as fh:
                fh.write(body if body.endswith('\n') else body + '\n')
            for p in txts:
                if os.path.normcase(p) != os.path.normcase(canonical):
                    try:
                        os.remove(p)
                    except OSError:
                        logger.warning('[NAS] Could not remove extra remark txt %s', p)
            merged_days.append(day_name)
    except OSError as exc:
        logger.error('[NAS] consolidate remark txts failed under %s: %s', root, exc)
        return {'ok': False, 'error': str(exc), 'days': merged_days, 'merged': len(merged_days)}

    return {'ok': True, 'days': merged_days, 'merged': len(merged_days)}


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
