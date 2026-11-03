"""Sync metadata and imports between NAS mount and WA projects/records."""
import logging
import os
import re
import shutil
import threading
import time
import hashlib
from datetime import datetime
from pathlib import Path

from bson import ObjectId

from app import mongo
from app.services.nas_watcher_service import nas_mount
from app.services.project_number_match_service import (
    is_nas_bucket_dir_name,
    is_nas_bucket_folder_code,
    is_range_folder_code,
    parse_nas_site_folder_code,
)
from app.services.reference_number_service import generate_reference_number

logger = logging.getLogger(__name__)

_NAS_INDEX_CACHE = None
_NAS_INDEX_CACHE_AT = 0.0
_NAS_INDEX_TTL_S = 90
_nas_sync_lock = threading.Lock()


def _bucket_child_site_code(child: dict) -> str | None:
    """Site project code for a direct child of a NAS bucket (PJ-xxxx or plain folder name)."""
    from app.services.wa_project_bucket_rules import is_reserved_nas_folder_name

    site_code = (child.get('code') or '').strip()
    folder_name = (child.get('folderName') or '').strip()
    if not site_code:
        site_code = folder_name
    if not site_code or is_range_folder_code(site_code):
        return None
    if is_reserved_nas_folder_name(site_code) or is_reserved_nas_folder_name(folder_name):
        return None
    return site_code


def _list_nas_folders_timed(timeout_s: float = 12.0):
    cached = nas_mount.get_cached_folders()
    if cached is not None:
        return cached
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(nas_mount.list_folders)
        try:
            folders = fut.result(timeout=timeout_s)
            nas_mount._set_folder_cache(folders)
            return folders
        except FuturesTimeout:
            logger.warning('[NAS] list_folders timed out after %ss', timeout_s)
            return None


def _build_index_from_folders(folders, synced_at=None):
    synced_at = synced_at or datetime.utcnow().isoformat()
    index = {}
    for folder in folders:
        site_code = (folder.get('code') or '').strip()
        if not site_code:
            site_code = parse_nas_site_folder_code(folder.get('folderName') or '') or ''
        if not site_code:
            continue
        key = site_code.upper()
        index[key] = {**folder, 'code': site_code, 'nasSyncedAt': synced_at}
    return index


def nas_folder_index(*, force_refresh=False, blocking_scan=True):
    """Map upper-case project code → NAS folder stats (cached for list views)."""
    global _NAS_INDEX_CACHE, _NAS_INDEX_CACHE_AT
    if not nas_mount.is_volume_mounted():
        return {}
    now = time.time()
    if (
        not force_refresh
        and _NAS_INDEX_CACHE is not None
        and (now - _NAS_INDEX_CACHE_AT) < _NAS_INDEX_TTL_S
    ):
        return _NAS_INDEX_CACHE

    cached_folders = nas_mount.get_cached_folders()
    if cached_folders is not None and not force_refresh:
        _NAS_INDEX_CACHE = _build_index_from_folders(cached_folders)
        _NAS_INDEX_CACHE_AT = now
        return _NAS_INDEX_CACHE

    if not blocking_scan:
        return _NAS_INDEX_CACHE or {}

    folders = _list_nas_folders_timed()
    if folders is None:
        return _NAS_INDEX_CACHE or {}
    _NAS_INDEX_CACHE = _build_index_from_folders(folders)
    _NAS_INDEX_CACHE_AT = now
    return _NAS_INDEX_CACHE


def _nas_entry_for_code(nas_index, code):
    """Resolve NAS folder stats by project code (exact or prefix e.g. LIGHT → LIGHT-high)."""
    if not code or not nas_index:
        return {}
    key = (code or '').upper()
    if key in nas_index:
        return nas_index[key]
    for entry in nas_index.values():
        folder = (entry.get('folderName') or entry.get('code') or '').strip()
        if not folder:
            continue
        fu = folder.upper()
        if (
            fu == key
            or fu.startswith(f'{key} ')
            or fu.startswith(f'{key}-')
            or fu.startswith(f'{key}_')
        ):
            return entry
    return {}


def _list_nas_folder_display_name(project_doc, nas_entry=None):
    """Display label for list API — index/cache/DB only, no per-row SMB."""
    code = (project_doc.get('code') or '').strip()
    code_u = code.upper()
    entry = nas_entry or {}
    fn = (entry.get('folderName') or '').strip()
    if fn and fn.upper() != code_u:
        return fn
    if fn and (' ' in fn or '_' in fn):
        return fn
    nf = (project_doc.get('nasFolder') or '').strip()
    if nf:
        base = Path(nf).name.strip()
        if base and base.upper() != code_u:
            return base
        if base and (' ' in base or '_' in base):
            return base
    stored = (project_doc.get('nasFolderName') or '').strip()
    if stored and stored.upper() != code_u:
        return stored
    if stored and (' ' in stored or '_' in stored):
        return stored
    return fn or stored or code


def enrich_wa_projects_display(projects) -> None:
    """Fill nasFolderName on project dict(s) for WhatsApp / UI labels (uses NAS index, no per-row SMB)."""
    if not projects:
        return
    projs = []
    for item in projects:
        if not item:
            continue
        projs.append(item[0] if isinstance(item, tuple) else item)
    if not projs:
        return

    buckets = sorted({
        (p.get('nasParentBucket') or '').strip()
        for p in projs
        if (p.get('nasParentBucket') or '').strip()
    })
    idx = nas_folder_index(blocking_scan=False)
    if not idx:
        cached = nas_mount.get_cached_folders() or nas_mount.peek_folder_cache()
        if cached:
            idx = _build_index_from_folders(cached)
    if not idx and buckets and nas_mount.is_volume_mounted():
        threading.Thread(
            target=lambda: build_nas_folder_index_from_buckets(buckets[:_NAS_BUCKET_SCAN_LIMIT]),
            daemon=True,
            name='nas-bucket-index-warm',
        ).start()

    for p in projs:
        code = (p.get('code') or '').strip()
        if not code:
            continue
        stored = (p.get('nasFolderName') or '').strip()
        # Keep any explicit folder name (bare PJ-xxxx or full name) — do not merge
        # duplicate physical folders to the single longest name in the NAS index.
        if stored:
            continue
        nas = _nas_entry_for_code(idx, code.upper())
        dn = _list_nas_folder_display_name(p, nas)
        if dn:
            p['nasFolderName'] = dn


