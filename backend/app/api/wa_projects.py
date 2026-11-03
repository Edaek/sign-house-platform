import re
import time
import threading

import mimetypes

from flask import Blueprint, jsonify, request, current_app, send_file
from flask_jwt_extended import jwt_required
from bson import ObjectId
from app import mongo
from app.models import serialize_doc

wa_projects_bp = Blueprint('wa_projects', __name__)

# Moved records are tombstones after relocate; do not count as active site records.
_RECORD_COUNTABLE = {'$nin': ['voided', 'moved']}

_mongo_bucket_rows_cache: dict[str, tuple[float, list]] = {}
_MONGO_BUCKET_ROWS_TTL_S = 45.0


def clear_mongo_bucket_rows_cache() -> None:
    """Drop cached Mongo bucket rows after NAS realign / sync (avoid stale KTEST2 cards)."""
    _mongo_bucket_rows_cache.clear()


def _nas_view_project_doc(project, req=None):
    """Merge query overrides so NAS I/O targets the physical folder the user opened."""
    doc = dict(project)
    src = req or request
    fn = (src.args.get('nasFolderName') or '').strip()
    pb = (src.args.get('nasParentBucket') or '').strip()
    if fn:
        doc['nasFolderName'] = fn
    if pb:
        doc['nasParentBucket'] = pb
    return doc


def _mongo_bucket_child_rows(bucket: str) -> list:
    """App projects belonging to a range bucket (fast Mongo — no SMB)."""
    key = (bucket or '').strip().lower()
    if key:
        cached = _mongo_bucket_rows_cache.get(key)
        if cached and (time.time() - cached[0]) <= _MONGO_BUCKET_ROWS_TTL_S:
            return list(cached[1])

    rows = _mongo_bucket_child_rows_compute(bucket)
    if key:
        _mongo_bucket_rows_cache[key] = (time.time(), rows)
    return rows


def _mongo_bucket_child_rows_compute(bucket: str) -> list:
    from app.services.project_number_match_service import (
        bucket_contains_site_number,
        is_range_folder_code,
        parse_nas_site_folder_code,
        parse_range_bucket,
    )

    bucket = (bucket or '').strip()
    if not bucket:
        return []
    out = []
    seen: set[str] = set()

    def _append(proj):
        code = (proj.get('code') or '').strip()
        if not code or is_range_folder_code(code):
            return
        folder_name = (proj.get('nasFolderName') or code).strip()
        if not folder_name:
            return
        key = folder_name.lower()
        if key in seen:
            return
        seen.add(key)
        parsed = parse_nas_site_folder_code(folder_name) or code
        out.append({
            'folderName': folder_name,
            'code': parsed,
            'isSiteProject': True,
        })

    from app.services.nas_bucket_code import nas_parent_bucket_match_values

    parent_or = [
        {'nasParentBucket': {'$regex': f'^{re.escape(v)}$', '$options': 'i'}}
        for v in nas_parent_bucket_match_values(bucket)
    ]
    if not parent_or:
        return []
    for proj in mongo.db.wa_projects.find({
        'status': {'$ne': 'archived'},
        '$or': parent_or,
    }):
        _append(proj)

    bounds = parse_range_bucket(bucket)
    if bounds:
        lo, hi = bounds
        cursor = mongo.db.wa_projects.find({
            'status': {'$ne': 'archived'},
            'code': {'$regex': r'^PJ-\d', '$options': 'i'},
        })
        for proj in cursor:
            code = (proj.get('code') or '').strip()
            if not code or is_range_folder_code(code):
                continue
            parent = (proj.get('nasParentBucket') or '').strip()
            if parent and parent.upper() == bucket.upper():
                continue
            folder_name = (proj.get('nasFolderName') or code).strip()
            site_code = parse_nas_site_folder_code(folder_name) or parse_nas_site_folder_code(code)
            if not site_code:
                continue
            try:
                site_n = int(re.search(r'(\d+)', site_code).group(1))
            except (AttributeError, ValueError):
                continue
            if lo <= site_n <= hi and bucket_contains_site_number(bucket, site_n):
                _append(proj)

    return out


