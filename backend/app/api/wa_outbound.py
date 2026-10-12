from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

wa_outbound_bp = Blueprint('wa_outbound', __name__)


def _outbound_type(data: dict) -> str:
    explicit = (data.get('type') or '').strip().lower()
    if explicit in ('text', 'media', 'group'):
        return explicit
    if data.get('groupId') or data.get('group_id'):
        return 'group'
    if data.get('mediaUrl') or data.get('media_url'):
        return 'media'
    return 'text'


@wa_outbound_bp.route('/outbound', methods=['POST'])
@jwt_required()
def send_outbound():
    data = request.get_json(silent=True) or {}
    kind = _outbound_type(data)

    try:
        if kind == 'text':
            to = data.get('to', '')
            message = data.get('message') or data.get('text', '')
            if not to or not message:
                return jsonify({'error': 'to and message (or text) required'}), 400
            from app.services.wa_send_service import send_message
            quoted = data.get('quotedMsgId') or data.get('quoted_msg_id')
            result = send_message(to, message, quoted_msg_id=quoted)
            return jsonify(result)

        if kind == 'media':
            to = data.get('to', '')
            media_url = data.get('mediaUrl') or data.get('media_url', '')
            if not to or not media_url:
                return jsonify({'error': 'to and mediaUrl required'}), 400
            from app.services.wa_send_service import send_media
            result = send_media(
                to,
                media_url,
                caption=data.get('caption'),
                filename=data.get('filename'),
            )
            return jsonify(result)

        group_id = data.get('groupId') or data.get('group_id', '')
        message = data.get('message') or data.get('text', '')
        if not group_id or not message:
            return jsonify({'error': 'groupId and message (or text) required'}), 400
        from app.services.wa_send_service import send_group_message
        quoted = data.get('quotedMsgId') or data.get('quoted_msg_id')
        result = send_group_message(
            group_id,
            message,
            media_data_uri=data.get('mediaUrl') or data.get('media_url'),
            quoted_msg_id=quoted,
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
