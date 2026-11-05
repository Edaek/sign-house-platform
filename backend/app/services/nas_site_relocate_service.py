"""Move NAS site folders between bucket parents and rewrite Mongo paths (ops / admin)."""
from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime
from app.services.wa_time import wa_now
from pathlib import Path

from bson import ObjectId

from app import mongo
from app.services.nas_bucket_code import nas_parent_bucket_match_values, nas_path_from_web_bucket
from app.services.nas_sync_service import _bucket_child_site_code
from app.services.nas_watcher_service import nas_mount
from app.services.wa_project_bucket_rules import is_reserved_nas_folder_name
from app.services.wa_project_validation import find_project_by_code

logger = logging.getLogger(__name__)


def _site_dir_parent_bucket_name(site_dir: Path) -> str | None:
    """Top-level NAS bucket folder name containing this site directory (KTEST/kelly → KTEST)."""
    watch = nas_mount._resolved_watch_dir()
    if not watch or not site_dir.is_dir():
        return None
    try:
        rel = site_dir.resolve().relative_to(Path(watch).resolve())
    except ValueError:
        return None
    if len(rel.parts) < 2:
        return None
    return rel.parts[0]


def _rewrite_path_bucket_folder(path: str | None, old_bucket: str, new_bucket: str, folder_name: str) -> str | None:
    """When a site folder moved between buckets, fix NAS paths that still mention the old bucket."""
    if not path or not old_bucket or not new_bucket or not folder_name:
        return path
    p = str(path).replace('\\', '/')
    if old_bucket.upper() == new_bucket.upper():
        return path
    pattern = re.compile(
        rf'/{re.escape(old_bucket)}/{re.escape(folder_name)}(?=/|$)',
        re.IGNORECASE,
    )
    repl = f'/{new_bucket}/{folder_name}'
    if pattern.search(p):
        return pattern.sub(repl, p, count=1)
    return path


def _rewrite_path_prefix(path: str | None, old_root: Path, new_root: Path) -> str | None:
    if not path:
        return path
    p = str(path).replace('\\', '/')
    old = str(old_root).replace('\\', '/').rstrip('/')
    new = str(new_root).replace('\\', '/').rstrip('/')
    if p.startswith(old + '/') or p == old:
        return new + p[len(old):]
    old_lower = old.lower()
    pl = p.lower()
    if pl.startswith(old_lower + '/') or pl == old_lower:
        return new + p[len(old):]
    return path


def _projects_for_site_folder(folder_name: str, source_parent_bucket: str) -> list[dict]:
    folder_name = (folder_name or '').strip()
    if not folder_name:
        return []
    parent_variants = list(nas_parent_bucket_match_values(source_parent_bucket))
    parent_variants.append(nas_path_from_web_bucket(source_parent_bucket))
    parent_variants = list({v for v in parent_variants if v})
    query = {
        'status': {'$ne': 'archived'},
        'nasParentBucket': {'$in': parent_variants},
        '$or': [
            {'nasFolderName': {'$regex': f'^{re.escape(folder_name)}$', '$options': 'i'}},
            {'code': {'$regex': f'^{re.escape(folder_name)}$', '$options': 'i'}},
        ],
    }
    return list(mongo.db.wa_projects.find(query))


def _update_records_nas_paths(project_ids: list[ObjectId], old_root: Path, new_root: Path) -> int:
    if not project_ids:
        return 0
    updated = 0
    for rec in mongo.db.wa_records.find({'projectId': {'$in': project_ids}}):
        patch = {}
        nas_photos = []
        changed = False
        for p in rec.get('nasPhotos') or []:
            np = _rewrite_path_prefix(p, old_root, new_root)
            nas_photos.append(np)
            if np != p:
                changed = True
        if changed:
            patch['nasPhotos'] = nas_photos
        sp = rec.get('nasSourcePath')
        if sp:
            nsp = _rewrite_path_prefix(sp, old_root, new_root)
            if nsp != sp:
                patch['nasSourcePath'] = nsp
                changed = True
        if changed:
            patch['updatedAt'] = wa_now()
            mongo.db.wa_records.update_one({'_id': rec['_id']}, {'$set': patch})
            updated += 1
    return updated


