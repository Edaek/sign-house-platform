"""NAS on-site layout: Photo/YYYY-MM-DD/ images + <site-folder>_<date>.txt remarks."""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from app.services.wa_time import hk_day_start_utc_naive, wa_now
from typing import Any, List, Optional
from zoneinfo import ZoneInfo

from app import mongo

logger = logging.getLogger(__name__)

HK = ZoneInfo('Asia/Hong_Kong')
PHOTO_SUBDIR = 'Photo'


def hk_today_str() -> str:
    return datetime.now(HK).date().isoformat()


def hk_date_str_from_utc_naive(dt: datetime | None) -> str:
    """Mongo UTC naive timestamps → Hong Kong calendar date (YYYY-MM-DD)."""
    if dt is None:
        return hk_today_str()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(HK).date().isoformat()


def assign_photo_day_hk(pool_images: List[Any]) -> str:
    """
    NAS Photo/YYYY-MM-DD and day remark txt use the pool intake date in HK.
    Falls back to hk_today_str() when createdAt is missing.
    """
    days: List[str] = []
    for img in pool_images or []:
        ca = img.get('createdAt') if isinstance(img, dict) else None
        if ca is not None:
            days.append(hk_date_str_from_utc_naive(ca))
    if not days:
        return hk_today_str()
    return max(days)


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
    """Photo paths under Photo/YYYY-MM-DD/ → all sibling .txt paths that day (incl. custom names)."""
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
        candidates = [
            os.path.join(day_dir, name)
            for name in list_remark_txt_basenames(day_dir)
        ]
        if not candidates:
            candidates = [
                os.path.join(day_dir, site_remark_filename(folder_name=folder, day_str=day)),
            ]
        for txt in candidates:
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
    extra_files_removed = 0
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
            if (
                len(txts) == 1
                and os.path.normcase(txts[0]) == os.path.normcase(canonical)
            ):
                continue
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
                        extra_files_removed += 1
                    except OSError:
                        logger.warning('[NAS] Could not remove extra remark txt %s', p)
            merged_days.append(day_name)
    except OSError as exc:
        logger.error('[NAS] consolidate remark txts failed under %s: %s', root, exc)
        return {
            'ok': False,
            'error': str(exc),
            'days': merged_days,
            'merged': len(merged_days),
            'extraFilesRemoved': extra_files_removed,
        }

    return {
        'ok': True,
        'days': merged_days,
        'merged': len(merged_days),
        'extraFilesRemoved': extra_files_removed,
    }


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


def normalize_remark_txt_basename(name: str) -> tuple[Optional[str], Optional[str]]:
    """User-chosen remark .txt basename; must be unique within the Photo/day folder."""
    raw = (name or '').strip()
    if not raw:
        return None, 'file name is required'
    base = os.path.basename(raw.replace('\\', '/'))
    if base in ('.', '..') or '..' in base.split('/'):
        return None, 'invalid file name'
    if not base.lower().endswith('.txt'):
        base = f'{base}.txt'
    for ch in '/\\:*?"<>|':
        if ch in base:
            return None, f'file name cannot contain {ch!r}'
    if not base or base == '.txt':
        return None, 'invalid file name'
    return base, None


def list_remark_txt_basenames(day_dir: str) -> list[str]:
    if not day_dir or not os.path.isdir(day_dir):
        return []
    return sorted(
        f
        for f in os.listdir(day_dir)
        if f.lower().endswith('.txt') and os.path.isfile(os.path.join(day_dir, f))
    )


def remark_txt_name_taken(day_dir: str, basename: str, *, except_basename: Optional[str] = None) -> bool:
    """Case-insensitive duplicate check within one Photo/YYYY-MM-DD folder."""
    target = (basename or '').strip()
    if not target:
        return False
    skip = (except_basename or '').strip()
    try:
        names = list_remark_txt_basenames(day_dir)
    except OSError:
        return False
    target_key = target.casefold()
    skip_key = skip.casefold() if skip else ''
    for n in names:
        if n.casefold() == target_key and n.casefold() != skip_key:
            return True
    return False


