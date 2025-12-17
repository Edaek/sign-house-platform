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
    'create_project_member_doc'
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
