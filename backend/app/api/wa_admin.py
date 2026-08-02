from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from bson import ObjectId
from datetime import datetime
from app import mongo
from app.models import serialize_doc
from app.utils.permissions import require_role

wa_admin_bp = Blueprint('wa_admin', __name__)

# Keywords
@wa_admin_bp.route('/keywords', methods=['GET'])
@jwt_required()
@require_role('admin', 'manager')
def list_keywords():
    keywords = list(mongo.db.wa_keywords.find().sort('term', 1))
    return jsonify([serialize_doc(k) for k in keywords])

@wa_admin_bp.route('/keywords', methods=['POST'])
@jwt_required()
@require_role('admin')
def create_keyword():
    data = request.get_json()
    now = datetime.utcnow()
    doc = {
        'term': data['term'].lower().strip(),
        'type': data['type'],
        'synonyms': [s.lower().strip() for s in data.get('synonyms', [])],
        'isActive': True,
        'createdAt': now,
        'updatedAt': now,
    }
    mongo.db.wa_keywords.insert_one(doc)
    return jsonify(serialize_doc(doc)), 201

@wa_admin_bp.route('/keywords', methods=['DELETE'])
@jwt_required()
@require_role('admin')
def delete_keyword():
    kw_id = request.args.get('id')
    if not kw_id:
        return jsonify({'error': 'id required'}), 400
    mongo.db.wa_keywords.delete_one({'_id': ObjectId(kw_id)})
    return jsonify({'message': 'Deleted'})

# Templates
@wa_admin_bp.route('/templates', methods=['GET'])
@jwt_required()
@require_role('admin')
def list_templates():
    templates = list(mongo.db.wa_templates.find().sort('typeName', 1))
    for t in templates:
        if t.get('projectId'):
            proj = mongo.db.wa_projects.find_one({'_id': t['projectId']}, {'code': 1, 'name': 1})
            if proj:
                t['projectId'] = {'code': proj['code'], 'name': proj['name']}
    return jsonify([serialize_doc(t) for t in templates])

@wa_admin_bp.route('/templates', methods=['POST'])
@jwt_required()
@require_role('admin')
def create_template():
    data = request.get_json()
    now = datetime.utcnow()
    doc = {
        'typeName': data['typeName'],
        'fields': data.get('fields', []),
        'isActive': True,
        'createdAt': now,
        'updatedAt': now,
    }
    mongo.db.wa_templates.insert_one(doc)
    return jsonify(serialize_doc(doc)), 201

# Projects (admin create)
@wa_admin_bp.route('/projects', methods=['POST'])
@jwt_required()
@require_role('admin', 'manager')
def create_project():
    from flask_jwt_extended import get_jwt_identity
    data = request.get_json()
    code = data.get('code', '').upper().strip()
    
    existing = mongo.db.wa_projects.find_one({'code': code})
    if existing:
        return jsonify({'error': f'Project code {code} already exists'}), 409
    
    now = datetime.utcnow()
    doc = {
        'code': code,
        'name': data['name'],
        'location': data.get('location', ''),
        'owner': ObjectId(get_jwt_identity()),
        'stage': data.get('stage', 'active'),
        'status': 'active',
        'members': [ObjectId(get_jwt_identity())],
        'createdAt': now,
        'updatedAt': now,
    }
    mongo.db.wa_projects.insert_one(doc)
    return jsonify(serialize_doc(doc)), 201

# System status
@wa_admin_bp.route('/system/status', methods=['GET'])
@jwt_required()
@require_role('admin')
def system_status():
    from app.services.wa_send_service import get_gateway_status
    return jsonify(get_gateway_status())

@wa_admin_bp.route('/system/infra', methods=['GET'])
@jwt_required()
@require_role('admin')
def system_infra():
    import requests as req
    from flask import current_app
    
    try:
        mongo.db.command('ping')
        mongo_status = 'ok'
    except Exception:
        mongo_status = 'error'
    
    try:
        ollama_url = current_app.config.get('OLLAMA_BASE_URL', 'http://localhost:11434')
        r = req.get(f'{ollama_url}/api/tags', timeout=3)
        ollama_status = 'ok' if r.ok else 'error'
    except Exception:
        ollama_status = 'error'
    
    return jsonify({'mongo': mongo_status, 'ollama': ollama_status})
