from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId

from app.services.nas_watcher_service import nas_mount
from app.services.project_number_match_service import is_range_folder_code
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
    """NAS ↔ web: folders/photos on the share and projects in the app stay in sync."""
    result = run_bidirectional_nas_sync(ObjectId(get_jwt_identity()), import_files=True)
    if not result.get('ok'):
        return jsonify(result), 503
    return jsonify(result)


@wa_nas_bp.route('/browse', methods=['GET'])
@jwt_required()
def browse_nas():
    code = (request.args.get('code') or '').strip()
    if code:
        if is_range_folder_code(code):
            children = nas_mount.list_bucket_child_folders(code)
            return jsonify({
                'ok': True,
                'code': code.upper(),
                'rangeBucket': True,
                'childFolders': children,
                'siteFolders': [c for c in children if c.get('isSiteProject')],
            })
        return jsonify({
            'ok': True,
            'code': code.upper(),
            'rangeBucket': False,
            'subfolders': nas_mount.list_project_subfolders(code),
            'files': nas_mount.list_folder_files(code),
        })

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
    parent_bucket = (data.get('parentBucketCode') or data.get('nasParentFolder') or '').strip() or None
    result = nas_mount.create_folder(code, parent_bucket_code=parent_bucket)
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


@wa_nas_bp.route('/root-folders/<path:folder_name>', methods=['DELETE'])
@jwt_required()
@require_role('admin', 'manager')
def delete_nas_root_folder(folder_name):
    """Remove a top-level NAS bucket folder (no wa_projects row required)."""
    from urllib.parse import unquote

    name = unquote(folder_name or '').strip()
    if not name or '..' in name or '/' in name:
        return jsonify({'ok': False, 'error': 'Invalid folder name'}), 400
    if not nas_mount.is_available():
        return jsonify({'ok': False, 'error': 'NAS mount not available'}), 503
    bucket = nas_mount._resolve_bucket_dir(name)
    if bucket is None:
        watch = nas_mount._resolved_watch_dir()
        if not watch:
            return jsonify({'ok': False, 'error': 'NAS watch dir not configured'}), 503
        from pathlib import Path
        bucket = Path(watch) / name
    if not bucket.is_dir():
        from pathlib import Path
        watch = nas_mount._resolved_watch_dir()
        quarantined = None
        if watch:
            prefix = f'.trash-{name}-'
            for entry in Path(watch).iterdir():
                if entry.is_dir() and (
                    entry.name == name
                    or entry.name.lower() == name.lower()
                    or entry.name.startswith(prefix)
                    or entry.name.lower().startswith(prefix.lower())
                ):
                    if entry.name.startswith('.trash-'):
                        quarantined = entry.name
                        break
        if quarantined:
            return jsonify({
                'ok': True,
                'folder': name,
                'alreadyRemoved': True,
                'quarantinedAs': quarantined,
                'message': f'Folder already removed (quarantined as {quarantined}).',
            })
        return jsonify({
            'ok': True,
            'folder': name,
            'alreadyRemoved': True,
            'message': 'Folder not found on NAS (may already be deleted).',
        })
    r = nas_mount.delete_path(str(bucket))
    if not r.get('ok'):
        return jsonify({'ok': False, 'error': r.get('error') or 'Delete failed'}), 503
    out = {'ok': True, 'folder': name}
    if r.get('quarantined'):
        out['quarantined'] = True
        out['message'] = r.get('message')
    return jsonify(out)
