"""Sync metadata and imports between NAS mount and WA projects/records."""
import logging
import os
import re
import shutil
import time
import hashlib
from datetime import datetime
from pathlib import Path

from bson import ObjectId

from app import mongo
from app.services.nas_watcher_service import nas_mount
from app.services.reference_number_service import generate_reference_number

logger = logging.getLogger(__name__)

_NAS_INDEX_CACHE = None
_NAS_INDEX_CACHE_AT = 0.0
_NAS_INDEX_TTL_S = 90


def nas_folder_index(*, force_refresh=False):
    """Map upper-case project code → NAS folder stats (cached for list views)."""
    global _NAS_INDEX_CACHE, _NAS_INDEX_CACHE_AT
    if not nas_mount.is_available():
        return {}
    now = time.time()
    if (
        not force_refresh
        and _NAS_INDEX_CACHE is not None
        and (now - _NAS_INDEX_CACHE_AT) < _NAS_INDEX_TTL_S
    ):
        return _NAS_INDEX_CACHE
    synced_at = datetime.utcnow().isoformat()
    index = {}
    for folder in nas_mount.list_folders():
        code = (folder.get('code') or folder.get('folderName') or '').upper()
        if code:
            index[code] = {**folder, 'nasSyncedAt': synced_at}
    _NAS_INDEX_CACHE = index
    _NAS_INDEX_CACHE_AT = now
    return index


def enrich_project_dict(project_doc, nas_index=None, *, fast_single=False):
    """Add NAS fields to a serialized project dict."""
    code = (project_doc.get('code') or '').upper()
    if fast_single and code and nas_mount.is_available():
        nas = nas_mount.folder_stats(code) or {}
        project_doc['nasFileCount'] = nas.get('fileCount', 0)
        project_doc['nasLastModified'] = nas.get('latestModified')
        project_doc['nasSyncedAt'] = datetime.utcnow().isoformat() if nas else None
        project_doc['nasFolderName'] = nas.get('folderName')
        return project_doc
    if nas_index is None:
        nas_index = nas_folder_index()
    nas = nas_index.get(code, {})
    project_doc['nasFileCount'] = nas.get('fileCount', 0)
    project_doc['nasLastModified'] = nas.get('latestModified')
    project_doc['nasSyncedAt'] = nas.get('nasSyncedAt')
    project_doc['nasFolderName'] = nas.get('folderName')
    return project_doc


def sync_projects_from_nas(owner_id):
    """Create web projects for NAS folders that do not exist yet."""
    if not nas_mount.is_available():
        return {'ok': False, 'error': 'NAS mount not available'}

    folders = nas_mount.list_folders()
    now = datetime.utcnow()
    created = []
    skipped = []

    for folder in folders:
        code = (folder.get('code') or folder.get('folderName') or '').upper()
        if not code:
            continue
        from app.services.wa_project_validation import (
            find_project_by_code,
            assert_name_available,
            normalize_name,
        )

        if find_project_by_code(code):
            skipped.append(code)
            continue

        folder_name = normalize_name(folder.get('folderName') or code)
        name_err = assert_name_available(folder_name)
        if name_err:
            logger.info('[NASSync] Skip folder %s: %s', code, name_err)
            skipped.append(code)
            continue

        doc = {
            'code': code,
            'name': folder_name,
            'nameNormalized': folder_name.casefold(),
            'location': '',
            'owner': owner_id,
            'stage': 'active',
            'status': 'active',
            'members': [owner_id],
            'nasFolder': folder.get('folderName'),
            'nasImportedAt': now,
            'createdAt': now,
            'updatedAt': now,
        }
        mongo.db.wa_projects.insert_one(doc)
        created.append(code)

    nas_folder_index(force_refresh=True)
    return {
        'ok': True,
        'created': created,
        'skippedExisting': skipped,
        'foldersScanned': len(folders),
    }


def _nas_file_path(project_code, filename):
    watch_dir = nas_mount._watch_dir()
    if not watch_dir:
        return None
    folder = Path(watch_dir) / project_code
    if not folder.is_dir():
        for d in Path(watch_dir).iterdir():
            if d.is_dir() and d.name.upper() == project_code.upper():
                folder = d
                break
        else:
            return None
    candidate = folder / filename
    return str(candidate) if candidate.is_file() else None


def _copy_nas_file_to_uploads(nas_path, media_dir):
    os.makedirs(media_dir, exist_ok=True)
    ext = os.path.splitext(nas_path)[1] or '.jpg'
    fname = f'nas-{int(time.time() * 1000)}-{hashlib.md5(os.urandom(8)).hexdigest()[:8]}{ext}'
    dest = os.path.join(media_dir, fname)
    shutil.copy2(nas_path, dest)
    return f'/uploads/wa-media/{fname}'