def rename_site_remark_txt(
    project_code: str,
    new_filename: str,
    *,
    day_str: Optional[str] = None,
    old_filename: Optional[str] = None,
    preferred_folder_name: Optional[str] = None,
    preferred_parent_bucket: Optional[str] = None,
) -> dict:
    """Rename a day remark .txt under Photo/YYYY-MM-DD/; custom names allowed (not forced canonical)."""
    new_base, err = normalize_remark_txt_basename(new_filename)
    if err or not new_base:
        return {'ok': False, 'error': err or 'invalid file name'}

    from app.services.nas_watcher_service import nas_mount

    if not nas_mount.is_available():
        return {'ok': False, 'error': 'NAS mount not available'}

    day = day_str or hk_today_str()
    pref = (preferred_folder_name or '').strip() or None
    bucket = (preferred_parent_bucket or '').strip() or None
    try:
        day_dir = nas_mount.resolve_photo_day_dir(
            project_code,
            day,
            preferred_folder_name=pref,
            preferred_parent_bucket=bucket,
        )
        if not day_dir:
            return {'ok': False, 'error': 'Photo day folder not found on NAS (no remark txt for that date?)'}

        old_base = (old_filename or '').strip()
        if old_base:
            old_base = os.path.basename(old_base.replace('\\', '/'))
            if not old_base.lower().endswith('.txt'):
                old_base = f'{old_base}.txt'
        else:
            txts = list_remark_txt_basenames(day_dir)
            if len(txts) == 0:
                return {'ok': False, 'error': 'no remark txt in this day folder'}
            if len(txts) > 1:
                return {
                    'ok': False,
                    'error': 'multiple remark txt files; pass old_filename',
                    'existingFiles': txts,
                }
            old_base = txts[0]

        old_path = os.path.join(day_dir, old_base)
        if not os.path.isfile(old_path):
            return {'ok': False, 'error': 'source remark txt not found', 'path': old_path}

        new_path = os.path.join(day_dir, new_base)
        if os.path.normcase(old_path) == os.path.normcase(new_path):
            return {'ok': True, 'path': new_path, 'unchanged': True, 'fileName': new_base}

        if remark_txt_name_taken(day_dir, new_base, except_basename=old_base):
            return {
                'ok': False,
                'error': 'duplicate_remark_txt',
                'message': f'同目录已有同名文件「{new_base}」，请换一个名称。',
                'dayDir': day_dir,
                'existingFiles': list_remark_txt_basenames(day_dir),
            }

        os.rename(old_path, new_path)
        logger.info('[NAS] Renamed site remark txt %s → %s', old_path, new_path)
        return {
            'ok': True,
            'path': new_path,
            'fileName': new_base,
            'previousFileName': old_base,
            'day': day,
        }
    except OSError as exc:
        logger.error('[NAS] Rename site remark txt failed: %s', exc)
        return {'ok': False, 'error': str(exc)}


_REMARK_TXT_READ_MAX_CHARS = 32_000


def _normalize_remark_filename_arg(name: Optional[str]) -> Optional[str]:
    raw = (name or '').strip()
    if not raw:
        return None
    base = os.path.basename(raw.replace('\\', '/'))
    if not base.lower().endswith('.txt'):
        base = f'{base}.txt'
    return base


def _pick_remark_txt_basename(day_dir: str, filename: Optional[str]) -> tuple[Optional[str], Optional[dict]]:
    """Pick one .txt in Photo/day; returns (basename, error_dict)."""
    explicit = _normalize_remark_filename_arg(filename)
    if explicit:
        path = os.path.join(day_dir, explicit)
        if not os.path.isfile(path):
            return None, {'ok': False, 'error': 'remark txt not found', 'fileName': explicit, 'path': path}
        return explicit, None
    try:
        txts = list_remark_txt_basenames(day_dir)
    except OSError as exc:
        return None, {'ok': False, 'error': str(exc)}
    if not txts:
        return None, {'ok': False, 'error': 'no remark txt in this day folder', 'dayDir': day_dir}
    if len(txts) > 1:
        return None, {
            'ok': False,
            'error': 'multiple remark txt files; pass filename',
            'existingFiles': txts,
            'dayDir': day_dir,
        }
    return txts[0], None


def _resolve_site_remark_day_dir(
    project_code: str,
    day_str: Optional[str],
    *,
    preferred_folder_name: Optional[str] = None,
    preferred_parent_bucket: Optional[str] = None,
) -> tuple[Optional[str], Optional[dict]]:
    from app.services.nas_watcher_service import nas_mount

    if not nas_mount.is_available():
        return None, {'ok': False, 'error': 'NAS mount not available'}
    day = day_str or hk_today_str()
    pref = (preferred_folder_name or '').strip() or None
    bucket = (preferred_parent_bucket or '').strip() or None
    day_dir = nas_mount.resolve_photo_day_dir(
        project_code,
        day,
        preferred_folder_name=pref,
        preferred_parent_bucket=bucket,
    )
    if not day_dir:
        return None, {'ok': False, 'error': 'Photo day folder not found on NAS (no remark txt for that date?)'}
    return day_dir, None