def _bucket_child_lookup_code(child: dict) -> str | None:
    """Project code used to match Mongo for a NAS bucket child row."""
    from app.services.wa_project_bucket_rules import is_reserved_nas_folder_name

    folder_name = (child.get('folderName') or '').strip()
    if is_reserved_nas_folder_name(folder_name):
        return None
    code = (child.get('code') or '').strip() or folder_name
    if is_reserved_nas_folder_name(code):
        return None
    return code or None


def _merge_bucket_children(
    nas_children: list,
    extra: list,
    *,
    supplement_mongo_only: bool = True,
) -> list:
    """Merge NAS folder rows with Mongo; optional Mongo-only rows when NAS list is authoritative."""
    by_key: dict[str, dict] = {}
    for row in nas_children or []:
        fn = (row.get('folderName') or '').strip()
        if fn:
            by_key[fn.lower()] = row
    if supplement_mongo_only:
        for row in extra or []:
            fn = (row.get('folderName') or '').strip()
            if fn and fn.lower() not in by_key:
                by_key[fn.lower()] = row
    return list(by_key.values())


def _build_nas_bucket_sites_payload(bucket: str, children: list, *, from_cache: bool) -> dict:
    from app.services.nas_bucket_code import nas_path_from_web_bucket, nas_parent_bucket_match_values
    from app.services.nas_watcher_service import nas_mount

    parent_bucket = nas_path_from_web_bucket(bucket)
    parent_match_values = {v.upper() for v in nas_parent_bucket_match_values(bucket)}
    children = sorted(children, key=lambda c: (c.get('folderName') or '').lower())
    unique_codes = list({
        lc
        for c in children
        if (lc := _bucket_child_lookup_code(c))
    })
    proj_by_code_upper = {}
    proj_by_code_and_parent: dict[tuple[str, str], dict] = {}
    parent_bucket_upper = (parent_bucket or '').upper()
    if unique_codes:
        or_codes = [
            {'code': {'$regex': f'^{re.escape(code)}$', '$options': 'i'}}
            for code in unique_codes
        ]
        for proj in mongo.db.wa_projects.find({
            'status': {'$ne': 'archived'},
            '$or': or_codes,
        }):
            key = (proj.get('code') or '').strip().upper()
            if not key:
                continue
            proj_by_code_upper[key] = proj
            from app.services.nas_bucket_code import nas_path_from_web_bucket as _np

            parent_key = _np(proj.get('nasParentBucket') or '').upper()
            proj_by_code_and_parent[(key, parent_key)] = proj
            for pv in parent_match_values:
                proj_by_code_and_parent[(key, _np(pv).upper())] = proj
            if parent_bucket_upper:
                proj_by_code_and_parent[(key, parent_bucket_upper)] = proj

    record_counts = {}
    matched_projects = list({id(p): p for p in proj_by_code_upper.values()}.values())
    if matched_projects:
        pid_list = [p['_id'] for p in matched_projects]
        for row in mongo.db.wa_records.aggregate([
            {'$match': {
                'projectId': {'$in': pid_list},
                'status': _RECORD_COUNTABLE,
            }},
            {'$group': {'_id': '$projectId', 'totalRecords': {'$sum': 1}}},
        ]):
            record_counts[row['_id']] = row['totalRecords']

    sites = []
    for child in children:
        folder_name = (child.get('folderName') or '').strip()
        code = _bucket_child_lookup_code(child)
        if not code:
            continue
        proj = None
        if code:
            code_upper = code.upper()
            proj = proj_by_code_and_parent.get((code_upper, parent_bucket_upper))
            if proj is None and not parent_bucket_upper:
                proj = proj_by_code_upper.get(code_upper)
        row = {
            'folderName': folder_name,
            'code': code or None,
            'isSiteProject': bool(child.get('isSiteProject')),
            'projectId': None,
            'nasFolderName': folder_name,
            'status': 'active',
            'totalRecords': 0,
        }
        if proj:
            d = serialize_doc(proj)
            d['nasFolderName'] = folder_name or d.get('nasFolderName') or d.get('code')
            row.update({
                'projectId': d['id'],
                'code': d.get('code') or code,
                'status': d.get('status', 'active'),
                'totalRecords': record_counts.get(proj['_id'], 0),
                'todayRecords': 0,
                'location': d.get('location'),
                'nasParentBucket': parent_bucket,
            })
        elif code:
            row['nasParentBucket'] = parent_bucket
        elif folder_name:
            row['code'] = folder_name
            row['nasParentBucket'] = parent_bucket
        sites.append(row)

    site_rows = [s for s in sites if s.get('code')]
    payload = {
        'ok': True,
        'bucket': bucket,
        'count': len(sites),
        'siteFolderCount': len(site_rows),
        'sites': sites,
    }
    if from_cache:
        payload['staleFromCache'] = True
        if not sites:
            payload['hint'] = 'Showing cached folder list; refreshing from shared drive.'
    elif not sites and nas_mount.is_volume_mounted():
        payload['hint'] = 'Could not list bucket folders (timeout or empty cache); refresh running in background.'
    return payload


