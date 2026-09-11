# MongoDB models - document schemas are defined inline in the API modules
# This file provides helper functions for common operations

from datetime import datetime
from bson import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash


__all__ = [
    'serialize_doc',
    'create_user_doc',
    'check_user_password',
    'user_to_dict',
    'create_project_doc',
    'create_template_doc',
    'create_floorplan_doc',
    'create_extracted_data_doc',
    'create_audit_log_doc',
    'create_project_member_doc',
    'create_dictionary_entry_doc',
    'dictionary_entry_to_dict',
    'create_sign_table_doc',
    'create_sign_row',
    'sign_table_to_dict',
    'create_processing_job_doc',
    'create_processing_file_doc',
    'processing_job_to_dict',
    'create_shape_template_doc',
    'shape_template_to_dict',
    'create_wa_record_doc',
    'wa_record_to_dict',
    'create_wa_project_doc',
    'wa_project_to_dict',
    'create_pool_image_doc',
    'pool_image_to_dict',
    'create_group_pending_image_doc',
    'group_pending_image_to_dict',
    'create_wa_keyword_doc',
    'wa_keyword_to_dict',
    'create_wa_template_doc',
    'wa_template_to_dict',
    'create_wa_organization_doc',
    'wa_organization_to_dict',
    'create_wa_pending_photo_doc',
    'wa_pending_photo_to_dict',
]


def serialize_doc(doc):
    """Convert MongoDB document to JSON-serializable dict."""
    if doc is None:
        return None
    
    result = {}
    for key, value in doc.items():
        if key == '_id':
            # Explicitly handle _id -> id conversion
            result['id'] = str(value)
        elif isinstance(value, ObjectId):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, list):
            result[key] = [serialize_doc(item) if isinstance(item, dict) else 
                          str(item) if isinstance(item, ObjectId) else item 
                          for item in value]
        elif isinstance(value, dict):
            result[key] = serialize_doc(value)
        else:
            result[key] = value
    
    return result


def create_user_doc(username, email, password, role='user'):
    """Create a user document."""
    return {
        'username': username,
        'email': email,
        'password_hash': generate_password_hash(password, method='pbkdf2:sha256'),
        'role': role,  # 'admin', 'manager', or 'user'
        'role_changed_at': None,
        'role_assigned_by': None,
        'created_at': datetime.utcnow(),
        'updated_at': datetime.utcnow(),
        'is_active': True
    }


def check_user_password(user_doc, password):
    """Check if password matches user's hash."""
    return check_password_hash(user_doc.get('password_hash', ''), password)


def user_to_dict(user_doc):
    """Convert user document to safe dict (no password)."""
    if not user_doc:
        return None
    return {
        'id': str(user_doc['_id']),
        'username': user_doc['username'],
        'email': user_doc['email'],
        'role': user_doc.get('role', 'user'),
        'created_at': user_doc['created_at'].isoformat(),
        'is_active': user_doc.get('is_active', True)
    }


def create_project_doc(name, description, user_id):
    """Create a project document."""
    return {
        'name': name,
        'description': description or '',
        'status': 'draft',
        'user_id': ObjectId(user_id),
        'created_at': datetime.utcnow(),
        'updated_at': datetime.utcnow()
    }


def create_template_doc(filename, filepath, project_id, columns=None):
    """Create a template document."""
    return {
        'filename': filename,
        'filepath': filepath,
        'columns': columns or [],
        'project_id': ObjectId(project_id),
        'created_at': datetime.utcnow()
    }


def create_floorplan_doc(floor_number, floor_name, pdf_filename, pdf_filepath, image_filepath, project_id):
    """Create a floorplan document."""
    return {
        'floor_number': floor_number,
        'floor_name': floor_name,
        'pdf_filename': pdf_filename,
        'pdf_filepath': pdf_filepath,
        'image_filepath': image_filepath,
        'shape_type': None,
        'status': 'pending',
        'project_id': ObjectId(project_id),
        'created_at': datetime.utcnow(),
        'updated_at': datetime.utcnow()
    }