def enrich_wa_project_display(project) -> None:
    if project:
        enrich_wa_projects_display([project])


def enrich_project_dict(project_doc, nas_index=None, *, fast_single=False, for_list=False, nas_view_doc=None):
    """Add NAS fields to a serialized project dict."""
    code = (project_doc.get('code') or '').upper()
    if fast_single and code and nas_mount.is_available():
        view = nas_view_doc or project_doc
        nas = nas_mount.folder_stats(code, project_doc=view) or {}
        if is_range_folder_code(code):
            project_doc['nasSiteFolderCount'] = nas.get('siteFolderCount', 0)
            project_doc['nasFileCount'] = 0
        else:
            project_doc['nasFileCount'] = nas.get('fileCount', 0)
        project_doc['nasLastModified'] = nas.get('latestModified')
        project_doc['nasSyncedAt'] = datetime.utcnow().isoformat() if nas else None
        stored = (project_doc.get('nasFolderName') or '').strip()
        if not stored and nas.get('folderName'):
            project_doc['nasFolderName'] = nas.get('folderName')
            _apply_nas_display_folder_name(project_doc)
        return project_doc
    if nas_index is None:
        nas_index = nas_folder_index(blocking_scan=not for_list)
    nas = _nas_entry_for_code(nas_index, code)
    project_doc['nasFileCount'] = nas.get('fileCount', 0)
    project_doc['nasLastModified'] = nas.get('latestModified')
    project_doc['nasSyncedAt'] = nas.get('nasSyncedAt')
    if for_list:
        project_doc['nasFolderName'] = _list_nas_folder_display_name(project_doc, nas)
    else:
        folder_name = (nas.get('folderName') or '').strip()
        if folder_name:
            project_doc['nasFolderName'] = folder_name
        else:
            project_doc['nasFolderName'] = nas.get('folderName')
            _apply_nas_display_folder_name(project_doc)
    return project_doc


def _apply_nas_display_folder_name(project_doc):
    code = (project_doc.get('code') or '').strip()
    if not code or not nas_mount.is_available():
        return
    try:
        from app.services.project_number_match_service import wa_classify_display_label

        dn = wa_classify_display_label(project_doc, max_len=500)
        if dn:
            project_doc['nasFolderName'] = dn
    except Exception:
        pass


def _is_nas_root_bucket_dir(name):
    """Root-level NAS folder that groups site projects (PJ-lo-hi, T-lo-hi, LIGHT, …)."""
    n = (name or '').strip()
    if not n:
        return False
    if is_range_folder_code(n) or is_nas_bucket_dir_name(n):
        return True
    if parse_nas_site_folder_code(n):
        return False
    if re.match(r'^P[-]', n, re.I):
        return False
    if re.match(r'^PJ-\d{1,6}$', n, re.I):
        return False
    upper = n.upper()
    if upper.startswith('PROJECT') or upper.startswith('PPPP'):
        return False
    if re.match(r'^[A-Za-z][A-Za-z0-9_-]{0,24}$', n):
        return True
    return False


_NAS_BUCKET_SCAN_LIMIT = 64


def build_nas_folder_index_from_buckets(bucket_names):
    """Scan range-bucket dirs on the mount for longest site folderName per code."""
    by_code: dict = {}
    for raw in bucket_names or []:
        name = (raw or '').strip()
        if not name:
            continue
        bucket = nas_mount._resolve_bucket_dir(name)
        if bucket is None or not bucket.is_dir():
            continue
        try:
            entries = sorted(bucket.iterdir())
        except OSError as e:
            logger.warning('[NAS] bucket scan failed for %s: %s', name, e)
            continue
        for entry in entries:
            if not entry.is_dir() or entry.name.startswith('.'):
                continue
            site_code = parse_nas_site_folder_code(entry.name)
            if not site_code:
                continue
            _merge_site_folder_row(by_code, {
                'code': site_code,
                'folderName': entry.name,
                'parentBucket': name,
            })
    index = _build_index_from_folders(list(by_code.values()))
    global _NAS_INDEX_CACHE, _NAS_INDEX_CACHE_AT
    if index:
        _NAS_INDEX_CACHE = index
        _NAS_INDEX_CACHE_AT = time.time()
    return index


def _merge_site_folder_row(by_code: dict, row: dict) -> None:
    """Keep the longest NAS folderName per site code (skip bare PJ-xxxx duplicates)."""
    code = (row.get('code') or '').strip()
    if not code:
        return
    key = code.upper()
    name = (row.get('folderName') or code).strip()
    row = {**row, 'code': code, 'folderName': name}
    prev = by_code.get(key)
    if prev is None or len(name) > len((prev.get('folderName') or '')):
        by_code[key] = row


