from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId

from app.services.nas_watcher_service import nas_mount
from app.services.project_number_match_service import is_range_folder_code
from app.services.nas_site_relocate_service import (
    realign_wa_projects_with_nas,
    relocate_all_site_folders_between_buckets,
    relocate_site_folder_between_buckets,
)
from app.services.nas_sync_service import (
    sync_projects_from_nas,
    sync_bucket_site_projects_from_nas,
    link_nas_bucket_folder_to_project,
    import_nas_files_for_project,
    import_all_projects_from_nas,
    run_bidirectional_nas_sync,
    get_last_nas_sync_status,
    reconcile_after_nas_folder_deleted,
    list_nas_root_bucket_summaries,
    _is_nas_root_bucket_dir,
)
from app.services.nas_bucket_code import nas_path_from_web_bucket
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
        if not nas_mount.is_volume_mounted():
            return jsonify({'ok': False, 'error': 'NAS not connected'}), 503
        nas_slow_hint = (
            'NAS is slow — folder listing may be incomplete. Records below are still available.'
        )
        include_files = request.args.get('includeFiles') == '1'
        files_only = request.args.get('filesOnly') == '1'
        subfolders_only = request.args.get('subfoldersOnly') == '1'
        nas_slow = not nas_mount.probe_responsive(timeout_s=2)
        path = nas_path_from_web_bucket(code)
        bucket_dir = nas_mount._resolve_bucket_dir(code)
        is_root_bucket = bool(
            bucket_dir
            and bucket_dir.is_dir()
            and _is_nas_root_bucket_dir(path)
        )
        if is_range_folder_code(code) or is_root_bucket:
            if nas_slow:
                children, from_cache = nas_mount.list_bucket_child_folders_with_fallback(code)
            else:
                children = nas_mount.list_bucket_child_folders(code)
                from_cache = False
            return jsonify({
                'ok': True,
                'code': code.upper(),
                'rangeBucket': is_range_folder_code(code),
                'standaloneBucket': is_root_bucket and not is_range_folder_code(code),
                'childFolders': children,
                'siteFolders': [c for c in children if c.get('isSiteProject') or c.get('folderName')],
                'staleFromCache': from_cache if nas_slow else False,
                'hint': nas_slow_hint if nas_slow and not children else None,
            })
        from app.services.wa_project_validation import find_project_by_code

        parent_for_lookup = (
            (request.args.get('nasParentBucket') or '').strip()
            or None
        )
        proj = find_project_by_code(code, parent_bucket=parent_for_lookup)
        if not proj and parent_for_lookup:
            proj = find_project_by_code(code)
        view = dict(proj) if proj else {'code': code}
        fn = (request.args.get('nasFolderName') or '').strip()
        pb = (request.args.get('nasParentBucket') or '').strip()
        if fn:
            view['nasFolderName'] = fn
        if pb:
            view['nasParentBucket'] = pb
        if files_only:
            files = nas_mount.list_folder_files(code, project_doc=view)
            return jsonify({
                'ok': True,
                'code': code.upper(),
                'rangeBucket': False,
                'subfolders': [],
                'files': files,
                'hint': nas_slow_hint if nas_slow and not files else None,
            })
        subfolders = nas_mount.list_project_subfolders(code, project_doc=view)
        if subfolders_only or not include_files:
            return jsonify({
                'ok': True,
                'code': code.upper(),
                'rangeBucket': False,
                'subfolders': subfolders,
                'files': [],
                'hint': nas_slow_hint if nas_slow and not subfolders else None,
            })
        files = nas_mount.list_folder_files(code, project_doc=view)
        hint = nas_slow_hint if nas_slow and not subfolders and not files else None
        return jsonify({
            'ok': True,
            'code': code.upper(),
            'rangeBucket': False,
            'subfolders': subfolders,
            'files': files,
            'hint': hint,
        })

    folders = nas_mount.list_folders()
    root_buckets = list_nas_root_bucket_summaries()
    root_names = nas_mount.list_watch_root_dir_names(timeout_s=8) or []
    return jsonify({
        'ok': True,
        'folders': folders,
        'rootFolderNames': root_names,
        'rootBuckets': root_buckets,
    })


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


@wa_nas_bp.route('/sync-bucket', methods=['POST'])
@jwt_required()
def sync_bucket_from_nas_route():
    """Import site folders under one NAS bucket into wa_projects (Projects drill-down)."""
    data = request.get_json() or {}
    bucket_code = (data.get('bucketCode') or data.get('code') or '').strip()
    if not bucket_code:
        return jsonify({'ok': False, 'error': 'bucketCode required'}), 400
    result = sync_bucket_site_projects_from_nas(bucket_code, ObjectId(get_jwt_identity()))
    if not result.get('ok'):
        return jsonify(result), 503
    return jsonify(result)


