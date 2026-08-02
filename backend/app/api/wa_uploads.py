import os
from flask import Blueprint, send_from_directory, current_app, abort

wa_uploads_bp = Blueprint('wa_uploads', __name__)

@wa_uploads_bp.route('/<path:filepath>', methods=['GET'])
def serve_wa_media(filepath):
    uploads_root = os.path.dirname(current_app.config.get('WA_UPLOADS_FOLDER', 'uploads/wa-media'))
    full_path = os.path.realpath(os.path.join(uploads_root, filepath))
    if not full_path.startswith(os.path.realpath(uploads_root)):
        abort(403)
    if not os.path.isfile(full_path):
        abort(404)
    return send_from_directory(os.path.dirname(full_path), os.path.basename(full_path))
