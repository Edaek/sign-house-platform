from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
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
            proj = mongo.db.wa_projects.find_one({'_id': t['projectId']}, {'code': 1, 'nasFolder': 1})
            if proj:
                t['projectId'] = {'code': proj['code'], 'nasFolder': proj.get('nasFolder')}
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
    from app.services.wa_project_validation import normalize_code, assert_code_available

    code = normalize_code(data.get('code'))
    if not code:
        return jsonify({'error': 'Project code is required'}), 400

    code_err = assert_code_available(code)
    if code_err:
        return jsonify({'error': code_err}), 409

    now = datetime.utcnow()
    doc = {
        'code': code,
        'location': data.get('location', ''),
        'owner': ObjectId(get_jwt_identity()),
        'stage': data.get('stage', 'active'),
        'status': 'active',
        'members': [ObjectId(get_jwt_identity())],
        'createdAt': now,
        'updatedAt': now,
    }
    try:
        insert = mongo.db.wa_projects.insert_one(doc)
    except DuplicateKeyError as exc:
        detail = getattr(exc, 'details', {}) or {}
        key = detail.get('keyPattern') or {}
        if 'code' in key:
            return jsonify({'error': f'Project code {code} already exists'}), 409
        return jsonify({'error': 'Project code already exists'}), 409
    doc['_id'] = insert.inserted_id

    from app.services.nas_watcher_service import nas_mount
    from app.services.project_number_match_service import is_range_folder_code

    parent_bucket = (data.get('parentBucketCode') or data.get('nasParentFolder') or '').strip() or None
    if not is_range_folder_code(code):
        if not nas_mount.is_available():
            mongo.db.wa_projects.delete_one({'_id': insert.inserted_id})
            return jsonify({
                'error': 'NAS is not connected — mount the share before creating a project folder.',
            }), 503
        nas_result = nas_mount.create_folder(code, parent_bucket_code=parent_bucket)
        if not nas_result.get('ok'):
            mongo.db.wa_projects.delete_one({'_id': insert.inserted_id})
            return jsonify({
                'error': nas_result.get('error') or 'Failed to create NAS folder',
            }), 503
        nas_fields = {'nasFolder': nas_result['path']}
        if parent_bucket:
            nas_fields['nasParentBucket'] = parent_bucket
        mongo.db.wa_projects.update_one({'_id': insert.inserted_id}, {'$set': nas_fields})
        doc['nasFolder'] = nas_result['path']
        if parent_bucket:
            doc['nasParentBucket'] = parent_bucket

    return jsonify(serialize_doc(doc)), 201


@wa_admin_bp.route('/projects/<project_id>', methods=['PATCH'])
@jwt_required()
@require_role('admin', 'manager')
def update_project(project_id):
    project = mongo.db.wa_projects.find_one({'_id': ObjectId(project_id)})
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    data = request.get_json() or {}
    sync_nas = data.get('syncNas', True)
    if isinstance(sync_nas, str):
        sync_nas = sync_nas.lower() not in ('0', 'false', 'no')

    from app.services.nas_sync_service import update_web_project, enrich_project_dict

    result = update_web_project(project, data, sync_nas=bool(sync_nas))
    if not result.get('ok'):
        err = result.get('error') or 'Update failed'
        status = 409 if 'already exists' in err.lower() else 503 if 'NAS' in err else 400
        return jsonify({'error': err}), status

    doc = serialize_doc(result['project'])
    enrich_project_dict(doc, fast_single=True)
    return jsonify(doc)


@wa_admin_bp.route('/projects/<project_id>', methods=['DELETE'])
@jwt_required()
@require_role('admin')
def delete_project(project_id):
    import shutil
    project = mongo.db.wa_projects.find_one({'_id': ObjectId(project_id)})
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    data = request.get_json(silent=True) or {}
    from app.services.nas_sync_service import delete_web_project
    from app.services.nas_watcher_service import nas_mount

    delete_nas_folder = bool(data.get('deleteNasFolder', False))

    result = delete_web_project(project, remove_nas_folder=bool(delete_nas_folder))
    if not result.get('ok'):
        err = result.get('error') or 'Delete failed'
        status = 503 if 'NAS' in err else 400
        return jsonify({'error': err, 'nasResult': result.get('nasResult')}), status

    nas_result = result.get('nasResult') or {}
    body = {'message': 'Project deleted', 'code': result.get('code') or project['code']}
    if nas_result.get('quarantined'):
        body['nasQuarantined'] = True
        body['message'] = (
            'Project deleted. NAS folder was quarantined (SMB locked files); '
            'remove the .trash-* folder in File Station if needed.'
        )
    return jsonify(body)


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
    
    ollama_url = current_app.config.get('OLLAMA_BASE_URL', 'http://localhost:11434')
    ollama_text_model = current_app.config.get('OLLAMA_TEXT_MODEL', 'gemma3:4b')
    ollama_vision_model = current_app.config.get('OLLAMA_VISION_MODEL', 'llava:latest')
    ollama_error = None
    try:
        r = req.get(f'{ollama_url.rstrip("/")}/api/tags', timeout=10)
        ollama_status = 'ok' if r.ok else 'error'
        if not r.ok:
            ollama_error = f'HTTP {r.status_code}'
    except Exception as exc:
        ollama_status = 'error'
        ollama_error = str(exc)[:200]

    return jsonify({
        'mongo': mongo_status,
        'ollama': ollama_status,
        'ollamaBaseUrl': ollama_url,
        'ollamaTextModel': ollama_text_model,
        'ollamaVisionModel': ollama_vision_model,
        'ollamaError': ollama_error,
    })