def create_extracted_data_doc(shape_index, shape_type, x, y, width, height, floorplan_id, shape_data=None):
    """Create an extracted data document."""
    return {
        'shape_index': shape_index,
        'shape_type': shape_type,
        'x': x,
        'y': y,
        'width': width,
        'height': height,
        'shape_data': shape_data,
        'extracted_text': None,
        'confidence': None,
        'quantity': 1,
        'merged_count': 1,
        'original_shape_indices': None,
        'all_bounding_boxes': None,
        'is_manual': False,
        'manual_text': None,
        'detection_method': 'auto',  # 'auto' | 'manual' | 'learned'
        'template_id': None,  # Reference to shape_template that matched (for 'learned')
        'floorplan_id': ObjectId(floorplan_id),
        'created_at': datetime.utcnow(),
        'updated_at': datetime.utcnow()
    }


def create_audit_log_doc(user_id, action, resource_type=None, resource_id=None, details=None, ip_address=None, user_agent=None):
    """Create an audit log document."""
    return {
        'user_id': ObjectId(user_id) if user_id else None,
        'action': action,
        'resource_type': resource_type,
        'resource_id': str(resource_id) if resource_id else None,
        'details': details or {},
        'ip_address': ip_address,
        'user_agent': user_agent,
        'timestamp': datetime.utcnow()
    }


def create_project_member_doc(project_id, user_id, role='member', added_by=None):
    """Create a project member document."""
    return {
        'project_id': ObjectId(project_id),
        'user_id': ObjectId(user_id),
        'role': role,  # 'member' for now (can be extended)
        'added_by': ObjectId(added_by) if added_by else None,
        'added_at': datetime.utcnow()
    }


def create_dictionary_entry_doc(english, chinese_list, created_by=None, sign=''):
    """Create a dictionary entry document for English-Sign-Chinese translation entries.
    
    Args:
        english: The English word (primary key)
        chinese_list: A list of Chinese translations, or a single string
        created_by: User ID who created the entry
        sign: The sign name/code corresponding to this English word
    """
    # Normalize chinese to a list
    if isinstance(chinese_list, str):
        chinese_list = [chinese_list.strip()] if chinese_list.strip() else []
    elif chinese_list is None:
        chinese_list = []
    else:
        chinese_list = [c.strip() for c in chinese_list if c and c.strip()]
    
    return {
        'english': english.strip() if english else '',
        'sign': sign.strip() if sign else '',  # Sign name/code for this English word
        'chinese': chinese_list,  # Array of Chinese translations
        'created_by': ObjectId(created_by) if created_by else None,
        'created_at': datetime.utcnow(),
        'updated_at': datetime.utcnow()
    }


def dictionary_entry_to_dict(entry_doc):
    """Convert dictionary entry document to dict."""
    if not entry_doc:
        return None
    
    # Handle both old format (string) and new format (array) for backwards compatibility
    chinese = entry_doc.get('chinese', [])
    if isinstance(chinese, str):
        chinese = [chinese] if chinese else []
    
    return {
        'id': str(entry_doc['_id']),
        'english': entry_doc.get('english', ''),
        'sign': entry_doc.get('sign', ''),  # Sign name/code for this English word
        'chinese': chinese,  # Always return as array
        'created_by': str(entry_doc['created_by']) if entry_doc.get('created_by') else None,
        'created_at': entry_doc['created_at'].isoformat() if entry_doc.get('created_at') else None,
        'updated_at': entry_doc['updated_at'].isoformat() if entry_doc.get('updated_at') else None
    }


def create_sign_row(row_number, sign_no, floor_counts, sign='', english='', chinese=''):
    """Create a sign row for the sign table.
    
    Args:
        row_number: Auto-incremented row number (1-based)
        sign_no: The extracted sign number from OCR
        floor_counts: Dict mapping floor names to counts, e.g., {"21/F": 3, "22/F": 2}
        sign: Optional sign description (user fills)
        english: Optional English translation (user fills, with autocomplete)
        chinese: Optional Chinese translation (auto-filled from dictionary)
    """
    return {
        'row_number': row_number,
        'sign_no': sign_no,
        'sign': sign,
        'english': english,
        'chinese': chinese,
        'floor_counts': floor_counts or {}
    }