@wa_projects_bp.route('', methods=['GET'])
@jwt_required()
def list_projects():
    status_filter = request.args.get('status')
    query = {'status': {'$ne': 'archived'}}
    if status_filter:
        query['status'] = status_filter
    
    projects = list(mongo.db.wa_projects.find(query).sort('updatedAt', -1))

    from datetime import datetime
    from app.services.nas_sync_service import (
        _build_index_from_folders,
        enrich_project_dict,
        nas_folder_index,
    )
    from app.services.nas_watcher_service import nas_mount

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    nas_index = nas_folder_index(blocking_scan=False)
    if not nas_index:
        cached = nas_mount.get_cached_folders() or nas_mount.peek_folder_cache()
        if cached:
            nas_index = _build_index_from_folders(cached)
        if not nas_index and nas_mount.is_volume_mounted():
            import threading

            threading.Thread(target=nas_mount.refresh_folder_cache, daemon=True).start()

    counts_by_project = {}
    if projects:
        pid_list = [p['_id'] for p in projects]
        pipeline = [
            {'$match': {
                'projectId': {'$in': pid_list},
                'status': _RECORD_COUNTABLE,
            }},
            {'$group': {
                '_id': '$projectId',
                'totalRecords': {'$sum': 1},
                'todayRecords': {
                    '$sum': {
                        '$cond': [{'$gte': ['$createdAt', today]}, 1, 0],
                    },
                },
            }},
        ]
        for row in mongo.db.wa_records.aggregate(pipeline):
            counts_by_project[row['_id']] = row

    result = []
    for p in projects:
        d = serialize_doc(p)
        stats = counts_by_project.get(p['_id'], {})
        d['totalRecords'] = stats.get('totalRecords', 0)
        d['todayRecords'] = stats.get('todayRecords', 0)
        enrich_project_dict(d, nas_index, for_list=True)
        result.append(d)

    return jsonify(result)


def _schedule_bucket_nas_refresh(bucket: str) -> None:
    """Refresh one bucket's NAS child-folder cache off the HTTP thread."""
    app = current_app._get_current_object()

    def _run():
        with app.app_context():
            from app.services.nas_watcher_service import nas_mount

            if nas_mount.is_volume_mounted():
                nas_mount.refresh_bucket_children_cache_for(bucket)

    threading.Thread(target=_run, daemon=True).start()


