from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from bson import ObjectId
from app import mongo
from app.models import serialize_doc

wa_projects_bp = Blueprint('wa_projects', __name__)


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


@wa_projects_bp.route('', methods=['GET'])
@jwt_required()
def list_projects():
    status_filter = request.args.get('status')
    query = {'status': {'$ne': 'archived'}}
    if status_filter:
        query['status'] = status_filter
    
    projects = list(mongo.db.wa_projects.find(query).sort('updatedAt', -1))
    parent_buckets = sorted({
        (p.get('nasParentBucket') or '').strip()
        for p in projects
        if (p.get('nasParentBucket') or '').strip()
    })

    from datetime import datetime
    from app.services.nas_sync_service import (
        _build_index_from_folders,
        build_nas_folder_index_from_buckets,
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
        elif nas_mount.is_volume_mounted() and parent_buckets:
            nas_index = build_nas_folder_index_from_buckets(parent_buckets)
        if not nas_index and nas_mount.is_volume_mounted():
            import threading

            threading.Thread(target=nas_mount.refresh_folder_cache, daemon=True).start()

    counts_by_project = {}
    if projects:
        pid_list = [p['_id'] for p in projects]
        pipeline = [
            {'$match': {
                'projectId': {'$in': pid_list},
                'status': {'$ne': 'voided'},
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


@wa_projects_bp.route('/nas-bucket-sites', methods=['GET'])
@jwt_required()
def list_nas_bucket_sites():
    """One row per physical NAS folder under a bucket (includes duplicate PJ-xxxx + long names)."""
    from flask_jwt_extended import get_jwt_identity
    from app.services.nas_sync_service import sync_bucket_site_projects_from_nas
    from app.services.nas_watcher_service import nas_mount
    from app.services.wa_project_validation import find_project_by_code
    bucket = (request.args.get('bucket') or '').strip()
    if not bucket:
        return jsonify({'ok': False, 'error': 'bucket query required'}), 400
    if not nas_mount.is_available():
        return jsonify({'ok': False, 'error': 'NAS not connected', 'sites': []}), 503

    if request.args.get('sync') != '0':
        sync_bucket_site_projects_from_nas(bucket, ObjectId(get_jwt_identity()))

    children = sorted(
        nas_mount._list_bucket_child_folders_sync(bucket),
        key=lambda c: (c.get('folderName') or '').lower(),
    )
    sites = []
    for child in children:
        folder_name = (child.get('folderName') or '').strip()
        code = (child.get('code') or '').strip()
        proj = find_project_by_code(code) if code else None
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
                'totalRecords': mongo.db.wa_records.count_documents({
                    'projectId': proj['_id'],
                    'status': {'$ne': 'voided'},
                }),
                'todayRecords': 0,
                'location': d.get('location'),
                'nasParentBucket': bucket,
            })
        elif code:
            row['nasParentBucket'] = bucket
        sites.append(row)

    site_rows = [s for s in sites if s.get('code')]
    return jsonify({
        'ok': True,
        'bucket': bucket,
        'count': len(sites),
        'siteFolderCount': len(site_rows),
        'sites': sites,
    })


@wa_projects_bp.route('/<project_id>', methods=['GET'])
@jwt_required()
def get_project(project_id):
    project = mongo.db.wa_projects.find_one({'_id': ObjectId(project_id)})
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    from app.services.nas_sync_service import enrich_project_dict, reconcile_project_from_nas
    from app.services.nas_watcher_service import nas_mount

    if nas_mount.is_available():
        outcome = reconcile_project_from_nas(project)
        if outcome.get('projectRemoved'):
            return jsonify({'error': 'Project not found on NAS (removed from app)'}), 404
        project = mongo.db.wa_projects.find_one({'_id': ObjectId(project_id)})
        if not project:
            return jsonify({'error': 'Project not found'}), 404
    from app.services.project_number_match_service import is_range_folder_code

    nas_view = _nas_view_project_doc(project)
    d = serialize_doc(project)
    if (request.args.get('nasFolderName') or '').strip():
        d['nasFolderName'] = request.args.get('nasFolderName').strip()
    if (request.args.get('nasParentBucket') or '').strip():
        d['nasParentBucket'] = request.args.get('nasParentBucket').strip()
    enrich_project_dict(d, fast_single=True, nas_view_doc=nas_view)
    pid = project['_id']
    code = (project.get('code') or '').strip()
    d['totalRecords'] = mongo.db.wa_records.count_documents({
        'projectId': pid,
        'status': {'$ne': 'voided'},
    })
    d['nasImportedCount'] = mongo.db.wa_records.count_documents({
        'projectId': pid,
        'nasSourcePath': {'$exists': True, '$nin': [None, '']},
        'status': {'$ne': 'voided'},
    })
    d['nasRangeBucket'] = is_range_folder_code(code)
    d['nasFiles'] = []
    d['nasTxtFiles'] = []
    d['nasSubfolders'] = []
    d['nasSiteFolders'] = []
    d['nasLooseFiles'] = []

    if nas_mount.is_available():
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
    else:
        d['nasPendingImport'] = 0

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
    return jsonify({'ok': True, 'files': nas_mount.list_project_txt_files(code, project_doc=view)})


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


@wa_projects_bp.route('/<project_id>/records', methods=['GET'])
@jwt_required()
def get_project_records(project_id):
    from app.services.nas_sync_service import reconcile_project_from_nas
    from app.services.nas_watcher_service import nas_mount

    try:
        pid = ObjectId(project_id)
    except Exception:
        return jsonify({'error': 'Invalid project id'}), 400

    project = mongo.db.wa_projects.find_one({'_id': pid, 'status': {'$ne': 'archived'}})
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    if nas_mount.is_available():
        outcome = reconcile_project_from_nas(project)
        if outcome.get('projectRemoved'):
            return jsonify({'error': 'Project not found on NAS (removed from app)'}), 404

    query = {'projectId': pid}
    status = request.args.get('status')
    rec_type = request.args.get('type')
    phone = request.args.get('phone')
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 50))

    if status:
        query['status'] = {'$in': status.split(',')}
    elif request.args.get('includeVoided') != '1':
        query['status'] = {'$ne': 'voided'}
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