def _update_pool_images_nas_paths(project_ids: list[ObjectId], old_root: Path, new_root: Path) -> int:
    if not project_ids:
        return 0
    n = 0
    for img in mongo.db.pool_images.find({'projectId': {'$in': project_ids}}):
        path = img.get('nasPath')
        if not path:
            continue
        new_path = _rewrite_path_prefix(path, old_root, new_root)
        if new_path != path:
            mongo.db.pool_images.update_one(
                {'_id': img['_id']},
                {'$set': {'nasPath': new_path, 'updatedAt': wa_now()}},
            )
            n += 1
    return n


def relocate_site_folder_between_buckets(
    site_folder_name: str,
    source_parent_bucket: str,
    target_parent_bucket: str,
    *,
    dry_run: bool = False,
) -> dict:
    """
    Move one site directory from source bucket to target bucket on the NAS share.

    Example: KTEST2/kelly → KTEST/kelly (folder name unchanged; updates wa_projects + record paths).
    """
    if not nas_mount.is_available():
        return {'ok': False, 'error': 'NAS mount not available'}

    folder_name = (site_folder_name or '').strip()
    if not folder_name or is_reserved_nas_folder_name(folder_name):
        return {'ok': False, 'error': f'Invalid or reserved site folder name: {folder_name!r}'}

    src_parent = nas_path_from_web_bucket(source_parent_bucket)
    tgt_parent = nas_path_from_web_bucket(target_parent_bucket)
    if not src_parent or not tgt_parent:
        return {'ok': False, 'error': 'sourceParentBucket and targetParentBucket are required'}
    if src_parent.upper() == tgt_parent.upper():
        return {'ok': False, 'error': 'Source and target parent bucket must differ'}

    src_bucket = nas_mount._resolve_bucket_dir(src_parent)
    tgt_bucket = nas_mount._resolve_bucket_dir(tgt_parent)
    if src_bucket is None or not src_bucket.is_dir():
        return {'ok': False, 'error': f'Source bucket folder not found on NAS: {src_parent}'}
    if tgt_bucket is None or not tgt_bucket.is_dir():
        return {'ok': False, 'error': f'Target bucket folder not found on NAS: {tgt_parent}'}

    src_dir = nas_mount._find_dir_named(src_bucket, folder_name)
    if src_dir is None or not src_dir.is_dir():
        return {
            'ok': False,
            'error': f'Site folder {folder_name!r} not found under {src_parent} on the shared drive.',
        }

    dest_dir = tgt_bucket / src_dir.name
    if dest_dir.exists():
        return {
            'ok': False,
            'error': f'Target already exists: {tgt_parent}/{src_dir.name}. Rename or remove it first.',
        }

    projects = _projects_for_site_folder(folder_name, source_parent_bucket)
    tgt_physical = nas_path_from_web_bucket(target_parent_bucket)
    for proj in projects:
        code = (proj.get('code') or '').strip()
        if code and find_project_by_code(code, parent_bucket=tgt_physical):
            return {
                'ok': False,
                'error': (
                    f'App project code {code} already exists under bucket {tgt_physical}. '
                    'Resolve the duplicate before moving NAS folders.'
                ),
            }

    payload = {
        'ok': True,
        'dryRun': dry_run,
        'siteFolderName': src_dir.name,
        'sourceParentBucket': src_parent,
        'targetParentBucket': tgt_parent,
        'fromPath': str(src_dir),
        'toPath': str(dest_dir),
        'projectsMatched': len(projects),
        'projectCodes': [(p.get('code') or '') for p in projects],
    }

    if dry_run:
        return payload

    try:
        shutil.move(str(src_dir), str(dest_dir))
    except OSError as e:
        logger.warning('[NAS] relocate site folder failed %s → %s: %s', src_dir, dest_dir, e)
        return {'ok': False, 'error': str(e)}

    from app.services.nas_site_remark_service import consolidate_photo_day_remark_txts

    remark_merge = consolidate_photo_day_remark_txts(str(dest_dir), src_dir.name)

    now = wa_now()
    project_ids: list[ObjectId] = []
    for proj in projects:
        project_ids.append(proj['_id'])
        mongo.db.wa_projects.update_one(
            {'_id': proj['_id']},
            {'$set': {
                'nasParentBucket': tgt_physical,
                'nasFolderName': src_dir.name,
                'nasFolder': str(dest_dir),
                'updatedAt': now,
            }},
        )

    records_updated = _update_records_nas_paths(project_ids, src_dir, dest_dir)
    pool_updated = _update_pool_images_nas_paths(project_ids, src_dir, dest_dir)

    try:
        nas_mount.refresh_bucket_children_cache_for(source_parent_bucket)
        nas_mount.refresh_bucket_children_cache_for(target_parent_bucket)
    except Exception:
        logger.exception('[NAS] bucket cache refresh after relocate failed')

    payload.update({
        'projectsUpdated': len(projects),
        'recordsUpdated': records_updated,
        'poolImagesUpdated': pool_updated,
        'remarkTxtMergedDays': remark_merge.get('days') or [],
        'remarkTxtMergeOk': remark_merge.get('ok', True),
    })
    if not remark_merge.get('ok'):
        payload['remarkTxtMergeError'] = remark_merge.get('error')
    return payload