@wa_projects_bp.route('/nas-root-buckets', methods=['GET'])
@jwt_required()
def list_nas_root_buckets():
    """Top-level NAS folders (PJ-lo-hi, LIGHT, …) for merging into Projects bucket grid."""
    from app.services.nas_sync_service import list_nas_root_bucket_summaries
    from app.services.nas_watcher_service import nas_mount

    if not nas_mount.is_volume_mounted():
        return jsonify({'ok': False, 'error': 'NAS not connected', 'buckets': []}), 503
    buckets = list_nas_root_bucket_summaries()
    return jsonify({'ok': True, 'buckets': buckets})


@wa_projects_bp.route('/nas-bucket-sites', methods=['GET'])
@jwt_required()
def list_nas_bucket_sites():
    """One row per physical NAS folder under a bucket (includes duplicate PJ-xxxx + long names)."""
    from flask_jwt_extended import get_jwt_identity
    from app.services.nas_sync_service import sync_bucket_site_projects_from_nas
    from app.services.nas_watcher_service import nas_mount
    bucket = (request.args.get('bucket') or '').strip()
    if not bucket:
        return jsonify({'ok': False, 'error': 'bucket query required'}), 400

    mounted = nas_mount.is_volume_mounted()
    live_scan = request.args.get('liveScan') == '1'
    cache_only = request.args.get('cacheOnly') == '1'

    mongo_rows = _mongo_bucket_child_rows(bucket)
    cached = nas_mount.bucket_child_folders_from_cache(bucket)

    if not mounted and not cached and not mongo_rows:
        return jsonify({'ok': False, 'error': 'NAS not connected', 'sites': []}), 503

    from_cache = True
    children = _merge_bucket_children(cached, mongo_rows)

    if live_scan and mounted and nas_mount.probe_responsive(timeout_s=2):
        if request.args.get('sync') != '0':
            sync_bucket_site_projects_from_nas(bucket, ObjectId(get_jwt_identity()))
        live = nas_mount._list_bucket_child_folders_sync(bucket)
        children = _merge_bucket_children(live, mongo_rows, supplement_mongo_only=False)
        from_cache = False
    elif mounted and not cache_only:
        _schedule_bucket_nas_refresh(bucket)

    payload = _build_nas_bucket_sites_payload(bucket, children, from_cache=from_cache)
    if from_cache and mounted and not cache_only:
        payload['backgroundNasScan'] = True
    return jsonify(payload)


