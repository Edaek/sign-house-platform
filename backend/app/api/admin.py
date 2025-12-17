"""Admin API endpoints for user management and system administration."""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime

from app import mongo
from app.utils.permissions import require_role, get_current_user
from app.services.audit_service import log_action, get_audit_logs, get_action_statistics
from app.models import user_to_dict

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/users', methods=['GET'])
@jwt_required()
@require_role('admin')
def list_users():
    """List all users (Admin only)."""
    try:
        # Get query parameters for filtering and pagination
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        search = request.args.get('search', '')
        role_filter = request.args.get('role')
        status_filter = request.args.get('status')
        
        # Build query
        query = {}
        if search:
            query['$or'] = [
                {'username': {'$regex': search, '$options': 'i'}},
                {'email': {'$regex': search, '$options': 'i'}}
            ]
        
        if role_filter:
            query['role'] = role_filter
        
        if status_filter == 'active':
            query['is_active'] = True
        elif status_filter == 'inactive':
            query['is_active'] = False
        
        # Get total count
        total = mongo.db.users.count_documents(query)
        
        # Calculate pagination
        skip = (page - 1) * per_page
        total_pages = (total + per_page - 1) // per_page
        
        # Get users with pagination
        users_cursor = mongo.db.users.find(query).sort('created_at', -1).skip(skip).limit(per_page)
        
        users = []
        for user in users_cursor:
            user_dict = user_to_dict(user)
            # Add additional admin-visible fields
            user_dict['role_changed_at'] = user.get('role_changed_at').isoformat() if user.get('role_changed_at') else None
            user_dict['updated_at'] = user.get('updated_at').isoformat() if user.get('updated_at') else None
            
            # Get project count for user
            project_count = mongo.db.projects.count_documents({'user_id': user['_id']})
            user_dict['project_count'] = project_count
            
            users.append(user_dict)
        
        return jsonify({
            'users': users,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/users/<user_id>', methods=['GET'])
@jwt_required()
@require_role('admin')
def get_user_details(user_id):
    """Get detailed information about a specific user (Admin only)."""
    try:
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        user_dict = user_to_dict(user)
        user_dict['role_changed_at'] = user.get('role_changed_at').isoformat() if user.get('role_changed_at') else None
        user_dict['updated_at'] = user.get('updated_at').isoformat() if user.get('updated_at') else None
        
        # Get user's projects
        projects = list(mongo.db.projects.find({'user_id': user['_id']}))
        user_dict['projects'] = [
            {
                'id': str(p['_id']),
                'name': p['name'],
                'status': p.get('status'),
                'created_at': p['created_at'].isoformat()
            }
            for p in projects
        ]
        
        # Get recent activity
        from app.services.audit_service import get_user_activity
        user_dict['recent_activity'] = get_user_activity(user_id, limit=10)
        
        return jsonify({'user': user_dict}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/users/<user_id>/role', methods=['PUT'])
@jwt_required()
@require_role('admin')
def change_user_role(user_id):
    """Change a user's role (Admin only)."""
    try:
        admin_id = get_jwt_identity()
        data = request.get_json()
        
        if not data or 'role' not in data:
            return jsonify({'error': 'Role is required'}), 400
        
        new_role = data['role']
        
        # Validate role
        if new_role not in ['admin', 'manager', 'user']:
            return jsonify({'error': 'Invalid role. Must be admin, manager, or user'}), 400
        
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        old_role = user.get('role', 'user')
        
        # Update user role
        mongo.db.users.update_one(
            {'_id': ObjectId(user_id)},
            {
                '$set': {
                    'role': new_role,
                    'role_changed_at': datetime.utcnow(),
                    'role_assigned_by': ObjectId(admin_id),
                    'updated_at': datetime.utcnow()
                }
            }
        )
        
        # Log the action
        log_action(
            user_id=admin_id,
            action='role_changed',
            resource_type='user',
            resource_id=user_id,
            details={
                'old_role': old_role,
                'new_role': new_role,
                'target_user': user['username']
            }
        )
        
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        
        return jsonify({
            'message': 'Role updated successfully',
            'user': user_to_dict(user)
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/users/<user_id>/status', methods=['PUT'])
@jwt_required()
@require_role('admin')
def change_user_status(user_id):
    """Activate or deactivate a user (Admin only)."""
    try:
        admin_id = get_jwt_identity()
        data = request.get_json()
        
        if not data or 'is_active' not in data:
            return jsonify({'error': 'is_active status is required'}), 400
        
        is_active = data['is_active']
        
        if not isinstance(is_active, bool):
            return jsonify({'error': 'is_active must be a boolean'}), 400
        
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Prevent deactivating yourself
        if user_id == admin_id:
            return jsonify({'error': 'You cannot deactivate your own account'}), 400
        
        # Update user status
        mongo.db.users.update_one(
            {'_id': ObjectId(user_id)},
            {
                '$set': {
                    'is_active': is_active,
                    'updated_at': datetime.utcnow()
                }
            }
        )
        
        # Log the action
        log_action(
            user_id=admin_id,
            action='user_deactivated' if not is_active else 'user_activated',
            resource_type='user',
            resource_id=user_id,
            details={
                'target_user': user['username'],
                'is_active': is_active
            }
        )
        
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        
        return jsonify({
            'message': f"User {'activated' if is_active else 'deactivated'} successfully",
            'user': user_to_dict(user)
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/audit-logs', methods=['GET'])
@jwt_required()
@require_role('admin')
def get_audit_logs_endpoint():
    """Get audit logs with filtering (Admin only)."""
    try:
        # Get query parameters
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        user_id = request.args.get('user_id')
        action = request.args.get('action')
        resource_type = request.args.get('resource_type')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        filters = {}
        if user_id:
            filters['user_id'] = user_id
        if action:
            filters['action'] = action
        if resource_type:
            filters['resource_type'] = resource_type
        if start_date:
            filters['start_date'] = start_date
        if end_date:
            filters['end_date'] = end_date
        
        result = get_audit_logs(filters=filters, page=page, per_page=per_page)
        
        return jsonify(result), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/stats', methods=['GET'])
@jwt_required()
@require_role('admin')
def get_system_stats():
    """Get system statistics (Admin only)."""
    try:
        # Count users by role
        total_users = mongo.db.users.count_documents({})
        admin_count = mongo.db.users.count_documents({'role': 'admin'})
        manager_count = mongo.db.users.count_documents({'role': 'manager'})
        user_count = mongo.db.users.count_documents({'role': 'user'})
        active_users = mongo.db.users.count_documents({'is_active': True})
        
        # Count projects
        total_projects = mongo.db.projects.count_documents({})
        
        # Count floorplans
        total_floorplans = mongo.db.floorplans.count_documents({})
        
        # Count extracted data
        total_extractions = mongo.db.extracted_data.count_documents({})
        
        # Get action statistics
        action_stats = get_action_statistics()
        
        # Recent registrations (last 30 days)
        from datetime import timedelta
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        recent_registrations = mongo.db.users.count_documents({
            'created_at': {'$gte': thirty_days_ago}
        })
        
        return jsonify({
            'users': {
                'total': total_users,
                'active': active_users,
                'by_role': {
                    'admin': admin_count,
                    'manager': manager_count,
                    'user': user_count
                },
                'recent_registrations': recent_registrations
            },
            'projects': {
                'total': total_projects
            },
            'floorplans': {
                'total': total_floorplans
            },
            'extractions': {
                'total': total_extractions
            },
            'actions': action_stats['action_counts']
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