def _list_physical_site_folders_impl(site_code_or_num):
    """Uncached NAS scan for one site code — may hang on stale SMB."""
    from app.services.project_number_match_service import (
        PROJECT_CODE_RE,
        SITE_KEY_RE,
        canonical_pj_code,
        classify_site_key_from_text,
        pj_number_from_project_code,
    )

    raw = (site_code_or_num or '').strip()
    if not raw:
        return []
    site_code = None
    if raw.upper().startswith('PJ-'):
        site_code = raw.upper()
        if not PROJECT_CODE_RE.match(site_code):
            site_code = None
    if not site_code:
        key = classify_site_key_from_text(raw)
        if key:
            km = SITE_KEY_RE.match(key)
            if km:
                site_code = canonical_pj_code(km.group(1), km.group(2) or '').upper()
    if not site_code or not nas_mount.is_available():
        return []

    target = site_code.upper()
    site_num = pj_number_from_project_code(site_code)
    seen = set()
    out = []

    def _add(folder_name, parent_bucket):
        fn = (folder_name or '').strip()
        if not fn:
            return
        dedupe_key = (fn, (parent_bucket or '').strip())
        if dedupe_key in seen:
            return
        parsed = parse_nas_site_folder_code(fn)
        if not parsed or parsed.upper() != target:
            return
        seen.add(dedupe_key)
        out.append({
            'folderName': fn,
            'parentBucket': parent_bucket,
            'code': parsed,
        })

    def _scan_bucket(bucket_name):
        for child in nas_mount._list_bucket_child_folders_sync(bucket_name):
            _add(child.get('folderName') or '', bucket_name)

    root_names = nas_mount.list_watch_root_dir_names() or []
    bucket_names = [n for n in root_names if _is_nas_root_bucket_dir(n)]
    bucket_set = set(bucket_names)
    scanned_buckets = set()

    priority_buckets = []
    if site_num is not None:
        watch = nas_mount._watch_dir()
        if watch:
            from app.services.project_number_match_service import find_range_bucket_dir

            primary = find_range_bucket_dir(watch, site_num)
            if primary is not None:
                priority_buckets.append(primary.name)
    try:
        from app import mongo

        for doc in mongo.db.wa_projects.find(
            {'code': {'$regex': f'^{re.escape(site_code)}$', '$options': 'i'}},
            {'nasParentBucket': 1},
        ):
            pb = (doc.get('nasParentBucket') or '').strip()
            if pb and pb not in priority_buckets:
                priority_buckets.append(pb)
    except Exception:
        pass

    for bucket in priority_buckets:
        if bucket in bucket_set or bucket in root_names:
            _scan_bucket(bucket)
            scanned_buckets.add(bucket)
    if len(out) > 1:
        out.sort(key=lambda r: (r.get('folderName') or '').lower())
        return out

    for bucket in bucket_names:
        if bucket in scanned_buckets:
            continue
        _scan_bucket(bucket)
        scanned_buckets.add(bucket)
    for name in root_names:
        if name in bucket_set:
            continue
        _add(name, None)

    out.sort(key=lambda r: (r.get('folderName') or '').lower())
    return out


def list_physical_site_folders(site_code_or_num):
    """Every NAS directory for one site code; time-boxed (SMB tunnel may hang)."""
    from app.services.nas_watcher_service import _run_with_timeout

    if not nas_mount.is_volume_mounted():
        return []
    timeout_s = float(os.environ.get('NAS_SITE_FOLDER_LIST_TIMEOUT_S', '8'))
    out = _run_with_timeout(
        lambda: _list_physical_site_folders_impl(site_code_or_num),
        timeout_s,
        default=None,
    )
    if out is None:
        logger.warning(
            '[NAS] list_physical_site_folders timed out after %ss (%s)',
            timeout_s,
            site_code_or_num,
        )
        return []
    return out


def collect_nas_site_folder_rows():
    """Fast NAS → site rows via root scan + per-bucket children (no full-tree walk)."""
    by_code: dict = {}
    root = nas_mount._watch_dir()
    if not root or not os.path.isdir(root):
        return []

    root_names = nas_mount.list_watch_root_dir_names()
    bucket_names = [n for n in root_names if _is_nas_root_bucket_dir(n)]
    bucket_set = set(bucket_names)
    for name in bucket_names[:_NAS_BUCKET_SCAN_LIMIT]:
        # Direct iterdir — avoid SMB timeout wrapper dropping bucket children.
        for child in nas_mount._list_bucket_child_folders_sync(name):
            site_code = _bucket_child_site_code(child)
            if not site_code:
                continue
            _merge_site_folder_row(by_code, {
                'code': site_code,
                'folderName': child.get('folderName') or site_code,
                'parentBucket': name,
            })

    for name in root_names:
        if name in bucket_set:
            continue
        site_code = parse_nas_site_folder_code(name)
        if site_code:
            _merge_site_folder_row(by_code, {
                'code': site_code,
                'folderName': name,
                'parentBucket': None,
            })
            continue
        _merge_site_folder_row(by_code, {
            'code': name,
            'folderName': name,
            'parentBucket': None,
        })

    cached = nas_mount.get_cached_folders() or nas_mount.peek_folder_cache()
    if cached:
        for folder in cached:
            code = (folder.get('code') or '').strip()
            if not code or is_range_folder_code(code):
                continue
            _merge_site_folder_row(by_code, {
                'code': code,
                'folderName': folder.get('folderName') or code,
                'parentBucket': (folder.get('parentBucket') or '').strip() or None,
            })
    return list(by_code.values())


def _ensure_nas_bucket_projects(owner_id, root_names, now):
    """Mongo records for range / T / grouping folders so Projects UI lists top-level buckets."""
    from app.services.wa_project_validation import find_project_by_code

    created = []
    for name in root_names:
        if not _is_nas_root_bucket_dir(name):
            continue
        if find_project_by_code(name):
            continue
        doc = {
            'code': name.upper() if is_nas_bucket_folder_code(name) else name,
            'location': '',
            'owner': owner_id,
            'stage': 'active',
            'status': 'active',
            'members': [owner_id],
            'nasFolder': name,
            'nasImportedAt': now,
            'createdAt': now,
            'updatedAt': now,
        }
        mongo.db.wa_projects.insert_one(doc)
        created.append(doc['code'])
    return created


def sync_bucket_site_projects_from_nas(bucket_code, owner_id):
    """Import/update all site folders under one NAS bucket (e.g. PJ-3000-3999)."""
    if not nas_mount.is_available():
        return {'ok': False, 'error': 'NAS mount not available'}

    code = (bucket_code or '').strip()
    if not code:
        return {'ok': False, 'error': 'bucketCode required'}

    from app.services.nas_bucket_code import nas_path_from_web_bucket
    from app.services.wa_project_validation import find_project_by_code

    parent_bucket = nas_path_from_web_bucket(code)
    now = datetime.utcnow()
    children = sorted(
        nas_mount._list_bucket_child_folders_sync(code),
        key=lambda c: len((c.get('folderName') or '')),
        reverse=True,
    )
    created = []
    updated = 0
    for child in children:
        site_code = _bucket_child_site_code(child)
        if not site_code:
            continue
        folder_name = (child.get('folderName') or site_code).strip()
        existing = find_project_by_code(site_code, parent_bucket=parent_bucket)
        if existing:
            patch = {'updatedAt': now, 'nasParentBucket': parent_bucket}
            if folder_name:
                patch['nasFolderName'] = folder_name
                patch['nasFolder'] = folder_name
            mongo.db.wa_projects.update_one({'_id': existing['_id']}, {'$set': patch})
            updated += 1
            continue
        doc = {
            'code': site_code,
            'location': '',
            'owner': owner_id,
            'stage': 'active',
            'status': 'active',
            'members': [owner_id],
            'nasFolder': folder_name,
            'nasFolderName': folder_name,
            'nasParentBucket': parent_bucket,
            'nasImportedAt': now,
            'createdAt': now,
            'updatedAt': now,
        }
        mongo.db.wa_projects.insert_one(doc)
        created.append(site_code)

    return {
        'ok': True,
        'bucketCode': code,
        'nasParentBucket': parent_bucket,
        'scanned': len(children),
        'created': created,
        'updated': updated,
    }