@wa_nas_bp.route('/link-bucket-folder', methods=['POST'])
@jwt_required()
def link_bucket_folder_route():
    """Link one NAS subfolder under a bucket to a wa_projects row (Projects «Link in app»)."""
    data = request.get_json() or {}
    bucket_code = (data.get('bucketCode') or data.get('code') or '').strip()
    folder_name = (data.get('folderName') or data.get('folder') or '').strip()
    if not bucket_code or not folder_name:
        return jsonify({'ok': False, 'error': 'bucketCode and folderName are required'}), 400
    result = link_nas_bucket_folder_to_project(
        bucket_code,
        folder_name,
        ObjectId(get_jwt_identity()),
    )
    if not result.get('ok'):
        return jsonify(result), 409 if 'already exists' in (result.get('error') or '') else 400
    return jsonify(result)


@wa_nas_bp.route('/realign-projects', methods=['POST'])
@jwt_required()
@require_role('admin', 'manager')
def realign_projects_route():
    """Match wa_projects parent bucket + NAS paths to where site folders actually are on the share."""
    data = request.get_json() or {}
    dry_run = bool(data.get('dryRun') or data.get('dry_run'))
    result = realign_wa_projects_with_nas(dry_run=dry_run)
    if not result.get('ok'):
        return jsonify(result), 503
    return jsonify(result)


@wa_nas_bp.route('/relocate-site-folder', methods=['POST'])
@jwt_required()
@require_role('admin', 'manager')
def relocate_site_folder_route():
    """Move one site folder to another NAS bucket parent (e.g. KTEST2/kelly → KTEST/kelly)."""
    data = request.get_json() or {}
    folder_name = (data.get('siteFolderName') or data.get('folderName') or '').strip()
    source = (data.get('sourceParentBucket') or data.get('fromParentBucket') or '').strip()
    target = (data.get('targetParentBucket') or data.get('toParentBucket') or '').strip()
    dry_run = bool(data.get('dryRun') or data.get('dry_run'))
    if not folder_name or not source or not target:
        return jsonify({
            'ok': False,
            'error': 'siteFolderName, sourceParentBucket, and targetParentBucket are required',
        }), 400
    result = relocate_site_folder_between_buckets(
        folder_name,
        source,
        target,
        dry_run=dry_run,
    )
    if not result.get('ok'):
        return jsonify(result), 409 if 'already exists' in (result.get('error') or '').lower() else 400
    return jsonify(result)


@wa_nas_bp.route('/relocate-bucket-children', methods=['POST'])
@jwt_required()
@require_role('admin', 'manager')
def relocate_bucket_children_route():
    """Move all site subfolders from one bucket to another (e.g. KTEST2/* → KTEST/*)."""
    data = request.get_json() or {}
    source = (data.get('sourceParentBucket') or data.get('fromParentBucket') or '').strip()
    target = (data.get('targetParentBucket') or data.get('toParentBucket') or '').strip()
    dry_run = bool(data.get('dryRun') or data.get('dry_run'))
    if not source or not target:
        return jsonify({
            'ok': False,
            'error': 'sourceParentBucket and targetParentBucket are required',
        }), 400
    result = relocate_all_site_folders_between_buckets(source, target, dry_run=dry_run)
    if not result.get('ok'):
        return jsonify(result), 409 if result.get('errors') else 400
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
        sync = reconcile_after_nas_folder_deleted(name)
        if quarantined:
            return jsonify({
                'ok': True,
                'folder': name,
                'alreadyRemoved': True,
                'quarantinedAs': quarantined,
                'message': f'Folder already removed (quarantined as {quarantined}).',
                'webProjectsRemoved': sync.get('projectsRemoved') or [],
                'webRecordsRemoved': sync.get('recordsRemoved') or 0,
            })
        return jsonify({
            'ok': True,
            'folder': name,
            'alreadyRemoved': True,
            'message': 'Folder not found on NAS (may already be deleted).',
            'webProjectsRemoved': sync.get('projectsRemoved') or [],
            'webRecordsRemoved': sync.get('recordsRemoved') or 0,
        })
    r = nas_mount.delete_path(str(bucket))
    if not r.get('ok'):
        return jsonify({'ok': False, 'error': r.get('error') or 'Delete failed'}), 503
    sync = reconcile_after_nas_folder_deleted(name)
    out = {
        'ok': True,
        'folder': name,
        'webProjectsRemoved': sync.get('projectsRemoved') or [],
        'webRecordsRemoved': sync.get('recordsRemoved') or 0,
    }
    if r.get('quarantined'):
        out['quarantined'] = True
        out['message'] = r.get('message')
    return jsonify(out)
