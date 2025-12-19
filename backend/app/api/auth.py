from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token,
    jwt_required,
    get_jwt_identity
)
from bson import ObjectId
from app import mongo
from app.models import create_user_doc, check_user_password, user_to_dict
from app.services.audit_service import log_action

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/register', methods=['POST'])
def register():
    """Register a new user."""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    
    if not all([username, email, password]):
        return jsonify({'error': 'Username, email, and password are required'}), 400
    
    # Check if user already exists
    if mongo.db.users.find_one({'username': username}):
        return jsonify({'error': 'Username already exists'}), 409
    
    if mongo.db.users.find_one({'email': email}):
        return jsonify({'error': 'Email already exists'}), 409
    
    # Check if this is the first user (make them admin)
    user_count = mongo.db.users.count_documents({})
    role = 'admin' if user_count == 0 else 'user'
    
    # Create new user
    user_doc = create_user_doc(username, email, password, role=role)
    result = mongo.db.users.insert_one(user_doc)
    user_doc['_id'] = result.inserted_id
    
    # Log the registration
    log_action(
        user_id=str(result.inserted_id),
        action='user_registered',
        resource_type='user',
        resource_id=str(result.inserted_id),
        details={'username': username, 'role': role}
    )
    
    # Create access token
    access_token = create_access_token(identity=str(result.inserted_id))
    
    return jsonify({
        'message': 'User registered successfully',
        'user': user_to_dict(user_doc),
        'access_token': access_token
    }), 201


@auth_bp.route('/login', methods=['POST'])
def login():
    """
    User login endpoint
    ---
    tags:
      - Authentication
    parameters:
      - name: body
        in: body
        required: true
        description: Login credentials
        schema:
          type: object
          required:
            - username
            - password
          properties:
            username:
              type: string
              description: Username or email
              example: admin
            password:
              type: string
              description: User password
              example: password123
    responses:
      200:
        description: Login successful
        schema:
          type: object
          properties:
            access_token:
              type: string
              description: JWT access token
            user:
              type: object
              properties:
                id:
                  type: string
                username:
                  type: string
                email:
                  type: string
                role:
                  type: string
                is_active:
                  type: boolean
      400:
        description: Missing data
        schema:
          type: object
          properties:
            error:
              type: string
      401:
        description: Invalid credentials
        schema:
          type: object
          properties:
            error:
              type: string
      403:
        description: Account deactivated
        schema:
          type: object
          properties:
            error:
              type: string
    """
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    username = data.get('username')
    password = data.get('password')
    
    if not all([username, password]):
        return jsonify({'error': 'Username and password are required'}), 400
    
    # Find user by username or email
    user = mongo.db.users.find_one({
        '$or': [
            {'username': username},
            {'email': username}
        ]
    })
    
    if not user or not check_user_password(user, password):
        return jsonify({'error': 'Invalid username or password'}), 401
    
    if not user.get('is_active', True):
        return jsonify({'error': 'Account is deactivated'}), 403
    
    # Create access token
    access_token = create_access_token(identity=str(user['_id']))
    
    # Log the login
    log_action(
        user_id=str(user['_id']),
        action='login',
        resource_type='user',
        resource_id=str(user['_id']),
        details={'username': user['username']}
    )
    
    return jsonify({
        'message': 'Login successful',
        'user': user_to_dict(user),
        'access_token': access_token
    }), 200


@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """Get current authenticated user."""
    user_id = get_jwt_identity()
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify({'user': user_to_dict(user)}), 200


@auth_bp.route('/me', methods=['PUT'])
@jwt_required()
def update_current_user():
    """Update current user's profile."""
    user_id = get_jwt_identity()
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    data = request.get_json()
    update_fields = {}
    
    if 'email' in data:
        # Check if email is already taken
        existing = mongo.db.users.find_one({
            'email': data['email'],
            '_id': {'$ne': ObjectId(user_id)}
        })
        if existing:
            return jsonify({'error': 'Email already in use'}), 409
        update_fields['email'] = data['email']
    
    if 'password' in data:
        from werkzeug.security import generate_password_hash
        update_fields['password_hash'] = generate_password_hash(data['password'], method='pbkdf2:sha256')
    
    if update_fields:
        from datetime import datetime
        update_fields['updated_at'] = datetime.utcnow()
        mongo.db.users.update_one({'_id': ObjectId(user_id)}, {'$set': update_fields})
    
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    
    return jsonify({
        'message': 'Profile updated successfully',
        'user': user_to_dict(user)
    }), 200