def _default_sync_owner_id():
    admin = mongo.db.users.find_one({'role': 'admin'}, sort=[('createdAt', 1)])
    if admin:
        return admin['_id']
    user = mongo.db.users.find_one({})
    return user['_id'] if user else None


def _record_has_nas_file(project_id, filename, nas_path=None):
    """True if this NAS file is already represented by a WA record (avoid broad regex false positives)."""
    if nas_path:
        if mongo.db.wa_records.find_one({'projectId': project_id, 'nasSourcePath': nas_path}):
            return True
        if mongo.db.wa_records.find_one({'projectId': project_id, 'nasPhotos': nas_path}):
            return True
    import_msg = f'[NAS import] {filename}'
    if mongo.db.wa_records.find_one({'projectId': project_id, 'rawMessage': import_msg}):
        return True
    if nas_path:
        tail = re.escape(nas_path)
        if mongo.db.wa_records.find_one({
            'projectId': project_id,
            'nasPhotos': {'$regex': tail + r'$', '$options': 'i'},
        }):
            return True
    return None


def get_last_nas_sync_status():
    doc = mongo.db.wa_system.find_one({'_id': 'nas_sync'})
    return doc if doc else {}


def _nas_paths_on_record(record) -> set:
    paths = set()
    sp = record.get('nasSourcePath')
    if sp:
        paths.add(sp)
    for p in record.get('nasPhotos') or []:
        if p:
            paths.add(p)
    return paths


def _record_query_nas_linked(project_id):
    return {
        'projectId': project_id,
        '$or': [
            {'nasSourcePath': {'$exists': True, '$nin': [None, '']}},
            {'nasPhotos.0': {'$exists': True}},
        ],
    }


def _project_linked_to_nas(project):
    if project.get('nasImportedAt') or project.get('nasFolder'):
        return True
    return mongo.db.wa_records.count_documents(_record_query_nas_linked(project['_id'])) > 0


def _media_dir():
    try:
        from flask import current_app
        return current_app.config.get('WA_UPLOADS_FOLDER', 'uploads/wa-media')
    except RuntimeError:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'uploads', 'wa-media')


def _delete_local_upload_paths(record, media_dir=None):
    if media_dir is None:
        media_dir = _media_dir()
    media_dir = os.path.abspath(media_dir)
    for web_path in record.get('photos') or []:
        if not isinstance(web_path, str):
            continue
        name = os.path.basename(web_path.split('?')[0])
        local = os.path.join(media_dir, name)
        if os.path.isfile(local):
            try:
                os.remove(local)
            except OSError as e:
                logger.warning('[NASSync] Local upload delete failed %s: %s', local, e)


def remove_nas_files_for_record(record):
    """Web → NAS: remove files on the share linked to a record."""
    paths = set()
    if record.get('nasSourcePath'):
        paths.add(record['nasSourcePath'])
    for p in record.get('nasPhotos') or []:
        if p:
            paths.add(p)
    deleted = []
    for p in paths:
        result = nas_mount.delete_path(p)
        if result.get('ok'):
            deleted.append(p)
    return deleted


def delete_web_record(record, *, remove_nas=True, media_dir=None):
    """Remove a WA record and optional NAS/local copies."""
    if remove_nas:
        remove_nas_files_for_record(record)
    _delete_local_upload_paths(record, media_dir=media_dir)
    mongo.db.pool_images.update_many(
        {'recordId': record['_id']},
        {'$unset': {'recordId': ''}},
    )
    mongo.db.wa_records.delete_one({'_id': record['_id']})


def delete_web_project(project, *, remove_nas_folder=False):
    """Remove project + records; optionally remove NAS folder (Web → NAS)."""
    if remove_nas_folder and nas_mount.is_available():
        nas_mount.delete_project_folder(project['code'])
    for rec in mongo.db.wa_records.find({'projectId': project['_id']}):
        delete_web_record(rec, remove_nas=False, media_dir=_media_dir())
    mongo.db.pool_images.update_many(
        {'projectId': project['_id']},
        {'$unset': {
            'projectId': '', 'projectCode': '', 'projectName': '',
            'assignedBy': '', 'assignedAt': '', 'recordId': '',
        }},
    )
    mongo.db.wa_projects.delete_one({'_id': project['_id']})


