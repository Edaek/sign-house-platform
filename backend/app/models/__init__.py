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
    'sign_table_to_dict'
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
        'quantity': 1,  # Default quantity (no multiplier)
        'merged_count': 1,  # Number of items merged (1 = not merged)
        'original_shape_indices': None,  # Array of shape indices that were merged
        'all_bounding_boxes': None,  # Array of all bounding boxes for merged items
        'is_manual': False,
        'manual_text': None,
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
    
    return {
        'id': str(sign_table_doc['_id']),
        'project_id': str(sign_table_doc['project_id']),
        'rows': sign_table_doc.get('rows', []),
        'floorplan_columns': sign_table_doc.get('floorplan_columns', []),
        'created_at': sign_table_doc['created_at'].isoformat() if sign_table_doc.get('created_at') else None,
        'updated_at': sign_table_doc['updated_at'].isoformat() if sign_table_doc.get('updated_at') else None
    }