def create_sign_table_doc(project_id, rows, floorplan_columns):
    """Create a sign table document for a project.
    
    Args:
        project_id: The project ID this sign table belongs to
        rows: List of sign rows created by create_sign_row()
        floorplan_columns: List of floorplan names that become dynamic columns
    """
    return {
        'project_id': ObjectId(project_id),
        'rows': rows or [],
        'floorplan_columns': floorplan_columns or [],
        'created_at': datetime.utcnow(),
        'updated_at': datetime.utcnow()
    }


def sign_table_to_dict(sign_table_doc):
    """Convert sign table document to dict for JSON response."""
    if not sign_table_doc:
        return None
    
    columns = sign_table_doc.get('floorplan_columns', [])
    return {
        'id': str(sign_table_doc['_id']),
        'project_id': str(sign_table_doc['project_id']),
        'rows': sign_table_doc.get('rows', []),
        'floorplan_columns': columns,
        'floorplan_column_names': sign_table_doc.get('floorplan_column_names', columns),
        'created_at': sign_table_doc['created_at'].isoformat() if sign_table_doc.get('created_at') else None,
        'updated_at': sign_table_doc['updated_at'].isoformat() if sign_table_doc.get('updated_at') else None
    }


def create_processing_file_doc(filename, status='pending'):
    """Create a processing file entry for batch upload jobs.
    
    Args:
        filename: Original filename of the PDF
        status: Current processing status
            - 'pending': Waiting to be processed
            - 'uploading': File is being uploaded
            - 'converting': Converting PDF to images
            - 'detecting': Running shape detection
            - 'ocr': Running OCR on detected shapes
            - 'completed': Successfully processed
            - 'error': Processing failed
    """
    return {
        'filename': filename,
        'status': status,
        'progress': 0,  # 0-100 percentage
        'error': None,
        'floorplan_ids': [],  # IDs of created floorplans (one per page)
        'pages_total': 0,
        'pages_processed': 0,
        'shapes_detected': 0,
        'cancel_requested': False,
        'started_at': None,
        'completed_at': None
    }


def create_processing_job_doc(project_id, user_id, files, job_type='batch_upload', floorplan_id=None):
    """Create a processing job document for batch PDF upload.
    
    Args:
        project_id: The project ID this job belongs to
        user_id: User who initiated the upload
        files: List of file info dicts created by create_processing_file_doc()
        job_type: 'batch_upload' or 'detect'
        floorplan_id: Optional floorplan ObjectId for single-page detect jobs
    """
    import uuid
    doc = {
        'job_id': str(uuid.uuid4()),
        'job_type': job_type,
        'project_id': ObjectId(project_id),
        'user_id': ObjectId(user_id),
        'status': 'pending',  # pending, processing, completed, error, cancelled
        'cancel_requested': False,
        'total_files': len(files),
        'processed_files': 0,
        'files': files,
        'created_at': datetime.utcnow(),
        'updated_at': datetime.utcnow(),
        'completed_at': None,
    }
    if floorplan_id is not None:
        doc['floorplan_id'] = ObjectId(floorplan_id)
    return doc


def create_detect_job_doc(project_id, user_id, floorplan_id, params=None):
    """Create a processing job for async single-floorplan detect."""
    import uuid
    now = datetime.utcnow()
    return {
        'job_id': str(uuid.uuid4()),
        'job_type': 'detect',
        'project_id': ObjectId(project_id),
        'user_id': ObjectId(user_id),
        'floorplan_id': ObjectId(floorplan_id),
        'status': 'pending',
        'cancel_requested': False,
        'stage': 'pending',
        'progress': 0,
        'params': params or {},
        'result': None,
        'error': None,
        'total_files': 0,
        'processed_files': 0,
        'files': [],
        'created_at': now,
        'updated_at': now,
        'completed_at': None,
    }


