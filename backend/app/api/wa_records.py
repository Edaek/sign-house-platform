from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime
from app.services.wa_time import wa_now
from app import mongo
from app.models import serialize_doc
from app.utils.permissions import require_role

wa_records_bp = Blueprint('wa_records', __name__)

_REMARK_FIELDS = {'remark', 'rawmessage', 'caption', '备注', '備註', '備注'}


def _is_remark_field(name: str) -> bool:
    key = (name or '').strip()
    return key.lower() in _REMARK_FIELDS or key in _REMARK_FIELDS

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
    
    now = wa_now()
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
    
    sets = {
        'extractedFields': fields,
        'updatedAt': now,
    }
    remark_result = None
    if _is_remark_field(field_name):
        from app.services.message_parser_service import site_note_from_text
        from app.services.nas_site_remark_service import append_site_remark_to_nas, hk_today_str

        note = site_note_from_text(str(value or '')) or str(value or '').strip()
        if note and note.lower() != '[pool media]':
            sets['rawMessage'] = note
            project = None
            if record.get('projectId'):
                project = mongo.db.wa_projects.find_one({'_id': record['projectId']})
            if project:
                remark_result = append_site_remark_to_nas(
                    project.get('code') or '',
                    note,
                    day_str=hk_today_str(),
                    preferred_folder_name=(project.get('nasFolderName') or '').strip() or None,
                    preferred_parent_bucket=(project.get('nasParentBucket') or '').strip() or None,
                )
                sets['nasRemarkOk'] = bool(remark_result.get('ok') and not remark_result.get('skipped'))
                if remark_result.get('path'):
                    sets['nasRemarkPath'] = remark_result.get('path')
                if remark_result.get('error'):
                    sets['nasRemarkError'] = remark_result.get('error')

    mongo.db.wa_records.update_one(
        {'_id': ObjectId(record_id)},
        {'$set': sets, '$push': {
            'editHistory': {
                'field': field_name,
                'oldValue': old_value,
                'newValue': value,
                'editedBy': ObjectId(user_id),
                'timestamp': now,
            }
        }}
    )
    body = {'message': 'Field updated'}
    if remark_result is not None:
        body['siteRemark'] = remark_result
    return jsonify(body)

@wa_records_bp.route('/<record_id>/confirm', methods=['POST'])
@jwt_required()
def confirm_record(record_id):
    user_id = get_jwt_identity()
    now = wa_now()
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
    now = wa_now()
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

@wa_records_bp.route('/<record_id>/move-project', methods=['POST'])
@jwt_required()
@require_role('admin', 'manager')
def move_record_project(record_id):
    data = request.get_json() or {}
    target_code = (data.get('targetProjectCode') or data.get('projectCode') or '').strip()
    project_id = (data.get('projectId') or '').strip()
    relocate_nas = data.get('relocateNas', True)
    if isinstance(relocate_nas, str):
        relocate_nas = relocate_nas.strip().lower() not in ('0', 'false', 'no')

    from app.services.image_pool_service import move_record_to_project, resolve_wa_move_target_project

    source_record = mongo.db.wa_records.find_one({'_id': ObjectId(record_id)})
    nas_folder = (data.get('nasFolderName') or data.get('nas_folder_name') or '').strip()
    nas_bucket = (data.get('nasParentBucket') or data.get('nas_parent_bucket') or '').strip()
    project = resolve_wa_move_target_project(
        project_id=project_id,
        target_code=target_code,
        nas_folder_name=nas_folder or None,
        nas_parent_bucket=nas_bucket or None,
        source_record=source_record,
    )
    if not project:
        return jsonify({'error': 'Target project not found'}), 404

    proj = dict(project)

    ref = (data.get('recordReference') or record_id or '').strip()
    try:
        result = move_record_to_project(
            ref,
            proj,
            moved_by='operator',
            relocate_nas=bool(relocate_nas),
        )
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500

    if result.get('moved', 0) <= 0:
        return jsonify({**result, 'error': '; '.join(result.get('errors') or ['move failed'])}), 409

    return jsonify({**result, 'targetProjectCode': proj.get('code')})


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
    
    now = wa_now()
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
