from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime
from app import mongo
from app.models import serialize_doc

wa_records_bp = Blueprint('wa_records', __name__)

@wa_records_bp.route('/<record_id>', methods=['GET'])
@jwt_required()
def get_record(record_id):
    record = mongo.db.wa_records.find_one({'_id': ObjectId(record_id)})
    if not record:
        return jsonify({'error': 'Record not found'}), 404
    return jsonify(serialize_doc(record))

@wa_records_bp.route('/<record_id>', methods=['PATCH'])
@jwt_required()
def update_record_field(record_id):
    data = request.get_json()
    field_name = data.get('field')
    value = data.get('value', '')
    user_id = get_jwt_identity()
    
    record = mongo.db.wa_records.find_one({'_id': ObjectId(record_id)})
    if not record:
        return jsonify({'error': 'Record not found'}), 404
    
    now = datetime.utcnow()
    fields = record.get('extractedFields', [])
    old_value = ''
    for f in fields:
        if f['name'] == field_name:
            old_value = f.get('value', '')
            f['value'] = value
            f['confidence'] = 'green'
            f['editedBy'] = ObjectId(user_id)
            f['editedAt'] = now
            break
    
    mongo.db.wa_records.update_one(
        {'_id': ObjectId(record_id)},
        {'$set': {
            'extractedFields': fields,
            'updatedAt': now,
        }, '$push': {
            'editHistory': {
                'field': field_name,
                'oldValue': old_value,
                'newValue': value,
                'editedBy': ObjectId(user_id),
                'timestamp': now,
            }
        }}
    )
    return jsonify({'message': 'Field updated'})

@wa_records_bp.route('/<record_id>/confirm', methods=['POST'])
@jwt_required()
def confirm_record(record_id):
    user_id = get_jwt_identity()
    now = datetime.utcnow()
    record = mongo.db.wa_records.find_one({'_id': ObjectId(record_id)})
    if not record:
        return jsonify({'error': 'Record not found'}), 404

    if record['status'] in ('completed', 'voided'):
        return jsonify({'error': f'Cannot confirm a record that is already {record["status"]}'}), 400

    old_status = record['status']
    mongo.db.wa_records.update_one(
        {'_id': ObjectId(record_id)},
        {'$set': {'status': 'completed', 'updatedAt': now},
         '$push': {'statusHistory': {
             'from': old_status, 'to': 'completed',
             'changedBy': ObjectId(user_id),
             'timestamp': now
         }}}
    )
    return jsonify({'message': 'Record confirmed'})

@wa_records_bp.route('/<record_id>/void', methods=['POST'])
@jwt_required()
def void_record(record_id):
    data = request.get_json()
    reason = data.get('reason', '')
    if len(reason) < 5:
        return jsonify({'error': 'Reason must be at least 5 characters'}), 400
    
    user_id = get_jwt_identity()
    now = datetime.utcnow()
    record = mongo.db.wa_records.find_one({'_id': ObjectId(record_id)})
    if not record:
        return jsonify({'error': 'Record not found'}), 404

    if record['status'] == 'voided':
        return jsonify({'error': 'Record is already voided'}), 400

    from app.services.nas_sync_service import remove_nas_files_for_record

    remove_nas_files_for_record(record)

    old_status = record['status']
    mongo.db.wa_records.update_one(
        {'_id': ObjectId(record_id)},
        {'$set': {'status': 'voided', 'voidReason': reason, 'updatedAt': now},
         '$push': {'statusHistory': {
             'from': old_status, 'to': 'voided',
             'changedBy': ObjectId(user_id),
             'reason': reason,
             'timestamp': now
         }}}
    )
    return jsonify({'message': 'Record voided'})

@wa_records_bp.route('/<record_id>/request-info', methods=['POST'])
@jwt_required()
def request_info(record_id):
    data = request.get_json()
    question = data.get('question', '')
    if not question.strip():
        return jsonify({'error': 'Question required'}), 400
    
    record = mongo.db.wa_records.find_one({'_id': ObjectId(record_id)})
    if not record:
        return jsonify({'error': 'Record not found'}), 404
    
    now = datetime.utcnow()
    round_num = record.get('followUpRound', 0) + 1
    
    try:
        from app.services.wa_send_service import send_message
        ref = record.get('referenceNumber', '')
        msg = f'Re: {ref}\n\n{question}' if ref else question
        send_message(record['senderPhone'], msg)
    except Exception as e:
        return jsonify({'error': f'Failed to send: {str(e)}'}), 500
    
    mongo.db.wa_records.update_one(
        {'_id': ObjectId(record_id)},
        {'$set': {'followUpRound': round_num, 'lastFollowUpAt': now, 'status': 'followup', 'updatedAt': now},
         '$push': {
             'followUpThread': {'question': question, 'timestamp': now, 'round': round_num},
             'statusHistory': {'from': record['status'], 'to': 'followup', 'timestamp': now}
         }}
    )
    return jsonify({'message': 'Follow-up sent'})
