"""API routes for folder watcher management."""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId

from app import mongo
from app.services.folder_watcher import watcher_manager
from app.api.processing import normalize_marker_colors

watcher_bp = Blueprint('watcher', __name__)


@watcher_bp.route('/start', methods=['POST'])
@jwt_required()
def start_watcher():
    """Start watching a folder for a project.
    ---
    tags: [Folder Watcher]
    parameters:
      - in: body
        schema:
          properties:
            project_id: { type: string }
            watch_folder: { type: string }
            detection_mode: { type: string, enum: [fast, accurate], default: accurate }
    responses:
      200: { description: Watcher started }
      400: { description: Missing parameters }
      404: { description: Project not found }
    """
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    project_id = data.get('project_id')
    watch_folder = data.get('watch_folder', '')
    detection_mode = data.get('detection_mode', 'accurate')
    try:
        marker_colors = normalize_marker_colors(data.get('marker_colors'))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    if not project_id or not watch_folder:
        return jsonify({'error': 'project_id and watch_folder are required'}), 400

    project = mongo.db.projects.find_one({'_id': ObjectId(project_id)})
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    started = watcher_manager.start(project_id, watch_folder, detection_mode, marker_colors)
    if not started:
        return jsonify({'message': 'Watcher already running', 'status': 'running'}), 200

    mongo.db.projects.update_one(
        {'_id': ObjectId(project_id)},
        {'$set': {
            'watcher_folder': watch_folder,
            'watcher_detection_mode': detection_mode,
            'watcher_marker_colors': marker_colors,
        }}
    )

    return jsonify({
        'message': 'Watcher started',
        'status': 'running',
        'watch_folder': watch_folder,
        'detection_mode': detection_mode,
        'marker_colors': marker_colors,
    }), 200


@watcher_bp.route('/stop', methods=['POST'])
@jwt_required()
def stop_watcher():
    """Stop watching a folder for a project.
    ---
    tags: [Folder Watcher]
    parameters:
      - in: body
        schema:
          properties:
            project_id: { type: string }
    responses:
      200: { description: Watcher stopped }
    """
    data = request.get_json() or {}
    project_id = data.get('project_id')

    if not project_id:
        return jsonify({'error': 'project_id is required'}), 400

    stopped = watcher_manager.stop(project_id)
    return jsonify({
        'message': 'Watcher stopped' if stopped else 'No active watcher',
        'status': 'stopped',
    }), 200


@watcher_bp.route('/status/<project_id>', methods=['GET'])
@jwt_required()
def watcher_status(project_id):
    """Get watcher status for a project.
    ---
    tags: [Folder Watcher]
    parameters:
      - in: path
        name: project_id
        type: string
    responses:
      200: { description: Watcher status }
    """
    status = watcher_manager.status(project_id)

    if status['status'] == 'stopped':
        project = mongo.db.projects.find_one({'_id': ObjectId(project_id)})
        if project and project.get('watcher_folder'):
            status['watch_folder'] = project['watcher_folder']
            status['detection_mode'] = project.get('watcher_detection_mode', 'accurate')

    recent_jobs = list(mongo.db.processing_jobs.find(
        {'project_id': project_id, 'source': 'folder_watcher'},
        {'_id': 0, 'job_id': 1, 'status': 1, 'files': 1, 'created_at': 1},
    ).sort('created_at', -1).limit(20))

    active_files = []
    for job in recent_jobs:
        for f in job.get('files', []):
            active_files.append({
                'filename': f.get('filename', ''),
                'status': f.get('status', 'pending'),
                'progress': f.get('progress', 0),
                'error': f.get('error', ''),
                'shapes_detected': f.get('shapes_detected', 0),
            })

    status['recent_files'] = active_files

    return jsonify(status), 200


@watcher_bp.route('/browse-folders', methods=['GET'])
@jwt_required()
def browse_folders():
    """Browse local filesystem folders (for folder selection UI).
    ---
    tags: [Folder Watcher]
    parameters:
      - in: query
        name: path
        type: string
        default: "~"
    responses:
      200: { description: List of subdirectories }
    """
    import os
    from pathlib import Path

    base = request.args.get('path', '~')
    base_path = Path(os.path.expanduser(base)).resolve()

    if not base_path.is_dir():
        return jsonify({'error': 'Not a directory', 'path': str(base_path)}), 400

    folders = []
    try:
        for entry in sorted(base_path.iterdir()):
            if entry.is_dir() and not entry.name.startswith('.'):
                folders.append({
                    'name': entry.name,
                    'path': str(entry),
                })
    except PermissionError:
        return jsonify({'error': 'Permission denied', 'path': str(base_path)}), 403

    return jsonify({
        'current_path': str(base_path),
        'parent_path': str(base_path.parent) if base_path.parent != base_path else None,
        'folders': folders,
    }), 200