def processing_job_to_dict(job_doc):
    """Convert processing job document to dict for JSON response."""
    if not job_doc:
        return None

    return {
        'id': str(job_doc['_id']),
        'job_id': job_doc['job_id'],
        'job_type': job_doc.get('job_type', 'batch_upload'),
        'project_id': str(job_doc['project_id']),
        'user_id': str(job_doc['user_id']),
        'status': job_doc['status'],
        'cancel_requested': job_doc.get('cancel_requested', False),
        'total_files': job_doc.get('total_files', 0),
        'processed_files': job_doc.get('processed_files', 0),
        'files': job_doc.get('files', []),
        'floorplan_id': str(job_doc['floorplan_id']) if job_doc.get('floorplan_id') else None,
        'stage': job_doc.get('stage'),
        'progress': job_doc.get('progress'),
        'result': job_doc.get('result'),
        'error': job_doc.get('error'),
        'recovered_stale': job_doc.get('recovered_stale', False),
        'paddle_device': job_doc.get('paddle_device'),
        'created_at': job_doc['created_at'].isoformat() if job_doc.get('created_at') else None,
        'updated_at': job_doc['updated_at'].isoformat() if job_doc.get('updated_at') else None,
        'completed_at': job_doc['completed_at'].isoformat() if job_doc.get('completed_at') else None
    }


def create_shape_template_doc(shape_type, image_path, width, height,
                               color_profile=None, source_floorplan_id=None,
                               extracted_text=None, created_by=None):
    """Create a shape template document for self-learning detection.

    Templates are cropped from user-drawn manual corrections and used
    in future detection runs via multi-scale template matching.
    """
    return {
        'shape_type': shape_type,
        'image_path': image_path,
        'width': width,
        'height': height,
        'color_profile': color_profile,
        'source_floorplan_id': ObjectId(source_floorplan_id) if source_floorplan_id else None,
        'extracted_text': extracted_text,
        'created_by': ObjectId(created_by) if created_by else None,
        'is_active': True,
        'match_count': 0,
        'created_at': datetime.utcnow(),
    }


def shape_template_to_dict(template_doc):
    """Convert shape template document to dict for JSON response."""
    if not template_doc:
        return None

    return {
        'id': str(template_doc['_id']),
        'shape_type': template_doc.get('shape_type', ''),
        'image_path': template_doc.get('image_path', ''),
        'width': template_doc.get('width', 0),
        'height': template_doc.get('height', 0),
        'color_profile': template_doc.get('color_profile'),
        'source_floorplan_id': str(template_doc['source_floorplan_id']) if template_doc.get('source_floorplan_id') else None,
        'extracted_text': template_doc.get('extracted_text'),
        'created_by': str(template_doc['created_by']) if template_doc.get('created_by') else None,
        'is_active': template_doc.get('is_active', True),
        'match_count': template_doc.get('match_count', 0),
        'created_at': template_doc['created_at'].isoformat() if template_doc.get('created_at') else None,
    }


# ============================================================
# WA (WhatsApp) Models
# ============================================================


def create_wa_record_doc(project_id, reference_number, sender_phone, sender_name=None,
                         status='incomplete', record_type='photo', tags=None,
                         description='', raw_message='', photos=None, nas_photos=None,
                         has_media=False, media_type=None, wakka_message_id=None,
                         extracted_fields=None):
    """Create a WA record document (wa_records collection)."""
    return {
        'project_id': ObjectId(project_id),
        'reference_number': reference_number,
        'status': status,
        'type': record_type,
        'tags': tags or [],
        'description': description,
        'raw_message': raw_message,
        'sender_phone': sender_phone,
        'sender_name': sender_name,
        'photos': photos or [],
        'nas_photos': nas_photos or [],
        'has_media': has_media,
        'media_type': media_type,
        'wakka_message_id': wakka_message_id,
        'extracted_fields': extracted_fields or [],
        'follow_up_thread': [],
        'follow_up_round': 0,
        'last_follow_up_at': None,
        'status_history': [],
        'edit_history': [],
        'merged_from': None,
        'split_from': None,
        'void_reason': None,
        'created_at': datetime.utcnow(),
        'updated_at': datetime.utcnow(),
    }