def relocate_all_site_folders_between_buckets(
    source_parent_bucket: str,
    target_parent_bucket: str,
    *,
    dry_run: bool = False,
) -> dict:
    """Move every site child folder from one bucket to another (e.g. all under KTEST2 → KTEST)."""
    if not nas_mount.is_available():
        return {'ok': False, 'error': 'NAS mount not available'}

    code = (source_parent_bucket or '').strip()
    if not code:
        return {'ok': False, 'error': 'sourceParentBucket required'}

    children = nas_mount._list_bucket_child_folders_sync(code)
    site_names = []
    for child in children:
        site_code = _bucket_child_site_code(child)
        if not site_code:
            continue
        folder_name = (child.get('folderName') or site_code).strip()
        if folder_name:
            site_names.append(folder_name)

    if not site_names:
        return {
            'ok': True,
            'dryRun': dry_run,
            'moved': [],
            'skipped': [],
            'message': 'No site folders to move under source bucket.',
        }

    moved = []
    errors = []
    for name in site_names:
        r = relocate_site_folder_between_buckets(
            name,
            source_parent_bucket,
            target_parent_bucket,
            dry_run=dry_run,
        )
        if r.get('ok'):
            moved.append({'folder': name, 'result': r})
        else:
            errors.append({'folder': name, 'error': r.get('error') or 'failed'})

    return {
        'ok': len(errors) == 0,
        'dryRun': dry_run,
        'sourceParentBucket': nas_path_from_web_bucket(source_parent_bucket),
        'targetParentBucket': nas_path_from_web_bucket(target_parent_bucket),
        'moved': moved,
        'errors': errors,
    }