def read_site_remark_txt(
    project_code: str,
    *,
    day_str: Optional[str] = None,
    filename: Optional[str] = None,
    preferred_folder_name: Optional[str] = None,
    preferred_parent_bucket: Optional[str] = None,
    list_all: bool = False,
) -> dict:
    """Read day remark .txt content from NAS (view)."""
    day_dir, err = _resolve_site_remark_day_dir(
        project_code,
        day_str,
        preferred_folder_name=preferred_folder_name,
        preferred_parent_bucket=preferred_parent_bucket,
    )
    if err:
        return err
    day = day_str or hk_today_str()

    if list_all or _normalize_remark_filename_arg(filename) is None:
        try:
            names = list_remark_txt_basenames(day_dir or '')
        except OSError as exc:
            return {'ok': False, 'error': str(exc)}
        if not names:
            return {'ok': True, 'day': day, 'dayDir': day_dir, 'files': [], 'content': ''}
        files = []
        for base in names:
            path = os.path.join(day_dir or '', base)
            text = read_remark_txt_file(path)
            truncated = False
            if len(text) > _REMARK_TXT_READ_MAX_CHARS:
                text = text[:_REMARK_TXT_READ_MAX_CHARS]
                truncated = True
            files.append({
                'fileName': base,
                'path': path,
                'content': text,
                'truncated': truncated,
            })
        if len(files) == 1 and not list_all:
            one = files[0]
            return {
                'ok': True,
                'day': day,
                'dayDir': day_dir,
                'fileName': one['fileName'],
                'path': one['path'],
                'content': one['content'],
                'truncated': one['truncated'],
            }
        return {'ok': True, 'day': day, 'dayDir': day_dir, 'files': files}

    base, pick_err = _pick_remark_txt_basename(day_dir or '', filename)
    if pick_err:
        return pick_err
    path = os.path.join(day_dir or '', base or '')
    text = read_remark_txt_file(path)
    truncated = False
    if len(text) > _REMARK_TXT_READ_MAX_CHARS:
        text = text[:_REMARK_TXT_READ_MAX_CHARS]
        truncated = True
    return {
        'ok': True,
        'day': day,
        'dayDir': day_dir,
        'fileName': base,
        'path': path,
        'content': text,
        'truncated': truncated,
    }


def set_site_remark_txt(
    project_code: str,
    content: str,
    *,
    day_str: Optional[str] = None,
    filename: Optional[str] = None,
    preferred_folder_name: Optional[str] = None,
    preferred_parent_bucket: Optional[str] = None,
    create_if_missing: bool = False,
) -> dict:
    """Replace entire remark .txt body (modify). Empty content deletes the file."""
    body = (content or '').strip()
    if not body:
        return delete_site_remark_txt(
            project_code,
            day_str=day_str,
            filename=filename,
            preferred_folder_name=preferred_folder_name,
            preferred_parent_bucket=preferred_parent_bucket,
        )

    day_dir, err = _resolve_site_remark_day_dir(
        project_code,
        day_str,
        preferred_folder_name=preferred_folder_name,
        preferred_parent_bucket=preferred_parent_bucket,
    )
    if err:
        return err
    day = day_str or hk_today_str()
    base, pick_err = _pick_remark_txt_basename(day_dir or '', filename)
    if pick_err:
        if pick_err.get('error') == 'multiple remark txt files; pass filename':
            return pick_err
        explicit = _normalize_remark_filename_arg(filename)
        if explicit and pick_err.get('error') == 'remark txt not found':
            base = explicit
        elif create_if_missing and pick_err.get('error') == 'no remark txt in this day folder':
            folder_label = site_folder_name_from_day_dir(day_dir or '')
            base = explicit or site_remark_filename(folder_name=folder_label, day_str=day)
        else:
            return pick_err
    if not base:
        return {'ok': False, 'error': 'could not resolve remark txt file name'}

    path = os.path.join(day_dir or '', base)
    if remark_txt_name_taken(day_dir or '', base) and not os.path.isfile(path):
        return {
            'ok': False,
            'error': 'duplicate_remark_txt',
            'message': f'同目录已有同名文件「{base}」，请换名称。',
            'existingFiles': list_remark_txt_basenames(day_dir or ''),
        }
    try:
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(body)
            if not body.endswith('\n'):
                fh.write('\n')
        logger.info('[NAS] Replaced site remark txt → %s', path)
        return {'ok': True, 'path': path, 'fileName': base, 'day': day, 'removedFile': False}
    except OSError as exc:
        logger.error('[NAS] Set site remark txt failed: %s', exc)
        return {'ok': False, 'error': str(exc)}