def reconcile_deletions_from_nas(media_dir=None):
    """NAS → web: drop records/projects when files/folders were removed on the share."""
    if not nas_mount.is_available():
        return {'recordsRemoved': 0, 'projectsRemoved': [], 'recordRefs': []}

    if media_dir is None:
        media_dir = _media_dir()

    records_removed = 0
    record_refs = []
    projects_removed = []

    projects = list(mongo.db.wa_projects.find({'status': {'$ne': 'archived'}}))
    for project in projects:
        folder = nas_mount._resolve_project_folder(project['code'])
        if folder is None and _project_linked_to_nas(project):
            code = project.get('code', '')
            delete_web_project(project, remove_nas_folder=False)
            projects_removed.append(code)
            continue

        if folder is None:
            continue

        for rec in mongo.db.wa_records.find(_record_query_nas_linked(project['_id'])):
            paths = _nas_paths_on_record(rec)
            if not paths:
                continue
            if any(os.path.isfile(p) for p in paths):
                continue
            ref = rec.get('referenceNumber', str(rec['_id']))
            delete_web_record(rec, remove_nas=False, media_dir=media_dir)
            records_removed += 1
            record_refs.append(ref)

    if records_removed or projects_removed:
        nas_folder_index(force_refresh=True)
    return {
        'recordsRemoved': records_removed,
        'recordRefs': record_refs,
        'projectsRemoved': projects_removed,
    }


def run_bidirectional_nas_sync(owner_id=None):
    """NAS ↔ web: reconcile deletes, then import new folders/files."""
    if not nas_mount.is_available():
        return {'ok': False, 'error': 'NAS mount not available'}

    oid = owner_id or _default_sync_owner_id()
    if not oid:
        return {'ok': False, 'error': 'No user available for imported project ownership'}

    deletions = reconcile_deletions_from_nas()
    proj = sync_projects_from_nas(oid)
    imports = import_all_projects_from_nas()
    records_imported = sum(r.get('created', 0) for r in imports if r.get('ok'))

    result = {
        'ok': True,
        'projectsCreated': proj.get('created', []),
        'projectsRemoved': deletions.get('projectsRemoved', []),
        'recordsImported': records_imported,
        'recordsRemoved': deletions.get('recordsRemoved', 0),
        'recordsRemovedRefs': deletions.get('recordRefs', []),
        'at': datetime.utcnow().isoformat(),
    }
    mongo.db.wa_system.update_one({'_id': 'nas_sync'}, {'$set': result}, upsert=True)
    return result


def import_nas_files_for_project(project_id, media_dir=None):
    """Import NAS images as WA records (skip files already linked)."""
    if not nas_mount.is_available():
        return {'ok': False, 'error': 'NAS mount not available'}

    project = mongo.db.wa_projects.find_one({'_id': ObjectId(project_id)})
    if not project:
        return {'ok': False, 'error': 'Project not found'}

    from flask import current_app
    if media_dir is None:
        media_dir = current_app.config.get('WA_UPLOADS_FOLDER', 'uploads/wa-media')

    files = nas_mount.list_folder_files(project['code'])
    created = 0
    skipped = 0
    now = datetime.utcnow()

    for meta in files:
        name = meta['name']
        nas_path = _nas_file_path(project['code'], name)
        if not nas_path:
            continue
        if _record_has_nas_file(project['_id'], name, nas_path):
            skipped += 1
            continue
        try:
            web_path = _copy_nas_file_to_uploads(nas_path, media_dir)
        except OSError as e:
            logger.warning('[NASSync] Copy failed %s: %s', name, e)
            continue

        record_doc = {
            'projectId': project['_id'],
            'referenceNumber': generate_reference_number(),
            'status': 'awaiting_review',
            'type': 'photo',
            'rawMessage': f'[NAS import] {name}',
            'senderPhone': '',
            'senderName': 'NAS',
            'photos': [web_path],
            'nasPhotos': [nas_path],
            'nasSourcePath': nas_path,
            'nasSyncStatus': 'synced',
            'nasSyncExpected': 1,
            'nasSyncActual': 1,
            'nasSyncUpdatedAt': now,
            'hasMedia': True,
            'mediaType': 'image',
            'extractedFields': [],
            'followUpThread': [],
            'followUpRound': 0,
            'statusHistory': [{'from': 'incomplete', 'to': 'awaiting_review', 'timestamp': now, 'reason': 'NAS import'}],
            'createdAt': now,
            'updatedAt': now,
        }
        mongo.db.wa_records.insert_one(record_doc)
        created += 1

    return {
        'ok': True,
        'created': created,
        'skipped': skipped,
        'filesOnNas': len(files),
    }


def import_all_projects_from_nas(media_dir=None):
    """Import NAS files for every active project."""
    results = []
    projects = list(mongo.db.wa_projects.find({'status': {'$ne': 'archived'}}))
    for p in projects:
        r = import_nas_files_for_project(str(p['_id']), media_dir=media_dir)
        r['code'] = p['code']
        results.append(r)
    return results
