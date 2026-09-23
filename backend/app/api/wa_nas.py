from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId

from app.services.nas_watcher_service import nas_mount
from app.services.nas_sync_service import (
    sync_projects_from_nas,
    import_nas_files_for_project,
    import_all_projects_from_nas,
    run_bidirectional_nas_sync,
    get_last_nas_sync_status,
)
from app.utils.permissions import require_role

wa_nas_bp = Blueprint('wa_nas', __name__)


@wa_nas_bp.route('/status', methods=['GET'])
@jwt_required()
def nas_status():
    data = nas_mount.status()
    last = get_last_nas_sync_status()
    if last.get('at'):
        data['lastAutoSyncAt'] = last.get('at')
        data['lastProjectsCreated'] = last.get('projectsCreated', [])
        data['lastRecordsImported'] = last.get('recordsImported', 0)
        data['lastRecordsRemoved'] = last.get('recordsRemoved', 0)
        data['lastProjectsRemoved'] = last.get('projectsRemoved', [])
    from flask import current_app
    data['autoSyncIntervalSec'] = current_app.config.get('NAS_SYNC_INTERVAL_S', 60)
    return jsonify(data)


@wa_nas_bp.route('/sync-bidirectional', methods=['POST'])
@jwt_required()
@require_role('admin', 'manager')
def sync_bidirectional():
    """NAS → web: new shared-drive folders and photos appear in the app."""
    result = run_bidirectional_nas_sync(ObjectId(get_jwt_identity()))
    if not result.get('ok'):
        return jsonify(result), 503
    return jsonify(result)


@wa_nas_bp.route('/browse', methods=['GET'])
@jwt_required()
def browse_nas():
    code = request.args.get('code')
    if code:
        files = nas_mount.list_folder_files(code)
        return jsonify({'ok': True, 'code': code.upper(), 'files': files})

    folders = nas_mount.list_folders()
    return jsonify({'ok': True, 'folders': folders})


@wa_nas_bp.route('/create-folder', methods=['POST'])
@jwt_required()
@require_role('admin', 'manager')
def create_folder():
    data = request.get_json()
    code = data.get('code', '').strip()
    if not code:
        return jsonify({'ok': False, 'error': 'code is required'}), 400
    result = nas_mount.create_folder(code)
    if not result.get('ok'):
        return jsonify(result), 500
    return jsonify(result)


@wa_nas_bp.route('/sync-projects', methods=['POST'])
@jwt_required()
@require_role('admin', 'manager')
def sync_projects_from_nas_route():
    """Create web projects for folders that exist on the NAS mount but not in Mongo."""
    result = sync_projects_from_nas(ObjectId(get_jwt_identity()))
    if not result.get('ok'):
        return jsonify(result), 503
    return jsonify(result)


@wa_nas_bp.route('/import-files', methods=['POST'])
@jwt_required()
@require_role('admin', 'manager')
def import_nas_files_route():
    """Import NAS images into WA records for one project (by projectId)."""
    data = request.get_json() or {}
    project_id = data.get('projectId', '').strip()
    if not project_id:
        return jsonify({'ok': False, 'error': 'projectId required'}), 400
    result = import_nas_files_for_project(project_id)
    if not result.get('ok'):
        return jsonify(result), 503
    return jsonify(result)


@wa_nas_bp.route('/import-all', methods=['POST'])
@jwt_required()
@require_role('admin', 'manager')
def import_all_nas_files_route():
    """Import NAS images for all active projects."""
    if not nas_mount.is_available():
        return jsonify({'ok': False, 'error': 'NAS mount not available'}), 503
    results = import_all_projects_from_nas()
    total_created = sum(r.get('created', 0) for r in results)
    return jsonify({'ok': True, 'totalCreated': total_created, 'projects': results})