def wa_record_to_dict(doc):
    """Convert WA record document to dict for JSON response."""
    if not doc:
        return None

    def _serialize_extracted_field(f):
        return {
            'name': f.get('name', ''),
            'value': f.get('value', ''),
            'confidence': f.get('confidence', 'gray'),
            'edited_by': str(f['edited_by']) if f.get('edited_by') else None,
            'edited_at': f['edited_at'].isoformat() if f.get('edited_at') else None,
        }

    def _serialize_follow_up(fu):
        return {
            'question': fu.get('question', ''),
            'answer': fu.get('answer'),
            'timestamp': fu['timestamp'].isoformat() if fu.get('timestamp') else None,
            'round': fu.get('round', 0),
        }

    def _serialize_status_history(sh):
        return {
            'from': sh.get('from', ''),
            'to': sh.get('to', ''),
            'changed_by': str(sh['changed_by']) if sh.get('changed_by') else None,
            'reason': sh.get('reason', ''),
            'timestamp': sh['timestamp'].isoformat() if sh.get('timestamp') else None,
        }

    def _serialize_edit_history(eh):
        return {
            'field': eh.get('field', ''),
            'old_value': eh.get('old_value', ''),
            'new_value': eh.get('new_value', ''),
            'edited_by': str(eh['edited_by']) if eh.get('edited_by') else None,
            'timestamp': eh['timestamp'].isoformat() if eh.get('timestamp') else None,
        }

    return {
        'id': str(doc['_id']),
        'project_id': str(doc['project_id']) if doc.get('project_id') else None,
        'reference_number': doc.get('reference_number', ''),
        'status': doc.get('status', 'incomplete'),
        'type': doc.get('type', 'photo'),
        'tags': doc.get('tags', []),
        'description': doc.get('description', ''),
        'raw_message': doc.get('raw_message', ''),
        'sender_phone': doc.get('sender_phone', ''),
        'sender_name': doc.get('sender_name'),
        'photos': doc.get('photos', []),
        'nas_photos': doc.get('nas_photos', []),
        'has_media': doc.get('has_media', False),
        'media_type': doc.get('media_type'),
        'wakka_message_id': doc.get('wakka_message_id'),
        'extracted_fields': [_serialize_extracted_field(f) for f in doc.get('extracted_fields', [])],
        'follow_up_thread': [_serialize_follow_up(fu) for fu in doc.get('follow_up_thread', [])],
        'follow_up_round': doc.get('follow_up_round', 0),
        'last_follow_up_at': doc['last_follow_up_at'].isoformat() if doc.get('last_follow_up_at') else None,
        'status_history': [_serialize_status_history(sh) for sh in doc.get('status_history', [])],
        'edit_history': [_serialize_edit_history(eh) for eh in doc.get('edit_history', [])],
        'merged_from': str(doc['merged_from']) if doc.get('merged_from') else None,
        'split_from': str(doc['split_from']) if doc.get('split_from') else None,
        'void_reason': doc.get('void_reason'),
        'created_at': doc['created_at'].isoformat() if doc.get('created_at') else None,
        'updated_at': doc['updated_at'].isoformat() if doc.get('updated_at') else None,
    }


def create_wa_project_doc(code, name, owner_id, description=None, location=None,
                          stage='active', status='active', members=None, overrides=None):
    """Create a WA project document (wa_projects collection)."""
    return {
        'code': code.upper(),
        'name': name,
        'description': description or '',
        'location': location,
        'owner': ObjectId(owner_id),
        'stage': stage,
        'status': status,
        'members': [ObjectId(m) for m in (members or [])],
        'overrides': overrides or {},
        'created_at': datetime.utcnow(),
        'updated_at': datetime.utcnow(),
    }


def wa_project_to_dict(doc):
    """Convert WA project document to dict for JSON response."""
    if not doc:
        return None

    return {
        'id': str(doc['_id']),
        'code': doc.get('code', ''),
        'name': doc.get('name', ''),
        'description': doc.get('description', ''),
        'location': doc.get('location'),
        'owner': str(doc['owner']) if doc.get('owner') else None,
        'stage': doc.get('stage', 'active'),
        'status': doc.get('status', 'active'),
        'members': [str(m) for m in doc.get('members', [])],
        'overrides': doc.get('overrides', {}),
        'created_at': doc['created_at'].isoformat() if doc.get('created_at') else None,
        'updated_at': doc['updated_at'].isoformat() if doc.get('updated_at') else None,
    }


