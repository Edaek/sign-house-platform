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
    from app.services.wa_project_validation import (
        normalize_code,
        normalize_name,
        assert_code_available,
        assert_name_available,
    )

    from app.services.nas_bucket_code import nas_path_from_web_bucket

    parent_raw = (
        data.get('parentBucketCode')
        or data.get('nasParentBucket')
        or data.get('nasParentFolder')
        or ''
    ).strip()
    parent_bucket = nas_path_from_web_bucket(parent_raw) if parent_raw else None

    code = normalize_code(data.get('code'))
    name = normalize_name(data.get('name') or data.get('code'))
    if not code:
        return jsonify({'error': 'Project code is required'}), 400
    if not name:
        return jsonify({'error': 'Project name is required'}), 400

    code_err = assert_code_available(code, parent_bucket=parent_bucket)
    if code_err:
        return jsonify({'error': code_err}), 409

    name_err = assert_name_available(name, parent_bucket=parent_bucket)
    if name_err:
        return jsonify({'error': name_err}), 409
    nas_folder_name = (data.get('nasFolderName') or name or code).strip()

    now = datetime.utcnow()
    doc = {
        'code': code,
        'name': name,
        'nameNormalized': name.casefold(),
        'location': data.get('location', ''),
        'owner': ObjectId(get_jwt_identity()),
        'stage': data.get('stage', 'active'),
        'status': 'active',
        'members': [ObjectId(get_jwt_identity())],
        'createdAt': now,
        'updatedAt': now,
    }
    if parent_bucket:
        doc['nasParentBucket'] = parent_bucket
    if nas_folder_name:
        doc['nasFolderName'] = nas_folder_name
    try:
        insert = mongo.db.wa_projects.insert_one(doc)
    except DuplicateKeyError as exc:
        detail = getattr(exc, 'details', {}) or {}
        key = detail.get('keyPattern') or {}
        if 'code' in key:
            return jsonify({'error': f'Project code {code} already exists'}), 409
        if 'nameNormalized' in key:
            return jsonify({'error': f'Project name "{name}" already exists'}), 409
        return jsonify({'error': 'Project code or name already exists'}), 409
    doc['_id'] = insert.inserted_id

    from app.services.nas_watcher_service import nas_mount
    if nas_mount.is_available():
        nas_result = nas_mount.create_folder(
            code,
            parent_bucket_code=parent_bucket,
            skip_deep_resolve=True,
        )
        if nas_result.get('ok'):
            mongo.db.wa_projects.update_one(
                {'_id': insert.inserted_id},
                {'$set': {
                    'nasFolder': nas_result['path'],
                    'nasImportedAt': now,
                }},
            )
            doc['nasFolder'] = nas_result['path']
            doc['nasImportedAt'] = now

    return jsonify(serialize_doc(doc)), 201


@wa_admin_bp.route('/projects/<project_id>', methods=['PATCH'])
@jwt_required()
@require_role('admin', 'manager')
def patch_project(project_id):
    from app.services.nas_sync_service import update_web_project

    try:
        oid = ObjectId(project_id)
    except Exception:
        return jsonify({'error': 'Invalid project id'}), 400
    project = mongo.db.wa_projects.find_one({'_id': oid, 'status': {'$ne': 'archived'}})
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    data = request.get_json(silent=True) or {}
    sync_nas = bool(data.get('syncNas'))
    result = update_web_project(project, data, sync_nas=sync_nas)
    if not result.get('ok'):
        return jsonify({'error': result.get('error') or 'Update failed'}), 400
    updated = result.get('project') or project
    body = serialize_doc(updated)
    for key in (
        'remarkTxtMergeOk',
        'remarkTxtMergedDays',
        'remarkTxtMerged',
        'remarkTxtMergeMessage',
        'remarkTxtMergeError',
        'remarkTxtExtraFilesRemoved',
    ):
        if key in result:
            body[key] = result[key]
    return jsonify(body)


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

    delete_nas_folder = data.get('deleteNasFolder')
    if delete_nas_folder is None:
        delete_nas_folder = nas_mount.is_available()

    delete_web_project(project, remove_nas_folder=bool(delete_nas_folder))

    return jsonify({'message': 'Project deleted', 'code': project['code']})


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