@wa_projects_bp.route('/<project_id>', methods=['GET'])
@jwt_required()
def get_project(project_id):
    project = mongo.db.wa_projects.find_one({'_id': ObjectId(project_id)})
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    from app.services.nas_sync_service import enrich_project_dict, nas_folder_index, _build_index_from_folders
    from app.services.nas_watcher_service import nas_mount
    from app.services.project_number_match_service import is_range_folder_code

    include_nas = request.args.get('includeNas') == '1'
    minimal = request.args.get('minimal') == '1'
    nas_view = _nas_view_project_doc(project)
    d = serialize_doc(project)
    if (request.args.get('nasFolderName') or '').strip():
        d['nasFolderName'] = request.args.get('nasFolderName').strip()
    if (request.args.get('nasParentBucket') or '').strip():
        d['nasParentBucket'] = request.args.get('nasParentBucket').strip()

    pid = project['_id']
    code = (project.get('code') or '').strip()

    if minimal:
        d['totalRecords'] = mongo.db.wa_records.count_documents({
            'projectId': pid,
            'status': _RECORD_COUNTABLE,
        })
        d['nasImportedCount'] = 0
    else:
        nas_index = nas_folder_index(blocking_scan=False)
        if not nas_index:
            cached = nas_mount.get_cached_folders() or nas_mount.peek_folder_cache()
            if cached:
                nas_index = _build_index_from_folders(cached)
        enrich_project_dict(d, nas_index or {}, for_list=True)
        d['totalRecords'] = mongo.db.wa_records.count_documents({
            'projectId': pid,
            'status': _RECORD_COUNTABLE,
        })
        d['nasImportedCount'] = mongo.db.wa_records.count_documents({
            'projectId': pid,
            'nasSourcePath': {'$exists': True, '$nin': [None, '']},
            'status': _RECORD_COUNTABLE,
        })
    d['nasRangeBucket'] = is_range_folder_code(code)
    d['nasFiles'] = []
    d['nasTxtFiles'] = []
    d['nasSubfolders'] = []
    d['nasSiteFolders'] = []
    d['nasLooseFiles'] = []
    d['nasPendingImport'] = max(0, (d.get('nasFileCount') or 0) - d['nasImportedCount'])

    if not include_nas:
        return jsonify(d)

    nas_responsive = nas_mount.is_volume_mounted() and nas_mount.probe_responsive(timeout_s=3)
    if not nas_mount.is_available() or not nas_responsive:
        if nas_mount.is_volume_mounted() and not nas_responsive:
            d['nasMountHint'] = (
                'NAS 响应较慢，本次未列出子目录/txt；WA 记录与 Mongo 数据仍可用。'
                '可稍后刷新或 remount 共享盘后再看 NAS 文件。'
            )
        return jsonify(d)

    enrich_project_dict(d, fast_single=True, nas_view_doc=nas_view)
    if d['nasRangeBucket']:
        d['nasChildFolders'] = nas_mount.list_bucket_child_folders(code)
        d['nasSiteFolders'] = [
            {'code': c['code'], 'folderName': c['folderName']}
            for c in d['nasChildFolders']
            if c.get('code')
        ]
        d['nasLooseFiles'] = nas_mount.list_loose_root_files(code)
        d['nasSiteFolderCount'] = len(d['nasSiteFolders'])
        d['nasPendingImport'] = 0
        d['nasFileCount'] = 0
    else:
        resolved = nas_mount._folder_for_project(code, nas_view)
        if resolved is not None:
            d['nasResolvedFolderName'] = resolved.name
        if not (request.args.get('nasFolderName') or '').strip():
            from app.services.nas_sync_service import list_physical_site_folders

            physical = list_physical_site_folders(code)
            if len(physical) > 1:
                d['nasPhysicalFolders'] = [
                    {
                        'folderName': r['folderName'],
                        'nasParentBucket': r.get('parentBucket') or d.get('nasParentBucket'),
                    }
                    for r in physical
                ]
        d['nasSubfolders'] = nas_mount.list_project_subfolders(code, project_doc=nas_view)
        nas_files = d.get('nasFileCount') or 0
        d['nasPendingImport'] = max(0, nas_files - d['nasImportedCount'])
        if request.args.get('includeNasTxt') == '1':
            d['nasTxtFiles'] = nas_mount.list_project_txt_files(code, project_doc=nas_view)
        elif request.args.get('includeNasFiles') == '1':
            d['nasFiles'] = nas_mount.list_folder_files(code, project_doc=nas_view)

    return jsonify(d)


def _wa_project_or_404(project_id):
    try:
        oid = ObjectId(project_id)
    except Exception:
        return None
    return mongo.db.wa_projects.find_one({'_id': oid, 'status': {'$ne': 'archived'}})