def create_pool_image_doc(phone, message_id, sender_name=None, image_path=None,
                          nas_path=None, download_failed=False, caption=None,
                          batch_id=None, project_id=None, project_code=None,
                          project_name=None, assigned_by=None, assigned_at=None,
                          record_id=None):
    """Create a pool image document (pool_images collection)."""
    return {
        'phone': phone,
        'sender_name': sender_name,
        'image_path': image_path,
        'nas_path': nas_path,
        'download_failed': download_failed,
        'caption': caption,
        'message_id': message_id,
        'batch_id': batch_id,
        'project_id': ObjectId(project_id) if project_id else None,
        'project_code': project_code,
        'project_name': project_name,
        'assigned_by': assigned_by,
        'assigned_at': assigned_at,
        'record_id': ObjectId(record_id) if record_id else None,
        'created_at': datetime.utcnow(),
        'updated_at': datetime.utcnow(),
    }


def pool_image_to_dict(doc):
    """Convert pool image document to dict for JSON response."""
    if not doc:
        return None

    return {
        'id': str(doc['_id']),
        'phone': doc.get('phone', ''),
        'sender_name': doc.get('sender_name'),
        'image_path': doc.get('image_path'),
        'nas_path': doc.get('nas_path'),
        'download_failed': doc.get('download_failed', False),
        'caption': doc.get('caption'),
        'message_id': doc.get('message_id', ''),
        'batch_id': doc.get('batch_id'),
        'project_id': str(doc['project_id']) if doc.get('project_id') else None,
        'project_code': doc.get('project_code'),
        'project_name': doc.get('project_name'),
        'assigned_by': doc.get('assigned_by'),
        'assigned_at': doc['assigned_at'].isoformat() if doc.get('assigned_at') else None,
        'record_id': str(doc['record_id']) if doc.get('record_id') else None,
        'created_at': doc['created_at'].isoformat() if doc.get('created_at') else None,
        'updated_at': doc['updated_at'].isoformat() if doc.get('updated_at') else None,
    }


def create_group_pending_image_doc(group_id, sender_phone, message_id, batch_id,
                                   sender_name=None, image_path=None, caption=None,
                                   categorized=False, project_id=None, project_code=None,
                                   reminder_count=0):
    """Create a group pending image document (group_pending_images collection)."""
    return {
        'group_id': group_id,
        'sender_phone': sender_phone,
        'sender_name': sender_name,
        'message_id': message_id,
        'image_path': image_path,
        'caption': caption,
        'batch_id': batch_id,
        'categorized': categorized,
        'project_id': ObjectId(project_id) if project_id else None,
        'project_code': project_code,
        'reminder_count': reminder_count,
        'last_reminded_at': None,
        'bot_reminder_msg_id': None,
        'bot_reminder_msg_ids': [],
        'created_at': datetime.utcnow(),
        'updated_at': datetime.utcnow(),
    }


def group_pending_image_to_dict(doc):
    """Convert group pending image document to dict for JSON response."""
    if not doc:
        return None

    return {
        'id': str(doc['_id']),
        'group_id': doc.get('group_id', ''),
        'sender_phone': doc.get('sender_phone', ''),
        'sender_name': doc.get('sender_name'),
        'message_id': doc.get('message_id', ''),
        'image_path': doc.get('image_path'),
        'caption': doc.get('caption'),
        'batch_id': doc.get('batch_id', ''),
        'categorized': doc.get('categorized', False),
        'project_id': str(doc['project_id']) if doc.get('project_id') else None,
        'project_code': doc.get('project_code'),
        'reminder_count': doc.get('reminder_count', 0),
        'last_reminded_at': doc['last_reminded_at'].isoformat() if doc.get('last_reminded_at') else None,
        'bot_reminder_msg_id': doc.get('bot_reminder_msg_id'),
        'bot_reminder_msg_ids': doc.get('bot_reminder_msg_ids', []),
        'created_at': doc['created_at'].isoformat() if doc.get('created_at') else None,
        'updated_at': doc['updated_at'].isoformat() if doc.get('updated_at') else None,
    }


