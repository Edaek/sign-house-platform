"""Audit logging service for tracking user actions."""
from datetime import datetime
from functools import wraps
from flask import request
from flask_jwt_extended import get_jwt_identity
from bson import ObjectId
from app import mongo
from app.models import create_audit_log_doc


def log_action(user_id, action, resource_type=None, resource_id=None, details=None):
    """
    Log a user action to the audit logs.
    
    Args:
        user_id: ID of the user performing the action
        action: Action being performed (e.g., 'login', 'project_created', 'role_changed')
        resource_type: Type of resource affected (e.g., 'project', 'user')
        resource_id: ID of the resource affected
        details: Additional details about the action
    """
    try:
        ip_address = request.remote_addr if request else None
        user_agent = request.headers.get('User-Agent') if request else None
        
        log_doc = create_audit_log_doc(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        mongo.db.audit_logs.insert_one(log_doc)
    except Exception as e:
        # Don't fail the request if audit logging fails
        print(f"Audit logging error: {str(e)}")


def audit_log(action, resource_type=None, get_resource_id=None):
    """
    Decorator to automatically log actions.
    
    Args:
        action: The action being performed
        resource_type: Type of resource (optional)
        get_resource_id: Function to extract resource_id from function kwargs (optional)
    
    Usage:
        @audit_log('project_created', resource_type='project', get_resource_id=lambda kwargs: kwargs.get('project_id'))
        def create_project():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_id = get_jwt_identity()
            
            # Execute the function first
            result = f(*args, **kwargs)
            
            # Extract resource_id if function provided
            resource_id = None
            if get_resource_id and callable(get_resource_id):
                try:
                    resource_id = get_resource_id(kwargs)
                except:
                    pass
            
            # Log the action
            if user_id:
                log_action(
                    user_id=user_id,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id
                )
            
            return result
        return decorated_function
    return decorator


def get_audit_logs(filters=None, page=1, per_page=50, sort_order=-1):
    """
    Retrieve audit logs with filtering and pagination.
    
    Args:
        filters: Dictionary of filter criteria
            - user_id: Filter by user ID
            - action: Filter by action
            - resource_type: Filter by resource type
            - start_date: Filter logs after this date
            - end_date: Filter logs before this date
        page: Page number (1-indexed)
        per_page: Number of logs per page
        sort_order: Sort order (1 for ascending, -1 for descending)
    
    Returns:
        Dictionary with logs, total count, and pagination info
    """
    filters = filters or {}
    query = {}
    
    # Build query from filters
    if filters.get('user_id'):
        query['user_id'] = ObjectId(filters['user_id'])
    
    if filters.get('action'):
        query['action'] = filters['action']
    
    if filters.get('resource_type'):
        query['resource_type'] = filters['resource_type']
    
    # Date range filters
    date_filter = {}
    if filters.get('start_date'):
        try:
            start_date = datetime.fromisoformat(filters['start_date'].replace('Z', '+00:00'))
            date_filter['$gte'] = start_date
        except:
            pass
    
    if filters.get('end_date'):
        try:
            end_date = datetime.fromisoformat(filters['end_date'].replace('Z', '+00:00'))
            date_filter['$lte'] = end_date
        except:
            pass
    
    if date_filter:
        query['timestamp'] = date_filter
    
    # Get total count
    total = mongo.db.audit_logs.count_documents(query)
    
    # Calculate pagination
    skip = (page - 1) * per_page
    total_pages = (total + per_page - 1) // per_page
    
    # Get logs with pagination
    logs_cursor = mongo.db.audit_logs.find(query).sort('timestamp', sort_order).skip(skip).limit(per_page)
    
    logs = []
    for log in logs_cursor:
        log_dict = {
            'id': str(log['_id']),
            'user_id': str(log['user_id']) if log.get('user_id') else None,
            'action': log['action'],
            'resource_type': log.get('resource_type'),
            'resource_id': log.get('resource_id'),
            'details': log.get('details', {}),
            'ip_address': log.get('ip_address'),
            'timestamp': log['timestamp'].isoformat()
        }
        
        # Enrich with user information
        if log.get('user_id'):
            user = mongo.db.users.find_one({'_id': log['user_id']})
            if user:
                log_dict['username'] = user['username']
        
        logs.append(log_dict)
    
    return {
        'logs': logs,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages
    }


def get_user_activity(user_id, limit=20):
    """
    Get recent activity for a specific user.
    
    Args:
        user_id: User ID
        limit: Maximum number of logs to return
    
    Returns:
        List of recent audit logs for the user
    """
    logs_cursor = mongo.db.audit_logs.find({
        'user_id': ObjectId(user_id)
    }).sort('timestamp', -1).limit(limit)
    
    logs = []
    for log in logs_cursor:
        logs.append({
            'id': str(log['_id']),
            'action': log['action'],
            'resource_type': log.get('resource_type'),
            'resource_id': log.get('resource_id'),
            'timestamp': log['timestamp'].isoformat()
        })
    
    return logs


def get_action_statistics():
    """
    Get statistics about actions in the system.
    
    Returns:
        Dictionary with action counts and trends
    """
    pipeline = [
        {
            '$group': {
                '_id': '$action',
                'count': {'$sum': 1}
            }
        },
        {
            '$sort': {'count': -1}
        }
    ]
    
    results = list(mongo.db.audit_logs.aggregate(pipeline))
    
    return {
        'action_counts': {r['_id']: r['count'] for r in results}
    }

