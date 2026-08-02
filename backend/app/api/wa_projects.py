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
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    result = []
    for p in projects:
        d = serialize_doc(p)
        d['totalRecords'] = mongo.db.wa_records.count_documents({'projectId': p['_id']})
        d['todayRecords'] = mongo.db.wa_records.count_documents({'projectId': p['_id'], 'createdAt': {'$gte': today}})
        result.append(d)
    
    return jsonify(result)

@wa_projects_bp.route('/<project_id>', methods=['GET'])
@jwt_required()
def get_project(project_id):
    project = mongo.db.wa_projects.find_one({'_id': ObjectId(project_id)})
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    return jsonify(serialize_doc(project))

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