def create_wa_keyword_doc(term, keyword_type, synonyms=None, project_id=None, is_active=True):
    """Create a WA keyword document (wa_keywords collection)."""
    return {
        'term': term.lower(),
        'type': keyword_type,
        'synonyms': [s.lower() for s in (synonyms or [])],
        'project_id': ObjectId(project_id) if project_id else None,
        'is_active': is_active,
        'created_at': datetime.utcnow(),
        'updated_at': datetime.utcnow(),
    }


def wa_keyword_to_dict(doc):
    """Convert WA keyword document to dict for JSON response."""
    if not doc:
        return None

    return {
        'id': str(doc['_id']),
        'term': doc.get('term', ''),
        'type': doc.get('type', ''),
        'synonyms': doc.get('synonyms', []),
        'project_id': str(doc['project_id']) if doc.get('project_id') else None,
        'is_active': doc.get('is_active', True),
        'created_at': doc['created_at'].isoformat() if doc.get('created_at') else None,
        'updated_at': doc['updated_at'].isoformat() if doc.get('updated_at') else None,
    }


def create_wa_template_doc(type_name, fields=None, project_id=None, is_active=True):
    """Create a WA record template document (wa_templates collection)."""
    return {
        'project_id': ObjectId(project_id) if project_id else None,
        'type_name': type_name,
        'fields': fields or [],
        'is_active': is_active,
        'created_at': datetime.utcnow(),
        'updated_at': datetime.utcnow(),
    }


def wa_template_to_dict(doc):
    """Convert WA record template document to dict for JSON response."""
    if not doc:
        return None

    def _serialize_field(f):
        return {
            'name': f.get('name', ''),
            'type': f.get('type', 'text'),
            'required': f.get('required', False),
            'conditional_required': f.get('conditional_required'),
            'options': f.get('options', []),
            'ai_aliases': f.get('ai_aliases', []),
        }

    return {
        'id': str(doc['_id']),
        'project_id': str(doc['project_id']) if doc.get('project_id') else None,
        'type_name': doc.get('type_name', ''),
        'fields': [_serialize_field(f) for f in doc.get('fields', [])],
        'is_active': doc.get('is_active', True),
        'created_at': doc['created_at'].isoformat() if doc.get('created_at') else None,
        'updated_at': doc['updated_at'].isoformat() if doc.get('updated_at') else None,
    }


def create_wa_organization_doc(name, logo=None, contact_email=None, defaults=None):
    """Create a WA organization document (wa_organizations collection)."""
    default_settings = {
        'quiet_hours_start': 22,
        'quiet_hours_end': 7,
        'max_follow_up_rounds': 3,
        'follow_up_cooldown_minutes': 30,
        'data_retention_days': 365,
        'merge_consecutive_messages': False,
    }
    if defaults:
        default_settings.update(defaults)

    return {
        'name': name,
        'logo': logo,
        'contact_email': contact_email,
        'defaults': default_settings,
        'created_at': datetime.utcnow(),
        'updated_at': datetime.utcnow(),
    }


def wa_organization_to_dict(doc):
    """Convert WA organization document to dict for JSON response."""
    if not doc:
        return None

    return {
        'id': str(doc['_id']),
        'name': doc.get('name', ''),
        'logo': doc.get('logo'),
        'contact_email': doc.get('contact_email'),
        'defaults': doc.get('defaults', {}),
        'created_at': doc['created_at'].isoformat() if doc.get('created_at') else None,
        'updated_at': doc['updated_at'].isoformat() if doc.get('updated_at') else None,
    }


def create_wa_pending_photo_doc(sender_phone, photo_path, message_id=None):
    """Create a WA pending photo document (wa_pending_photos collection).
    
    These documents should have a TTL index on created_at for 1-hour expiry.
    """
    return {
        'sender_phone': sender_phone,
        'photo_path': photo_path,
        'message_id': message_id,
        'created_at': datetime.utcnow(),
    }


def wa_pending_photo_to_dict(doc):
    """Convert WA pending photo document to dict for JSON response."""
    if not doc:
        return None

    return {
        'id': str(doc['_id']),
        'sender_phone': doc.get('sender_phone', ''),
        'photo_path': doc.get('photo_path', ''),
        'message_id': doc.get('message_id'),
        'created_at': doc['created_at'].isoformat() if doc.get('created_at') else None,
    }