def realign_project_record_paths(
    project_id,
    old_parent_bucket: str,
    new_parent_bucket: str,
    folder_name: str,
) -> dict:
    """Rewrite wa_records / pool_images NAS paths after parent bucket changed."""
    old_b = nas_path_from_web_bucket(old_parent_bucket)
    new_b = nas_path_from_web_bucket(new_parent_bucket)
    folder_name = (folder_name or '').strip()
    pid = project_id if isinstance(project_id, ObjectId) else ObjectId(str(project_id))
    records_updated = 0
    for rec in mongo.db.wa_records.find({'projectId': pid}):
        patch = {}
        nas_photos = []
        changed = False
        for p in rec.get('nasPhotos') or []:
            np = _rewrite_path_bucket_folder(p, old_b, new_b, folder_name)
            nas_photos.append(np)
            if np != p:
                changed = True
        if changed:
            patch['nasPhotos'] = nas_photos
        sp = rec.get('nasSourcePath')
        if sp:
            nsp = _rewrite_path_bucket_folder(sp, old_b, new_b, folder_name)
            if nsp != sp:
                patch['nasSourcePath'] = nsp
                changed = True
        if changed:
            patch['updatedAt'] = wa_now()
            mongo.db.wa_records.update_one({'_id': rec['_id']}, {'$set': patch})
            records_updated += 1

    pool_updated = 0
    for img in mongo.db.pool_images.find({'projectId': pid}):
        path = img.get('nasPath')
        if not path:
            continue
        new_path = _rewrite_path_bucket_folder(path, old_b, new_b, folder_name)
        if new_path != path:
            mongo.db.pool_images.update_one(
                {'_id': img['_id']},
                {'$set': {'nasPath': new_path, 'updatedAt': wa_now()}},
            )
            pool_updated += 1

    return {'recordsUpdated': records_updated, 'poolImagesUpdated': pool_updated}


def realign_wa_projects_with_nas(*, dry_run: bool = False) -> dict:
    """
    Point wa_projects (and record NAS paths) at the bucket where the site folder actually lives.

    Use after manual SMB moves or relocate outside the app so the web UI matches the share.
    """
    if not nas_mount.is_available():
        return {'ok': False, 'error': 'NAS mount not available'}

    updated: list[dict] = []
    skipped = 0
    now = wa_now()

    for proj in mongo.db.wa_projects.find({'status': {'$ne': 'archived'}}):
        parent_raw = (proj.get('nasParentBucket') or '').strip()
        code = (proj.get('code') or '').strip()
        if not parent_raw or not code:
            skipped += 1
            continue
        from app.services.wa_project_bucket_rules import is_bucket_container_project

        if is_bucket_container_project(proj):
            skipped += 1
            continue

        folder = nas_mount._folder_for_project(code, proj)
        if folder is None or not folder.is_dir():
            skipped += 1
            continue

        actual_parent = _site_dir_parent_bucket_name(folder)
        if not actual_parent:
            skipped += 1
            continue

        mongo_parent = nas_path_from_web_bucket(parent_raw)
        if actual_parent.upper() == mongo_parent.upper():
            skipped += 1
            continue

        folder_label = (proj.get('nasFolderName') or folder.name or code).strip()
        row = {
            'projectId': str(proj['_id']),
            'code': code,
            'fromParentBucket': mongo_parent,
            'toParentBucket': actual_parent,
            'nasFolder': str(folder),
        }
        if dry_run:
            updated.append(row)
            continue

        mongo.db.wa_projects.update_one(
            {'_id': proj['_id']},
            {'$set': {
                'nasParentBucket': actual_parent,
                'nasFolderName': folder.name,
                'nasFolder': str(folder),
                'updatedAt': now,
            }},
        )
        path_stats = realign_project_record_paths(
            proj['_id'],
            mongo_parent,
            actual_parent,
            folder_label,
        )
        from app.services.nas_site_remark_service import consolidate_photo_day_remark_txts

        remark_merge = consolidate_photo_day_remark_txts(str(folder), folder.name)
        row.update(path_stats)
        row['remarkTxtMergedDays'] = remark_merge.get('days') or []
        updated.append(row)

    try:
        nas_mount._refresh_bucket_children_caches()
    except Exception:
        logger.exception('[NAS] bucket cache refresh after realign failed')
    try:
        from app.api.wa_projects import clear_mongo_bucket_rows_cache

        clear_mongo_bucket_rows_cache()
    except Exception:
        logger.exception('[NAS] clear mongo bucket rows cache after realign failed')

    return {
        'ok': True,
        'dryRun': dry_run,
        'projectsRealigned': len(updated),
        'projectsSkipped': skipped,
        'updates': updated,
    }
