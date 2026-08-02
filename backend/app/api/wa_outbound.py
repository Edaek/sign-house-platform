from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

wa_outbound_bp = Blueprint('wa_outbound', __name__)

@wa_outbound_bp.route('/outbound', methods=['POST'])
@jwt_required()
def send_outbound():
    data = request.get_json()
    to = data.get('to', '')
    message = data.get('message') or data.get('text', '')

    if not to or not message:
        return jsonify({'error': 'to and message (or text) required'}), 400

    try:
        from app.services.wa_send_service import send_message
        result = send_message(to, message)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