@wa_projects_bp.route('/<project_id>/nas/txt', methods=['GET'])
@jwt_required()
def list_project_nas_txt(project_id):
    project = _wa_project_or_404(project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    from app.services.nas_watcher_service import nas_mount

    if not nas_mount.is_available():
        return jsonify({'ok': False, 'error': 'NAS not connected', 'files': []}), 503
    code = (project.get('code') or '').strip()
    view = _nas_view_project_doc(project)
    nas_slow = not nas_mount.probe_responsive(timeout_s=2)
    files = nas_mount.list_project_txt_files(code, project_doc=view)
    hint = (
        'NAS is slow — remark file listing may be incomplete.'
        if nas_slow and not files
        else None
    )
    return jsonify({'ok': True, 'files': files, 'hint': hint})


@wa_projects_bp.route('/<project_id>/nas/txt/content', methods=['GET', 'PUT'])
@jwt_required()
def project_nas_txt_content(project_id):
    project = _wa_project_or_404(project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    from app.services.nas_watcher_service import nas_mount

    if not nas_mount.is_available():
        return jsonify({'ok': False, 'error': 'NAS not connected'}), 503
    code = (project.get('code') or '').strip()
    rel = (request.args.get('path') or '').strip()

    if request.method == 'GET':
        if not rel:
            return jsonify({'ok': False, 'error': 'path is required'}), 400
        view = _nas_view_project_doc(project)
        result = nas_mount.read_project_txt_file(code, rel, project_doc=view)
        if not result.get('ok'):
            status = 404 if result.get('missing') else 400
            return jsonify(result), status
        return jsonify(result)

    data = request.get_json(silent=True) or {}
    rel = (data.get('path') or rel or '').strip()
    if not rel:
        return jsonify({'ok': False, 'error': 'path is required'}), 400
    view = _nas_view_project_doc(project)
    result = nas_mount.write_project_txt_file(
        code, rel, data.get('content', ''), project_doc=view,
    )
    if not result.get('ok'):
        return jsonify(result), 400
    return jsonify(result)


@wa_projects_bp.route('/<project_id>/nas/media', methods=['GET'])
def project_nas_media(project_id):
    """Serve NAS image bytes for project detail previews (same-origin img tags; path-validated)."""
    project = _wa_project_or_404(project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    from app.services.nas_watcher_service import nas_mount

    if not nas_mount.is_available():
        return jsonify({'error': 'NAS not connected'}), 503
    rel = (request.args.get('path') or '').strip()
    if not rel:
        return jsonify({'error': 'path is required'}), 400
    view = _nas_view_project_doc(project)
    code = (project.get('code') or '').strip()
    _root, target = nas_mount._resolve_project_image_path(code, rel, project_doc=view)
    if target is None:
        return jsonify({'error': 'Invalid path'}), 400
    if not target.is_file():
        return jsonify({'error': 'File not found'}), 404
    mime, _ = mimetypes.guess_type(str(target))
    return send_file(target, mimetype=mime or 'application/octet-stream', conditional=True)


@wa_projects_bp.route('/<project_id>/records', methods=['GET'])
@jwt_required()
def get_project_records(project_id):
    try:
        pid = ObjectId(project_id)
    except Exception:
        return jsonify({'error': 'Invalid project id'}), 400

    project = mongo.db.wa_projects.find_one({'_id': pid, 'status': {'$ne': 'archived'}})
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    query = {'projectId': pid}
    status = request.args.get('status')
    rec_type = request.args.get('type')
    phone = request.args.get('phone')
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 50))

    if status:
        query['status'] = {'$in': status.split(',')}
    elif request.args.get('includeVoided') != '1':
        if request.args.get('includeMoved') == '1':
            query['status'] = {'$ne': 'voided'}
        else:
            query['status'] = {'$nin': ['voided', 'moved']}
    if rec_type:
        query['type'] = rec_type
    if phone:
        query['senderPhone'] = {'$regex': phone, '$options': 'i'}

    total = mongo.db.wa_records.count_documents(query)
    skip = (page - 1) * limit
    records = list(mongo.db.wa_records.find(query).sort('createdAt', -1).skip(skip).limit(limit))
    from app.services.image_pool_service import resolve_record_remark

    out = []
    for r in records:
        d = serialize_doc(r)
        d['remark'] = resolve_record_remark(r)
        out.append(d)
    return jsonify({
        'records': out,
        'pagination': {
            'page': page,
            'limit': limit,
            'total': total,
            'pages': (total + limit - 1) // limit if limit else 1,
        },
    })
