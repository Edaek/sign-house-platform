from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from bson import ObjectId
from app import mongo
from app.models import serialize_doc

wa_projects_bp = Blueprint('wa_projects', __name__)

@wa_projects_bp.route('', methods=['GET'])
@jwt_required()
def list_projects():
    status_filter = request.args.get('status')
    query = {'status': {'$ne': 'archived'}}
    if status_filter:
        query['status'] = status_filter
    
    projects = list(mongo.db.wa_projects.find(query).sort('updatedAt', -1))

    from datetime import datetime
    from app.services.nas_sync_service import nas_folder_index, enrich_project_dict

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    nas_index = nas_folder_index(blocking_scan=False)

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
        enrich_project_dict(d, nas_index)
        result.append(d)

    return jsonify(result)

@wa_projects_bp.route('/<project_id>', methods=['GET'])
@jwt_required()
def get_project(project_id):
    project = mongo.db.wa_projects.find_one({'_id': ObjectId(project_id)})
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    from app.services.nas_sync_service import enrich_project_dict
    from app.services.nas_watcher_service import nas_mount
    from app.services.project_number_match_service import is_range_folder_code

    d = serialize_doc(project)
    enrich_project_dict(d, fast_single=True)
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
            d['nasSubfolders'] = nas_mount.list_project_subfolders(code)
            nas_files = d.get('nasFileCount') or 0
            d['nasPendingImport'] = max(0, nas_files - d['nasImportedCount'])
            if request.args.get('includeNasFiles') == '1':
                d['nasFiles'] = nas_mount.list_folder_files(code)
    else:
        d['nasPendingImport'] = 0

    return jsonify(d)

@wa_projects_bp.route('/<project_id>/records', methods=['GET'])
@jwt_required()
def get_project_records(project_id):
    query = {'projectId': ObjectId(project_id)}
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