def delete_site_remark_txt(
    project_code: str,
    *,
    day_str: Optional[str] = None,
    filename: Optional[str] = None,
    preferred_folder_name: Optional[str] = None,
    preferred_parent_bucket: Optional[str] = None,
) -> dict:
    """Delete a day remark .txt file."""
    day_dir, err = _resolve_site_remark_day_dir(
        project_code,
        day_str,
        preferred_folder_name=preferred_folder_name,
        preferred_parent_bucket=preferred_parent_bucket,
    )
    if err:
        return err
    day = day_str or hk_today_str()
    base, pick_err = _pick_remark_txt_basename(day_dir or '', filename)
    if pick_err:
        if pick_err.get('error') == 'no remark txt in this day folder':
            return {'ok': True, 'skipped': True, 'day': day, 'removedFile': False}
        return pick_err
    path = os.path.join(day_dir or '', base or '')
    if not os.path.isfile(path):
        return {'ok': True, 'skipped': True, 'path': path, 'removedFile': False}
    try:
        os.remove(path)
        logger.info('[NAS] Deleted site remark txt → %s', path)
        return {'ok': True, 'path': path, 'fileName': base, 'day': day, 'removedFile': True}
    except OSError as exc:
        logger.error('[NAS] Delete site remark txt failed: %s', exc)
        return {'ok': False, 'error': str(exc)}


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
    remark_file_name: Optional[str] = None,
) -> None:
    day = day_str or hk_today_str()
    payload = {
        'projectCode': project_code,
        'day': day,
        'at': wa_now(),
        'groupId': group_id,
        'sender': sender,
    }
    fn = (nas_folder_name or '').strip()
    pb = (nas_parent_bucket or '').strip()
    rfn = (remark_file_name or '').strip()
    if fn:
        payload['nasFolderName'] = fn
    if pb:
        payload['nasParentBucket'] = pb
    if rfn:
        payload['remarkFileName'] = rfn
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


def clear_remark_filename_contexts_for_project(project_code: str) -> int:
    """Drop custom remarkFileName after NAS consolidate (canonical day txt restored)."""
    code = (project_code or '').strip()
    if not code:
        return 0
    try:
        result = mongo.db.wa_system.update_many(
            {
                '_id': {'$regex': r'^nas_site_remark_ctx:'},
                'projectCode': {'$regex': f'^{re.escape(code)}$', '$options': 'i'},
                'remarkFileName': {'$exists': True},
            },
            {'$unset': {'remarkFileName': ''}},
        )
        return int(result.modified_count)
    except Exception as exc:
        logger.warning('[NAS] clear remarkFileName contexts failed for %s: %s', code, exc)
        return 0


def append_site_remark_to_nas(
    project_code: str,
    text: str,
    *,
    day_str: Optional[str] = None,
    preferred_folder_name: Optional[str] = None,
    preferred_parent_bucket: Optional[str] = None,
    preferred_remark_filename: Optional[str] = None,
    fallback_to_canonical_if_missing: bool = False,
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
        custom = (preferred_remark_filename or '').strip()
        if custom:
            fname, norm_err = normalize_remark_txt_basename(custom)
            if norm_err or not fname:
                return {'ok': False, 'error': norm_err or 'invalid file name'}
            path = os.path.join(day_dir, fname)
            if not os.path.isfile(path) and fallback_to_canonical_if_missing:
                fname = site_remark_filename(folder_name=folder_label, day_str=day)
                path = os.path.join(day_dir, fname)
            elif not os.path.isfile(path) and remark_txt_name_taken(day_dir, fname):
                return {
                    'ok': False,
                    'error': 'duplicate_remark_txt',
                    'message': f'同目录已有同名文件「{fname}」，请换名称或追加到已有文件。',
                    'existingFiles': list_remark_txt_basenames(day_dir),
                }
        else:
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
        preferred_remark_filename=ctx.get('remarkFileName'),
        fallback_to_canonical_if_missing=True,
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
    since = hk_day_start_utc_naive()
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
        {'$set': {'rawMessage': merged, 'updatedAt': wa_now()}},
    )
