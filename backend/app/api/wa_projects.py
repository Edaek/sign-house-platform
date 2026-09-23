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
    nas_index = nas_folder_index()
    result = []
    for p in projects:
        d = serialize_doc(p)
        d['totalRecords'] = mongo.db.wa_records.count_documents({
            'projectId': p['_id'],
            'status': {'$ne': 'voided'},
        })
        d['todayRecords'] = mongo.db.wa_records.count_documents({'projectId': p['_id'], 'createdAt': {'$gte': today}})
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

    d = serialize_doc(project)
    enrich_project_dict(d, fast_single=True)
    pid = project['_id']
    d['totalRecords'] = mongo.db.wa_records.count_documents({
        'projectId': pid,
        'status': {'$ne': 'voided'},
    })
    d['nasImportedCount'] = mongo.db.wa_records.count_documents({
        'projectId': pid,
        'nasSourcePath': {'$exists': True, '$nin': [None, '']},
        'status': {'$ne': 'voided'},
    })
    nas_files = d.get('nasFileCount') or 0
    d['nasPendingImport'] = max(0, nas_files - d['nasImportedCount']) if nas_mount.is_available() else 0
    # NAS file listing over SMB can be slow — only when explicitly requested
    if request.args.get('includeNasFiles') == '1' and nas_mount.is_available():
        d['nasFiles'] = nas_mount.list_folder_files(project['code'])
    else:
        d['nasFiles'] = []
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
    return jsonify({
        'records': [serialize_doc(r) for r in records],
        'pagination': {
            'page': page,
            'limit': limit,
            'total': total,
            'pages': (total + limit - 1) // limit if limit else 1,
        },
    })
