"""Permission decorators and utilities for RBAC."""
from functools import wraps
from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity
from bson import ObjectId
from app import mongo


def get_current_user():
    """Get the current authenticated user from JWT."""
    user_id = get_jwt_identity()
    if not user_id:
        return None
    return mongo.db.users.find_one({'_id': ObjectId(user_id)})


def require_role(*allowed_roles):
    """
    Decorator to require specific role(s) for an endpoint.
    
    Usage:
        @require_role('admin')
        @require_role('admin', 'manager')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            
            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            if not user.get('is_active', True):
                return jsonify({'error': 'Account is deactivated'}), 403
            
            user_role = user.get('role', 'user')
            
            if user_role not in allowed_roles:
                return jsonify({
                    'error': 'Access denied',
                    'message': f'This action requires one of the following roles: {", ".join(allowed_roles)}'
                }), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def check_project_access(user_id, project_id):
    """
    Check if a user has access to a project.
    
    Access rules:
    - Admin: Can access all projects
    - Manager: Can access all projects
    - User: Can access projects they own OR are a member of
    
    Returns:
        tuple: (has_access: bool, user: dict, project: dict)
    """
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return False, None, None
    
    project = mongo.db.projects.find_one({'_id': ObjectId(project_id)})
    if not project:
        return False, user, None
    
    user_role = user.get('role', 'user')
    
    # Admins and managers can access all projects
    if user_role in ['admin', 'manager']:
        return True, user, project
    
    # Project owner can access
    if str(project['user_id']) == user_id:
        return True, user, project
    
    # Check if user is a project member
    is_member = mongo.db.project_members.find_one({
        'project_id': ObjectId(project_id),
        'user_id': ObjectId(user_id)
    })
    
    if is_member:
        return True, user, project
    
    return False, user, project


def require_project_access(f):
    """
    Decorator to check project access for endpoints with project_id parameter.
    
    The decorated function should have project_id as a parameter.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = get_jwt_identity()
        project_id = kwargs.get('project_id')
        
        if not project_id:
            return jsonify({'error': 'Project ID is required'}), 400
        
        has_access, user, project = check_project_access(user_id, project_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        if not project:
            return jsonify({'error': 'Project not found'}), 404
        
        if not has_access:
            return jsonify({'error': 'Access denied to this project'}), 403
        
        # Pass user and project to the function for convenience
        kwargs['_user'] = user
        kwargs['_project'] = project
        
        return f(*args, **kwargs)
    return decorated_function


def can_modify_project(user_id, project_id):
    """
    Check if a user can modify (update/delete) a project.
    
    Modification rules:
    - Admin: Can modify any project
    - Manager: Can modify any project
    - User: Can modify projects they own OR are a member of
    
    Returns:
        tuple: (can_modify: bool, user: dict, project: dict)
    """
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return False, None, None
    
    project = mongo.db.projects.find_one({'_id': ObjectId(project_id)})
    if not project:
        return False, user, None
    
    user_role = user.get('role', 'user')
    
    # Admins and managers can modify any project
    if user_role in ['admin', 'manager']:
        return True, user, project
    
    # Project owner can modify
    if str(project['user_id']) == user_id:
        return True, user, project
    
    # Check if user is a project member
    is_member = mongo.db.project_members.find_one({
        'project_id': ObjectId(project_id),
        'user_id': ObjectId(user_id)
    })
    
    if is_member:
        return True, user, project
    
    return False, user, project


def require_project_modify(f):
    """
    Decorator to check project modification rights.
    
    The decorated function should have project_id as a parameter.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = get_jwt_identity()
        project_id = kwargs.get('project_id')
        
        if not project_id:
            return jsonify({'error': 'Project ID is required'}), 400
        
        can_modify, user, project = can_modify_project(user_id, project_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        if not project:
            return jsonify({'error': 'Project not found'}), 404
        
        if not can_modify:
            return jsonify({'error': 'You do not have permission to modify this project'}), 403
        
        # Pass user and project to the function for convenience
        kwargs['_user'] = user
        kwargs['_project'] = project
        
        return f(*args, **kwargs)
    return decorated_function


def is_admin(user):
    """Check if a user is an admin."""
    return user.get('role') == 'admin'


def is_manager(user):
    """Check if a user is a manager or higher."""
    return user.get('role') in ['admin', 'manager']


def get_user_role(user_id):
    """Get the role of a user by ID."""
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    return user.get('role', 'user') if user else None

