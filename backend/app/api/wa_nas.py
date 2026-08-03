from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from app.services.nas_watcher_service import nas_mount
from app.utils.permissions import require_role

wa_nas_bp = Blueprint('wa_nas', __name__)


@wa_nas_bp.route('/status', methods=['GET'])
@jwt_required()
def nas_status():
    return jsonify(nas_mount.status())


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