def sync_projects_from_nas(owner_id):
    """Create web projects for NAS folders that do not exist yet."""
    if not nas_mount.is_available():
        return {'ok': False, 'error': 'NAS mount not available'}

    now = datetime.utcnow()
    root_names = nas_mount.list_watch_root_dir_names()
    buckets_created = _ensure_nas_bucket_projects(owner_id, root_names, now)

    folders = collect_nas_site_folder_rows()
    if not folders:
        folders = nas_mount.list_folders_for_api() or []

    created = list(buckets_created)
    skipped = []

    for folder in folders:
        raw_code = (folder.get('code') or folder.get('folderName') or '').strip()
        if not raw_code or is_range_folder_code(raw_code):
            continue
        code = raw_code.upper() if raw_code.upper().startswith('PJ-') else raw_code
        from app.services.wa_project_validation import find_project_by_code

        parent_bucket = (folder.get('parentBucket') or '').strip() or None
        existing = find_project_by_code(code, parent_bucket=parent_bucket)
        if existing:
            fn = (folder.get('folderName') or '').strip()
            if fn and (existing.get('nasFolderName') or '').strip() != fn:
                mongo.db.wa_projects.update_one(
                    {'_id': existing['_id']},
                    {'$set': {'nasFolderName': fn, 'updatedAt': now}},
                )
            skipped.append(code)
            continue
        doc = {
            'code': code,
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
        if parent_bucket:
            doc['nasParentBucket'] = parent_bucket
        mongo.db.wa_projects.insert_one(doc)
        created.append(code)

    try:
        nas_folder_index(force_refresh=False)
    except Exception:
        pass
    return {
        'ok': True,
        'created': created,
        'skippedExisting': skipped,
        'foldersScanned': len(folders),
        'bucketsCreated': buckets_created,
    }


def _nas_file_path(project_code, filename, *, relative_path=None, absolute_path=None):
    if absolute_path and os.path.isfile(absolute_path):
        return absolute_path
    folder = nas_mount._resolve_project_folder(project_code)
    if not folder:
        return None
    if relative_path:
        candidate = folder / relative_path
        return str(candidate) if candidate.is_file() else None
    candidate = folder / filename
    if candidate.is_file():
        return str(candidate)
    for f in folder.rglob(filename):
        if f.is_file():
            return str(f)
    return None


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
    if project.get('nasImportedAt') or project.get('nasFolder') or project.get('nasParentBucket'):
        return True
    if mongo.db.wa_records.count_documents(_record_query_nas_linked(project['_id'])) > 0:
        return True
    if mongo.db.pool_images.find_one({
        'projectId': project['_id'],
        'nasPath': {'$exists': True, '$nin': [None, '']},
    }):
        return True
    if mongo.db.pool_images.find_one({
        'projectId': project['_id'],
        'recordId': {'$exists': True, '$nin': [None, '']},
    }):
        return True
    return False


def _record_media_basenames(record) -> set:
    names = set()
    for ph in record.get('photos') or []:
        if not isinstance(ph, str):
            continue
        base = os.path.basename(ph.split('?')[0]).lower()
        if base:
            names.add(base)
    for img in mongo.db.pool_images.find({'recordId': record['_id']}):
        for key in ('nasPath', 'imagePath', 'fileName'):
            val = (img.get(key) or '').strip()
            if not val:
                continue
            base = os.path.basename(val.split('?')[0]).lower()
            if base:
                names.add(base)
    return names


def _project_nas_image_basenames(project_code, project_doc=None):
    """Lowercase file names of images under the project folder on the share."""
    folder = nas_mount._folder_for_project(project_code, project_doc)
    if folder is None:
        return None
    from app.services.nas_watcher_service import _iter_project_images

    try:
        root = Path(folder)
    except (TypeError, ValueError):
        return set()
    return {f.name.lower() for f in _iter_project_images(root)}


def _nas_share_still_has_record_files(record, *, nas_image_names, folder_missing=False) -> bool:
    """True if any expected media filename still exists on the NAS project tree."""
    if folder_missing:
        return False
    if nas_image_names is None:
        return False
    want = _record_media_basenames(record)
    if not want:
        return True
    for name in want:
        stem, _ext = os.path.splitext(name)
        for on_disk in nas_image_names:
            if on_disk == name:
                return True
            if stem and on_disk.startswith(stem):
                return True
    return False


def _wa_assign_record_gone_from_share(record, project, *, nas_image_names, folder_missing=False) -> bool:
    """WhatsApp pool assign: drop web row when share no longer has those files."""
    if not mongo.db.pool_images.find_one({'recordId': record['_id']}):
        return False
    if not _project_linked_to_nas(project):
        return False
    return not _nas_share_still_has_record_files(
        record,
        nas_image_names=nas_image_names,
        folder_missing=folder_missing,
    )


def _collect_record_nas_paths(record) -> set:
    paths = _nas_paths_on_record(record)
    for img in mongo.db.pool_images.find({'recordId': record['_id']}):
        np = (img.get('nasPath') or '').strip()
        if np:
            paths.add(np)
    return paths


def _record_had_nas_expectation(record) -> bool:
    if _collect_record_nas_paths(record):
        return True
    if record.get('nasSourcePath'):
        return True
    status = (record.get('nasSyncStatus') or '').strip()
    if status and status != 'skipped':
        return True
    if (record.get('nasSyncExpected') or 0) > 0:
        return True
    return False


def _record_site_days(record) -> set[str]:
    """Dates under Photo/YYYY-MM-DD linked to this WA record."""
    from app.services.nas_site_remark_service import site_day_from_nas_path

    days: set[str] = set()
    for p in _nas_paths_on_record(record):
        d = site_day_from_nas_path(p)
        if d:
            days.add(d)
    if not days:
        ca = record.get('createdAt')
        if ca is not None:
            if hasattr(ca, 'strftime'):
                days.add(ca.strftime('%Y-%m-%d'))
            else:
                s = str(ca)
                if len(s) >= 10:
                    days.add(s[:10])
    return days


def _record_linked_to_site_nas(record) -> bool:
    if _record_had_nas_expectation(record):
        return True
    if (record.get('status') or '').strip().lower() == 'moved':
        return True
    return False


def _site_day_dirs_missing_on_share(site_folder, days: set[str]) -> bool:
    """True when every Photo/YYYY-MM-DD dir for these days is gone on the share."""
    if not days or site_folder is None:
        return False
    try:
        root = Path(site_folder)
    except (TypeError, ValueError):
        return False
    if not root.is_dir():
        return False
    for day in days:
        if (root / 'Photo' / day).is_dir():
            return False
    return True


def _should_remove_record_after_nas_deletion(
    record,
    project,
    *,
    nas_image_names=None,
    folder_missing=False,
    site_folder=None,
) -> bool:
    """True when NAS-backed content is gone on the share (including WA assign + local-only thumbs)."""
    if (
        not folder_missing
        and site_folder is not None
        and _record_linked_to_site_nas(record)
    ):
        days = _record_site_days(record)
        if days and _site_day_dirs_missing_on_share(site_folder, days):
            return True

    if _wa_assign_record_gone_from_share(
        record,
        project,
        nas_image_names=nas_image_names,
        folder_missing=folder_missing,
    ):
        return True
    if not _record_had_nas_expectation(record):
        return False
    paths = _collect_record_nas_paths(record)
    if paths:
        return not any(os.path.isfile(p) for p in paths)
    status = (record.get('nasSyncStatus') or '').strip()
    if (record.get('nasSyncExpected') or 0) > 0 and record.get('nasSyncUpdatedAt'):
        if status in ('synced', 'partial', 'failed'):
            if not _nas_share_still_has_record_files(
                record,
                nas_image_names=nas_image_names or set(),
                folder_missing=folder_missing,
            ):
                return True
    return False


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


def delete_nas_paths(paths):
    """Delete NAS files by absolute/share path; returns paths successfully removed."""
    deleted = []
    for p in paths or []:
        path = (p or '').strip()
        if not path:
            continue
        result = nas_mount.delete_path(path)
        if result.get('ok'):
            deleted.append(path)
    return deleted


def photo_day_dir_from_nas_path(path: str) -> str | None:
    """Parent dir when *path* is a file under …/Photo/YYYY-MM-DD/."""
    from app.services.nas_site_remark_service import PHOTO_SUBDIR, site_day_from_nas_path

    p = (path or '').strip()
    if not p:
        return None
    day = site_day_from_nas_path(p)
    if not day:
        return None
    day_dir = os.path.dirname(p)
    if os.path.basename(day_dir) != day:
        return None
    if os.path.basename(os.path.dirname(day_dir)) != PHOTO_SUBDIR:
        return None
    return day_dir


def _photo_day_dir_has_user_content(day_dir: str) -> bool:
    """True if the day folder still has non-hidden files or subfolders."""
    try:
        for ent in os.scandir(day_dir):
            if ent.name.startswith('.'):
                continue
            return True
    except OSError:
        return True
    return False


def _clear_hidden_junk_in_day_dir(day_dir: str) -> None:
    try:
        for ent in os.scandir(day_dir):
            if not ent.name.startswith('.'):
                continue
            if ent.is_file(follow_symlinks=False):
                try:
                    os.remove(ent.path)
                except OSError:
                    pass
    except OSError:
        pass


def remove_empty_photo_day_dirs(for_paths) -> list[str]:
    """After move/delete, drop Photo/YYYY-MM-DD dirs with no remaining site files."""
    day_dirs: set[str] = set()
    for path in for_paths or []:
        day_dir = photo_day_dir_from_nas_path(path)
        if day_dir:
            day_dirs.add(day_dir)
    removed: list[str] = []
    for day_dir in sorted(day_dirs):
        if not os.path.isdir(day_dir):
            continue
        if _photo_day_dir_has_user_content(day_dir):
            continue
        _clear_hidden_junk_in_day_dir(day_dir)
        if _photo_day_dir_has_user_content(day_dir):
            continue
        result = nas_mount.delete_path(day_dir)
        if result.get('ok'):
            removed.append(day_dir)
            logger.info('[NASSync] Removed empty Photo day folder → %s', day_dir)
    return removed


def remove_nas_files_for_record(record):
    """Web → NAS: remove files on the share linked to a record."""
    paths = set()
    if record.get('nasSourcePath'):
        paths.add(record['nasSourcePath'])
    for p in record.get('nasPhotos') or []:
        if p:
            paths.add(p)
    path_list = list(paths)
    deleted = delete_nas_paths(path_list)
    remove_empty_photo_day_dirs(path_list)
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
    nas_result = None
    if remove_nas_folder:
        if not nas_mount.is_available():
            return {
                'ok': False,
                'error': 'NAS is not connected — uncheck “delete NAS folder” or mount the share first.',
            }
        nas_result = nas_mount.delete_project_folder(
            project['code'],
            project_doc=project,
        )
        if not nas_result.get('ok') and not nas_result.get('missing'):
            return {
                'ok': False,
                'error': nas_result.get('error') or 'Failed to delete NAS folder',
                'nasResult': nas_result,
            }
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
    return {'ok': True, 'code': project.get('code'), 'nasResult': nas_result}


def _migrate_bucket_parent_code(old_bucket: str, new_bucket: str, *, exclude_project_id=None):
    """When a NAS bucket folder is renamed, site rows must follow the new parent."""
    old_b = (old_bucket or '').strip()
    new_b = (new_bucket or '').strip()
    if not old_b or not new_b or old_b.upper() == new_b.upper():
        return
    now = datetime.utcnow()
    mongo.db.wa_projects.update_many(
        {
            'nasParentBucket': {'$regex': f'^{re.escape(old_b)}$', '$options': 'i'},
        },
        {'$set': {'nasParentBucket': new_b, 'updatedAt': now}},
    )
    dup_query = {
        'code': {'$regex': f'^{re.escape(old_b)}$', '$options': 'i'},
        'status': {'$ne': 'archived'},
    }
    if exclude_project_id is not None:
        dup_query['_id'] = {'$ne': exclude_project_id}
    mongo.db.wa_projects.delete_many(dup_query)
    _refresh_site_nas_folders_under_bucket(new_b)


def _refresh_site_nas_folders_under_bucket(bucket_code: str):
    """Point site rows at folders under the bucket after bucket rename or sync."""
    bucket_code = (bucket_code or '').strip()
    if not bucket_code or not nas_mount.is_available():
        return
    bucket_dir = nas_mount._resolve_bucket_dir(bucket_code)
    if bucket_dir is None or not bucket_dir.is_dir():
        return
    now = datetime.utcnow()
    cursor = mongo.db.wa_projects.find(
        {
            'nasParentBucket': {'$regex': f'^{re.escape(bucket_code)}$', '$options': 'i'},
            'status': {'$ne': 'archived'},
        },
        {'code': 1, 'nasFolderName': 1},
    )
    for doc in cursor:
        code = (doc.get('code') or '').strip()
        if not code or is_range_folder_code(code) or is_nas_bucket_folder_code(code):
            continue
        label = (doc.get('nasFolderName') or '').strip() or code
        site_path = bucket_dir / label
        if not site_path.is_dir() and label != code:
            site_path = bucket_dir / code
        if not site_path.is_dir():
            continue
        mongo.db.wa_projects.update_one(
            {'_id': doc['_id']},
            {'$set': {'nasFolder': str(site_path.resolve()), 'updatedAt': now}},
        )


def update_web_project(project, data, *, sync_nas=True):
    """Update WA project; optionally rename NAS folder (Web ↔ path on share)."""
    from app.services.wa_project_validation import normalize_code, assert_code_available

    if not project:
        return {'ok': False, 'error': 'Project not found'}

    old_code = (project.get('code') or '').strip()
    parent_on_row = (project.get('nasParentBucket') or '').strip()
    is_bucket = is_nas_bucket_folder_code(old_code) or (
        not parent_on_row and _is_nas_root_bucket_dir(old_code)
    )

    new_code = normalize_code(data.get('code', old_code)) if data.get('code') is not None else normalize_code(old_code)
    if not new_code:
        return {'ok': False, 'error': 'Project code is required'}
    if is_bucket and new_code != normalize_code(old_code):
        return {'ok': False, 'error': 'NAS bucket folder codes cannot be renamed'}

    if new_code != normalize_code(old_code):
        err = assert_code_available(
            new_code,
            parent_bucket=parent_on_row or None,
            exclude_id=project['_id'],
        )
        if err:
            return {'ok': False, 'error': err}

    nas_folder_label = data.get('nasFolderName')
    if nas_folder_label is not None:
        nas_folder_label = (nas_folder_label or '').strip()
    else:
        nas_folder_label = None

    code_changed = new_code != normalize_code(old_code)

    if is_bucket:
        target_dir_name = (nas_folder_label or old_code).strip()
    else:
        old_norm = normalize_code(old_code)
        if nas_folder_label:
            label_norm = normalize_code(nas_folder_label)
            if code_changed and label_norm == old_norm:
                target_dir_name = new_code
            else:
                target_dir_name = nas_folder_label
        else:
            target_dir_name = new_code

    mongo_updates = {'updatedAt': datetime.utcnow()}
    if data.get('location') is not None:
        mongo_updates['location'] = (data.get('location') or '').strip()
    if data.get('stage') is not None:
        mongo_updates['stage'] = data.get('stage') or project.get('stage', 'active')
    if data.get('status') is not None:
        mongo_updates['status'] = data.get('status') or project.get('status', 'active')
    if nas_folder_label is not None:
        mongo_updates['nasFolderName'] = nas_folder_label

    parent_bucket = parent_on_row or None
    if data.get('nasParentBucket') is not None:
        from app.services.nas_bucket_code import nas_path_from_web_bucket

        parent_bucket = nas_path_from_web_bucket(data.get('nasParentBucket') or '') or None
        mongo_updates['nasParentBucket'] = parent_bucket

    if sync_nas and is_bucket:
        current = nas_mount._resolve_bucket_dir(old_code) if nas_mount.is_available() else None
        current_name = current.name if current is not None else None
        needs_rename = bool(current is not None and current_name and current_name != target_dir_name)
        if needs_rename:
            if not nas_mount.is_available():
                return {'ok': False, 'error': 'NAS is not connected — mount the share or turn off sync'}
            r = nas_mount.rename_bucket_folder(old_code, target_dir_name)
            if not r.get('ok'):
                return {'ok': False, 'error': r.get('error') or 'NAS bucket rename failed'}
            mongo_updates['nasFolder'] = r.get('path')
            if target_dir_name.upper() != old_code.upper():
                new_bucket_code = (
                    target_dir_name.upper()
                    if is_nas_bucket_folder_code(target_dir_name)
                    else target_dir_name
                )
                err = assert_code_available(
                    new_bucket_code,
                    parent_bucket=parent_on_row or None,
                    exclude_id=project['_id'],
                )
                if err:
                    return {'ok': False, 'error': err}
                mongo_updates['code'] = new_bucket_code
                _migrate_bucket_parent_code(old_code, new_bucket_code, exclude_project_id=project['_id'])
        elif current is not None and nas_mount.is_available():
            mongo_updates['nasFolder'] = str(current.resolve())

    elif sync_nas and not is_bucket:
        lookup_code = old_code
        current = nas_mount._resolve_project_folder(lookup_code) if nas_mount.is_available() else None
        if current is None and nas_mount.is_available() and parent_bucket:
            parent_dir = nas_mount._resolve_bucket_dir(parent_bucket)
            if parent_dir is not None:
                for name in (old_code, target_dir_name):
                    candidate = parent_dir / name
                    if candidate.is_dir():
                        current = candidate
                        break
        current_name = current.name if current is not None else None
        wants_nas_change = code_changed or (
            current_name is not None and current_name != target_dir_name
        )
        needs_rename = bool(current is not None and wants_nas_change)
        if needs_rename:
            if not nas_mount.is_available():
                return {'ok': False, 'error': 'NAS is not connected — mount the share or turn off sync'}
            r = nas_mount.rename_site_folder(
                lookup_code,
                target_dir_name,
                parent_bucket_code=parent_bucket,
            )
            if not r.get('ok'):
                return {'ok': False, 'error': r.get('error') or 'NAS rename failed'}
            mongo_updates['nasFolder'] = r.get('path')
        elif current is not None and nas_mount.is_available():
            mongo_updates['nasFolder'] = str(current.resolve())
        elif nas_mount.is_available():
            created = nas_mount.create_folder(
                new_code,
                parent_bucket_code=parent_bucket,
                skip_deep_resolve=True,
            )
            if created.get('ok'):
                mongo_updates['nasFolder'] = created['path']
            elif wants_nas_change:
                return {
                    'ok': False,
                    'error': created.get('error') or 'NAS site folder not found under parent bucket',
                }

    if new_code != normalize_code(old_code):
        mongo_updates['code'] = new_code
        mongo.db.wa_records.update_many(
            {'projectId': project['_id']},
            {'$set': {'projectCode': new_code, 'updatedAt': datetime.utcnow()}},
        )
        mongo.db.pool_images.update_many(
            {'projectId': project['_id']},
            {'$set': {'projectCode': new_code, 'updatedAt': datetime.utcnow()}},
        )

    mongo.db.wa_projects.update_one({'_id': project['_id']}, {'$set': mongo_updates})
    updated = mongo.db.wa_projects.find_one({'_id': project['_id']})
    if updated and nas_mount.is_available() and not is_bucket:
        nas_folder_index(force_refresh=True)
    return {'ok': True, 'project': updated}


def _infer_parent_bucket_from_path(project, watch_dir):
    nf = project.get('nasFolder')
    if not nf or not watch_dir:
        return None
    try:
        folder = Path(nf).resolve()
        root = Path(watch_dir).resolve()
        if folder.parent == root:
            return None
        if str(folder.parent).startswith(str(root)):
            return folder.parent.name
    except (OSError, ValueError):
        return None
    return None


def sync_projects_to_nas():
    """Web → NAS: create missing project folders on the shared drive."""
    if not nas_mount.is_available():
        return {'ok': False, 'error': 'NAS mount not available', 'foldersCreated': []}

    watch_dir = nas_mount._watch_dir()
    folders_created = []
    errors = []

    projects = list(mongo.db.wa_projects.find({'status': {'$ne': 'archived'}}))
    root = Path(watch_dir) if watch_dir else None
    for project in projects:
        code = (project.get('code') or '').strip()
        if not code or is_range_folder_code(code):
            continue
        parent = (project.get('nasParentBucket') or '').strip() or None
        if not parent and watch_dir:
            parent = _infer_parent_bucket_from_path(project, watch_dir)
        expected = None
        if root is not None:
            if parent:
                parent_dir = nas_mount._resolve_parent_dir(parent)
                if parent_dir is not None:
                    expected = parent_dir / code
            else:
                expected = root / code
        if expected is not None and expected.is_dir():
            if project.get('nasFolder') != str(expected):
                mongo.db.wa_projects.update_one(
                    {'_id': project['_id']},
                    {'$set': {'nasFolder': str(expected), 'updatedAt': datetime.utcnow()}},
                )
            continue
        result = nas_mount.create_folder(
            code, parent_bucket_code=parent, skip_deep_resolve=True,
        )
        if result.get('ok'):
            folders_created.append(code)
            updates = {
                'nasFolder': result['path'],
                'updatedAt': datetime.utcnow(),
            }
            if parent:
                updates['nasParentBucket'] = parent
            mongo.db.wa_projects.update_one({'_id': project['_id']}, {'$set': updates})
        else:
            errors.append({'code': code, 'error': result.get('error') or 'create failed'})

    if folders_created:
        nas_folder_index(force_refresh=True)
    return {'ok': True, 'foldersCreated': folders_created, 'errors': errors}


def reconcile_project_from_nas(project, *, media_dir=None):
    """NAS → web for one project: remove row if share folder/files are gone."""
    if not nas_mount.is_available():
        return {'projectRemoved': False, 'recordsRemoved': 0, 'recordRefs': []}

    if media_dir is None:
        media_dir = _media_dir()

    code = (project.get('code') or '').strip()
    folder = nas_mount._folder_for_project(code, project)
    if folder is None and _project_linked_to_nas(project):
        delete_web_project(project, remove_nas_folder=False)
        return {
            'projectRemoved': True,
            'recordsRemoved': 0,
            'recordRefs': [],
            'code': code,
        }

    folder_missing = folder is None
    nas_image_names = _project_nas_image_basenames(code, project) if not folder_missing else None

    records_removed = 0
    record_refs = []
    for rec in mongo.db.wa_records.find({'projectId': project['_id']}):
        if not _should_remove_record_after_nas_deletion(
            rec,
            project,
            nas_image_names=nas_image_names,
            folder_missing=folder_missing,
            site_folder=folder,
        ):
            continue
        ref = rec.get('referenceNumber', str(rec['_id']))
        delete_web_record(rec, remove_nas=False, media_dir=media_dir)
        records_removed += 1
        record_refs.append(ref)

    return {
        'projectRemoved': False,
        'recordsRemoved': records_removed,
        'recordRefs': record_refs,
        'code': code,
    }


def _purge_web_projects_for_nas_bucket(bucket_name: str, *, media_dir=None) -> list[str]:
    """NAS → web: remove bucket container + all site rows under a deleted top-level folder."""
    from app.services.nas_bucket_code import nas_parent_bucket_match_values

    path = (bucket_name or '').strip()
    if not path:
        return []
    match_vals = {v.upper() for v in nas_parent_bucket_match_values(path)}
    removed: list[str] = []
    for proj in list(mongo.db.wa_projects.find({'status': {'$ne': 'archived'}})):
        code = (proj.get('code') or '').strip()
        parent = (proj.get('nasParentBucket') or '').strip()
        is_container = (
            code.upper() == path.upper()
            and _is_nas_root_bucket_dir(path)
            and not parent
        )
        under_bucket = bool(parent and parent.upper() in match_vals)
        if not (is_container or under_bucket):
            continue
        delete_web_project(proj, remove_nas_folder=False)
        removed.append(code or str(proj['_id']))
    return removed


def reconcile_after_nas_folder_deleted(folder_name, *, media_dir=None):
    """After manual NAS folder delete — drop matching web project/records."""
    name = (folder_name or '').strip()
    if not name:
        return reconcile_deletions_from_nas(media_dir=media_dir)

    bucket_removed: list[str] = []
    if _is_nas_root_bucket_dir(name):
        bucket_removed = _purge_web_projects_for_nas_bucket(name, media_dir=media_dir)
        nas_folder_index(force_refresh=True)
        base = reconcile_deletions_from_nas(media_dir=media_dir)
        base['projectsRemoved'] = list({
            *(base.get('projectsRemoved') or []),
            *bucket_removed,
        })
        return base

    site_code = parse_nas_site_folder_code(name)
    project = None
    if site_code:
        project = mongo.db.wa_projects.find_one({
            'code': {'$regex': f'^{re.escape(site_code)}$', '$options': 'i'},
            'status': {'$ne': 'archived'},
        })
    if project is None:
        project = mongo.db.wa_projects.find_one({
            'nasFolderName': {'$regex': f'^{re.escape(name)}$', '$options': 'i'},
            'status': {'$ne': 'archived'},
        })
    if project and _project_linked_to_nas(project):
        reconcile_project_from_nas(project, media_dir=media_dir)
        return reconcile_deletions_from_nas(media_dir=media_dir)

    if is_nas_bucket_dir_name(name) or is_range_folder_code(name):
        nas_folder_index(force_refresh=True)

    return reconcile_deletions_from_nas(media_dir=media_dir)


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
        outcome = reconcile_project_from_nas(project, media_dir=media_dir)
        if outcome.get('projectRemoved'):
            projects_removed.append(outcome.get('code') or project.get('code', ''))
        records_removed += outcome.get('recordsRemoved') or 0
        record_refs.extend(outcome.get('recordRefs') or [])

    if records_removed or projects_removed:
        nas_folder_index(force_refresh=True)
    return {
        'recordsRemoved': records_removed,
        'recordRefs': record_refs,
        'projectsRemoved': projects_removed,
    }


def list_nas_root_bucket_summaries():
    """Top-level NAS bucket folders for Projects UI (merge with Mongo buckets)."""
    from app.services.nas_bucket_code import web_bucket_key_for_nas_root

    if not nas_mount.is_volume_mounted():
        return []
    out = []
    for name in nas_mount.list_watch_root_dir_names() or []:
        if not _is_nas_root_bucket_dir(name):
            continue
        web_key = web_bucket_key_for_nas_root(name)
        cached = (
            nas_mount.peek_bucket_children_cache(web_key)
            or nas_mount.peek_bucket_children_cache(name)
        )
        row = {'nasName': name, 'bucketCode': web_key}
        if cached is not None:
            row['childCount'] = len(cached)
        out.append(row)
    out.sort(key=lambda r: (r.get('nasName') or '').lower())
    return out


def run_bidirectional_nas_sync(owner_id=None, *, import_files=False):
    """NAS ↔ web: reconcile deletes; optional full photo import (manual Sync NAS only)."""
    if not nas_mount.is_available():
        return {'ok': False, 'error': 'NAS mount not available'}

    if not _nas_sync_lock.acquire(blocking=False):
        return {'ok': True, 'skipped': True, 'reason': 'sync_already_running'}

    try:
        oid = owner_id or _default_sync_owner_id()
        if not oid:
            return {'ok': False, 'error': 'No user available for imported project ownership'}

        to_nas = sync_projects_to_nas()
        if not to_nas.get('ok'):
            return to_nas

        proj = sync_projects_from_nas(oid)
        deletions = reconcile_deletions_from_nas()
        records_imported = 0
        if import_files:
            imports = import_all_projects_from_nas()
            records_imported = sum(r.get('created', 0) for r in imports if r.get('ok'))

        try:
            nas_mount._refresh_bucket_children_caches()
        except Exception:
            logger.exception('[NAS] Bucket cache refresh after bidirectional sync failed')

        result = {
            'ok': True,
            'foldersCreated': to_nas.get('foldersCreated', []),
            'foldersCreateErrors': to_nas.get('errors', []),
            'projectsCreated': proj.get('created', []),
            'projectsRemoved': deletions.get('projectsRemoved', []),
            'recordsImported': records_imported,
            'recordsRemoved': deletions.get('recordsRemoved', 0),
            'recordsRemovedRefs': deletions.get('recordRefs', []),
            'at': datetime.utcnow().isoformat(),
        }
        mongo.db.wa_system.update_one({'_id': 'nas_sync'}, {'$set': result}, upsert=True)
        return result
    finally:
        _nas_sync_lock.release()


def import_nas_files_for_project(project_id, media_dir=None):
    """Import NAS images as WA records (skip files already linked)."""
    if not nas_mount.is_available():
        return {'ok': False, 'error': 'NAS mount not available'}

    project = mongo.db.wa_projects.find_one({'_id': ObjectId(project_id)})
    if not project:
        return {'ok': False, 'error': 'Project not found'}

    if is_range_folder_code(project.get('code', '')):
        return {
            'ok': True,
            'created': 0,
            'skipped': 0,
            'filesOnNas': 0,
            'note': 'Range bucket projects do not import NAS photos; open a PJ-xxxx site project instead.',
        }

    from flask import current_app
    if media_dir is None:
        media_dir = current_app.config.get('WA_UPLOADS_FOLDER', 'uploads/wa-media')

    files = nas_mount.list_folder_files(project['code'])
    created = 0
    skipped = 0
    now = datetime.utcnow()

    for meta in files:
        name = meta['name']
        nas_path = meta.get('absolutePath') or _nas_file_path(
            project['code'],
            name,
            relative_path=meta.get('relativePath'),
        )
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
